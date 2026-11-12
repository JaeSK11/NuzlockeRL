"""Game data read straight out of the Kaizo ROM: species, moves, learnsets,
evolutions, trainers, wild encounters and names. The formats are the retail
Platinum ones (pret/pokeplatinum include/struct_defs/*.h); the values are
whatever the hack put there.

Every loader parses its whole table on first use and caches it, so ids index
into already-built tuples. The ROM is read from $NUZLOCKERL_ROM or
roms/plat-kaizo-nightmare-update-final.nds.

Species ids 0..493 are the national dex, 494 is the egg, 495 is Bad Egg and
496..507 are alternate-form entries. Move ids run 0..467.
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from functools import cache

import ndspy.narc
import ndspy.rom

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROM_PATH = os.environ.get("NUZLOCKERL_ROM", os.path.join(ROOT, "roms/plat-kaizo-nightmare-update-final.nds"))

STATS = ("hp", "atk", "def", "spe", "spa", "spd")   # the ROM's order, not the in-game menu order
TYPE_NAMES = ("Normal", "Fighting", "Flying", "Poison", "Ground", "Rock", "Bug", "Ghost", "Steel", "???",
              "Fire", "Water", "Grass", "Electric", "Psychic", "Ice", "Dragon", "Dark")
GROWTH_RATES = ("medium_fast", "erratic", "fluctuating", "medium_slow", "fast", "slow")
MOVE_CLASSES = ("physical", "special", "status")
MOVE_FLAGS = ("makes_contact", "can_protect", "can_magic_coat", "can_snatch",
              "can_mirror_move", "triggers_kings_rock", "hides_hp_gauges", "hides_shadows")
MOVE_RANGES = {0: "single_target", 1: "single_target_special", 2: "random_opponent", 4: "adjacent_opponents",
               8: "all_adjacent", 0x10: "user", 0x20: "user_side", 0x40: "field", 0x80: "opponent_side",
               0x100: "ally", 0x200: "user_or_ally", 0x400: "single_target_me_first"}   # Move.target is one of these masks
AI_FLAGS = ("basic", "eval_attack", "expert", "setup_first_turn", "risky", "prioritize_extremes",
            "baton_pass", "tag_strategy", "check_hp", "weather", "harrassment")
EVO_METHODS = ("none", "level_happiness", "level_happiness_day", "level_happiness_night", "level", "trade",
               "trade_with_held_item", "use_item", "level_atk_gt_def", "level_atk_eq_def", "level_atk_lt_def",
               "level_pid_low", "level_pid_high", "level_ninjask", "level_shedinja", "level_beauty",
               "use_item_male", "use_item_female", "level_with_held_item_day", "level_with_held_item_night",
               "level_know_move", "level_species_in_party", "level_male", "level_female",
               "level_magnetic_field", "level_moss_rock", "level_ice_rock")
GRASS_SLOT_PERCENT = (20, 20, 10, 10, 10, 10, 5, 5, 4, 4, 1, 1)
WATER_SLOT_PERCENT = {"surf": (60, 30, 5, 4, 1), "old_rod": (60, 30, 5, 4, 1),
                      "good_rod": (40, 40, 15, 4, 1), "super_rod": (40, 40, 15, 4, 1)}

# Retail's sTrainerClassGender (female entries). The trainer's PID depends on it.
_FEMALE_TRAINER_CLASSES = frozenset({1, 3, 5, 7, 8, 10, 13, 17, 18, 21, 22, 25, 26, 30, 33, 35, 36, 40, 43, 45, 50,
                                     54, 56, 61, 66, 69, 72, 74, 76, 77, 78, 80, 84, 85, 87, 88, 89, 90, 92, 94,
                                     96, 98, 99, 101, 104})

# Offset of the MapHeader table (24 bytes per entry) inside the decompressed ARM9. Found by matching
# 593 header fields against the decomp; the reader below rejects it if the table stops looking right.
_MAP_HEADER_OFFSET = 942108
_MAP_HEADER_COUNT = 593
_NO_ENCOUNTERS = 0xFFFF


def _u16(b, o): return struct.unpack_from("<H", b, o)[0]
def _u32(b, o): return struct.unpack_from("<I", b, o)[0]


@cache
def _rom() -> ndspy.rom.NintendoDSRom:
    return ndspy.rom.NintendoDSRom.fromFile(ROM_PATH)


@cache
def _narc(path: str) -> tuple[bytes, ...]:
    return tuple(bytes(f) for f in ndspy.narc.NARC(_rom().getFileByName(path)).files)


@dataclass(frozen=True, slots=True)
class Species:
    id: int
    name: str
    base_stats: tuple[int, ...]       # STATS order
    types: tuple[int, int]            # TYPE_NAMES indices; equal when single-typed
    abilities: tuple[int, int]        # 0 = none
    growth_rate: int                  # index into GROWTH_RATES
    catch_rate: int
    base_exp: int
    gender_ratio: int                 # female threshold out of 254; 0 male only, 254 female only, 255 genderless
    ev_yield: tuple[int, ...]         # STATS order
    held_items: tuple[int, int]       # common, rare
    egg_groups: tuple[int, int]
    base_friendship: int
    hatch_cycles: int
    tm_mask: int                      # 128 bits, bit i = TM/HM i+1 (92 TMs then 8 HMs)

    @property
    def ability_names(self) -> tuple[str, str]:
        return tuple(ability_name(a) for a in self.abilities)


@dataclass(frozen=True, slots=True)
class Move:
    id: int
    name: str
    type: int
    cls: int                          # index into MOVE_CLASSES
    power: int
    accuracy: int
    pp: int
    priority: int
    effect: int                       # battle effect id (decomp enum BattleEffect)
    effect_chance: int
    target: int                       # key of MOVE_RANGES
    flags: int                        # bitmask over MOVE_FLAGS

    def flag_names(self) -> tuple[str, ...]:
        return tuple(n for i, n in enumerate(MOVE_FLAGS) if self.flags >> i & 1)


@dataclass(frozen=True, slots=True)
class Evolution:
    method: int                       # index into EVO_METHODS
    param: int                        # level, item id, move id or species id, by method
    target: int


@dataclass(frozen=True, slots=True)
class TrainerMon:
    species: int
    form: int
    level: int
    iv_scale: int                     # 0..255; the game uses iv_scale * 31 // 255 for every IV
    item: int | None                  # None when the data format has no item field
    moves: tuple[int, ...] | None     # None when the data format has no move field: use default_moves()
    ball_seal: int

    @property
    def iv(self) -> int:
        return self.iv_scale * 31 // 255


@dataclass(frozen=True, slots=True)
class Trainer:
    id: int
    name: str
    class_id: int
    class_name: str
    ai_flags: int                     # bitmask over AI_FLAGS
    double_battle: bool
    items: tuple[int, ...]
    party: tuple[TrainerMon, ...]

    def ai_flag_names(self) -> tuple[str, ...]:
        return tuple(n for i, n in enumerate(AI_FLAGS) if self.ai_flags >> i & 1)

    def mon_pid(self, i: int) -> int:
        """Personality value the game gives party member i (src/trainer_data.c, TrainerData_BuildParty).
        PID % 25 is the nature."""
        m = self.party[i]
        seed = (m.iv_scale + m.level + m.species + self.id) & 0xFFFFFFFF
        rnd = seed
        for _ in range(self.class_id):
            seed = (seed * 0x41C64E6D + 0x6073) & 0xFFFFFFFF
            rnd = seed >> 16
        return ((rnd << 8) + (120 if self.class_id in _FEMALE_TRAINER_CLASSES else 136)) & 0xFFFFFFFF


@dataclass(frozen=True, slots=True)
class GrassSlot:
    level: int
    species: int


@dataclass(frozen=True, slots=True)
class WaterSlot:
    min_level: int
    max_level: int
    species: int


@dataclass(frozen=True, slots=True)
class WaterTable:
    rate: int
    slots: tuple[WaterSlot, ...]


@dataclass(frozen=True, slots=True)
class Encounters:
    id: int
    grass_rate: int
    grass: tuple[GrassSlot, ...]      # 12 slots, odds in GRASS_SLOT_PERCENT
    swarm: tuple[int, ...]            # species lists. The decomp (overlay006/wild_encounters.c) swaps swarm into
                                      # grass slots 0 and 1 on the swarm's map, day or night into slots 2 and 3.
    day: tuple[int, ...]
    night: tuple[int, ...]
    radar: tuple[int, ...]
    surf: WaterTable
    old_rod: WaterTable
    good_rod: WaterTable
    super_rod: WaterTable

    def grass_species(self, time_of_day: str = "morning") -> tuple[int, ...]:
        """The 12 grass slots' species at "morning" (the stored default), "day" or "night"."""
        sp = [g.species for g in self.grass]
        timed = {"morning": None, "day": self.day, "night": self.night}[time_of_day]
        if timed:
            sp[2], sp[3] = timed
        return tuple(sp)


