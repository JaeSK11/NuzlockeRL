"""Battle-scenario generator for Platinum Kaizo.

Writes a chosen player party into RAM while the player stands in Route 201
grass, walks until a wild battle starts, and saves a state at the first command
prompt. No hand-playing. See scripts/make_scenario.py for the command line.

Struct layout: docs/RAM_MAP.md and the decomp's include/struct_defs/pokemon.h.
A Pokémon is held as a flat 228-byte plaintext (blocks A, B, C, D in canonical
order, then the 100 bytes of battle stats), so encoding is the exact inverse of
gen4.decode_mon for every byte, not only the fields gen4.Mon exposes.
"""
import itertools, json, os, random, struct, sys
from dataclasses import dataclass

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pynds

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import drive
import gen4
import romdata as R

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ROM = R.ROM_PATH
START_STATE = os.path.join(ROOT, "states/milestones/04_after_barry1_home.state")
GRASS_STATE = os.path.join(ROOT, "states/generated/route201_grass.state")
WALK_SCRIPT = os.path.join(ROOT, "scripts/milestones/05_route201_wild_battle.txt")

MAX_SPECIES = 493
PARTY_SLOTS = 6
ENCOUNTER_OFFSET = 0x233E4      # from gen4's version pointer: the current map's wild table, copied out of the ROM's wild encounter data
# Battle states are saved this many frames before the first command selection, where the enemy
# picks its turn-1 move. A state saved on the frame the selection begins reloads differently
# after another battle has run in the same emulator; 1 to 60 frames earlier reloads the same.
SAVE_MARGIN = 10
# The enemy's BattleMon, BattleContext.battleMons[1] (layout in RAM_MAP.md, include/battle/battle_mon.h)
ENEMY_BATTLE_MON = 0x2E00
BM_MOVES, BM_PP_CUR, BM_PP_UPS, BM_HELD_ITEM = 0xC, 0x2C, 0x30, 0x78

# (struct format, offset) into the 228-byte plaintext. Block A at 0, B at 32, C at 64, D at 96, battle stats at 128.
FIELDS = {
    "species": ("<H", 0), "item": ("<H", 2), "ot_id": ("<I", 4), "exp": ("<I", 8),
    "friendship": ("B", 12), "ability": ("B", 13), "markings": ("B", 14), "language": ("B", 15),
    "evs": ("6B", 16), "contest": ("6B", 22), "ribbons1": ("<I", 28),
    "moves": ("<4H", 32), "pp": ("4B", 40), "pp_ups": ("4B", 44), "iv_word": ("<I", 48),
    "ribbons_gba": ("<I", 52), "form_byte": ("B", 56), "unused1": ("B", 57), "unused2": ("<H", 58),
    "egg_loc_pt": ("<H", 60), "met_loc_pt": ("<H", 62),
    "nickname": ("<11H", 64), "unused_c": ("B", 86), "origin_game": ("B", 87), "ribbons2": ("<Q", 88),
    "ot_name": ("<8H", 96), "egg_date": ("3B", 112), "met_date": ("3B", 115),
    "egg_loc_dp": ("<H", 118), "met_loc_dp": ("<H", 120), "pokerus": ("B", 122), "ball": ("B", 123),
    "met_level_otgender": ("B", 124), "met_terrain": ("B", 125), "unused_d": ("<H", 126),
    "status": ("<I", 128), "level": ("B", 132), "capsule_id": ("B", 133),
    "hp": ("<H", 134), "max_hp": ("<H", 136), "stats": ("<5H", 138), "tail": ("80B", 148),
}
PLAIN_SIZE = 228


@dataclass
class MonData:
    pid: int
    flags: int                  # u16 at struct offset 4, always 0 in real structs
    data: bytearray

    def __getitem__(self, name):
        fmt, off = FIELDS[name]
        v = struct.unpack_from(fmt, self.data, off)
        return v[0] if len(v) == 1 else list(v)

    def __setitem__(self, name, value):
        fmt, off = FIELDS[name]
        struct.pack_into(fmt, self.data, off, *(value if isinstance(value, (list, tuple)) else [value]))

    @property
    def ivs(self) -> list[int]:
        w = self["iv_word"]
        return [(w >> (5 * i)) & 31 for i in range(6)]


