"""Gen 4 (Platinum) memory layout and Pokémon decryption for PyNDS.

Pointer chain and offsets come from NDS-Ironmon-Tracker
(repos/NDS-Ironmon-Tracker/ironmon_tracker/constants/MemoryAddresses.lua),
for retail US Platinum (game code CPUE). The Kaizo hack reports JAK7, so every
offset here must be checked against the hack. See verify_party().
"""
from dataclasses import dataclass, field
from typing import NamedTuple

from platinum_locations import location_name

MAIN_RAM = 0x02000000
GLOBAL_POINTER = 0xBA8          # main-RAM offset of the global pointer
VERSION_POINTER_OFFSET = 0x20
OFFSETS = {                     # added to the resolved version pointer
    "playerBase": 0xB4,         # first party Pokémon (236-byte structs)
    "playerBattleBase": 0x4B8AC,
    "enemyBase": 0x4BE5C,
    "enemyTrainerID": 0x4189E,
    "playerBattleMonPID": 0x47620,
    "enemyBattleMonPID": 0x476E0,
    "statStagesPlayer": 0x475D0,
    "statStagesEnemy": 0x47690,
    "enemyPokemonID": 0x47678,
    "battleRngSeed": 0x43C44,   # u32, BattleSystem.seedRandNext. LCG seed*0x41C64E6D+0x6073. Writing it randomizes the battle
    "battleRngStart": 0x43C48,  # u32, BattleSystem.seedDTO, the seed the battle started with
    "battleResult": 0x43C1C,    # u8, resultMask: 1 win, 2 lose, 4 captured. Garbage once battle memory is freed
    "battleCtxPtr": 0x4182C,    # u32 pointer to BattleContext (main RAM). +0 u8 curCommandState[0], +8 u32 command
    "battleOptionsPtr": 0x419B0,  # u32 pointer to the u16 Options bitfield, BattleSystem.options. Garbage outside battle
    "inputSystemPtr": 0x41998,  # u32 pointer; u8 at +0x6DC is the menu input mode, 0 touch, 1 buttons
    "itemStartNoBattle": 0xB60, # start of the Medicine pocket (not the bag start). The bag is at "bag"
    "itemStartBattle": 0x442BC, # same pocket in the battle copy of the bag
    "badges": 0x96,             # u8 bitfield, TrainerInfo.badgeMask. Bit n = badge n+1; verified on the Trainer Card
    "childMapHeader": 0x239B0,  # map header ID, tracks "location" but reads 0 until the first map change after a new game
    "facingDirection": 0x238A4, # u8, 0 up, 1 down, 2 left, 3 right
    "repelSteps": 0x8087,       # not verified
    "location": 0x1294,         # Location {i32 mapHeaderID, i32 warpID, i32 x, i32 z, i32 facing}. x and z track the player live; facing is stale
    "money": 0x90,              # u32, TrainerInfo.money (TrainerInfo starts at +0x7C)
    "pokedex": 0x133C,          # Pokedex save struct: u32 magic, caught[16] u32, seen[16] u32. Not updated until a battle ends
    "battlePokedexPtr": 0x4185C,  # u32 pointer to the battle's own Pokedex copy. Valid only during battle
    "bag": 0x644,               # Bag, see BAG_POCKETS. The battle copy is at "bagBattle"
    "bagBattle": 0x43DA0,       # battle copy of the bag, valid only during battle. Items used in battle drop here first
    "pcBoxes": 0xCF40,          # PCBoxes: u32 currentBoxID, 18 x 30 x 136-byte box mons, then names. Empty-box layout only; no occupied slot seen
}
BATTLE_STATUS = 0x24A55A        # tracker global; reads 0 even mid-battle in Kaizo. Use in_battle()

POKEDEX_MAGIC = 0xBEEFCAFE
DEX_SPECIES = 493               # bits above this in the Pokedex bitfields are padding, and read as set
BAG_POCKETS = (("items", 165), ("key_items", 50), ("tm_hm", 100), ("mail", 12),
               ("medicine", 40), ("berries", 64), ("balls", 15), ("battle_items", 30))
BAG_SIZE = 4 * sum(n for _, n in BAG_POCKETS) + 4   # trailing u32 is the registered item
PC_BOXES, BOX_SLOTS, BOX_MON_SIZE = 18, 30, 136

PARTY_MON_SIZE = 236            # 8 header + 128 blocks + 100 battle stats
BLOCK_ORDERS = [
    "ABCD", "ABDC", "ACBD", "ACDB", "ADBC", "ADCB",
    "BACD", "BADC", "BCAD", "BCDA", "BDAC", "BDCA",
    "CABD", "CADB", "CBAD", "CBDA", "CDAB", "CDBA",
    "DABC", "DACB", "DBAC", "DBCA", "DCAB", "DCBA",
]


