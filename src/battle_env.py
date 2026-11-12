"""Gymnasium battle env for Pokémon Platinum Kaizo on PyNDS.

reset() loads a battle save state and writes a random battle RNG seed. step()
taps one decision on the touchscreen and runs the game until it asks for the next
decision or the battle is decided. A decision is the action menu (a move or a
switch) or the forced switch after the active Pokémon faints. Rewards come from
faint events only; see REWARDS. The env never plays out the text after the final KO.

Actions: 0-3 use move slot 0-3, 4-8 switch to party position 1-5. Positions are the
game's party-menu order, so position 0 is always the active Pokémon. Struggle is
action 0 when no move has PP left.
"""
import enum, functools, json, os, sys
from dataclasses import dataclass

import gymnasium as gym
import numpy as np
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pynds

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen4
import romdata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ROM = os.environ.get("NUZLOCKERL_ROM", os.path.join(ROOT, "roms/plat-kaizo-nightmare-update-final.nds"))

FIGHT_XY, POKEMON_XY = (128, 87), (215, 160)
MOVE_XY = [(64, 40), (192, 40), (64, 115), (192, 115)]
PARTY_XY = [(64, 28), (192, 36), (64, 76), (192, 84), (64, 124), (192, 132)]   # party-menu positions 0-5
SHIFT_XY = (128, 110)           # confirm button of the party submenu, also in the forced switch
N_ACTIONS = 9                   # 0-3 move slot, 4-8 switch to party position 1-5
SETTLE = 20                     # frames to wait after the prompt rises; earlier taps are dropped
TAP_HOLD, TAP_CHECK, TAP_TRIES = 6, 20, 4   # the game reacts 2 to 9 frames after a tap, depending on the button
PARTY_SETTLE, PARTY_GAP, PARTY_CHECK = 50, 30, 40   # the party screen takes 40 frames to open and 30 to close
SNAPSHOT_EVERY = 10
ENDED_CHECKS = 3                # snapshots in a row with no battle before it is called over; in_battle() reads False on a frame where the game holds the struct decrypted
STEP_FRAME_GUARD = 6000         # frames one step or reset may run before it is called STUCK



class Phase(enum.Enum):
    """What the game is waiting for, read from BattleContext.command, curCommandState[0]
    and the player's SWITCHING flag. Only ACTION_MENU and FORCED_SWITCH are decisions."""
    ACTION_MENU = enum.auto()    # command 5, cs0 1
    MOVE_MENU = enum.auto()      # command 5, cs0 4
    PARTY_MENU = enum.auto()     # command 5, cs0 10
    FORCED_SWITCH = enum.auto()  # command 21 with the SWITCHING flag; cs0 stays 14 and says nothing
    BUSY = enum.auto()           # everything else: animations, text, the turn running


DECISIONS = (Phase.ACTION_MENU, Phase.FORCED_SWITCH)
_MENU_OF_CS0 = {gen4.CS_ACTION_MENU: Phase.ACTION_MENU, gen4.CS_MOVE_MENU: Phase.MOVE_MENU,
                gen4.CS_PARTY_MENU: Phase.PARTY_MENU}


def _ctx_ptr(nds, addrs: dict) -> int | None:
    """The BattleContext pointer if it points into main RAM, as in gen4.read_battle_command."""
    p = nds.memory.read_u32(False, addrs["battleCtxPtr"])
    return p if gen4.MAIN_RAM <= p < gen4.MAIN_RAM + 0x400000 - 0x4000 and not p & 3 else None


def read_phase(nds, addrs: dict) -> Phase:
    ptr = _ctx_ptr(nds, addrs)
    if ptr is None:
        return Phase.BUSY
    rd = nds.memory.read_u32
    command, cs0 = rd(False, ptr + 8), rd(False, ptr) & 0xFF
    if command == gen4.CMD_SELECTION_INPUT:
        phase = _MENU_OF_CS0.get(cs0, Phase.BUSY)
    elif command == gen4.CMD_EXEC_SCRIPT and rd(False, ptr + gen4.CTX_STATUS_FLAGS) & gen4.BATTLER_STATUS_SWITCHING:
        phase = Phase.FORCED_SWITCH
    else:
        return Phase.BUSY
    return phase if gen4.in_battle(nds, addrs) else Phase.BUSY


@dataclass(frozen=True)
class Screen:
    """One screen of a route. Wait until the game shows `phase`, wait `settle` frames, tap
    the points in order `gap` frames apart, and repeat until the phase changes within
    `check` frames of the last tap. A dropped tap shows up as no change."""
    phase: Phase
    taps: tuple
    settle: int = 0
    gap: int = 0
    check: int = TAP_CHECK