def parse_mon(raw: bytes) -> MonData:
    """The 236-byte party struct as plaintext. Raises if the checksum fails."""
    pid, flags, checksum = struct.unpack_from("<IHH", raw)
    blocks = gen4._crypt(raw[8:136], checksum)
    if sum(struct.unpack("<64H", blocks)) & 0xFFFF != checksum:
        raise ValueError("checksum mismatch")
    order = gen4.BLOCK_ORDERS[((pid & 0x3E000) >> 13) % 24]
    canon = {letter: blocks[32 * i:32 * (i + 1)] for i, letter in enumerate(order)}
    plain = b"".join(canon[c] for c in "ABCD") + gen4._crypt(raw[136:236], pid)
    return MonData(pid, flags, bytearray(plain))


def encode_mon(mon: MonData) -> bytes:
    """Inverse of parse_mon, and of gen4.decode_mon for every field it reads."""
    abcd = bytes(mon.data[:128])
    checksum = sum(struct.unpack("<64H", abcd)) & 0xFFFF
    if checksum == 0:
        raise ValueError("checksum 0 reads as an empty slot; change the PID or a stat")
    order = gen4.BLOCK_ORDERS[((mon.pid & 0x3E000) >> 13) % 24]
    shuffled = b"".join(abcd[32 * "ABCD".index(c):32 * "ABCD".index(c) + 32] for c in order)
    return (struct.pack("<IHH", mon.pid, mon.flags, checksum) + gen4._crypt(shuffled, checksum)
            + gen4._crypt(bytes(mon.data[128:]), mon.pid))


def gender_of(pid: int, ratio: int) -> int:
    """0 male, 1 female, 2 genderless."""
    if ratio == 255:
        return 2
    return 1 if ratio == 254 or (ratio and (pid & 0xFF) < ratio) else 0


def is_shiny(pid: int, ot_id: int) -> bool:
    return ((ot_id & 0xFFFF) ^ (ot_id >> 16) ^ (pid >> 16) ^ (pid & 0xFFFF)) < 8


@dataclass(frozen=True)
class Trainer:
    """Original-trainer fields. Copy the real player's so the Pokémon are not treated as traded."""
    ot_id: int = 0
    ot_name: tuple = (0xFFFF,) + (0,) * 7
    language: int = 2
    origin_game: int = 12

    @classmethod
    def from_mon(cls, mon: MonData) -> "Trainer":
        return cls(mon["ot_id"], tuple(mon["ot_name"]), mon["language"], mon["origin_game"])


def _per_stat(value, name: str) -> list[int]:
    v = [value] * 6 if isinstance(value, int) else list(value)
    if len(v) != 6:
        raise ValueError(f"{name} needs one int or six (hp, atk, def, spe, spa, spd)")
    return v


def build_mon(species: int, level: int, moves, *, pid=None, ivs=31, evs=0, nature=None,
              ability_slot=None, item=0, trainer: Trainer | None = None,
              rng: random.Random | None = None) -> MonData:
    """A full-HP Pokémon with stats, PP and EXP computed from the hack's tables.
    A random PID is non-shiny and honors `nature` (0..24) and `ability_slot` (0/1)."""
    if not 1 <= species <= MAX_SPECIES:
        raise ValueError(f"species {species} outside 1..{MAX_SPECIES}")
    sp = R.species(species)
    if not 1 <= level <= 100:
        raise ValueError(f"level {level} outside 1..100")
    moves = list(moves)
    if not 1 <= len(moves) <= 4:
        raise ValueError("1 to 4 moves")
    ivs, evs = _per_stat(ivs, "ivs"), _per_stat(evs, "evs")
    t = trainer or Trainer()
    if pid is None:
        rng = rng or random.Random()
        while True:
            pid = rng.getrandbits(32)
            if ((nature is None or pid % 25 == nature) and (ability_slot is None or pid & 1 == ability_slot)
                    and not is_shiny(pid, t.ot_id)):
                break
    nature = pid % 25
    m = MonData(pid, 0, bytearray(PLAIN_SIZE))
    m["species"], m["item"], m["ot_id"] = species, item, t.ot_id
    m["exp"] = R.exp_for_level(species, level)
    m["friendship"] = sp.base_friendship
    m["ability"] = sp.abilities[pid & 1] or sp.abilities[0]
    m["language"], m["origin_game"], m["ot_name"] = t.language, t.origin_game, t.ot_name
    m["evs"] = evs
    m["moves"] = moves + [0] * (4 - len(moves))
    m["pp"] = [R.move(mv).pp if mv else 0 for mv in m["moves"]]
    m["iv_word"] = sum(v << (5 * i) for i, v in enumerate(ivs))
    m["form_byte"] = gender_of(pid, sp.gender_ratio) << 1
    name = R.species_name_codes(species)[:10]
    m["nickname"] = name + [0xFFFF] + [0] * (10 - len(name))
    m["ball"] = 4
    m["met_level_otgender"] = level
    stats = R.calc_stats(species, level, ivs, evs, nature)
    m["level"], m["hp"], m["max_hp"], m["stats"] = level, stats[0], stats[0], stats[1:]
    return m


