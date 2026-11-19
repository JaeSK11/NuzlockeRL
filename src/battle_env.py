"""Gymnasium battle env for Pokémon Platinum Kaizo on PyNDS.

reset() loads a battle save state and writes a random battle RNG seed. step()
taps one decision on the touchscreen and runs the game until it asks for the next
decision or the battle is decided. A decision is the action menu (a move or a
switch) or the forced switch after the active Pokémon faints. Rewards come from
faints and the battle's end only: REWARDS, and faint_penalty, which weighs a player
faint by the Pokémon's strength in its team. The env never plays out the text after
the final KO.

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
N_ACTIONS = 10                  # 0-3 move slot, 4-8 switch to party position 1-5, 9 throw a ball
BALL_ACTION = 9                 # the first ball in the Poké Balls pocket, when the caller allows a catch
SETTLE = 20                     # frames to wait after the prompt rises; earlier taps are dropped
TAP_HOLD, TAP_CHECK, TAP_TRIES = 6, 20, 4   # the game reacts 2 to 9 frames after a tap, depending on the button
PARTY_SETTLE, PARTY_GAP, PARTY_CHECK = 50, 30, 40   # the party screen takes 40 frames to open and 30 to close
SNAPSHOT_EVERY = 10
ENDED_CHECKS = 3                # snapshots in a row with no battle before it is called over; in_battle() reads False on a frame where the game holds the struct decrypted
STEP_FRAME_GUARD = 6000         # frames one step or reset may run before it is called STUCK
END_FRAME_GUARD = 4000          # frames to wait after a wipe for the game to record the result: 300 to 800 in a wild battle, about 1,150 after Barry 1's level-up
# Throwing a ball: BAG on the action menu, the POKé BALLS pocket, the first ball, USE. Each bag
# screen takes a moment to draw, and all of them read as Phase.BAG.
BAG_XY, BALLS_POCKET_XY, FIRST_BALL_XY, USE_XY = (40, 172), (193, 48), (64, 40), (100, 172)
BAG_SCREEN_FRAMES = 60
# The catch task's states (the decomp's CatchMonTaskState) that wait for the player. It shares
# its struct with the experience task, so the two are told apart by whether a ball is in flight.
CATCH_TEXT_WAITS = (9, 24)      # "Gotcha! ... was caught!" and "... was transferred to the PC": B
CATCH_POKEDEX = 13              # the new Pokédex entry: A or a tap, not B
CATCH_NICKNAME = 19             # "Give a nickname?": B answers no
POKEDEX_TAP = (128, 100)
# The experience task's states (the decomp's GetExpTaskState) that wait for the player
EXP_BUTTON_WAITS = (7, 11, 13)  # "grew to Lv. N!" and the two stat boxes: B moves them on and answers nothing
EXP_FORGET_PROMPT = 21          # "Make it forget another move?": Forget a move! above, Keep old moves! below
EXP_FORGET_SELECT = 23          # the move to forget: tap it, then FORGET on its page
EXP_GIVE_UP_PROMPT = 34         # "Should this Pokémon give up on learning this new move?": Give up above
UPPER_BUTTON, LOWER_BUTTON = (128, 64), (128, 135)          # the two answers of either prompt
FORGET_SLOTS = ((64, 70), (192, 70), (64, 120), (192, 120))   # the four moves on the forget screen
FORGET_BUTTON, FORGET_PAGE_FRAMES = (115, 172), 30            # FORGET on the move's page, which takes a moment to open



class Phase(enum.Enum):
    """What the game is waiting for, read from BattleContext.command, curCommandState[0]
    and the player's SWITCHING flag. Only ACTION_MENU and FORCED_SWITCH are decisions."""
    ACTION_MENU = enum.auto()    # command 5, cs0 1
    MOVE_MENU = enum.auto()      # command 5, cs0 4
    PARTY_MENU = enum.auto()     # command 5, cs0 10
    BAG = enum.auto()            # command 5, cs0 8: the battle bag, on any of its screens
    FORCED_SWITCH = enum.auto()  # command 21 with the SWITCHING flag; cs0 stays 14 and says nothing
    BUSY = enum.auto()           # everything else: animations, text, the turn running


