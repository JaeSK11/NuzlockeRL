# RAM map: Pokémon Platinum Kaizo

Verified 2026-11-11 against the Kaizo ROM with SHA-1
`e8d13c6504406324a4a9ea9daf8d6bd409f8a644` (game code `JAK7`).
Implementation: [`src/gen4.py`](../src/gen4.py). Tests:
[`tests/test_gen4.py`](../tests/test_gen4.py).

Addresses are ARM9 bus addresses. Read them with PyNDS:
`nds.memory.read_u32(False, addr)`.

## Pointer chain

Gen 4 keeps most game state in heap memory that moves, so it's found
through pointers. These offsets come from NDS-Ironmon-Tracker's retail
Platinum table, and they hold for the hack too.

```
g = read_u32(0x02000000 + 0xBA8) & 0xFFFFFF          # global pointer
v = read_u32(0x02000000 + g + 0x20) & 0xFFFFFF       # version pointer
addr(field) = 0x02000000 + v + OFFSET[field]
```

Re-resolve after every save-state load (`gen4.resolve(nds)`).

## Fields

| Field | Offset from v | Type | Status |
|---|---|---|---|
| playerBase | 0xB4 | 6 × 236-byte encrypted party structs | ✅ The only valid struct a full RAM scan finds |
| playerBattleBase | 0x4B8AC | 6 × 236 B, battle copy of the party | ✅ Live HP and PP during battle; garbage outside battle |
| enemyBase | 0x4BE5C | 6 × 236 B, enemy party | ✅ Species, level, HP, moves; HP reaches 0 on faint |
| enemyTrainerID | 0x4189E | u16 | ✅ 851 = Barry 1. 0 outside battle **and in wild battles** |
| playerBattleMonPID | 0x47620 | u32 | ✅ PID of the active player Pokémon |
| enemyBattleMonPID | 0x476E0 | u32 | ✅ PID of the active enemy Pokémon |
| enemyPokemonID | 0x47678 | u16 species | ✅ 390 (Chimchar) in Barry 1 |
| statStagesPlayer | 0x475D0 | 8 × u8, 6 = ±0 | ✅ Neutral seen; changes not verified |
| statStagesEnemy | 0x47690 | 8 × u8 | ✅ Neutral seen; changes not verified |
| itemStartNoBattle / itemStartBattle | 0xB60 / 0x442BC | bag | ⏳ Not checked |
| badges | 0x96 | u8 bitfield | ⏳ Not checked |
| childMapHeader | 0x239B0 | map ID | ⏳ Not checked |
| facingDirection | 0x238A4 | | ⏳ Not checked |
| repelSteps | 0x8087 | | ⏳ Not checked |
| battleStatus | global 0x0224A55A | u8 | ❌ **Always 0 in this hack.** Use `gen4.in_battle()` |

`gen4.in_battle()` returns true when the struct at `playerBattleBase` is
checksum-valid. That works for both wild and trainer battles.

## Pokémon struct (236 bytes)

| Bytes | Contents |
|---|---|
| 0x00–0x03 | PID (unencrypted). `PID % 25` = nature |
| 0x04–0x05 | Unused, always 0 (used as a filter in the scan) |
| 0x06–0x07 | Checksum (unencrypted) = sum of the decrypted 16-bit words in 0x08–0x87 |
| 0x08–0x87 | Four 32-byte blocks A/B/C/D, encrypted, shuffled |
| 0x88–0xEB | Battle stats (party only), encrypted |

**Decryption:** XOR each 16-bit word with the high 16 bits of an LCG,
`seed = seed * 0x41C64E6D + 0x6073`. The blocks use `seed = checksum`; the
battle stats use `seed = PID`.

**Block order:** `((PID & 0x3E000) >> 13) % 24` indexes the 24 permutations
of ABCD (`gen4.BLOCK_ORDERS`).

Decoded so far:
- **A:** species u16 @0, held item @2, experience u32 @8, ability u8 @13
- **B:** moves 4 × u16 @0, PP 4 × u8 @8, IV word @16 (bit 30 = egg)
- **Battle stats:** status u32 @0, level @4, HP u16 @6, max HP @8, then
  atk, def, spe, spa, spd

## Caveats

- **The party copy is stale during battle.** It keeps pre-battle HP until the
  battle ends. Read `playerBattleBase` in battle.
- **The hack changes data:** Turtwig's ability reads 75 (Shell Armor), not
  vanilla 65 (Overgrow). Don't rely on vanilla species or move tables.
- `scan_for_mons()` searches all 4 MB of main RAM in ~1.7 s. Use it to
  re-find struct locations if the hack ever moves them.

## How addresses were verified

Each one was checked against what was on screen, from save states made with
`src/drive.py`: the starter in the party, every turn of the Barry 1 battle,
then after the battle (level up, learned move, healed at home). The tests
replay these checks.