def _decode_text(b: bytes) -> list[str]:
    """One text bank (msgdata/pl_msg.narc member): per-message XOR keys, 16-bit characters."""
    count, seed = struct.unpack_from("<HH", b, 0)
    k1 = seed * 0x2FD & 0xFFFF
    out = []
    for i in range(count):
        k2 = k1 * (i + 1) & 0xFFFF
        k2 |= k2 << 16
        off, length = _u32(b, 4 + 8 * i) ^ k2, _u32(b, 8 + 8 * i) ^ k2
        key = 0x91BD3 * (i + 1) & 0xFFFF
        words = []
        for j in range(length):
            words.append(_u16(b, off + 2 * j) ^ key)
            key = key + 0x493D & 0xFFFF
        out.append(_words_to_str(words))
    return out


def _words_to_str(words: list[int]) -> str:
    if words and words[0] == 0xF100 and all(w < 0x200 for w in words[1:-1]):   # name stored unpacked (guess: a packed word is never this small)
        words = words[1:]
    elif words and words[0] == 0xF100:          # retail trainer names: 9-bit characters packed 15 bits per word
        bits = 0
        stream = 0
        chars = []
        for w in words[1:]:
            stream |= (w & 0x7FFF) << bits
            bits += 15
            while bits >= 9:
                chars.append(stream & 0x1FF)
                stream >>= 9
                bits -= 9
        words = []
        for c in chars:
            if c == 0x1FF:
                break
            words.append(c)
        return "".join(_char(c) for c in words)
    s, j = [], 0
    while j < len(words) and words[j] != 0xFFFF:
        if words[j] == 0xFFFE:                  # control code: id, argument count, arguments
            s.append("{}")
            j += 3 + words[j + 2]
            continue
        s.append(_char(words[j]))
        j += 1
    return "".join(s)


