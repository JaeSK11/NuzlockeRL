"""Gymnasium battle env for Pokémon Platinum Kaizo on PyNDS.

reset() loads a battle save state and writes a random battle RNG seed. step()
taps a move on the touchscreen and runs the game until it waits for the next
command or the battle is decided. Rewards come from faint events only; see
REWARDS. The env never plays out the text after the final KO.
"""
import enum, json, os, sys
from dataclasses import dataclass

import gymnasium as gym
import numpy as np
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pynds

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen4

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ROM = os.environ.get("NUZLOCKERL_ROM", os.path.join(ROOT, "roms/plat-kaizo-nightmare-update-final.nds"))

FIGHT_XY = (128, 87)
# Slot 1 is verified by Mega Drain's PP on state 05. Slots 2 and 3 are unverified guesses.
MOVE_XY = [(64, 40), (192, 40), (64, 115), (192, 115)]
N_ACTIONS = 9                   # 0-3 move slot, 4-8 switch to party slot 1-5
SETTLE = 20                     # frames to wait after the prompt rises; earlier taps are dropped
TAP_HOLD, TAP_CHECK, TAP_TRIES = 6, 8, 4
SNAPSHOT_EVERY = 10
STEP_FRAME_GUARD = 6000         # frames one step or reset may run before it is called STUCK
OBS_SIZE = 6 * 14 + 4 + 6 + 16 + 1


class Event(enum.Enum):
    ENEMY_FAINTED = enum.auto()
    PLAYER_FAINTED = enum.auto()
    WON = enum.auto()
    LOST = enum.auto()
    TURN_CAP = enum.auto()      # counts as a loss so stalling never pays
    ENDED = enum.auto()         # battle over with neither side wiped, e.g. a flee
    STUCK = enum.auto()         # no prompt and no end in the frame guard


REWARDS: dict[Event, float] = {
    Event.ENEMY_FAINTED: 1.0,
    Event.PLAYER_FAINTED: -3.0,
    Event.WON: 5.0,
    Event.LOST: -10.0,
    Event.TURN_CAP: -10.0,
    Event.ENDED: 0.0,
    Event.STUCK: 0.0,
}


@dataclass(frozen=True)
class Snapshot:
    """One read of both battle parties. Active indices are party slots, None if unmatched."""
    player: tuple
    enemy: tuple
    player_active: int | None
    enemy_active: int | None
    stages_player: tuple
    stages_enemy: tuple


def events_between(prev: Snapshot, cur: Snapshot) -> list[Event]:
    """Faint events from slots whose HP fell to 0, then WON or LOST once a side is wiped.
    LOST wins a tie, so a mutual wipe is never rewarded."""
    events = [Event.PLAYER_FAINTED for a, b in zip(prev.player, cur.player) if a.hp > 0 and b.hp == 0]
    events += [Event.ENEMY_FAINTED for a, b in zip(prev.enemy, cur.enemy) if a.hp > 0 and b.hp == 0]
    if cur.player and all(m.hp == 0 for m in cur.player):
        events.append(Event.LOST)
    elif cur.enemy and all(m.hp == 0 for m in cur.enemy):
        events.append(Event.WON)
    return events


def _wiped(snap: Snapshot) -> bool:
    return all(m.hp == 0 for m in snap.player) or all(m.hp == 0 for m in snap.enemy)


def read_snapshot(nds, addrs: dict) -> Snapshot | None:
    """None unless in battle and every struct decodes cleanly."""
    if not gen4.in_battle(nds, addrs):
        return None
    player = tuple(gen4.read_party(nds, addrs["playerBattleBase"]))
    enemy = tuple(gen4.read_party(nds, addrs["enemyBase"]))
    if not player or not enemy:
        return None
    if not all(m.checksum_ok and m.hp <= m.max_hp for m in player + enemy):
        return None

    def active(party, pid):
        return next((i for i, m in enumerate(party) if m.pid == pid), None)

    rd = nds.memory.read_u32
    return Snapshot(
        player, enemy,
        active(player, rd(False, addrs["playerBattleMonPID"])),
        active(enemy, rd(False, addrs["enemyBattleMonPID"])),
        tuple(gen4.read_bytes(nds, addrs["statStagesPlayer"], 8)),
        tuple(gen4.read_bytes(nds, addrs["statStagesEnemy"], 8)))