def write_party(nds, mons: list[MonData]) -> None:
    """Write the party and its count. The u32 before playerBase is Party.currentCount,
    and the u32 before that is its capacity (6)."""
    if not 1 <= len(mons) <= PARTY_SLOTS:
        raise ValueError(f"party of 1 to {PARTY_SLOTS}")
    base = gen4.resolve(nds)["playerBase"]
    blob = b"".join(encode_mon(m) for m in mons).ljust(PARTY_SLOTS * gen4.PARTY_MON_SIZE, b"\0")
    for i in range(0, len(blob), 4):
        nds.memory.write_u32(False, base + i, int.from_bytes(blob[i:i + 4], "little"))
    nds.memory.write_u32(False, base - 4, len(mons))


def _box_addr(nds, slot: tuple[int, int]) -> int:
    return gen4.resolve(nds)["pcBoxes"] + 4 + (slot[0] * gen4.BOX_SLOTS + slot[1]) * gen4.BOX_MON_SIZE


def from_box(raw: bytes) -> MonData:
    """A box slot's 136 bytes as a party Pokémon, as the PC's withdraw makes it: the level from
    its EXP, the stats from the hack's tables, full HP and no status."""
    m = parse_mon(bytes(raw[:gen4.BOX_MON_SIZE]).ljust(gen4.PARTY_MON_SIZE, b"\0"))
    m.data[128:] = bytes(PLAIN_SIZE - 128)
    level = R.level_for_exp(m["species"], m["exp"])
    stats = R.calc_stats(m["species"], level, m.ivs, m["evs"], m.pid % 25)
    m["level"], m["hp"], m["max_hp"], m["stats"] = level, stats[0], stats[0], stats[1:]
    return m


def read_box_data(nds) -> dict[tuple[int, int], MonData]:
    """Every Pokémon in the PC by (box, slot), in box order, as from_box makes it."""
    size = gen4.BOX_MON_SIZE
    raw = gen4.read_bytes(nds, _box_addr(nds, (0, 0)), gen4.PC_BOXES * gen4.BOX_SLOTS * size)
    mons = {}
    for n in range(gen4.PC_BOXES * gen4.BOX_SLOTS):
        chunk = raw[n * size:(n + 1) * size]
        if struct.unpack_from("<I", chunk)[0] or struct.unpack_from("<H", chunk, 6)[0]:   # gen4.read_box's empty test
            mons[divmod(n, gen4.BOX_SLOTS)] = from_box(chunk)
    return mons


def pc_swap(nds, leave: list[int], take=()) -> list[tuple[int, int]]:
    """Deposit the party Pokémon in slots `leave` into the first empty PC box slots, and withdraw
    the box Pokémon at the (box, slot)s `take` into the party after the ones that stay, as the
    PC's deposit and withdraw do. Both at once, so the party never runs empty. A box slot holds
    the party struct's first 136 bytes, encrypted the same way. Returns the (box, slot) each
    deposit went to. Not the PC's screens: the runner's stand-in until they are mapped."""
    party, boxed = read_party_data(nds), read_box_data(nds)
    team = [m for k, m in enumerate(party) if k not in leave] + [boxed[s] for s in take]
    if not 1 <= len(team) <= PARTY_SLOTS:
        raise ValueError(f"leaving {leave} and taking {list(take)} would make a party of {len(team)}")
    for s in take:
        for i in range(0, gen4.BOX_MON_SIZE, 4):
            nds.memory.write_u32(False, _box_addr(nds, s) + i, 0)
    empty = [s for s in ((b, i) for b in range(gen4.PC_BOXES) for i in range(gen4.BOX_SLOTS)) if s not in boxed]
    placed = []
    for k, slot in zip(sorted(leave), empty):
        box_mon = encode_mon(party[k])[:gen4.BOX_MON_SIZE]
        for i in range(0, len(box_mon), 4):
            nds.memory.write_u32(False, _box_addr(nds, slot) + i, int.from_bytes(box_mon[i:i + 4], "little"))
        placed.append(slot)
    write_party(nds, team)
    return placed


def deposit(nds, slots: list[int]) -> list[tuple[int, int]]:
    """Move the party Pokémon in `slots` into the first empty PC box slots (pc_swap)."""
    if not slots:
        raise ValueError("no Pokémon to deposit")
    return pc_swap(nds, slots)