def route_for(action: int, forced: bool, struggling: bool) -> tuple[Screen, ...]:
    """The screens an action walks through, starting from the decision it is taken at."""
    if forced:
        return (Screen(Phase.FORCED_SWITCH, (PARTY_XY[action - 3], SHIFT_XY), settle=20, gap=PARTY_GAP, check=PARTY_CHECK),)
    if action >= 4:
        return (Screen(Phase.ACTION_MENU, (POKEMON_XY,)),
                Screen(Phase.PARTY_MENU, (PARTY_XY[action - 3], SHIFT_XY),
                       settle=PARTY_SETTLE, gap=PARTY_GAP, check=PARTY_CHECK))
    fight = Screen(Phase.ACTION_MENU, (FIGHT_XY,))
    return (fight,) if struggling else (fight, Screen(Phase.MOVE_MENU, (MOVE_XY[action],)))


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
    """One read of both battle parties. player and enemy are in RAM order, which stays a
    Pokémon's identity for the whole battle. Active indices are RAM indices, None if
    unmatched. `order` maps party-menu position to RAM index; empty means identity."""
    player: tuple
    enemy: tuple
    player_active: int | None
    enemy_active: int | None
    stages_player: tuple
    stages_enemy: tuple
    order: tuple = ()

    def slots(self) -> list[int]:
        """RAM indices of the player's Pokémon in party-menu order, existing ones only."""
        order = self.order or tuple(range(len(self.player)))
        return [i for i in order if i < len(self.player)]


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
    ptr = _ctx_ptr(nds, addrs)
    if ptr is None:
        return None
    order = tuple(gen4.read_bytes(nds, ptr + gen4.CTX_PARTY_ORDER, 6))
    player = tuple(gen4.read_party(nds, addrs["playerBattleBase"]))
    enemy = tuple(gen4.read_party(nds, addrs["enemyBase"]))
    if not player or not enemy or sorted(order) != list(range(6)):
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
        tuple(gen4.read_bytes(nds, addrs["statStagesEnemy"], 8)),
        order)


def usable_moves(mon) -> list[bool]:
    return [mon.moves[k] != 0 and mon.pp[k] > 0 for k in range(4)]


def is_struggling(snap: Snapshot) -> bool:
    return snap.player_active is not None and not any(usable_moves(snap.player[snap.player_active]))


def action_mask(snap: Snapshot, forced: bool = False) -> np.ndarray:
    """Moves with PP left, and switches to existing, unfainted, non-active Pokémon.
    With no PP left only action 0 is valid: the game then uses Struggle whatever slot is
    tapped. At a forced switch only the switches are valid."""
    mask = np.zeros(N_ACTIONS, dtype=bool)
    if snap.player_active is None:
        return mask
    if not forced:
        usable = usable_moves(snap.player[snap.player_active])
        if not any(usable):
            mask[0] = True
            return mask
        mask[:4] = usable
    for position, idx in enumerate(snap.slots()[1:6], start=1):
        mask[3 + position] = idx != snap.player_active and snap.player[idx].hp > 0
    return mask


# The observation is declared once, here. Every value is in [0, 1] except the stat stages,
# which are in [-1, 1]. Party slots follow the party-menu order, so slot 0 is the active
# Pokémon and slot k is the target of action 3 + k. Empty slots are all zeros.
# Species and move ids are left out on purpose: an id carries no meaning a network can use.
# Types, power, accuracy and class, read from the hack's ROM, carry what the id stands for.
N_TYPES = len(romdata.TYPE_NAMES)
STATUS_BITS = (("asleep", 0x07), ("poisoned", 0x88), ("burned", 0x10), ("frozen", 0x20), ("paralyzed", 0x40))
MOVE_FIELDS = (("type", N_TYPES), ("power", 1), ("accuracy", 1), ("class", len(romdata.MOVE_CLASSES)),
               ("pp", 1), ("valid", 1))
MON_FIELDS = (("types", N_TYPES), ("level", 1), ("hp", 1), ("status", len(STATUS_BITS)))
PARTY_FIELDS = (MON_FIELDS + (("active", 1), ("alive", 1))
                + tuple((f"move{k}.{n}", s) for k in range(4) for n, s in MOVE_FIELDS))
OBS_FIELDS = (
    tuple((f"party{i}.{n}", s) for i in range(6) for n, s in PARTY_FIELDS)
    + tuple((f"enemy.{n}", s) for n, s in MON_FIELDS)
    + (("enemy_fainted", 6), ("enemy_remaining", 1), ("stages_player", 8), ("stages_enemy", 8),
       ("turn", 1), ("forced_switch", 1)))
OBS_SLICES: dict[str, slice] = {}
OBS_SIZE = 0
for _name, _size in OBS_FIELDS:
    OBS_SLICES[_name] = slice(OBS_SIZE, OBS_SIZE + _size)
    OBS_SIZE += _size