_LATIN1 = "ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖ×ØÙÚÛÜÝÞßàáâãäåæçèéêëìíîïðñòóôõö÷øùúûüýþÿ"
_PUNCT = {0x1AB: "!", 0x1AC: "?", 0x1AD: ",", 0x1AE: ".", 0x1AF: "…", 0x1B1: "/", 0x1B2: "‘", 0x1B3: "’",
          0x1B4: "“", 0x1B5: "”", 0x1B9: "(", 0x1BA: ")", 0x1BB: "♂", 0x1BC: "♀", 0x1BD: "+", 0x1BE: "-",
          0x1C0: "#", 0x1C1: "=", 0x1C2: "&", 0x1C4: ":", 0x1C5: ";", 0x1DE: " ", 0x1E0: "Pk", 0x1E1: "Mn", 0xE000: "\n", 0x25BC: "\n"}


def _char(c: int) -> str:
    if 0x121 <= c <= 0x12A: return chr(ord("0") + c - 0x121)
    if 0x12B <= c <= 0x144: return chr(ord("A") + c - 0x12B)
    if 0x145 <= c <= 0x15E: return chr(ord("a") + c - 0x145)
    if 0x15F <= c <= 0x15F + len(_LATIN1) - 1: return _LATIN1[c - 0x15F]
    return _PUNCT.get(c, "�")


@cache
def _text(bank: int) -> tuple[str, ...]:
    return tuple(_decode_text(_narc("msgdata/pl_msg.narc")[bank]))


def _name(bank: int, i: int) -> str:
    t = _text(bank)
    return t[i] if 0 <= i < len(t) else ""


def species_name(i: int) -> str:
    n = _name(412, i)                          # stored in capitals
    return "".join(c if k == 0 or n[k - 1] in " .-" else c.lower() for k, c in enumerate(n))


