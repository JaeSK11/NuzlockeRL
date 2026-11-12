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
| statStagesPlayer | 0x475D0 | 8 × u8, 6 = ±0, range 0–12 | ✅ The player's `BattleMon.statBoosts`. Forced enemy moves changed it: Leer took Defense (index 2) down to 1, Growl took Attack (index 1) to 0, Swagger raised Attack to 12 |
| statStagesEnemy | 0x47690 | 8 × u8 | ✅ The enemy's `BattleMon.statBoosts`, the same layout |
| battleRngSeed | 0x43C44 | u32, `BattleSystem.seedRandNext` | ✅ Both battles. Writing it right after a state load randomizes the battle |
| battleRngStart | 0x43C48 | u32, `BattleSystem.seedDTO` | ✅ The seed the battle started with. At the first prompt, `seedRandNext` is this seed advanced 13 times (Barry 1) or 7 times (wild) |
| battleResult | 0x43C1C | u8, `resultMask` | ✅ 1 after a win, 2 after a loss (one battle each). See [Battle system](#battle-system) |
| battleCtxPtr | 0x4182C | u32 pointer to `BattleContext` | ✅ Both battles. See [Battle system](#battle-system) |
| (party count) | playerBase − 4 | u32, `Party.currentCount`; the u32 before it is the capacity, 6 | ✅ 0 in state 00, 1 afterwards. `scenario.write_party` sets it |
| (wild encounter table) | 0x233E4 | The current map's table, copied from `pl_enc_data.narc`: u32 rate, then 12 × (u32 level, u32 species), then 6 swarm, day, and night species | ✅ On Route 201. Writing it before an encounter picks the wild Pokémon (`scenario.set_wild_encounter`) |
| battleOptionsPtr | 0x419B0 | u32 pointer to the Options u16, `BattleSystem.options` | ✅ Both battles, valid only during a battle. Bits: text speed 0–3 (2 = fast), battle style 6 (1 = Set), battle scene 7 (1 = off). The battle reads through the pointer on every check, so writes take effect mid-battle |
| inputSystemPtr | 0x41998 | u32 pointer to the battle subscreen | ✅ Both battles. The u8 at +0x6DC is the menu input mode, 0 = touch, 1 = buttons |
| (no name in `gen4`) | 0x2370C | u8 | ✅ The input mode each new battle starts in. It was 0 in states 00–02 and 1 in state 04 |
| location | 0x1294 | `Location {i32 mapHeaderID, warpID, x, z, facing}` | ✅ The map ID changes at the same step as the screen: 414 home 1F, 411 Twinleaf Town, 342 Route 201. x and z track the player. The facing field here is stale; use facingDirection |
| facingDirection | 0x238A4 | u8: 0 up, 1 down, 2 left, 3 right | ✅ Changes on a turn in place |
| childMapHeader | 0x239B0 | map header ID | ✅ Matches location, except it reads 0 until the first map change after a new game. Use location |
| badges | 0x96 | u8 bitfield, `TrainerInfo.badgeMask`. Bit n is badge n+1 | ✅ Writing 0, 0xFF, and 0x05 showed 0, 8, and 2 badges on the Trainer Card. 0 in every milestone |
| money | 0x90 | u32, `TrainerInfo.money` | ✅ Matches the Trainer Card |
| pokedex | 0x133C | u32 magic 0xBEEFCAFE, caught[16] u32, seen[16] u32; bit = species − 1 | ✅ Turtwig caught from state 01, Chimchar seen from 04. Bits above 493 are padding and read as set |
| battlePokedexPtr | 0x4185C | u32 pointer to the battle's own Pokédex copy | ✅ During battle only. A battle writes its copy back when it ends, so the save copy lags. `gen4.read_pokedex` picks the right one |
| bag | 0x644 | 8 pockets of (u16 item, u16 quantity): items 165, key 50, TM/HM 100, mail 12, medicine 40, berries 64, balls 15, battle items 30 | ✅ Every slot matched the Bag screen |
| bagBattle | 0x43DA0 | Battle copy of the bag | ✅ A thrown ball drops here first and reaches the bag when the battle ends |
| itemStartNoBattle / itemStartBattle | 0xB60 / 0x442BC | The Medicine pocket in each copy, not the start of the bag | ✅ The tracker's names for these are misleading |
| pcBoxes | 0xCF40 | u32 current box, then 18 × 30 box structs of 136 bytes, then names | ⚠️ The layout and the 18 default box names match the decomp. No real deposit has been read yet |
| repelSteps | 0x8087 | | ⏳ Not checked |
| (the game's clock) | absolute 0x021BF5D8 | 7 × u32: year % 100, month, day, weekday (0 = Sunday), hour, minute, second | ✅ Not behind the pointer chain. Matched the emulator's clock in all 6 milestone states, for two different fixed times. `gen4.read_clock` |
| battleStatus | global 0x0224A55A | u8 | ❌ **Always 0 in this hack.** Use `gen4.in_battle()` |

`gen4.in_battle()` returns true when the struct at `playerBattleBase` is
checksum-valid. That works for both wild and trainer battles.

## Battle system

`BattleSystem` starts at v+0x417FC. Its `trainerIDs` field, at +0xA0, sits
2 bytes before `enemyTrainerID`. The u32 at v+0x4182C points to
`BattleContext` (the address is v+0x44878 in both test battles, but follow
the pointer):

| Field | Where | Values |
|---|---|---|
| `command` | u32 at ctx+8 | 5 = waits for the player's command (`BATTLE_CONTROL_COMMAND_SELECTION_INPUT`), 21 = a battle script runs (`EXEC_SCRIPT`), 44 = end of battle, others during the turn |
| `curCommandState[0]` | u8 at ctx+0 | 1 = the FIGHT, BAG, POKéMON, RUN menu is up; 3 = the move menu is opening; 4 = the move menu is up; 10 = the party menu is up; 13 = waiting; 14 = command chosen; 15 = an alert message; 17 = clearing the touch screen. Tapping a move with no PP left goes 17, 15, 13, 14 (Struggle) |
| `battlerStatusFlags[0]` | u32 at ctx+0x13C | The player's side. Bit 0 (`SWITCHING`) is set while the game waits for the player to pick a replacement after a faint |
| `partyOrder[0]` | 6 × u8 at ctx+0x312C | Party-menu position → index in `playerBattleBase`. A switch permutes this and never moves the structs. Position 0 is the active Pokémon |

**The forced switch** after a faint is `command == 21` with `SWITCHING`
set. Command 21 alone also holds during the faint animation, and
`curCommandState[0]` stays 14, so neither works alone. These offsets follow
the decomp's struct order and were checked on generated teams of 2 to 6.

**Waiting for a command** is `command == 5 and curCommandState[0] == 1 and
in_battle()` (`gen4.waiting_for_command`). Over the whole Barry 1 battle it
matched the FIGHT button being on screen on 14,098 of 14,151 frames. The
signal rises 7 to 12 frames before the button shows.

**Tap timing,** measured on Barry 1:
- Taps in the first 2 frames after the signal rises are dropped. On the
  first prompt after a battle starts, taps are ignored for 15 frames. The env
  waits 20.
- The game takes a tap 8 to 10 frames after touch-down. The env reads
  `curCommandState` 14 frames after touch-down and taps again if nothing
  changed.
- The move menu takes a tap as soon as `curCommandState[0]` reads 4.

**Battle RNG.** The game seeds `seedRandNext` once, at battle setup
(decomp `src/battle/battle_main.c:1034`). After that, only
`BattleSystem_RandNext` advances it, each time the battle draws a number:
25 draws in Barry 1's first turn, 22 in the wild battle's. Nothing advances
it while the game waits at a menu, so a battle save state fixes that
battle's luck. This is vanilla behavior.

**BattleMon.** `BattleContext` holds one `BattleMon` per battler, 0xC0
bytes each, at ctx+0x2D40 (the player's) and ctx+0x2E00 (the enemy's). The
layout matches decomp `include/battle/battle_mon.h` exactly.
`statStagesPlayer` is the player's `statBoosts`, `enemyPokemonID` is the
enemy's `species`, and `personality` is `playerBattleMonPID`. The game
copies a `BattleMon` back into the party struct a few frames after it
changes (`BattleMon_CopyToParty`), so the two agree at every prompt.
Checked by `scripts/ram_audit.py` (see [PROGRESS.md](PROGRESS.md#13-ram-audit-2026-11-12)).

| Offset | Field | Status |
|---|---|---|
| 0x00 | `species` u16 | ✅ |
| 0x02–0x0A | atk, def, spe, spa, spd, u16 each | ✅ |
| 0x0C | `moves` 4 × u16 | ✅ |
| 0x18 | `statBoosts` 8 × s8, 6 = ±0 | ✅ Changes verified |
| 0x27 | `ability` u8 | ✅ |
| 0x2C | `ppCur` 4 × u8 | ✅ |
| 0x34 | `level` u8 | ✅ |
| 0x4C | `curHP` i32 | ✅ |
| 0x50 | `maxHP` u32 | ✅ |
| 0x64 | `exp` u32 | ✅ |
| 0x68 | `personality` u32 | ✅ |
| 0x6C | `status` u32 | ✅ Every major status seen |
| 0x70 | `statusVolatile` u32 | ✅ Confusion turns in bits 0–2 (1–5 seen), flinch bit 3. Other bits not yet seen |
| 0x78 | `heldItem` u16 | ⚠️ 0 in every battle so far |
| 0x7C | `timesDamaged` u8 | ⚠️ Rises with hits; not checked against exact counts |
| 0x80 | `moveEffectsMask` u32 | ⏳ 0 in every battle so far |
| 0x84 | `moveEffectsTemp` u32 | ⏳ 0 in every battle so far |

**Battle result.** The decomp's `resultMask` bits are 1 = win, 2 = lose,
and 4 = captured, and the flee results combine them. The game sets the bit
during the text after the final KO, which needs A presses to get through.
Once the battle frees its memory, the byte reads garbage (168 was seen). The
env decides wins and losses from HP instead.

## Differences from retail Platinum

Everything below was seen in this hack (game code `JAK7`) and differs from
retail US Platinum (`CPUE`). Retail is the source of the tracker's offsets
and of the pret/pokeplatinum decomp. Add a row whenever a new difference
turns up. Differences in game data, such as species, moves, trainers, and
encounters, are in [HACK_DATA.md](HACK_DATA.md).

| What | Retail | This hack | Effect on the project |
|---|---|---|---|
| Game code | `CPUE` | `JAK7` | No address carries over without a check |
| The tracker's global `battleStatus` | Set during battle | Always 0 | `gen4.in_battle()` replaces it |
| Turtwig's ability | 65, Overgrow | 75, Shell Armor | Species data must come from the hack's ROM |
| Turtwig's moves | Tackle and Withdraw at Lv5 | Tackle only at Lv5, and Mega Drain at Lv6 | Learnsets come from `romdata` |
| Route 201 wild Pokémon | Starly, Bidoof, Kricketot at Lv2–3 | Igglybuff, Delibird, Venonat, Vulpix, and 7 more at Lv4–5 | Encounter tables come from `romdata` |
| Barry's Chimchar | Scratch and Leer | Scratch only | Barry 1 can't change stat stages |
| `seedRandNext` position | `BattleSystem`+0x2444, from the decomp's field names | `BattleSystem`+0x2448 | None, because the env uses the measured address. It may mean the hack added 4 bytes earlier in the struct. Unconfirmed |

## Pokémon struct (236 bytes)

| Bytes | Contents |
|---|---|
| 0x00–0x03 | PID (unencrypted). `PID % 25` = nature |
| 0x04–0x05 | Flags: bit 0 `partyDecrypted`, bit 1 `boxDecrypted` (decomp `include/struct_defs/pokemon.h`). 0 at rest. For single frames mid-turn the game holds a struct decrypted in place and sets them, and then the bytes are plaintext. `gen4.decode_mon` reports such a struct as not `checksum_ok` |
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

**Status word** (seen in both the party struct and `BattleMon`): sleep
turns in bits 0–2 (1–5 seen), poison 8, burn 16, freeze 32, paralysis 64,
toxic 128. The toxic counter, in bits 8–11, exists only in `BattleMon`;
the party copy keeps 128. A fainted Pokémon's party status is cleared while
its `BattleMon` keeps the last one.

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

The battle system fields were found by searching RAM for the fields that
the decomp names, then checked by behavior:
- The seed passes the LCG test from `seedDTO`, and writing it changes the
  battle.
- The command signal matches the FIGHT button on screen.
- Writing the input-mode byte changes how an A press behaves.

Each one was checked again on a second battle, the wild Delibird in
`05_route201_wild_battle.state`. The tests in `tests/test_battle_env.py`
replay both battles.