def action_mask(snap: Snapshot) -> np.ndarray:
    """Move slots with a move and PP left on the active Pokémon. Switches stay off
    until a switch macro can be verified on a state with 2+ party Pokémon."""
    mask = np.zeros(N_ACTIONS, dtype=bool)
    if snap.player_active is not None:
        mon = snap.player[snap.player_active]
        for k in range(4):
            mask[k] = mon.moves[k] != 0 and mon.pp[k] > 0
    return mask


def observation(snap: Snapshot, turn: int) -> np.ndarray:
    """What a human player sees: own party in full, the enemy's active Pokémon
    and which enemy slots are down. No enemy moves."""
    obs = np.zeros(OBS_SIZE, dtype=np.float32)
    for i, m in enumerate(snap.player):
        obs[i * 14:(i + 1) * 14] = [m.species, m.level, m.hp, m.max_hp, m.status,
                                    *m.moves, *m.pp, i == snap.player_active]
    o = 84
    if snap.enemy_active is not None:
        e = snap.enemy[snap.enemy_active]
        obs[o:o + 4] = [e.species, e.level, e.hp / max(e.max_hp, 1), e.status]
    for i, m in enumerate(snap.enemy):
        obs[88 + i] = m.hp == 0
    obs[94:102], obs[102:110], obs[110] = snap.stages_player, snap.stages_enemy, turn
    return obs


class _Stuck(Exception):
    pass