def move_name(i: int) -> str: return _name(647, i)
def ability_name(i: int) -> str: return _name(610, i)
def item_name(i: int) -> str: return _name(392, i)
def trainer_class_name(i: int) -> str: return _name(619, i)
def trainer_name(i: int) -> str: return _name(618, i)


@cache
def _species_table() -> tuple[Species, ...]:
    out = []
    for i, b in enumerate(_narc("poketool/personal/pl_personal.narc")):
        ev = _u16(b, 10)
        out.append(Species(
            id=i, name=species_name(i), base_stats=tuple(b[0:6]), types=(b[6], b[7]), abilities=(b[22], b[23]),
            growth_rate=b[19], catch_rate=b[8], base_exp=b[9], gender_ratio=b[16],
            ev_yield=tuple(ev >> (2 * k) & 3 for k in range(6)), held_items=(_u16(b, 12), _u16(b, 14)),
            egg_groups=(b[20], b[21]), base_friendship=b[18], hatch_cycles=b[17],
            tm_mask=int.from_bytes(b[28:44], "little")))
    return tuple(out)


def species(i: int) -> Species:
    return _species_table()[i]


def all_species() -> tuple[Species, ...]:
    return _species_table()


@cache
def _move_table() -> tuple[Move, ...]:
    out = []
    for i, b in enumerate(_narc("poketool/waza/pl_waza_tbl.narc")):
        out.append(Move(id=i, name=move_name(i), type=b[4], cls=b[2], power=b[3], accuracy=b[5], pp=b[6],
                        priority=struct.unpack_from("<b", b, 10)[0], effect=_u16(b, 0), effect_chance=b[7],
                        target=_u16(b, 8), flags=b[11]))
    return tuple(out)


def move(i: int) -> Move:
    return _move_table()[i]


def all_moves() -> tuple[Move, ...]:
    return _move_table()


@cache
def _learnsets() -> tuple[tuple[tuple[int, int], ...], ...]:
    out = []
    for b in _narc("poketool/personal/wotbl.narc"):
        entries = []
        for o in range(0, len(b) - 1, 2):
            w = _u16(b, o)
            if w == 0xFFFF:
                break
            entries.append((w >> 9, w & 0x1FF))
        out.append(tuple(entries))
    return tuple(out)


def learnset(species_id: int) -> tuple[tuple[int, int], ...]:
    """[(level, move)] in the order the game lists them."""
    return _learnsets()[species_id]


def moves_from_learnset(entries, level: int) -> tuple[int, ...]:
    """Moves a freshly generated Pokémon of this level knows: each learnset move up to `level` in order,
    the oldest dropping out once four are known. This is how wild Pokémon and move-less trainer
    Pokémon get their moves."""
    known: list[int] = []
    for lv, mv in entries:
        if lv > level:
            break
        if mv in known:
            continue
        if len(known) == 4:
            known.pop(0)
        known.append(mv)
    return tuple(known)


def default_moves(species_id: int, level: int) -> tuple[int, ...]:
    return moves_from_learnset(learnset(species_id), level)


@cache
def _evolutions() -> tuple[tuple[Evolution, ...], ...]:
    out = []
    for b in _narc("poketool/personal/evo.narc"):
        evs = (Evolution(*struct.unpack_from("<HHH", b, 6 * k)) for k in range(7))
        out.append(tuple(e for e in evs if e.method != 0))
    return tuple(out)


def evolutions(species_id: int) -> tuple[Evolution, ...]:
    return _evolutions()[species_id]


_MON_LAYOUT = {  # monDataType -> (struct size, has moves, has item)
    0: (8, False, False), 1: (16, True, False), 2: (10, False, True), 3: (18, True, True)}


