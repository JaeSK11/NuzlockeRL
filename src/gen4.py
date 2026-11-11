"""Gen 4 (Platinum) memory layout and Pokémon decryption for PyNDS.

Pointer chain and offsets come from NDS-Ironmon-Tracker
(repos/NDS-Ironmon-Tracker/ironmon_tracker/constants/MemoryAddresses.lua),
for retail US Platinum (game code CPUE). The Kaizo hack reports JAK7, so every
offset here must be checked against the hack. See verify_party().
"""
from dataclasses import dataclass, field

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
    "itemStartNoBattle": 0xB60,
    "itemStartBattle": 0x442BC,
    "badges": 0x96,
    "childMapHeader": 0x239B0,
    "facingDirection": 0x238A4,
    "repelSteps": 0x8087,
}
BATTLE_STATUS = 0x24A55A        # tracker global; reads 0 even mid-battle in Kaizo. Use in_battle()

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
    """Decode one 236-byte party struct (or a 136-byte box struct)."""
    pid, checksum = _u32(raw, 0), _u16(raw, 6)
    blocks = _crypt(raw[8:136], checksum)
    ok = checksum != 0 and (sum(_u16(blocks, i) for i in range(0, 128, 2)) & 0xFFFF) == checksum
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