def read_bytes(nds, addr: int, n: int) -> bytes:
    """Read n bytes of ARM9 memory. Uses u32 reads; n is rounded up to 4."""
    rd = nds.memory.read_u32
    out = bytearray()
    for a in range(addr, addr + n, 4):
        out += rd(False, a).to_bytes(4, "little")
    return bytes(out[:n])


def resolve(nds) -> dict:
    """Follow the pointer chain; return absolute ARM9 addresses."""
    rd = nds.memory.read_u32
    g = rd(False, MAIN_RAM + GLOBAL_POINTER) & 0xFFFFFF
    v = rd(False, MAIN_RAM + g + VERSION_POINTER_OFFSET) & 0xFFFFFF
    addrs = {k: MAIN_RAM + v + off for k, off in OFFSETS.items()}
    addrs["battleStatus"] = MAIN_RAM + BATTLE_STATUS
    addrs["_global"] = MAIN_RAM + g
    addrs["_version"] = MAIN_RAM + v
    return addrs


def _crypt(data: bytes, seed: int) -> bytes:
    """Gen 4 stream cipher: XOR each u16 with the high half of an LCG."""
    out = bytearray(len(data))
    for i in range(0, len(data), 2):
        seed = (seed * 0x41C64E6D + 0x6073) & 0xFFFFFFFF
        w = int.from_bytes(data[i:i + 2], "little") ^ (seed >> 16)
        out[i:i + 2] = w.to_bytes(2, "little")
    return bytes(out)


def _u16(b, o): return int.from_bytes(b[o:o + 2], "little")
def _u32(b, o): return int.from_bytes(b[o:o + 4], "little")


@dataclass
class Mon:
    pid: int
    checksum_ok: bool
    species: int = 0
    item: int = 0
    exp: int = 0
    ability: int = 0
    moves: list = field(default_factory=list)
    pp: list = field(default_factory=list)
    is_egg: bool = False
    status: int = 0
    level: int = 0
    hp: int = 0
    max_hp: int = 0
    stats: dict = field(default_factory=dict)  # atk, def, spe, spa, spd

    @property
    def fainted(self) -> bool:
        return self.checksum_ok and self.species != 0 and self.hp == 0


def decode_mon(raw: bytes, with_battle_stats: bool = True) -> Mon:
    """Decode one 236-byte party struct (or a 136-byte box struct). checksum_ok is False
    while the game holds the struct decrypted in place (decomp partyDecrypted/boxDecrypted
    flags in the u16 at +4), because its bytes are then plaintext and decode as garbage.

    Pokemon_GetValue and Pokemon_SetValue (decomp src/pokemon.c) also decrypt in place, without
    the flags, and they decrypt the battle stats before the blocks. A read in between passes the
    checksum but decodes the battle stats as garbage, so with_battle_stats also requires a level
    of 1-100, hp <= max_hp, and no status bits above the toxic counter's (bits 8-11)."""
    pid, flags, checksum = _u32(raw, 0), _u16(raw, 4), _u16(raw, 6)
    blocks = _crypt(raw[8:136], checksum)
    ok = flags == 0 and checksum != 0 and (sum(_u16(blocks, i) for i in range(0, 128, 2)) & 0xFFFF) == checksum
    order = BLOCK_ORDERS[((pid & 0x3E000) >> 13) % 24]
    blk = {letter: blocks[32 * i:32 * (i + 1)] for i, letter in enumerate(order)}
    a, b = blk["A"], blk["B"]
    m = Mon(pid=pid, checksum_ok=ok)
    m.species, m.item = _u16(a, 0), _u16(a, 2)
    m.exp, m.ability = _u32(a, 8), a[13]
    m.moves = [_u16(b, 2 * i) for i in range(4)]
    m.pp = list(b[8:12])
    m.is_egg = bool((_u32(b, 16) >> 30) & 1)       # IV word, bit 30
    if with_battle_stats and len(raw) >= PARTY_MON_SIZE:
        s = _crypt(raw[136:236], pid)
        m.status, m.level = _u32(s, 0), s[4]
        m.hp, m.max_hp = _u16(s, 6), _u16(s, 8)
        m.stats = dict(zip(("atk", "def", "spe", "spa", "spd"),
                           (_u16(s, 10 + 2 * i) for i in range(5))))
        m.checksum_ok = ok and 1 <= m.level <= 100 and m.hp <= m.max_hp and m.status >> 12 == 0
    return m