DECISIONS = (Phase.ACTION_MENU, Phase.FORCED_SWITCH)
_MENU_OF_CS0 = {gen4.CS_ACTION_MENU: Phase.ACTION_MENU, gen4.CS_MOVE_MENU: Phase.MOVE_MENU,
                gen4.CS_PARTY_MENU: Phase.PARTY_MENU, gen4.CS_BAG: Phase.BAG}


def move_value(move: int, types) -> float:
    """An attack's power times its accuracy, x1.5 in the user's own type; 0 for a status move."""
    if not move:
        return 0.0
    m = romdata.move(move)
    if m.cls == 2 or not m.power:
        return 0.0
    return m.power * (m.accuracy or 100) / 100 * (1.5 if m.type in types else 1.0)


def move_to_forget(moves, types, new_move: int) -> int | None:
    """A stand-in for the agent's choice when a level-up offers a fifth move: the slot of the
    lowest-valued move (move_value) if the new move is worth more, else None to keep the old moves."""
    values = [move_value(m, types) for m in moves]
    slot = min(range(len(values)), key=values.__getitem__)
    return slot if move_value(new_move, types) > values[slot] else None


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


def route_for(action: int, forced: bool, fight_only: bool) -> tuple[Screen, ...]:
    """The screens an action walks through, starting from the decision it is taken at.
    fight_only: FIGHT alone chooses the move, as under Struggle or Encore (fights_at_once)."""
    if forced:
        return (Screen(Phase.FORCED_SWITCH, (PARTY_XY[action - 3], SHIFT_XY), settle=20, gap=PARTY_GAP, check=PARTY_CHECK),)
    if action >= 4:
        return (Screen(Phase.ACTION_MENU, (POKEMON_XY,)),
                Screen(Phase.PARTY_MENU, (PARTY_XY[action - 3], SHIFT_XY),
                       settle=PARTY_SETTLE, gap=PARTY_GAP, check=PARTY_CHECK))
    fight = Screen(Phase.ACTION_MENU, (FIGHT_XY,))
    return (fight,) if fight_only else (fight, Screen(Phase.MOVE_MENU, (MOVE_XY[action],)))


class Event(enum.Enum):
    ENEMY_FAINTED = enum.auto()
    PLAYER_FAINTED = enum.auto()
    WON = enum.auto()
    LOST = enum.auto()
    TURN_CAP = enum.auto()      # counts as a loss so stalling never pays
    FLED = enum.auto()          # the game recorded a flee: Roar or Whirlwind, by either side, ended a wild battle
    CAUGHT = enum.auto()        # the game recorded a catch (resultMask 4)
    ENDED = enum.auto()         # battle over with neither side wiped, and no flee recorded
    STUCK = enum.auto()         # no prompt and no end in the frame guard