def read_party_data(nds) -> list[MonData]:
    base = gen4.resolve(nds)["playerBase"]
    count = nds.memory.read_u32(False, base - 4)
    raw = gen4.read_bytes(nds, base, gen4.PARTY_MON_SIZE * PARTY_SLOTS)
    return [parse_mon(raw[i * gen4.PARTY_MON_SIZE:(i + 1) * gen4.PARTY_MON_SIZE]) for i in range(count)]


def set_wild_encounter(nds, species: int, level: int) -> None:
    """Make every grass encounter this species and level. The table is u32 rate, then 12
    (level, species) u32 pairs, then swarm/day/night species that replace slots 2 and 3."""
    if not 1 <= species <= MAX_SPECIES or not 1 <= level <= 100:
        raise ValueError(f"enemy {species} Lv{level} out of range")
    t = gen4.resolve(nds)["_version"] + ENCOUNTER_OFFSET
    rd = lambda off: nds.memory.read_u32(False, t + off)
    if not (0 < rd(0) <= 100 and all(1 <= rd(8 + 8 * k) <= MAX_SPECIES for k in range(12))):
        raise RuntimeError("no wild encounter table at the expected address; is the player on a route?")
    for k in range(12):
        nds.memory.write_u32(False, t + 4 + 8 * k, level)
        nds.memory.write_u32(False, t + 8 + 8 * k, species)
    for k in range(6):
        nds.memory.write_u32(False, t + 100 + 4 * k, species)


def set_enemy_moves(nds, moves, item: int | None = None) -> None:
    """Give the wild enemy these moves (up to 4 ids) at full PP, and a held item if given. Both
    copies the battle keeps are written: its BattleMon, which the battle and the enemy's AI use,
    and its party struct in enemyBase, which the game later updates from the BattleMon. Call it
    in battle, before any move is chosen."""
    moves = list(moves) + [0] * (4 - len(moves))
    if len(moves) != 4 or not any(moves):
        raise ValueError(f"need 1 to 4 moves, got {moves}")
    pp = [R.move(m).pp if m else 0 for m in moves]
    addrs = gen4.resolve(nds)
    ctx = nds.memory.read_u32(False, addrs["battleCtxPtr"])
    if not gen4.in_battle(nds, addrs) or not gen4.MAIN_RAM <= ctx < gen4.MAIN_RAM + 0x400000:
        raise RuntimeError("no battle is running")
    mon = parse_mon(gen4.read_bytes(nds, addrs["enemyBase"], gen4.PARTY_MON_SIZE))
    mon["moves"], mon["pp"], mon["pp_ups"] = moves, pp, [0] * 4
    if item is not None:
        mon["item"] = item
    for i, b in enumerate(encode_mon(mon)):
        nds.memory.write_u8(False, addrs["enemyBase"] + i, b)
    bm = ctx + ENEMY_BATTLE_MON
    for i in range(4):
        nds.memory.write_u16(False, bm + BM_MOVES + 2 * i, moves[i])
        nds.memory.write_u8(False, bm + BM_PP_CUR + i, pp[i])
        nds.memory.write_u8(False, bm + BM_PP_UPS + i, 0)
    if item is not None:
        nds.memory.write_u16(False, bm + BM_HELD_ITEM, item)


def ensure_grass_state(rom: str = DEFAULT_ROM, path: str = GRASS_STATE) -> str:
    """The overworld state in Route 201 grass: the milestone script up to the first step into the grass."""
    if os.path.exists(path):
        return path
    with open(WALK_SCRIPT) as f:
        script = " ".join(line for line in f.read().splitlines() if not line.startswith("#"))
    approach, step, _ = script.partition(" hold:right:48")
    nds = pynds.PyNDS(rom)
    nds.load_state_from_file(START_STATE)
    nds.tick(2)
    drive.run(nds, approach + step + " w20")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    nds.save_state_to_file(path)
    return path