@cache
def _trainers() -> tuple[Trainer, ...]:
    heads, parties = _narc("poketool/trainer/trdata.narc"), _narc("poketool/trainer/trpoke.narc")
    out = []
    for tid, (h, p) in enumerate(zip(heads, parties)):
        kind, cls, _sprite, size = h[0], h[1], h[2], h[3]
        step, has_moves, has_item = _MON_LAYOUT[kind]
        party = []
        for k in range(size):
            o = k * step
            iv_scale, level, sp = struct.unpack_from("<HHH", p, o)
            o += 6
            item = None
            if has_item:
                item, o = _u16(p, o), o + 2
            moves = None
            if has_moves:
                moves, o = struct.unpack_from("<4H", p, o), o + 8
            party.append(TrainerMon(species=sp & 0x3FF, form=sp >> 10, level=level, iv_scale=iv_scale,
                                    item=item, moves=moves, ball_seal=_u16(p, o)))
        out.append(Trainer(id=tid, name=trainer_name(tid), class_id=cls, class_name=trainer_class_name(cls),
                           ai_flags=_u32(h, 12), double_battle=bool(_u32(h, 16) & 2),
                           items=tuple(x for x in struct.unpack_from("<4H", h, 4) if x), party=tuple(party)))
    return tuple(out)


def trainer(i: int) -> Trainer:
    return _trainers()[i]


def num_trainers() -> int:
    return len(_trainers())


def _water(b: bytes, o: int) -> WaterTable:
    slots = tuple(WaterSlot(max_level=b[o + 4 + 8 * k], min_level=b[o + 5 + 8 * k],
                            species=_u32(b, o + 8 + 8 * k)) for k in range(5))
    return WaterTable(rate=_u32(b, o), slots=slots)


@cache
def _encounters() -> tuple[Encounters, ...]:
    out = []
    for i, b in enumerate(_narc("fielddata/encountdata/pl_enc_data.narc")):
        ids = lambda o, n: tuple(_u32(b, o + 4 * k) for k in range(n))
        out.append(Encounters(
            id=i, grass_rate=_u32(b, 0),
            grass=tuple(GrassSlot(level=b[4 + 8 * k], species=_u32(b, 8 + 8 * k)) for k in range(12)),
            swarm=ids(100, 2), day=ids(108, 2), night=ids(116, 2), radar=ids(124, 4),
            surf=_water(b, 204), old_rod=_water(b, 292), good_rod=_water(b, 336), super_rod=_water(b, 380)))
    return tuple(out)


def encounters(encounter_id: int) -> Encounters:
    """Wild tables by pl_enc_data.narc member index."""
    return _encounters()[encounter_id]


def encounter_id_for_map(map_header_id: int) -> int | None:
    """Encounter table id of a map header (the id in RAM at childMapHeader), or None for maps without wild Pokémon."""
    if not 0 <= map_header_id < _MAP_HEADER_COUNT:
        raise IndexError(map_header_id)
    arm9, n_enc = _rom().arm9, len(_narc("fielddata/encountdata/pl_enc_data.narc"))
    ids = [_u16(arm9, _MAP_HEADER_OFFSET + 24 * i + 14) for i in range(_MAP_HEADER_COUNT)]
    if not all(e == _NO_ENCOUNTERS or e < n_enc for e in ids):
        raise RuntimeError("map header table is not where romdata expects it; the ROM differs from the one measured")
    e = ids[map_header_id]
    return None if e == _NO_ENCOUNTERS else e


def encounters_for_map(map_header_id: int) -> Encounters | None:
    e = encounter_id_for_map(map_header_id)
    return None if e is None else encounters(e)


NATURE_NAMES = ("Hardy", "Lonely", "Brave", "Adamant", "Naughty", "Bold", "Docile", "Relaxed", "Impish", "Lax",
                "Timid", "Hasty", "Serious", "Jolly", "Naive", "Modest", "Mild", "Quiet", "Bashful", "Rash",
                "Calm", "Gentle", "Sassy", "Careful", "Quirky")


def calc_stats(species_id: int, level: int, ivs, evs, nature: int) -> tuple[int, ...]:
    """Gen 4 stat formula. ivs and evs are in STATS order; nature is PID % 25. Returns STATS order."""
    base = species(species_id).base_stats
    out = []
    for k in range(6):
        core = (2 * base[k] + ivs[k] + evs[k] // 4) * level // 100
        if k == 0:
            out.append(core + level + 10)
            continue
        v = core + 5
        up, down = nature // 5, nature % 5                  # nature boosts/cuts one of atk, def, spe, spa, spd
        order = (1, 2, 3, 4, 5)                              # STATS indices of those five, in nature order
        if up != down:
            if order[up] == k: v = v * 110 // 100
            elif order[down] == k: v = v * 90 // 100
        out.append(v)
    return tuple(out)