# A player faint costs FAINT_BASE + FAINT_SCALE x the Pokémon's strength in its team (see
# strengths): about -2.4 for fodder and -8 for the ace. A win that costs fodder still pays
# (+3.6), one that costs the ace doesn't (-2), and a loss is worse than either.
FAINT_BASE, FAINT_SCALE = 1.0, 7.0
REWARDS: dict[Event, float] = {     # every event but PLAYER_FAINTED, whose cost depends on the Pokémon
    Event.ENEMY_FAINTED: 1.0,
    Event.WON: 5.0,
    Event.LOST: -10.0,
    Event.TURN_CAP: -10.0,
    Event.FLED: 0.0,
    Event.CAUGHT: 0.0,          # a catch pays off in later battles, which the run, not this env, sees
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
    locks: tuple = (False,) * 4  # moves the game refuses besides those out of PP (move_locks)
    encored: bool = False        # FIGHT uses the encored move at once, with no move menu
    trapped: bool = False        # the active Pokémon can't switch out (is_trapped)
    field: gen4.FieldEffects = gen4.FieldEffects()   # weather, screens and hazards
    volatile: tuple = (0, 0)     # statusVolatile of the player's and the enemy's active Pokémon

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


def strengths(party) -> list[float]:
    """Each Pokémon's stat total (max HP plus the five other stats) over the team's highest:
    1 for the strongest, lower for the rest. Stats don't change during a battle."""
    totals = [m.max_hp + sum(m.stats.values()) for m in party]
    top = max(totals, default=0) or 1
    return [t / top for t in totals]


def fainted_strengths(prev: Snapshot, cur: Snapshot) -> list[float]:
    """The strength of each player Pokémon that fainted between two snapshots."""
    s = strengths(cur.player)
    return [s[i] for i, (a, b) in enumerate(zip(prev.player, cur.player)) if a.hp > 0 and b.hp == 0]


def faint_penalty(prev: Snapshot, cur: Snapshot) -> float:
    """The reward for the player faints between two snapshots, weighted by strength."""
    return -sum(FAINT_BASE + FAINT_SCALE * s for s in fainted_strengths(prev, cur))


def decision(prev: Snapshot, action: int, forced: bool) -> dict:
    """What a decision was, for the logs: the move by name, its PP before the turn, and its
    kind. The kind is switch, forced_switch, struggle, status, or for an attack its type
    matchup against the enemy's active Pokémon: super, neutral, resisted or immune."""
    if action == BALL_ACTION:
        return {"pick": "ball", "move": None, "pp_before": None}
    if action >= 4:
        return {"pick": "forced_switch" if forced else "switch", "move": None, "pp_before": None}
    if is_struggling(prev):
        return {"pick": "struggle", "move": "Struggle", "pp_before": None}
    mon = prev.player[prev.player_active]
    move = romdata.move(mon.moves[action])
    if romdata.MOVE_CLASSES[move.cls] == "status":
        pick = "status"
    else:
        enemy = prev.enemy[prev.enemy_active] if prev.enemy_active is not None else None
        mult = romdata.type_effectiveness(move.type, romdata.species(enemy.species).types) if enemy else 1.0
        pick = "immune" if mult == 0 else "super" if mult > 1 else "resisted" if mult < 1 else "neutral"
    return {"pick": pick, "move": move.name, "pp_before": mon.pp[action]}


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
    mine, foe = gen4.read_battle_effects(nds, addrs, 0), gen4.read_battle_effects(nds, addrs, 1)
    enemy_active = active(enemy, rd(False, addrs["enemyBattleMonPID"]))
    foe_ability = foe.ability if foe and enemy_active is not None and enemy[enemy_active].hp else None
    return Snapshot(
        player, enemy,
        active(player, rd(False, addrs["playerBattleMonPID"])), enemy_active,
        tuple(gen4.read_bytes(nds, addrs["statStagesPlayer"], 8)),
        tuple(gen4.read_bytes(nds, addrs["statStagesEnemy"], 8)),
        order,
        locks=move_locks(mine) if mine else (False,) * 4,
        encored=bool(mine and mine.encored_move),
        trapped=bool(mine) and is_trapped(mine, foe_ability),
        field=gen4.read_field_effects(nds, addrs) or gen4.FieldEffects(),
        volatile=(mine.volatile if mine else 0, foe.volatile if foe else 0))


# What the game refuses at a prompt besides an empty slot or a move out of PP: the decomp's
# BattleSystem_CheckInvalidMoves and Battler_IsTrapped. This hack has no Taunt and no Bind
# (their move ids were reused), but the checks cost nothing and other Gen 4 games need them.
# Imprison, Gravity and Heal Block aren't modeled; no enemy before Roark uses them.
VOLATILE_BIND, VOLATILE_MEAN_LOOK, VOLATILE_TORMENT = 7 << 13, 1 << 26, 1 << 31
VOLATILE_CONFUSION, VOLATILE_SUBSTITUTE, VOLATILE_CURSE = 7, 1 << 24, 1 << 28
EFFECT_INGRAIN = 1 << 10
SHED_SHELL, CHOICE_ITEMS = 295, (220, 287, 297)            # Choice Band, Scarf, Specs
SHADOW_TAG, LEVITATE, MAGNET_PULL, ARENA_TRAP = 23, 26, 42, 71
TYPE_FLYING, TYPE_STEEL = 2, 8


def move_locks(b: gen4.BattleEffects) -> tuple:
    """Per move slot, whether Disable, Torment, Taunt, Encore or a Choice item's lock forbids it."""
    choice = b.item in CHOICE_ITEMS and b.choice_move in b.moves
    return tuple(bool(m) and (
        m == b.disabled_move
        or (b.volatile & VOLATILE_TORMENT and m == b.last_move)
        or (b.taunt_turns and romdata.move(m).power == 0)
        or (b.encored_move and m != b.encored_move)
        or (choice and b.choice_move and m != b.choice_move)) for m in b.moves)


def is_trapped(b: gen4.BattleEffects, foe_ability: int | None) -> bool:
    """Bound (Wrap and the like), under Mean Look or Block, rooted by Ingrain, or held by the
    enemy's Shadow Tag, Magnet Pull (if Steel) or Arena Trap (if grounded). Shed Shell frees it."""
    if b.item == SHED_SHELL:
        return False
    if b.volatile & (VOLATILE_BIND | VOLATILE_MEAN_LOOK) or b.effects_mask & EFFECT_INGRAIN:
        return True
    grounded = TYPE_FLYING not in b.types and b.ability != LEVITATE and not b.magnet_rise_turns
    return ((foe_ability == SHADOW_TAG and b.ability != SHADOW_TAG)
            or (foe_ability == MAGNET_PULL and TYPE_STEEL in b.types)
            or (foe_ability == ARENA_TRAP and grounded))


def usable_moves(mon) -> list[bool]:
    return [mon.moves[k] != 0 and mon.pp[k] > 0 for k in range(4)]


def allowed_moves(snap: Snapshot) -> list[bool]:
    """Moves the game accepts: PP left and no lock (move_locks)."""
    return [u and not lock for u, lock in zip(usable_moves(snap.player[snap.player_active]), snap.locks)]


def is_struggling(snap: Snapshot) -> bool:
    """No move is allowed, so FIGHT makes the game use Struggle."""
    return snap.player_active is not None and not any(allowed_moves(snap))


def fights_at_once(snap: Snapshot) -> bool:
    """FIGHT chooses the move without the move menu: Struggle, or the encored move."""
    return is_struggling(snap) or snap.encored


def action_mask(snap: Snapshot, forced: bool = False, can_throw: bool = False) -> np.ndarray:
    """Moves the game accepts (allowed_moves), and switches to existing, unfainted, non-active
    Pokémon unless the active one is trapped. With no move allowed only action 0 is valid: the
    game then uses Struggle whatever slot is tapped. At a forced switch only the switches are
    valid, trapped or not, since the trapped Pokémon has fainted. A ball can be thrown when
    `can_throw` (the caller allows a catch and the bag has a ball), but not at a forced switch."""
    mask = np.zeros(N_ACTIONS, dtype=bool)
    if snap.player_active is None:
        return mask
    mask[BALL_ACTION] = can_throw and not forced
    if not forced:
        allowed = allowed_moves(snap)
        if not any(allowed):
            mask[0] = True
            return mask
        mask[:4] = allowed
        if snap.trapped:
            return mask
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
# Type matchups against the enemy's active Pokémon, from the hack's type chart: for each move its
# effectiveness, whether the target is immune, and the same-type bonus; for the Pokémon, how hard
# each of the enemy's types hits it (the enemy's moves are hidden, so its types stand in for them).
MATCHUP_FIELDS = (("effect", 1), ("immune", 1), ("stab", 1))
PARTY_FIELDS = (MON_FIELDS + (("active", 1), ("alive", 1), ("strength", 1), ("hit_by_enemy_types", 2))
                + tuple((f"move{k}.{n}", s) for k in range(4) for n, s in MOVE_FIELDS + MATCHUP_FIELDS))
# Battle effects (PROGRESS §43). A side's turns and layers, and the active Pokémon's volatile
# bits, each over the most it usually reaches: (name, most) and (name, bits, most).
SIDE_FIELDS = (("reflect", 5), ("light_screen", 5), ("safeguard", 5), ("mist", 5), ("tailwind", 3),
               ("spikes", 3), ("toxic_spikes", 2), ("stealth_rock", 1))
VOLATILE_FIELDS = (("bound", VOLATILE_BIND, 5), ("cursed", VOLATILE_CURSE, 1),
                   ("confused", VOLATILE_CONFUSION, 5), ("substitute", VOLATILE_SUBSTITUTE, 1))
OBS_FIELDS = (
    tuple((f"party{i}.{n}", s) for i in range(6) for n, s in PARTY_FIELDS)
    + tuple((f"enemy.{n}", s) for n, s in MON_FIELDS)
    + (("enemy_fainted", 6), ("enemy_remaining", 1), ("stages_player", 8), ("stages_enemy", 8),
       ("turn", 1), ("forced_switch", 1))
    # The effects come last, so a checkpoint from before them can be widened for them
    # (scripts/widen_checkpoint.py).
    + (("weather", len(gen4.WEATHER_BITS)), ("weather_turns", 1), ("trick_room", 1), ("gravity", 1),
       ("side_player", len(SIDE_FIELDS)), ("side_enemy", len(SIDE_FIELDS)),
       ("volatile_player", len(VOLATILE_FIELDS)), ("volatile_enemy", len(VOLATILE_FIELDS))))
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


def _effect(multiplier: float) -> float:
    """A type multiplier on [-1, 1]: log2 of it over 2, so 1/4 reads -1, 1 reads 0, 4 reads 1. Immune reads -1."""
    return float(np.clip(np.log2(multiplier) / 2, -1, 1)) if multiplier > 0 else -1.0


def _mon_values(prefix: str, m) -> dict:
    return {f"{prefix}.types": _type_hot(m.species), f"{prefix}.level": m.level / 100,
            f"{prefix}.hp": m.hp / max(m.max_hp, 1),
            f"{prefix}.status": [bool(m.status & mask) for _, mask in STATUS_BITS]}


def _party_values(prefix: str, m, active: bool, strength: float, enemy=None) -> dict:
    values = _mon_values(prefix, m)
    values[f"{prefix}.active"], values[f"{prefix}.alive"] = active, m.hp > 0
    values[f"{prefix}.strength"] = strength
    own_types = romdata.species(m.species).types
    if enemy is not None:
        enemy_types = romdata.species(enemy.species).types
        values[f"{prefix}.hit_by_enemy_types"] = [_effect(romdata.type_effectiveness(t, own_types)) for t in enemy_types]
    for k, (move_id, pp) in enumerate(zip(m.moves, m.pp)):
        if not move_id:
            continue
        for name, value in _move_features(move_id).items():
            values[f"{prefix}.move{k}.{name}"] = value
        move_type = romdata.move(move_id).type
        values[f"{prefix}.move{k}.stab"] = move_type in own_types
        if enemy is not None:
            multiplier = romdata.type_effectiveness(move_type, enemy_types)
            values[f"{prefix}.move{k}.effect"], values[f"{prefix}.move{k}.immune"] = _effect(multiplier), multiplier == 0
        # The ROM gives the base PP. PP Ups are not read from RAM, so the maximum is at least the current PP.
        values[f"{prefix}.move{k}.pp"] = pp / max(romdata.move(move_id).pp, pp)
        values[f"{prefix}.move{k}.valid"] = pp > 0
    return values


def observation(snap: Snapshot, turn: int, turn_cap: int, forced: bool = False) -> np.ndarray:
    """What a human player sees: own party in full, the enemy's active Pokémon, which
    enemy slots are down, and the weather, screens, hazards and traps. No enemy moves."""
    values = {}
    enemy = snap.enemy[snap.enemy_active] if snap.enemy_active is not None else None
    strength = strengths(snap.player)
    for position, idx in enumerate(snap.slots()[:6]):
        values.update(_party_values(f"party{position}", snap.player[idx], idx == snap.player_active,
                                    strength[idx], enemy))
    if enemy is not None:
        values.update(_mon_values("enemy", enemy))
    values["enemy_fainted"] = [i < len(snap.enemy) and snap.enemy[i].hp == 0 for i in range(6)]
    values["enemy_remaining"] = sum(m.hp > 0 for m in snap.enemy) / 6
    values["stages_player"] = (np.array(snap.stages_player) - 6) / 6
    values["stages_enemy"] = (np.array(snap.stages_enemy) - 6) / 6
    values["turn"], values["forced_switch"] = min(turn / turn_cap, 1.0), forced
    f = snap.field
    values["weather"] = [f.weather == name for name, _ in gen4.WEATHER_BITS]
    values["weather_turns"], values["trick_room"], values["gravity"] = (
        min(t / 5, 1.0) for t in (f.weather_turns, f.trick_room, f.gravity))
    for key, side in zip(("side_player", "side_enemy"), f.sides):
        values[key] = [min(getattr(side, name) / most, 1.0) for name, most in SIDE_FIELDS]
    for key, v in zip(("volatile_player", "volatile_enemy"), snap.volatile):
        values[key] = [min((v & bits) // (bits & -bits) / most, 1.0) for _, bits, most in VOLATILE_FIELDS]
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
                 log_path: str | None = None, fast_battles: bool = True, nds=None):
        pynds.config.set_threaded_2d(0)
        pynds.config.set_threaded_3d(0)
        self.states, self.turn_cap, self.fast_battles = list(states), turn_cap, fast_battles
        self.nds = nds or pynds.PyNDS(rom)     # a live run passes its own emulator and attaches to its battles
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

    def _press(self, key: str):
        self.nds.button.press_key(key)
        self._tick(2)
        self.nds.button.release_key(key)
        self._tick(8)

    def _tap_until_moved(self, taps, seq: int, settle: int):
        """Tap `taps` in turn until the experience task leaves state `seq`, as _walk does for menus."""
        for _ in range(TAP_TRIES):
            self._tick(settle)
            for i, xy in enumerate(taps):
                if i:
                    self._tick(FORGET_PAGE_FRAMES)
                self._tap(xy)
            for _ in range(TAP_CHECK * 3):
                self._tick()
                task = gen4.read_script_task(self.nds, self.addrs)
                if task is None or task[0] != seq:
                    return
            self.retries += 1
        raise _Stuck

    def _can_throw(self) -> bool:
        return self.catch_allowed and bool(gen4.read_bag(self.nds, self.addrs, from_battle=True)["balls"])

    def _throw_ball(self):
        """BAG, the Poké Balls pocket, the first ball in it, USE. A dropped tap inside the bag
        can't be retried in place, since the same spot on another bag screen picks something
        else, so the bag is closed with B and the whole route walked again."""
        for _ in range(TAP_TRIES):
            self._walk(Screen(Phase.ACTION_MENU, (BAG_XY,)))
            for xy in (BALLS_POCKET_XY, FIRST_BALL_XY, USE_XY):
                self._tick(BAG_SCREEN_FRAMES)
                self._tap(xy)
            for _ in range(BAG_SCREEN_FRAMES):
                self._tick()
                if self._phase() is not Phase.BAG:
                    return
            self.retries += 1
            for _ in range(4):
                self._press("b")
                self._tick(BAG_SCREEN_FRAMES)
        raise _Stuck

    def _answer_task(self):
        """While a ball is in flight the script task is the catch; otherwise it's the experience
        task. The catch is over once its task is gone."""
        if not self._throwing:
            return self._answer_exp_task()
        task = gen4.read_script_task(self.nds, self.addrs)
        if task is None:
            if self._catch_seen:
                self._throwing = False
            return
        self._catch_seen = True
        if task[0] in CATCH_TEXT_WAITS or task[0] == CATCH_NICKNAME:
            self._press("b")
        elif task[0] == CATCH_POKEDEX:
            self._tick(SETTLE)
            self._tap(POKEDEX_TAP)
            self._tick(SETTLE)

    def _answer_exp_task(self):
        """Answer the experience task when it waits for the player: B through the level-up text
        and stat boxes, and move_to_forget's choice when a level-up offers a fifth move. In a
        trainer battle the game records the result only after this, and a mid-battle level-up
        would otherwise hold the battle until the step is called STUCK."""
        task = gen4.read_script_task(self.nds, self.addrs)
        if task is None:
            return
        seq, tmp = task
        if seq in EXP_BUTTON_WAITS:
            self._press("b")
        elif seq == EXP_FORGET_PROMPT:
            mon = self.snap.player[tmp[gen4.EXP_TMP_PARTY_SLOT]]
            new = tmp[gen4.EXP_TMP_MOVE]
            self._forget = move_to_forget(mon.moves, romdata.species(mon.species).types, new)
            self.learned.append({"pid": mon.pid, "move": romdata.move_name(new),
                                 "forgot": None if self._forget is None else romdata.move_name(mon.moves[self._forget])})
            self._tap_until_moved([UPPER_BUTTON if self._forget is not None else LOWER_BUTTON], seq, SETTLE)
        elif seq == EXP_FORGET_SELECT:
            self._tap_until_moved([FORGET_SLOTS[self._forget], FORGET_BUTTON], seq, 2 * SETTLE)
        elif seq == EXP_GIVE_UP_PROMPT:
            self._tap_until_moved([UPPER_BUTTON], seq, SETTLE)

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
            self._answer_task()
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
                    self._await_result()
                    return Event.LOST if all(m.hp == 0 for m in self.snap.player) else Event.WON
        raise _Stuck

    def _await_result(self):
        """A side reads 0 HP, but the turn may not be over: Selfdestruct zeroes its user's HP
        before its blast lands, about 200 frames later. Run on until the game records the
        result, keeping the last snapshot, so every faint of the turn is counted. Stops early
        if the battle memory is freed first, or after END_FRAME_GUARD frames. A snapshot that
        reads invalid while the battle runs is skipped: the game decrypts a party struct in
        place while it writes it, as when it adds the exp after a win. A level-up's text holds
        the result until it is answered (_answer_exp_task)."""
        start, gone = self._frames, 0
        while not self.result_mask and self._frames - start < END_FRAME_GUARD:
            self._answer_task()
            self._tick(SNAPSHOT_EVERY)
            snap = read_snapshot(self.nds, self.addrs)
            if snap is None:
                gone = 0 if gen4.in_battle(self.nds, self.addrs) else gone + 1
                if gone >= ENDED_CHECKS:
                    return
                continue
            gone = 0
            self.snap = snap
            self.result_mask = self.nds.memory.read_u8(False, self.addrs["battleResult"])

    def _info(self, **extra) -> dict:
        return {"action_mask": action_mask(self.snap, self.forced, self._can_throw()), "state": self.state_name,
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
        self.catch_allowed = bool(options.get("catch"))     # set by the caller from the rules: this encounter may be caught
        if options.get("attach"):                           # a battle already running in self.nds
            self.state_name = "attached"
        else:
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
        self.snap, self.learned, self._forget = None, [], None
        self._throwing = self._catch_seen = False
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
        mask = action_mask(self.snap, self.forced, self._can_throw())
        if not 0 <= action < N_ACTIONS or not mask[action]:
            raise ValueError(f"action {action} is masked: {mask.tolist()}")
        prev, forced, fight_only = self.snap, self.forced, fights_at_once(self.snap)
        chosen = decision(prev, action, forced)
        target = prev.player[prev.slots()[action - 3]].pid if 4 <= action < BALL_ACTION else None
        self.turn += not forced
        self._frames = 0
        events, end = [], None
        try:
            if action == BALL_ACTION:
                self._throwing, self._catch_seen = True, False
                self._throw_ball()
            else:
                for screen in route_for(action, forced, fight_only):
                    self._walk(screen)
            end = self._run_to_prompt()
        except _Stuck:
            events.append(Event.STUCK)
        finally:
            self._throwing = False
        if Event.STUCK not in events:
            events += events_between(prev, self.snap)
            if end is Event.ENDED and not _wiped(self.snap):
                events.append({gen4.RESULT_FLED: Event.FLED, gen4.RESULT_CAUGHT: Event.CAUGHT}.get(
                    self.result_mask, Event.ENDED))
            elif end is None and self.turn >= self.turn_cap:
                events.append(Event.TURN_CAP)
        reward = sum((REWARDS[e] for e in events if e is not Event.PLAYER_FAINTED), 0.0)
        if Event.STUCK not in events:
            reward += faint_penalty(prev, self.snap)
        self.ret += reward
        stuck = Event.STUCK in events
        terminated = not stuck and (_wiped(self.snap) or any(e in events for e in (Event.FLED, Event.CAUGHT, Event.ENDED, Event.TURN_CAP)))
        self._done = terminated or stuck
        names = [e.name for e in events]
        info = self._info(events=names, frames=self._frames, **chosen,
                          fainted_strengths=[] if stuck else fainted_strengths(prev, self.snap))
        if target is not None and not stuck and self.snap.player_active is not None:
            info["switched_in"] = self.snap.player[self.snap.player_active].pid == target
        self._write({
            "episode": self.episode_id, "state": os.path.basename(self.state_name),
            "rng_seed": self.rng_seed, "turn": self.turn, "action": action, "forced": forced,
            **chosen, "events": names, "reward": reward, "player_hp": [m.hp for m in self.snap.player],
            "enemy_hp": [m.hp for m in self.snap.enemy], "frames": self._frames,
            **({"signal": self._stuck_signal()} if stuck else {})})
        if self._done:
            outcome = next(e.name for e in (Event.WON, Event.LOST, Event.TURN_CAP, Event.FLED, Event.CAUGHT, Event.ENDED, Event.STUCK)
                           if e in events)
            info["outcome"], info["learned"] = outcome, self.learned
            self._write({"episode": self.episode_id, "summary": True, "outcome": outcome,
                         "turns": self.turn, "return": self.ret, "frames": self._ep_frames,
                         "result_mask": self.result_mask, "learned": self.learned})
        return self._obs(), reward, terminated, stuck, info