@functools.cache
def _type_hot(species: int) -> np.ndarray:
    hot = np.zeros(N_TYPES, dtype=np.float32)
    hot[list(romdata.species(species).types)] = 1.0
    return hot


@functools.cache
def _move_features(move_id: int) -> dict:
    """Type, power, accuracy and class of a move. Accuracy 0 in the ROM means the move
    never misses, so it reads 1. Power is capped at 1 because the hack has moves above 250."""
    m = romdata.move(move_id)
    return {"type": np.eye(N_TYPES, dtype=np.float32)[m.type], "power": min(m.power / 250, 1.0),
            "accuracy": (m.accuracy or 100) / 100, "class": np.eye(len(romdata.MOVE_CLASSES), dtype=np.float32)[m.cls]}


def _mon_values(prefix: str, m) -> dict:
    return {f"{prefix}.types": _type_hot(m.species), f"{prefix}.level": m.level / 100,
            f"{prefix}.hp": m.hp / max(m.max_hp, 1),
            f"{prefix}.status": [bool(m.status & mask) for _, mask in STATUS_BITS]}


def _party_values(prefix: str, m, active: bool) -> dict:
    values = _mon_values(prefix, m)
    values[f"{prefix}.active"], values[f"{prefix}.alive"] = active, m.hp > 0
    for k, (move_id, pp) in enumerate(zip(m.moves, m.pp)):
        if not move_id:
            continue
        for name, value in _move_features(move_id).items():
            values[f"{prefix}.move{k}.{name}"] = value
        # The ROM gives the base PP. PP Ups are not read from RAM, so the maximum is at least the current PP.
        values[f"{prefix}.move{k}.pp"] = pp / max(romdata.move(move_id).pp, pp)
        values[f"{prefix}.move{k}.valid"] = pp > 0
    return values


def observation(snap: Snapshot, turn: int, turn_cap: int, forced: bool = False) -> np.ndarray:
    """What a human player sees: own party in full, the enemy's active Pokémon and which
    enemy slots are down. No enemy moves."""
    values = {}
    for position, idx in enumerate(snap.slots()[:6]):
        values.update(_party_values(f"party{position}", snap.player[idx], idx == snap.player_active))
    if snap.enemy_active is not None:
        values.update(_mon_values("enemy", snap.enemy[snap.enemy_active]))
    values["enemy_fainted"] = [i < len(snap.enemy) and snap.enemy[i].hp == 0 for i in range(6)]
    values["enemy_remaining"] = sum(m.hp > 0 for m in snap.enemy) / 6
    values["stages_player"] = (np.array(snap.stages_player) - 6) / 6
    values["stages_enemy"] = (np.array(snap.stages_enemy) - 6) / 6
    values["turn"], values["forced_switch"] = min(turn / turn_cap, 1.0), forced
    obs = np.zeros(OBS_SIZE, dtype=np.float32)
    for name, value in values.items():
        obs[OBS_SLICES[name]] = value
    return obs


class _Stuck(Exception):
    pass