class BattleEnv(gym.Env):
    """Single-battle env. A step is one command: the agent picks a move slot, the
    env taps it and runs the game to the next command prompt or the battle's end.

    Episode end: terminated on WON, LOST, TURN_CAP or ENDED; truncated on STUCK
    (an unmodeled prompt, such as a forced switch or a move-learn question).
    """
    metadata = {"render_modes": []}

    def __init__(self, states: list[str], rom: str = DEFAULT_ROM, turn_cap: int = 100,
                 log_path: str | None = None, fast_battles: bool = True):
        pynds.config.set_threaded_2d(0)
        pynds.config.set_threaded_3d(0)
        self.states, self.turn_cap, self.fast_battles = list(states), turn_cap, fast_battles
        self.nds = pynds.PyNDS(rom)
        self.action_space = gym.spaces.Discrete(N_ACTIONS)
        self.observation_space = gym.spaces.Box(0.0, np.inf, (OBS_SIZE,), np.float32)
        self._log = open(log_path, "a", buffering=1) if log_path else None
        self._episodes = 0
        self._done = True

    def close(self):
        if self._log:
            self._log.close()
            self._log = None

    def _tick(self, n: int = 1):
        self.nds.tick(n)
        self._frames += n
        self._ep_frames += n

    def _write(self, record: dict):
        if self._log:
            self._log.write(json.dumps(record) + "\n")

    def _cs0(self) -> int | None:
        c = gen4.read_battle_command(self.nds, self.addrs)
        return None if c is None else c[1]

    def _tap(self, xy):
        self.nds.button.set_touch(*xy)
        self.nds.button.touch()
        self._tick(TAP_HOLD)
        self.nds.button.release_touch()

    def _press(self, xy, menu_state: int, wait_for_menu: bool):
        """Tap until curCommandState[0] leaves menu_state. Taps are dropped now and
        then, so a tap that changed nothing after TAP_CHECK frames is repeated."""
        for _ in range(TAP_TRIES):
            if wait_for_menu:
                waited = 0
                while self._cs0() != menu_state:
                    self._tick()
                    waited += 1
                    if waited > STEP_FRAME_GUARD:
                        raise _Stuck
            self._tap(xy)
            self._tick(TAP_CHECK)
            cs0 = self._cs0()
            if cs0 is not None and cs0 != menu_state:
                return
        raise _Stuck

    def _run_to_prompt(self):
        """Tick until the game waits for a command, the battle is decided, or it
        ends. Keeps self.snap as the last valid Snapshot. Returns an Event for the
        two end cases, None at a prompt."""
        start = self._frames
        while self._frames - start < STEP_FRAME_GUARD:
            self._tick()
            if gen4.waiting_for_command(self.nds, self.addrs):
                self._tick(SETTLE)
                snap = read_snapshot(self.nds, self.addrs)
                if snap:
                    self.snap = snap
                return None
            if (self._frames - start) % SNAPSHOT_EVERY == 0:
                snap = read_snapshot(self.nds, self.addrs)
                if snap is None:
                    if not gen4.in_battle(self.nds, self.addrs):
                        return Event.ENDED
                    continue
                self.snap = snap
                self.result_mask = self.nds.memory.read_u8(False, self.addrs["battleResult"])
                if _wiped(snap):
                    return Event.LOST if all(m.hp == 0 for m in snap.player) else Event.WON
        raise _Stuck

    def _info(self, **extra) -> dict:
        return {"action_mask": action_mask(self.snap), "state": self.state_name,
                "rng_seed": self.rng_seed, "turn": self.turn,
                "result_mask": self.result_mask, **extra}

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        options = options or {}
        self.state_name = options.get("state") or self.states[int(self.np_random.integers(len(self.states)))]
        self.nds.load_state_from_file(self.state_name)
        self.addrs = gen4.resolve(self.nds)
        if options.get("keep_rng"):
            self.rng_seed = self.nds.memory.read_u32(False, self.addrs["battleRngSeed"])
        else:
            self.rng_seed = int(self.np_random.integers(2 ** 32))
            gen4.write_battle_seed(self.nds, self.addrs, self.rng_seed)
        if self.fast_battles:
            gen4.write_battle_options(self.nds, self.addrs, text_speed=gen4.TEXT_FAST,
                                      battle_scene=gen4.SCENE_OFF, battle_style=gen4.STYLE_SET)
        self.input_mode = gen4.read_input_mode(self.nds, self.addrs)
        self._frames = self._ep_frames = 0
        self.turn, self.ret, self.result_mask = 0, 0.0, 0
        self.snap = None
        self._episodes += 1
        self.episode_id = f"{os.getpid()}:{self._episodes}"
        self._done = False
        try:
            end = self._run_to_prompt()
        except _Stuck:
            end = Event.STUCK
        if end or self.snap is None:
            raise RuntimeError(f"{self.state_name} did not reach a command prompt ({end})")
        return observation(self.snap, 0), self._info(input_mode=self.input_mode, frames=self._frames)

    def step(self, action):
        if self._done:
            raise RuntimeError("step() after the episode ended; call reset()")
        action = int(action)
        if not 0 <= action < N_ACTIONS or not action_mask(self.snap)[action]:
            raise ValueError(f"action {action} is masked: {action_mask(self.snap).tolist()}")
        prev, self.turn, self._frames = self.snap, self.turn + 1, 0
        events, end = [], None
        try:
            self._press(FIGHT_XY, gen4.CS_ACTION_MENU, wait_for_menu=False)
            self._press(MOVE_XY[action], gen4.CS_MOVE_MENU, wait_for_menu=True)
            end = self._run_to_prompt()
        except _Stuck:
            events.append(Event.STUCK)
        if Event.STUCK not in events:
            events += events_between(prev, self.snap)
            if end is Event.ENDED and not _wiped(self.snap):
                events.append(Event.ENDED)
            elif end is None and self.turn >= self.turn_cap:
                events.append(Event.TURN_CAP)
        reward = sum((REWARDS[e] for e in events), 0.0)
        self.ret += reward
        stuck = Event.STUCK in events
        terminated = not stuck and (_wiped(self.snap) or Event.ENDED in events or Event.TURN_CAP in events)
        self._done = terminated or stuck
        names = [e.name for e in events]
        info = self._info(events=names, frames=self._frames)
        self._write({
            "episode": self.episode_id, "state": os.path.basename(self.state_name),
            "rng_seed": self.rng_seed, "turn": self.turn, "action": action, "events": names,
            "reward": reward, "player_hp": [m.hp for m in self.snap.player],
            "enemy_hp": [m.hp for m in self.snap.enemy], "frames": self._frames,
            **({"signal": gen4.read_battle_command(self.nds, self.addrs)} if stuck else {})})
        if self._done:
            outcome = next(e.name for e in (Event.WON, Event.LOST, Event.TURN_CAP, Event.ENDED, Event.STUCK)
                           if e in events)
            info["outcome"] = outcome
            self._write({"episode": self.episode_id, "summary": True, "outcome": outcome,
                         "turns": self.turn, "return": self.ret, "frames": self._ep_frames,
                         "result_mask": self.result_mask})
        return observation(self.snap, self.turn), reward, terminated, stuck, info