def _walk(nds, key: str, frames: int, addrs: dict) -> bool:
    """Hold `key`, return True as soon as a battle starts."""
    nds.button.press_key(key)
    try:
        for _ in range(frames // 2):
            nds.tick(2)
            if gen4.in_battle(nds, addrs):
                return True
    finally:
        nds.button.release_key(key)
    nds.tick(4)
    return False


def start_wild_battle(nds, stop_at: int | None = None, max_walk_frames: int = 20000,
                      max_intro_frames: int = 3000) -> tuple[int, int]:
    """Pace right and left in the grass until a wild battle starts, then run the intro until the
    first command selection is about to begin (BattleContext.command reads INIT_COMMAND_SELECTION,
    12 frames before the prompt), or until `stop_at` intro frames. Returns (walk frames, intro
    frames). The enemy picks its turn-1 move during command selection, so a state saved before it
    leaves that pick to the battle seed the env writes after loading; a state saved at the prompt
    fixed it."""
    addrs = gen4.resolve(nds)
    walk = 0
    for key in itertools.cycle(("right", "left")):
        if _walk(nds, key, 32, addrs):
            break
        walk += 36
        if walk > max_walk_frames:
            raise RuntimeError(f"no wild battle in {max_walk_frames} frames")
    addrs = gen4.resolve(nds)
    for intro in range(1, max_intro_frames + 1):
        nds.tick()
        if intro == stop_at:
            return walk, intro
        c = gen4.read_battle_command(nds, addrs)
        if c and c[0] == gen4.CMD_INIT_COMMAND_SELECTION and gen4.in_battle(nds, addrs):
            if stop_at is not None:
                raise RuntimeError(f"command selection began at intro frame {intro}, before {stop_at}")
            return walk, intro
    raise RuntimeError("battle started but never reached its first command selection")


def mons_from_spec(spec: list[dict], trainer: Trainer, rng: random.Random) -> list[MonData]:
    """spec items: {species, level, moves, and optional pid, ivs, evs, nature, ability_slot, item,
    exp}. exp replaces the level's starting EXP, for a Pokémon close to its next level."""
    mons = []
    for s in spec:
        m = build_mon(s["species"], s["level"], s["moves"], trainer=trainer, rng=rng,
                      **{k: s[k] for k in ("pid", "ivs", "evs", "nature", "ability_slot", "item") if k in s})
        if "exp" in s:
            m["exp"] = s["exp"]
        mons.append(m)
    return mons


def make_scenario(party_spec: list[dict], out_path: str, seed: int = 0, rom: str = DEFAULT_ROM,
                  base_state: str | None = None, enemy: tuple[int, int] | None = None,
                  enemy_moves: list[int] | None = None, enemy_item: int | None = None) -> dict:
    """Save a battle state SAVE_MARGIN frames before the first command selection of a wild
    battle fought with the given party; the env's reset runs it on to the first prompt. The
    battle is played twice from the same start, which the emulator repeats exactly: once to find
    the frame the selection begins, once to stop short of it. `seed` picks the PIDs and how long
    the player idles first, which changes the encounter. `enemy=(species, level)` forces every
    grass encounter to it. `enemy_moves` and `enemy_item` replace the enemy's own level-up moves
    and held item (set_enemy_moves), before it picks its first move.
    Writes out_path and out_path + '.json'. Returns the JSON record."""
    def battle(stop_at=None):
        rng = random.Random(seed)
        nds = pynds.PyNDS(rom)
        nds.load_state_from_file(base_state or ensure_grass_state(rom))
        nds.tick(2)
        trainer = Trainer.from_mon(read_party_data(nds)[0])
        write_party(nds, mons_from_spec(party_spec, trainer, rng))
        if enemy:
            set_wild_encounter(nds, *enemy)
        nds.tick(rng.randrange(120))
        return nds, start_wild_battle(nds, stop_at)
    _, (_, selection) = battle()
    nds, (walk, intro) = battle(selection - SAVE_MARGIN)
    frames = walk + intro
    addrs = gen4.resolve(nds)
    if enemy_moves is not None or enemy_item is not None:
        own = gen4.read_party(nds, addrs["enemyBase"])[0].moves
        set_enemy_moves(nds, enemy_moves if enemy_moves is not None else own, enemy_item)
    foe = gen4.read_party(nds, addrs["enemyBase"])[0]
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    nds.save_state_to_file(out_path)
    record = {"party": party_spec, "seed": seed, "forced_enemy": enemy, "frames": frames,
              "enemy": {"species": foe.species, "level": foe.level, "moves": foe.moves, "item": foe.item}}
    with open(out_path + ".json", "w") as f:
        json.dump(record, f, indent=1)
    return record


def check_state(path: str, rom: str = DEFAULT_ROM) -> str:
    """"ok" if a fresh env reaches a decision from this state and its first tap registers,
    else why not. Training stops on any worker error, so check a state before a run uses it."""
    from battle_env import BattleEnv    # imported here: the env isn't needed to build states
    env = BattleEnv([path], rom)
    try:
        _, info = env.reset(seed=0)
        _, _, _, truncated, _ = env.step(next(i for i, ok in enumerate(info["action_mask"]) if ok))
        return "the first tap didn't register (STUCK)" if truncated else "ok"
    except Exception as e:
        return f"{type(e).__name__}: {e}"
    finally:
        env.close()