class BattleEnv(gym.Env):
    """Single-battle env. A step is one decision: the agent picks a move slot or a switch
    (or, after its Pokémon faints, the replacement), the env taps it through the game's
    screens and runs the game to the next decision or the battle's end.

    A forced switch is a decision but not a turn: it doesn't advance the turn counter or
    count toward the turn cap, because the faint that caused it was already part of a turn.
    A party has at most 6 Pokémon, so forced switches can't loop.

    Episode end: terminated on WON, LOST, TURN_CAP or ENDED; truncated on STUCK
    (an unmodeled prompt, such as a move-learn question, or a tap that never registered).
    """
    metadata = {"render_modes": []}

    def __init__(self, states: list[str], rom: str = DEFAULT_ROM, turn_cap: int = 100,
                 log_path: str | None = None, fast_battles: bool = True):
        pynds.config.set_threaded_2d(0)
        pynds.config.set_threaded_3d(0)
        self.states, self.turn_cap, self.fast_battles = list(states), turn_cap, fast_battles
        self.nds = pynds.PyNDS(rom)
        self.action_space = gym.spaces.Discrete(N_ACTIONS)
        self.observation_space = gym.spaces.Box(-1.0, 1.0, (OBS_SIZE,), np.float32)
        self._log = open(log_path, "a", buffering=1) if log_path else None
        self._episodes = 0
        self._done = True
        self.forced = False

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

    def _phase(self) -> Phase:
        return read_phase(self.nds, self.addrs)

    def _tap(self, xy):
        self.nds.button.set_touch(*xy)
        self.nds.button.touch()
        self._tick(TAP_HOLD)
        self.nds.button.release_touch()

    def _walk(self, screen: Screen):
        """Wait for the screen, then tap it until the game leaves it. Taps are dropped now
        and then, so a screen that is still up after `check` frames is tapped again."""
        for _ in range(TAP_TRIES):
            waited = 0
            while self._phase() != screen.phase:
                self._tick()
                waited += 1
                if waited > STEP_FRAME_GUARD:
                    raise _Stuck
            self._tick(screen.settle)
            for i, xy in enumerate(screen.taps):
                if i:
                    self._tick(screen.gap)
                self._tap(xy)
            for _ in range(screen.check):
                self._tick()
                if self._phase() != screen.phase:
                    return
            self.retries += 1
        raise _Stuck

    def _run_to_prompt(self):
        """Tick until the game waits for a decision, the battle is decided, or it ends.
        Keeps self.snap as the last valid Snapshot and sets self.forced. Returns an Event
        for the two end cases, None at a decision."""
        start, gone = self._frames, 0
        self.forced = False
        while self._frames - start < STEP_FRAME_GUARD:
            self._tick()
            phase = self._phase()
            if phase in DECISIONS:
                self._tick(SETTLE)
                snap = read_snapshot(self.nds, self.addrs)
                if snap:
                    self.snap = snap
                self.forced = phase is Phase.FORCED_SWITCH
                return None
            if (self._frames - start) % SNAPSHOT_EVERY == 0:
                snap = read_snapshot(self.nds, self.addrs)
                if snap is None:
                    gone = 0 if gen4.in_battle(self.nds, self.addrs) else gone + 1
                    if gone >= ENDED_CHECKS:
                        return Event.ENDED
                    continue
                gone = 0
                self.snap = snap
                self.result_mask = self.nds.memory.read_u8(False, self.addrs["battleResult"])
                if _wiped(snap):
                    return Event.LOST if all(m.hp == 0 for m in snap.player) else Event.WON
        raise _Stuck

    def _info(self, **extra) -> dict:
        return {"action_mask": action_mask(self.snap, self.forced), "state": self.state_name,
                "rng_seed": self.rng_seed, "turn": self.turn, "forced_switch": self.forced,
                "result_mask": self.result_mask, **extra}

    def _obs(self) -> np.ndarray:
        return observation(self.snap, self.turn, self.turn_cap, self.forced)

    def _stuck_signal(self) -> list:
        """(command, curCommandState[0], player status flags) for the log."""
        c = gen4.read_battle_command(self.nds, self.addrs)
        ptr = _ctx_ptr(self.nds, self.addrs)
        flags = self.nds.memory.read_u32(False, ptr + gen4.CTX_STATUS_FLAGS) if ptr else None
        return [*(c or (None, None)), flags]

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
        self.turn, self.ret, self.result_mask, self.retries = 0, 0.0, 0, 0
        self.snap = None
        self._episodes += 1
        self.episode_id = f"{os.getpid()}:{self._episodes}"
        self._done = False
        try:
            end = self._run_to_prompt()
        except _Stuck:
            end = Event.STUCK
        if end or self.snap is None:
            raise RuntimeError(f"{self.state_name} did not reach a decision prompt ({end})")
        return self._obs(), self._info(input_mode=self.input_mode, frames=self._frames)

    def step(self, action):
        if self._done:
            raise RuntimeError("step() after the episode ended; call reset()")
        action = int(action)
        mask = action_mask(self.snap, self.forced)
        if not 0 <= action < N_ACTIONS or not mask[action]:
            raise ValueError(f"action {action} is masked: {mask.tolist()}")
        prev, forced, struggling = self.snap, self.forced, is_struggling(self.snap)
        target = prev.player[prev.slots()[action - 3]].pid if action >= 4 else None
        self.turn += not forced
        self._frames = 0
        events, end = [], None
        try:
            for screen in route_for(action, forced, struggling):
                self._walk(screen)
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
        if target is not None and not stuck and self.snap.player_active is not None:
            info["switched_in"] = self.snap.player[self.snap.player_active].pid == target
        self._write({
            "episode": self.episode_id, "state": os.path.basename(self.state_name),
            "rng_seed": self.rng_seed, "turn": self.turn, "action": action, "forced": forced,
            "events": names, "reward": reward, "player_hp": [m.hp for m in self.snap.player],
            "enemy_hp": [m.hp for m in self.snap.enemy], "frames": self._frames,
            **({"signal": self._stuck_signal()} if stuck else {})})
        if self._done:
            outcome = next(e.name for e in (Event.WON, Event.LOST, Event.TURN_CAP, Event.ENDED, Event.STUCK)
                           if e in events)
            info["outcome"] = outcome
            self._write({"episode": self.episode_id, "summary": True, "outcome": outcome,
                         "turns": self.turn, "return": self.ret, "frames": self._ep_frames,
                         "result_mask": self.result_mask})
        return self._obs(), reward, terminated, stuck, info