def read_party(nds, base: int | None = None) -> list[Mon]:
    """Read up to 6 party Pokémon, stopping at the first empty slot."""
    if base is None:
        base = resolve(nds)["playerBase"]
    raw = read_bytes(nds, base, PARTY_MON_SIZE * 6)
    party = []
    for i in range(6):
        chunk = raw[i * PARTY_MON_SIZE:(i + 1) * PARTY_MON_SIZE]
        if _u32(chunk, 0) == 0 and _u16(chunk, 6) == 0:
            break
        party.append(decode_mon(chunk))
    return party


def scan_for_mons(nds, start=MAIN_RAM, end=MAIN_RAM + 0x400000, step=4):
    """Brute-force search for checksum-valid party structs, independent of offsets.
    Returns [(addr, Mon)]. Use it to find or verify playerBase in a romhack."""
    ram = read_bytes(nds, start, end - start)
    hits = []
    for off in range(0, len(ram) - PARTY_MON_SIZE, step):
        cs = _u16(ram, off + 6)
        if cs == 0 or _u16(ram, off + 4) != 0:   # bytes 4-5 are unused, always 0
            continue
        m = decode_mon(ram[off:off + PARTY_MON_SIZE])
        if m.checksum_ok and 0 < m.species <= 493 and 0 < m.level <= 100 and m.max_hp:
            hits.append((start + off, m))
    return hits


def in_battle(nds, addrs: dict | None = None) -> bool:
    """True while a battle is running. The battle copy of the player's party at
    playerBattleBase is checksum-valid only during battle (it is freed memory
    afterwards). Works for wild and trainer battles; enemyTrainerID is 0 for
    wild battles, so it can't be used alone."""
    a = addrs or resolve(nds)
    raw = read_bytes(nds, a["playerBattleBase"], PARTY_MON_SIZE)
    m = decode_mon(raw)
    return m.checksum_ok and 0 < m.species <= 493


CMD_SELECTION_INPUT = 5         # BattleContext.command while the game waits for the player
CS_ACTION_MENU = 1              # curCommandState[0]: FIGHT / BAG / POKEMON / RUN is up
CS_MOVE_MENU = 4                # curCommandState[0]: move menu is up (3 while it opens)
CS_PARTY_MENU = 10              # curCommandState[0]: the party menu opened from the action menu is up
CMD_EXEC_SCRIPT = 21            # BattleContext.command while a battle script runs, also while it waits for the forced switch
# BattleContext offsets from the decomp's struct order, checked against this hack's RAM
CTX_STATUS_FLAGS = 0x13C        # u32 battlerStatusFlags[0], the player's side
CTX_PARTY_ORDER = 0x312C        # u8 partyOrder[0][6]: party-menu position -> index in playerBattleBase
BATTLER_STATUS_SWITCHING = 1    # battlerStatusFlags bit: the game waits for the player to pick a replacement


def read_battle_command(nds, addrs: dict) -> tuple[int, int] | None:
    """(command, curCommandState[0]) of the battle context, or None when the
    context pointer isn't in main RAM (no battle, or still being set up)."""
    rd = nds.memory.read_u32
    p = rd(False, addrs["battleCtxPtr"])
    if not (MAIN_RAM <= p < MAIN_RAM + 0x400000 - 0x100) or p & 3:
        return None
    return rd(False, p + 8), rd(False, p) & 0xFF


def waiting_for_command(nds, addrs: dict) -> bool:
    """True while the game shows the action menu and waits for the player."""
    c = read_battle_command(nds, addrs)
    return c == (CMD_SELECTION_INPUT, CS_ACTION_MENU) and in_battle(nds, addrs)


def write_battle_seed(nds, addrs: dict, seed: int) -> None:
    nds.memory.write_u32(False, addrs["battleRngSeed"], seed & 0xFFFFFFFF)


def read_input_mode(nds, addrs: dict) -> int | None:
    """0 = touch menus, 1 = button menus, None if the pointer is invalid."""
    p = nds.memory.read_u32(False, addrs["inputSystemPtr"])
    if not (MAIN_RAM <= p < MAIN_RAM + 0x400000 - 0x800):
        return None
    return nds.memory.read_u8(False, p + 0x6DC)


# Options bitfield (decomp include/game_options.h). The battle reads it through
# BattleSystem.options on every check, so a write takes effect mid-battle.
OPTION_FIELDS = {"text_speed": (0, 0xF), "battle_style": (6, 1), "battle_scene": (7, 1)}
TEXT_FAST, STYLE_SET, SCENE_OFF = 2, 1, 1


def decode_options(x: int) -> dict:
    return {"text_speed": x & 0xF, "sound_mode": (x >> 4) & 3, "battle_style": (x >> 6) & 1,
            "battle_scene": (x >> 7) & 1, "button_mode": (x >> 8) & 3, "frame": (x >> 10) & 0x1F}


def _options_addr(nds, addrs: dict) -> int | None:
    p = nds.memory.read_u32(False, addrs["battleOptionsPtr"])
    return p if MAIN_RAM <= p < MAIN_RAM + 0x400000 - 4 and not p & 1 else None


def read_battle_options(nds, addrs: dict) -> int | None:
    """The raw Options u16 the running battle reads, or None if the pointer is invalid."""
    p = _options_addr(nds, addrs)
    return None if p is None else nds.memory.read_u16(False, p)


def write_battle_options(nds, addrs: dict, **fields: int) -> int:
    """Set the named OPTION_FIELDS and keep every other bit. Returns the new u16."""
    p = _options_addr(nds, addrs)
    if p is None or not in_battle(nds, addrs):
        raise RuntimeError("no battle is running; battleOptionsPtr is stale outside battle")
    x = nds.memory.read_u16(False, p)
    for name, val in fields.items():
        shift, mask = OPTION_FIELDS[name]
        x = (x & ~(mask << shift)) | ((val & mask) << shift)
    nds.memory.write_u16(False, p, x)
    return x


class Location(NamedTuple):
    map_id: int     # map header ID
    x: int
    z: int
    facing: int     # 0 up, 1 down, 2 left, 3 right

    @property
    def name(self) -> str | None:
        return location_name(self.map_id)


def read_location(nds, addrs: dict | None = None) -> Location:
    a = addrs or resolve(nds)
    map_id, _warp, x, z = (nds.memory.read_u32(False, a["location"] + 4 * i) for i in range(4))
    return Location(map_id, x, z, nds.memory.read_u8(False, a["facingDirection"]))


def read_badges(nds, addrs: dict | None = None) -> int:
    a = addrs or resolve(nds)
    return nds.memory.read_u8(False, a["badges"])


def _dex_sets(raw: bytes) -> tuple[set, set]:
    def species(off):
        words = [_u32(raw, off + 4 * i) for i in range(16)]
        return {s for s in range(1, DEX_SPECIES + 1) if words[(s - 1) // 32] >> ((s - 1) % 32) & 1}
    return species(4), species(4 + 64)


def read_pokedex(nds, addrs: dict | None = None, from_battle: bool | None = None) -> tuple[set, set]:
    """(caught, seen) species sets. A battle works on its own Pokedex copy and writes it
    back when the battle ends, so during battle the copy is the current one.
    from_battle=None picks by in_battle(); False reads the save copy."""
    a = addrs or resolve(nds)
    if from_battle is None:
        from_battle = in_battle(nds, a)
    base = a["pokedex"]
    if from_battle:
        p = nds.memory.read_u32(False, a["battlePokedexPtr"])
        if MAIN_RAM <= p < MAIN_RAM + 0x400000 - 0x100 and not p & 3 and nds.memory.read_u32(False, p) == POKEDEX_MAGIC:
            base = p
    return _dex_sets(read_bytes(nds, base, 4 + 128))


def read_bag(nds, addrs: dict | None = None, from_battle: bool | None = None) -> dict[str, list[tuple[int, int]]]:
    """{pocket: [(item ID, quantity)]} for the non-empty slots. During battle the battle
    copy is the current one, because item use only reaches the saved bag when the battle ends."""
    a = addrs or resolve(nds)
    if from_battle is None:
        from_battle = in_battle(nds, a)
    raw = read_bytes(nds, a["bagBattle" if from_battle else "bag"], BAG_SIZE)
    bag, off = {}, 0
    for name, n in BAG_POCKETS:
        slots = [(_u16(raw, off + 4 * i), _u16(raw, off + 4 * i + 2)) for i in range(n)]
        bag[name] = [s for s in slots if s[0]]
        off += 4 * n
    return bag


def read_box(nds, box: int, addrs: dict | None = None) -> list[Mon | None]:
    """The 30 slots of PC box `box` (0-based) as Mon, or None for an empty slot."""
    if not 0 <= box < PC_BOXES:
        raise IndexError(f"box {box} is not in 0..{PC_BOXES - 1}")
    a = addrs or resolve(nds)
    raw = read_bytes(nds, a["pcBoxes"] + 4 + box * BOX_SLOTS * BOX_MON_SIZE, BOX_SLOTS * BOX_MON_SIZE)
    mons = []
    for i in range(BOX_SLOTS):
        chunk = raw[i * BOX_MON_SIZE:(i + 1) * BOX_MON_SIZE]
        empty = _u32(chunk, 0) == 0 and _u16(chunk, 6) == 0
        mons.append(None if empty else decode_mon(chunk, with_battle_stats=False))
    return mons
