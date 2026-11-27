# Progress log

What has been done, in order, and why.

## 1. Survey of prior work (2026-11-11)

**Question:** has anyone trained an RL model to play a Pokémon Nuzlocke?

**Finding:** no published paper or open-source project does Nuzlocke RL. The
nearest work falls into three groups:

- **Overworld RL on Pokémon Red** (PyBoy + PPO): PWhiddy's
  PokemonRedExperiments, Pleines et al. 2025, drubinstein's
  pokemonred_puffer, and PokeRL. None of them penalizes fainting.
- **Battle-only RL** on Pokémon Showdown: Metamon (Grigsby et al. 2025)
  reaches human level with offline RL. Showdown has no overworld or catching.
- **KP Labs**, covered in pChal's video (2024-05-30): the only known Nuzlocke
  attempt. It was streamed on Twitch, with no code or paper. Details are
  below.

**What we took from KP Labs** (from the video transcript):
- The target was **Emerald Kaizo** Hardcore Nuzlocke, and the RL was
  **battle-only**. A save state was loaded before each mandatory battle,
  and random encounters were simulated in software.
- Actions were moves and switches. Reward was + for KOs and wins and − for
  losing Pokémon. Observations did not include the opponent's moveset.
- **Reward hacking:** a damage-based reward taught it to stall battles for
  points, even when it had a one-hit KO. Every reward change meant
  retraining from scratch.
- Best run: 12 trainer battles won.

**Decisions:**
- Start battle-only, from save states, the same way KP Labs did.
- Reward outcomes (KOs, wins, Pokémon lost), not damage dealt, to avoid
  the stalling hack.
- Treat permadeath as a reason for risk-sensitive or constrained RL later.
  It is a different problem from maximizing expected reward.

All sources are listed in [REFERENCES.md](REFERENCES.md).

## 2. Choosing the game and emulator

**Target:** Pokémon Platinum Kaizo (NDS), chosen by the project owner. It has
Hardcore Nuzlocke level caps built in, which give the agent a gym-by-gym
curriculum and a hard constraint for free.

**Problem:** the reference work uses PyBoy, which only emulates the Game Boy
and Game Boy Color. Platinum is a DS game.

Options considered:

| Option | Verdict |
|---|---|
| PyBoy | Can't run DS games |
| py-desmume (DeSmuME bindings) | Viable fallback |
| melonDS | No mature Python bindings. The hack's FAQ also says melonDS cores can't save in-game. |
| BizHawk + Lua | Lua, not Python; awkward for RL |
| **PyNDS** (NooDS core) | **Chosen.** Modeled on PyBoy and built for RL and bots: frames, buttons, touch, memory and save states from Python |
| Switch to Emerald Kaizo (GBA, mGBA) | Faster emulation and fully documented RAM, but not the chosen target |

## 3. Making PyNDS work

Done one step at a time, each tested on the Kaizo ROM:

1. **pip `pynds==0.0.4`.** Booted the ROM headless with no BIOS files, and
   buttons and touch worked. Speed was ~650–1000 fps per process (11–17×
   real time). Save states are ~5.5 MB and load in 2.7 ms.
2. **Missing dependency.** `import pynds` failed without PortAudio, because it
   imports `sounddevice`. A stub module worked around it; later
   `libportaudio2` was installed. Audio costs nothing unless
   `open_audio()` is called, since the emulator computes sound either way.
3. **Misleading benchmark.** `run_until_frame()` returns at once until the
   frame is consumed, so the first test reported over a million fps while
   emulating nothing. `tick()` consumes the frame; always use it.
4. **Memory reads returned 0 everywhere** in the pip wheel. The GitHub source
   (5a40a52) has a newer memory API, `read_u32(arm7, addr, tcm)`. **Building
   from source fixed it.** The game header reads back correctly, and 100k
   reads take ~11 ms.

The speed means battles started from save states are practical, but learning
the overworld from scratch would be slow, roughly 15× slower than PyBoy runs
Gen 1. That's another reason to start battle-only.

## 4. Mapping RAM

**Source of addresses:** NDS-Ironmon-Tracker's table for retail Platinum,
plus pret/pokeplatinum for struct layouts. The hack's game code is `JAK7`,
not retail `CPUE`, so nothing was assumed to carry over.

**Verifying on the hack:**
- Wrote `src/gen4.py`: the pointer chain, Gen 4 decryption (an LCG stream
  cipher seeded by the checksum, blocks shuffled by PID, battle stats seeded
  by PID), `read_party`, and `scan_for_mons`, a brute-force search of all
  RAM for checksum-valid structs.
- Wrote `src/drive.py`, a scripted input driver, and played from a new game
  through the first rival battle, saving states along the way.
- With the starter (Turtwig), the full RAM scan found exactly **one** valid
  Pokémon struct, at the pointer chain's `playerBase`. The chain is
  confirmed for the hack.
- In the Barry 1 battle, the enemy party, trainer ID (851), active PIDs and
  stat stages all decoded. HP tracked the screen every turn, and the enemy's
  HP reached 0 on faint.
- The tracker's global `battleStatus` flag reads 0 even mid-battle in this
  hack. It was replaced with `gen4.in_battle()`, which checks whether the
  battle copy of the party is checksum-valid. That copy is garbage outside
  battle.

**Findings that affect design:**
- During battle the party copy is stale; live HP is in `playerBattleBase`.
- The hack changes abilities (Turtwig has Shell Armor), so species and move
  data must come from the hack's ROM, not vanilla tables.
- Inputs closer than ~25–30 frames apart are dropped during text and fades.
  Actions need to be "hold N frames, then wait M frames".

Details are in [RAM_MAP.md](RAM_MAP.md) and [EMULATOR.md](EMULATOR.md).

## 5. Emulator compatibility check

A Reddit report said that only Start works in Twinleaf Town on melonDS and
DeSmuME. **That doesn't happen under PyNDS.** A, B, X (menu), Start, the
D-pad and touch were all tested in that area.

## 6. Tests and save states

- `tests/test_gen4.py` has 4 tests covering no party, starter + full scan,
  the Barry battle, and the party updating after battle. They run against
  milestone save states and pass.
- Save states are kept locally in `states/milestones/` and not committed,
  because they contain game memory.

## 7. Parallel speed, input modes, and battle determinism (2026-11-11)

These were measured on an 8-core, 16-thread Ryzen 7 7840U. The 4 tests
pass there on Python 3.10.12 once `libportaudio2` is installed. The project
has no CPU-vendor or GPU-specific code.

**Parallel speed.** NooDS's render threads make each process use about 1.7
cores, which oversubscribes the CPU at 16 processes. With the render
threads off, 16 processes reach about 3400 fps in total, twice the default.
Details are in [EMULATOR.md](EMULATOR.md#parallel-speed-on-an-8-core-cpu-ryzen-7-7840u-2026-11-11).

**Battles in a save state are deterministic.** From
`03_barry1_battle_turn1.state`, the script waited 0 to 610 frames at the
move prompt, then used Tackle until the battle ended. All 8 waits gave the
same battle, turn by turn. If timing changed the RNG, all 8 runs would
match only about once in 1500 tries, assuming vanilla crit and accuracy
odds. An agent trained from one battle state can therefore memorize that
battle's luck. That is how the Pokémon Red agent learned a fixed opening
that caught a Pokémon on the first throw. The battle env must randomize the
RNG at reset (see the [roadmap](ROADMAP.md)).

**Battle menus have an input mode.** A move first took three A presses.
Screenshots showed why. The battle menus switch between touch and button
modes, and in touch mode the first button press only shows the cursor. A
tap selects in either mode (corrected in section 8), so with touch, every
turn of Barry 1 took exactly two taps, **FIGHT** and then the move. The battle env should act by
touch. Details are in [EMULATOR.md](EMULATOR.md#input-timing-important-for-the-action-space).

**GPU.** No GPU is needed yet. A small policy over RAM values is unlikely
to need one while the emulators use every core.

## 8. Battle environment (2026-11-11)

Goal: roadmap step 3, a battle env that applies the lessons from KP Labs and
from the Pokémon Red agent (PWhiddy's video). The lessons are to reward
events rather than totals, make stalling lose, randomize luck, act only when
the game waits, and log everything.

### What was built, and why

**RAM fields** (`src/gen4.py`, mapped in [RAM_MAP.md](RAM_MAP.md#battle-system)):
- The battle RNG seed.
- The battle result.
- The "waiting for a command" signal.
- The menu input mode.

The pret/pokeplatinum decomp named the fields to look for. RAM searches
found them in the hack, and each one was checked by behavior on two battles.

**A second battle state.** `05_route201_wild_battle.state` is a wild
Delibird (Lv4) against Turtwig (Lv6, Tackle and Mega Drain).
`scripts/milestones/05_route201_wild_battle.txt` rebuilds it from state 04.
A second battle catches addresses that hold in only one battle. Its second
move tests move slot 1, and its original seed gives a loss to test against.

**`BattleEnv`** (`src/battle_env.py`). The design choices:
- **One step is one command.** The env taps FIGHT and then the move, and runs
  the game until `waiting_for_command()` is true again. Fixed frame waits
  either waste frames or tap too early when a turn runs long.
- **Touch only.** A tap selects in either input mode and doesn't depend on
  where the cursor was left. A button press in touch mode only shows the
  cursor.
- **Rewards come from events** (`Event`, `REWARDS`): +1 per enemy faint, −3
  per own faint, +5 win, −10 loss. There is no damage reward, because KP
  Labs' agent learned to stall for damage points. There is no reward from a
  total that can drop either. The Pokémon Red agent lost a huge one-time
  reward when it put a Pokémon in the PC, and it then avoided Pokémon
  Centers. Boxing the dead (roadmap step 4) would hit the same trap.
- **A turn cap scores as a loss** (default 100 turns), so stalling never
  pays. The Pokémon Red agent learned to stop pressing buttons to dodge a
  loss penalty.
- **A random RNG seed at every reset,** so the agent can't memorize one
  battle's luck. `options={"keep_rng": True}` keeps the state's own seed
  for reproducible tests.
- **The episode ends at the wipe.** The text after the final KO needs A
  presses and can hold level-up or move-learn questions. Ending at the wipe
  skips them, and the outcome comes from HP.
- **STUCK instead of a crash.** If no prompt and no end come within 6,000
  frames, the env truncates the episode and logs the RAM signal. An
  unmodeled prompt shows up in the logs instead of killing a 14-env run.
- **The observation is what a player sees.** That's the player's own party
  in full, the enemy's active Pokémon and HP fraction, and which enemy slots
  have fainted. No enemy moves are shown, which the roadmap leaves open.
- **JSON-lines logs** of every step and episode. The Pokémon Red agent's
  most useful analysis came from per-step logs.

**`scripts/rollout.py`.** It runs envs in parallel with a random policy.
The default is one env per hardware thread, minus 2 to leave room for the
main process, because throughput stops rising at one emulator per hardware
thread. It stops early if the CPU stays above 99 °C for more than 30 s.

### Results

- `pytest -q tests`: 13 passed. These are the 4 RAM tests plus 9 env tests.
- **Barry 1 with its own seed and Tackle every turn:** won in 5 turns, HP
  as on screen, return +6. `resultMask` then reads 1.
- **Wild Delibird with its own seed:** lost in 2 turns (Turtwig's HP went
  23, then 11, then 0), return −13. `resultMask` then reads 2.
- **The same seed twice gives the same battle,** and different seeds give
  different battles.
- **`rollout.py --envs 14 --episodes 200` on the 7840U:**
  - 200 battles in 201 s, at 2,475 emulated frames/s.
  - No STUCK episodes.
  - 211 episodes got 211 different seeds.
  - The random policy won Barry 1 in 87 of 87 battles, and won the wild
    battle in 10 of 113.
- **Where the time goes.** A profile of one env puts 97% of the time in
  emulation and 3% in the env's own Python. The rollout ran 23% below the
  raw emulator speed because Gymnasium's vector env waits for the slowest
  battle at every step. Step lengths ran from 248 to 1,512 frames, and the
  14 processes averaged 7.3 busy cores.

### Issues and how they were resolved

| Issue | Cause | Resolution |
|---|---|---|
| Tests failed at import with "PortAudio library not found" | `libportaudio2` wasn't installed | Installed it. `emu_tests/stub` is a fallback |
| One emulator ran below the documented 650–1000 fps | The docs were measured on a 32-core machine | Measured on the 7840U (about 590 fps). Recorded in EMULATOR.md |
| 16 emulators ran slower than 8 | NooDS's render threads gave about 27 threads for 16 hardware threads, and its wait loops spin | Render threads off: 2× faster at 16 |
| Using a move took three A presses | Battle menus have touch and button modes. In touch mode, the first button press only shows the cursor | The env acts by touch |
| My first account of the input modes was wrong | A misread screenshot. The tap meant for Tackle hit FIGHT, because the game was still on the main menu | A RAM test showed taps work in both modes. Docs corrected |
| Every battle from a save state played out the same | Vanilla design: the battle seeds its RNG once at setup | The env writes a random seed at reset |
| An early RNG test reported "deterministic" without a turn ever happening | Two A presses never selected the move | The test checked that HP changed before trusting the result |
| Fixed waits between taps dropped inputs or wasted frames | Taps within 2 frames of the prompt are dropped, and taps in the first 15 frames of a battle are ignored | The env waits for the RAM signal, settles 20 frames, and taps again if the menu didn't change |
| `resultMask` turned to garbage after a battle | The game sets it during the post-KO text, then frees battle memory | The env takes the outcome from HP at the wipe |
| The wild state was in button mode | Barry 1 was fought with A presses, and the mode carries over into later battles | None needed, because taps work in either mode |
| Rebuilding the wild state isn't byte-identical (13 to 21 bytes differ) | Not traced. The DS clock is a guess | The rebuilt state gives the same battle. Left open |
| The rollout ran 23% below raw emulator speed | The vector env steps in lockstep | Recorded as a roadmap gap |
| `seedRandNext` is 4 bytes past where the decomp puts it | Unknown | Recorded in RAM_MAP's differences table. The env uses the measured address |
| A probe script wrote a stray `t1.state` into the repo root | A relative output path | Deleted before any commit |

### Open

The open items are in the roadmap's [Gaps in the env](ROADMAP.md#gaps-in-the-env):
switches, move slots 2 and 3, unmodeled prompts, the no-PP case, and
lockstep stepping.

## 9. Faster battles through the Options in RAM (2026-11-11)

Goal: roadmap step 0. Fewer emulated frames per battle mean more battles
per hour of training.

**What was built.** The decomp shows that the battle keeps a pointer to the
game's Options and reads through it on every check, for example
`BattleSystem_AreAnimationsOn`. So `BattleEnv(fast_battles=True)` writes
text speed fast, battle scene off, and battle style Set through
`battleOptionsPtr` right after loading a state. No save state had to be
re-made. `gen4.write_battle_options` keeps all other option bits, and it
refuses to write outside a battle.

**Results.** Each run used the state's own seed and always took action 0:

| Battle | Frames, as saved | Frames, animations off | Change |
|---|---|---|---|
| Barry 1 (5 turns) | 2547 | 1839 | −28% |
| Wild Delibird (2 turns) | 1329 | 617 | −54% |

- HP before every step was identical in every setting, so the options don't
  touch the battle RNG.
- Setting text speed to normal or slow made the same battles longer (Barry
  1 took 3623 and 5053 frames). That confirms the write takes effect
  mid-battle.
- Over 24 battles with random seeds, every step still took exactly 2 taps.
  The 20-frame settle holds with animations off.
- Tests: 16 pass.

| Issue | Cause | Resolution |
|---|---|---|
| Fast text gave no speedup | Both saves already had text speed fast and battle style Set | Only the animation switch matters for the current states. The env still writes all three, for states made later |
| No overworld address for the Options | The pointer target sits at a different offset from v in each save, and the pointer is stale outside battle | The env writes during battle only. `write_battle_options` raises outside a battle instead of writing through a stale pointer |
| Battle style Set can't be tested | No state has a trainer with 2+ Pokémon | Left unverified in the roadmap until the scenario generator makes one |

## 10. The hack's game data from the ROM (2026-11-11)

Goal: roadmap step 2. Observations, the scenario generator, and the
Nuzlocke rules all need the hack's own data, and the hack changed most of it.

**What was built.**
- `src/romdata.py` parses the ROM's NARC files with ndspy into frozen
  dataclasses: species, moves, learnsets, evolutions, trainers with their
  parties and AI flags, wild encounters by map, and names from the text
  banks. The tables load lazily and are cached.
- `scripts/hack_diff.py` compares them with vanilla Platinum from the
  decomp's data files. The summary is in [HACK_DATA.md](HACK_DATA.md).

The extracted data and the full report stay under `roms/`, outside git.

**Verified.** `tests/test_romdata.py` checks the data against RAM. Turtwig's
ability and stats match at Lv5 and Lv6. Barry's Chimchar matches down to its
PID. The Route 201 table holds the Delibird that appeared. 11 tests pass.

| Issue | Cause | Resolution |
|---|---|---|
| I expected Barry's Chimchar to use Leer and move stat stages | That was vanilla knowledge; the hack's Chimchar knows only Scratch | The audit forced stat moves instead (section 13) |
| The extraction report said some Jubilife grunts fight double battles | They don't; 3 other Galactic teams do | Checked `double_battle` for all trainers and corrected HACK_DATA.md |
| Decomp map-header lines didn't match ids at first | The decomp's line numbers are 1-based | Fixed in the parser; Route 201 is header 342 |
| The rival's trainer name reads "Cedric" | Not traced | Left open in HACK_DATA.md |

## 11. Battle-scenario generator (2026-11-11)

Goal: battles with real choices. The two milestone battles give Turtwig one
or two moves and no team, so an agent has almost nothing to learn from them.

**What was built.** `src/scenario.py` builds Pokémon from the hack's data
(`romdata`) and writes them into the party in RAM while the player stands
in Route 201 grass:
- `build_mon` sets species, level, moves, IVs, EVs, nature, and ability
  slot. It computes stats, PP, and EXP the way the game does.
- `encode_mon` is the exact inverse of the decryption, byte for byte.
- `set_wild_encounter` overwrites the map's wild table in RAM, so the
  next encounter is the chosen species and level.

The generator then walks until a battle starts and saves a state a few
frames after the first command prompt. `scripts/make_scenario.py` is the
command line. Generated states go to `states/generated/`, outside git.

This avoids hand-playing the Kaizo hack to reach each kind of battle, and
it gives teams of 2–6 Pokémon, which switches need.

**Verified.**
- Encoding round-trips exactly on every real struct in the milestone
  states.
- The stat formula, EXP curve, nature, gender, and ability slot match what
  the game stored.
- Written teams appear in the battle copy with the right species, level,
  moves, PP, and HP, and the screen shows the right names.
- Forcing the wild table gave exactly the chosen enemy every time, for
  example Pikachu Lv7, Eevee Lv13, and Mewtwo Lv50.
- A random policy finished every battle with a solo Lv10 Turtwig with 4
  moves (8 of 8) and with a team of 3 (10 of 10), and none ended STUCK.
- Tapping (64, 115) and (192, 115) drops exactly move slot 2's and slot 3's
  PP, so the env's last two move positions are confirmed.

| Issue | Cause | Resolution |
|---|---|---|
| A generated Pokémon showed as "What will do?" | The game keeps the species name in the nickname field | `build_mon` writes the name from the ROM's text bank |
| Two of ten team battles ended STUCK | When the lead faints with teammates alive, the game waits for the player to pick the next Pokémon (command 21) | An env gap, not a generator fault. Listed in the roadmap |
| The generator and `romdata` both read the ROM's tables | They were built in parallel | The generator now uses `romdata` only. 27 generated Pokémon were byte-identical before and after |
| `--rom` changes only the emulator's ROM | `romdata` reads one ROM, set by `$NUZLOCKERL_ROM` | Fine with one hack. Set `$NUZLOCKERL_ROM` to switch both |

Not yet done: enemy moves, IVs, and PID are the game's own rolls, the met
location and dates are left at zero, and the generator makes wild battles
only.

## 12. RAM for the Nuzlocke rules (2026-11-11)

Goal: roadmap step 4's RAM, meaning the run state the Nuzlocke rules check
between battles.

**What was built.** New fields in `gen4.OFFSETS`, with readers:
- `read_location`, `read_badges`, `read_pokedex`, `read_bag`, and
  `read_box`.
- `src/platinum_locations.py` names the map IDs. It is generated from
  NDS-Ironmon-Tracker's retail table, and only the IDs listed in its header
  were checked in the hack.

The fields and their evidence are in [RAM_MAP.md](RAM_MAP.md#fields).

**How each was verified.**
- **Location:** the map ID changed at the same step as the screen when
  walking from the house to Route 201.
- **Badges:** writing the byte changed the badge count on the Trainer Card.
- **Bag:** every slot matched the Bag screen in a state made after Mom's
  cutscenes.
- **Catch:** a Great Ball thrown at the wild Delibird set `battleResult` to
  4, took a ball from the battle bag, added Delibird to the party, and set
  its caught flag.

Tests are in `tests/test_nuzlocke_ram.py`.

| Issue | Cause | Resolution |
|---|---|---|
| Chimchar wasn't "seen" in the Barry 1 state, nor Delibird in the wild state | A battle works on its own Pokédex copy and writes it back when it ends | `read_pokedex` reads the battle copy during battle |
| Items used in battle didn't show in the bag | The battle has its own bag copy too | `read_bag` reads the battle copy during battle |
| The tracker's `itemStartNoBattle` didn't point at the start of the bag | It points at the Medicine pocket | Corrected in RAM_MAP and gen4 |
| `childMapHeader` read 0 in the bedroom state | It isn't set until the first map change after a new game | Use `location` |
| Viewing the three starters didn't mark them as seen | The selection screen sets no Pokédex flags | Expectation corrected |
| No way to verify the PC with a real Pokémon | The bedroom PC in this hack is the Kaizo difficulty menu, and Pokémon Storage needs a Pokémon Center | Layout checked against the decomp only. Left open in the roadmap |

## 13. RAM audit (2026-11-12)

Goal: make a silent wrong RAM read loud. Each field so far was checked on
two battles. A mapping that is wrong only some of the time would pass those
checks, and the agent would learn from bad data.

**What was built.** `scripts/ram_audit.py` plays random battles in parallel
with a random policy. It checks RAM at every decision and every 10 frames
mid-turn:
- Every struct decodes, and its values are in range: species, level, HP,
  moves, PP, and status bits.
- The active PIDs match a party slot, stat stages stay in 0–12,
  `enemyTrainerID` is right for the battle, `command` and
  `curCommandState` stay within the decomp's values, and `resultMask` is 0
  until the battle is decided.
- Every party struct matches the game's second copy of the same Pokémon,
  its `BattleMon` in `BattleContext`: species, level, HP, max HP, moves,
  PP, EXP, ability, stats, held item, and stat stages.

`--probe N` writes a status or stat move into the enemy's `BattleMon`, so
the player really gets hit by Leer, Thunder Wave, Toxic, Hypnosis, Confuse
Ray, and others. Barry's Chimchar and the wild Delibird never use such
moves.

**Result.** 200 random battles and 44 probe battles (seed 11) gave 0
strict violations, over 1,984 struct reads at decisions and 57,926
mid-turn.
- Every mapped field is right.
- The `BattleMon` layout matches the decomp exactly; see
  [RAM_MAP.md](RAM_MAP.md#battle-system).
- Stat stages, every major status, confusion, and flinch read correctly.

**Finding: the game decrypts structs in place.** For single frames
mid-turn, a party struct can't be decoded, because the game is partway
through reading or changing it. There are two forms:
- With the flags in the u16 at +4 set (`Pokemon_EnterDecryptionContext`),
  the whole struct is plaintext.
- With no flags, inside `Pokemon_GetValue` and `Pokemon_SetValue` (decomp
  `src/pokemon.c`). These decrypt the battle stats, then the blocks, change
  a field, and encrypt both again in the same order. A frame can end at any
  point in between, even partway through one section.

In one of these windows the checksum still passes but the battle stats
decode as garbage, such as level 196. The env took that as a valid struct.

`gen4.decode_mon` now rejects every form. It rejects nonzero flags, and
battle stats that no real Pokémon has: a level outside 1–100, HP above max
HP, or status bits above 11. The status word is decrypted first, so a
section that is partly done fails too. The audit checks each rejected
struct the other way around: some in-place state must make it valid, or it
counts as a violation. `in_battle()` decodes the player's battle struct, so
it also reads False on those frames.

| Issue | Cause | Resolution |
|---|---|---|
| 12 violations on the first run, all mid-turn, all on the enemy's struct | The game held the struct decrypted with the flags set | `decode_mon` rejects nonzero flags |
| 56 more frames passed the checksum with garbage battle stats | The `Pokemon_GetValue` window: battle stats plaintext, blocks still encrypted, no flags | `decode_mon` checks that the battle stats are possible |
| 4 rejected structs in Hypnosis probes matched no whole-section state | The game was partway through encrypting the blocks again, after `Pokemon_SetValue` wrote the new move | The audit accepts sections that are partly converted |
| `test_barry_with_fixed_rng_is_won_in_five_turns` failed after the fix | Its helper stopped at the first frame `in_battle()` read False, before `resultMask` was set | The helper waits for 3 frames in a row |
| The overnight audit ran 7 h 20 min and produced nothing | The script passed `$NUZLOCKERL_ROM`, unset, as the ROM path instead of the default. `multiprocessing.Pool` replaces a worker whose setup raises, with no limit, so it never stopped: 17 million workers and 14 GB of tracebacks | The script uses the env's default ROM, and a setup error is raised from the first job in the main process. A missing ROM now exits 1 at once |
| An audit sampling every frame stalled in its main process after the workers finished | Not found | Killed it. Sampling every 10 frames runs fine. Still open |
| The random battles never moved a stat stage | In this hack Barry's Chimchar knows only Scratch, and Delibird only Present and Powder Snow | `--probe` forces the moves |

## 14. Switches, the forced switch, Struggle, and a richer observation (2026-11-12)

Goal: make team battles playable. Generated teams of 2 to 6 ended STUCK
whenever the lead fainted, the agent couldn't switch, and the observation
had no move types.

**What was built,** in `src/battle_env.py`:
- **A phase read from RAM.** `read_phase` turns `command`,
  `curCommandState[0]`, and the player's `SWITCHING` flag into one of
  ACTION_MENU, MOVE_MENU, PARTY_MENU, FORCED_SWITCH, or BUSY. Only
  ACTION_MENU and FORCED_SWITCH are decisions.
- **Routes.** `route_for` lists the screens each action passes through.
  `_walk` waits for each screen's phase, taps, and taps again if the phase
  doesn't change.
  - A switch taps POKéMON, then the slot, then SHIFT.
  - A forced switch taps the slot, then SHIFT.
- **Switches.** Actions 4–8 pick party-menu positions 1–5. The party menu
  follows `partyOrder`, not the order of the structs, so position k means
  `partyOrder[k]`.
- **The forced switch.** It is a decision but not a turn. The mask allows
  only living teammates, the reward is 0, the turn counter doesn't move,
  and `info["forced_switch"]` is set. A party has at most 6 Pokémon, so
  forced switches can't loop.
- **Struggle.** With no PP left, the mask allows only action 0. Tapping a
  move then makes the game use Struggle.
- **An 812-value observation** built from one `OBS_FIELDS` table. Each party
  slot, in menu order, has:
  - Types, level, HP fraction, 5 status flags, active, and alive.
  - For each move: type, power, accuracy, class (physical, special, or
    status), and PP fraction, all from `romdata`.

  Then come the enemy's active Pokémon (types, level, HP, status), which
  enemy slots have fainted, both sides' stat stages, the turn, and the
  forced-switch flag.

Species and move IDs are left out on purpose: an ID tells a network
nothing, while types, power, and class do. Max PP is the ROM's base PP,
because the RAM readers don't expose PP Ups.

**Verified.**
- On a team of 6, every position switched to the right Pokémon, 28 times
  with no retries, and switching back reached the previous Pokémon.
- On a team of 3 against a Lv12 Starly, the lead's faint reached the forced
  prompt, the mask allowed only the living teammates, and the battle went
  on to a win.
- With every PP at 0, the enemy still took damage.
- A random policy played 40 episodes over 7 states, including 62 switches
  and 9 forced switches, with 0 STUCK.
- 200 random battles under the RAM audit (§13) ended with 0 STUCK or
  errors.

The BattleContext fields are in [RAM_MAP.md](RAM_MAP.md#battle-system).

| Issue | Cause | Resolution |
|---|---|---|
| A slow POKéMON tap was tapped twice | The tap check ran 8 frames after the press, and that button reacts after 9 | `TAP_CHECK` is 20 frames, polled each frame. The party screen needs 40 frames before it takes a slot tap, and 30 between taps |
| Two episodes on the team of 6 ended as ENDED mid-battle | `in_battle()` read False for one frame. §13 found why: the game held the struct decrypted on that frame | ENDED needs 3 snapshots in a row with no battle |
| Command 21 didn't mark the forced switch alone | It also holds during the faint animation, and `curCommandState[0]` stays 14 | The forced switch is command 21 with `SWITCHING` set |
| `weaklead_vs_eevee.state` ends STUCK | After loading, the touch menu is never drawn, even after 600 frames. A fresh process sometimes works. The env at HEAD fails on it too | Left out of runs. The cause, found later, was a NooDS state-load bug (§17) |
| Trapping and move locks aren't modeled | No state uses Mean Look, Arena Trap, Disable, Encore, or a Choice item yet | A refused tap ends the step STUCK. Listed in the roadmap |

## 15. Training: an async env pool and masked PPO (2026-11-12)

Goal: train an agent on this project's CPU, and use every core while doing
it. Gymnasium's vector env steps all envs in lockstep. With 14 envs it kept
only 7.3 cores busy (§8), because every step waited for the slowest battle.

**What was built.**
- **`src/pool.py`, an asynchronous env pool.** Each env runs in its own
  spawned worker process, and the trainer acts on whichever envs are ready.
  - A worker that raises, dies, or stops answering becomes a `WorkerError`,
    never a silent hang.
  - Autoreset happens inside the worker, in the step that ends the episode,
    so one `send` is exactly one decision.
  - Workers are spawned, not forked, because the trainer holds torch
    threads, and a forked child can inherit a lock one of them held.
- **`src/ppo.py`, masked PPO** after CleanRL's `ppo.py`, with two 64-unit
  networks on the CPU.
  - Invalid actions get a logit of −inf, both when sampling and in the
    loss.
  - The pool returns envs in any order, so each transition carries its env
    ID and GAE runs over each env's own transitions.
  - A truncated episode bootstraps from the value of its last observation.
    A terminated one doesn't.
  - Observations are normalized with running statistics.
- **`scripts/train_ppo.py`** trains on a list of battle states.
  - It saves checkpoints atomically, and rerunning the same command resumes
    from the newest one. Log rows after that checkpoint are dropped, so
    each update is logged once.
  - It refuses a checkpoint trained on a different observation size.
- **`src/thermal.py`.** The thermal guard moved here from `rollout.py`, so
  training stops the same way when the CPU stays above 99 °C for 30 s.
  Training saves a checkpoint first.

`scripts/rollout.py` now uses the pool by default. `--pool gym` runs the
old lockstep path for comparison.

**Verified.**
- **Throughput,** with 14 envs, a random policy, and 3 runs each: the pool
  made 7.83 decisions/s against 6.02 for `AsyncVectorEnv`, 1.30× more.
  Busy cores went from 8.3 to 13.2. The numbers are in
  [EMULATOR.md](EMULATOR.md#how-many-emulators-to-run).
- **18 tests** in `tests/test_pool.py` and `tests/test_ppo.py` cover worker
  errors, autoreset, the mask, per-env GAE, bootstrapping, and resume. Each
  of 11 deliberate breaks of the code made a test fail.
- **Learning,** on a smoke battle with one damaging move, where a random
  policy wins 26 of 60. With 4 envs:

  | Decisions | Win rate | Mean return | Turns |
  |---|---|---|---|
  | 0 – 640 | 0.55 | −2.52 | 7.3 |
  | 640 – 1,280 | 0.85 | +3.09 | 6.4 |
  | 1,280 – 1,920 | 0.98 | +5.58 | 4.7 |
  | 1,920 – 5,120 | 1.00 | +6.00 | 3.2 |

- **Resume:** the trainer was killed with SIGKILL after update 8. The rerun
  resumed from update 5 and dropped the three logged updates it repeated.

**Risks for a long run.**
- 7.8 decisions/s is about 28,000 an hour, so a million decisions take
  about 36 hours.
- Any worker error stops training, and nothing restarts it. A battle state
  that fails to load is one such error, so a run should use only states
  that have been loaded and checked.
- STUCK is a truncation, so it bootstraps from the value of its last
  state. The agent might come to prefer a STUCK episode to a loss. This is
  untested.
- The settings are CleanRL's defaults, untuned. Entropy fell to 0.04 in the
  smoke run.

| Issue | Cause | Resolution |
|---|---|---|
| PufferLib, the plan's choice for the env pool, doesn't install | Versions 3.0.0 and 2.0.6 pin `gymnasium<=0.29.1`, and 3.0.0 also pins `numpy<2.0` | A small pool of our own, `src/pool.py` |
| The pool's speedup is below the ratio of busy cores | 14 emulators share 8 physical cores, so frames per busy core fell from 265 to 217 | Expected with hyperthreads |
| Installing torch upgraded setuptools from 59.6 to 78.1 | torch's dependencies | No effect seen. `requirements.txt` takes the CPU-only torch wheel |
| A trainer run crashed once mid-run | The env file was being edited by another task at the same time | Runs during that work used a frozen copy of the env. Three updates against the final env passed |

## 16. A fixed DS clock (2026-11-12)

Goal: the same inputs should give the same game on any host, at any hour.

**Finding.** `test_walking_changes_map_position_and_facing` passed when it
was written, at night, and failed the next morning with nothing changed.
The walk from `04_after_barry1_home.state` ended at z = 855 instead of 853.
NooDS sets the DS clock from the host's local time (`rtc.cpp`), and
Platinum's overworld changes with the time of day.

The cause was confirmed in two steps:
- With the time zone shifted so the local time read 22:47, the test
  passed. At 12:47 it failed.
- With the patched clock fixed at 22:00 it passed, and fixed at 12:00 it
  failed.

A time zone only shifts the clock, so it can't fix this. On a server in
another time zone, or at another hour, the walk to the generator's grass
state could end somewhere else.

**What was built.**
- `patches/noods-fixed-rtc.patch` makes NooDS use `NOODS_RTC_EPOCH` when
  it is set, and the clock stays at that time. `scripts/setup_env.sh`
  applies the patch before building PyNDS.
- `src/gen4.py` sets the variable to Wednesday 2026-11-11 22:00:00 (night)
  unless it is already set.
- `gen4.read_clock` reads the game's copy of the clock at 0x021BF5D8, and
  `test_clock_is_fixed` checks it. On the unpatched build that test fails,
  showing the host's real time.

Night was chosen because the walk script and the tests were recorded at
night. The day/night wild slots don't matter to the generator, which
writes all 18 slots.

| Issue | Cause | Resolution |
|---|---|---|
| The walking test failed in the morning | The DS clock follows the host's time, and the overworld changes with the time of day | NooDS reads a fixed time from `NOODS_RTC_EPOCH` |
| A time-zone setting can't pin the clock | A time zone only shifts the time, which still moves | Patch NooDS instead |
| PyNDS has no clock setting | Not exposed by its bindings | A 9-line patch to `rtc.cpp`, applied by `setup_env.sh` |
| An unpatched build would ignore the variable without a sign | The variable only does something in the patched build | `test_clock_is_fixed` reads the game's clock and fails on an unpatched build |

## 17. State loads that don't depend on what ran before (2026-11-12)

Goal: find why `weaklead_vs_eevee.state` ended STUCK (§14).

**Finding.** A rollout on that state ended 11 of 24 episodes STUCK. Every
STUCK was the first step of an episode: the action menu stayed up through
all 4 taps. In each worker, a STUCK episode came right after a WON or LOST,
and the episode after a STUCK was fine. Resetting mid-battle never failed.
So whatever ran before a load changed the loaded game.

To narrow it down:
- **One process, 10 resets after a finished battle:** 9 ended STUCK.
  Loading the state twice (load, 1 frame, load) brought that to 0.
  Running 600 frames before the reset didn't help.
- **The same input after a load.** The test applied a fixed battle seed,
  20 frames, a FIGHT tap, and 400 frames. A load after a LOST gave
  different RAM from a fresh process's load, and the tap did nothing. The
  double load wasn't a real fix: after a STUCK it gave different RAM too.
- **Memory frame by frame.** Right after the load, main RAM, both CPUs'
  I/O registers, ARM7 RAM, and shared RAM matched a fresh load exactly.
  One frame later the ARM7 had stopped: its frame counter at `0x03806DE8`
  stayed put, its sound registers froze, and its interrupt flags stayed
  pending. The ARM7 reads the touchscreen, so no tap reached the game.

**Cause.** NooDS's `SaveStates::loadState` restores `Core` first, and
`Core::loadState` picks the function that runs the CPUs from their halt
flags. The interpreters, and their halt flags, are restored after that. So
the run function followed the CPUs from before the load. A battle that just
ended leaves the ARM7 halted. After the next load the ARM7 should run, but
only the ARM9 did. The milestone states didn't trigger it, which is why
nothing failed before.

**Fix.** `patches/noods-load-state-run-function.patch` schedules
`UPDATE_RUN` once every component is loaded, the way a CPU's halt or wake
does. `scripts/setup_env.sh` applies every `patches/noods-*.patch`.

**Verified.**
- After a WON, a LOST, or a STUCK, single or double, every load gave the
  same RAM as a fresh process's load, and that matches what a fresh load
  gave before the fix.
- 10 resets after finished battles gave 0 STUCK.
- `test_a_state_loads_the_same_whatever_ran_before` builds the weak-lead
  scenario, plays it to the end, loads it, and compares RAM after a FIGHT
  tap with a fresh emulator. It fails without the patch.

| Issue | Cause | Resolution |
|---|---|---|
| After a won or lost battle, the next episode's taps were all ignored | NooDS picked the CPU run function from the halt flags before the load, so the ARM7 stayed stopped | Pick it again after the load (`noods-load-state-run-function.patch`) |
| My first check of the state found nothing (20 of 20 fine) | It reset mid-battle each time, never after a finished battle | Tested resets after finished battles |
| The double load looked like a fix | It only made the bad case rarer: after a STUCK it still gave different RAM | Compared RAM after the same input instead of counting STUCK |
| The old `weaklead_vs_eevee.state` came from the live clock | Generated before §16 | Moved out of the way; the test builds it again from its recipe |

## 18. Getting the PPO pilot ready (2026-11-16)

Goal: steps 1 to 3 of [NEXT_PHASE.md](NEXT_PHASE.md), and its open question
on how STUCK counts, so that the pilot can start.

**What was built.**
- `scenario.check_state` loads a state in a fresh env and plays one
  decision. It returns "ok", or why the state can't be played.
  `make_scenario.py` now runs it on every state it saves, and exits 1 on a
  failure.
- `scripts/make_battle_set.py` builds a set of battles from a JSON file,
  such as `scripts/pilot_battles.json`, and checks each one. Species are
  given by name, and each Pokémon gets its level-up moves at that level.
- `ppo.load_policy` and `ppo.evaluate` play a fixed number of episodes per
  env with a saved policy, sampled or always taking the most likely valid
  action. Nothing is learned. `scripts/eval_ppo.py` runs them on a list of
  states and prints the results per state. Three new tests cover the episode
  count, the mask in greedy play, and a trained checkpoint. Each of two
  deliberate breaks made a test fail. The script also ran end to end on the
  emulator.

**STUCK keeps bootstrapping.** The plan first said to end a STUCK as a
terminal step with 0 reward. That would make a STUCK worth 0, more than any
loss, so in a losing position the agent could learn to cause one. As a
truncation, a STUCK bootstraps from the value of its last state, so it is
worth about as much as playing on, neither rewarded nor punished. The real
fix for STUCKs the agent causes is in the action mask (below).

**Random-policy baseline,** with 8 envs:

| Split | Battle | Episodes | Won | Lost | STUCK | ENDED |
|---|---|---|---|---|---|---|
| train | Turtwig team vs Bonsly 15 | 60 | 56 | 4 | | |
| train | Turtwig team vs Lileep 13 | 44 | 44 | | | |
| train | Turtwig team vs Corsola 14 | 51 | 49 | 2 | | |
| train | Turtwig team vs Shuckle 13 | 47 | 1 | | 46 | |
| train | Chimchar team vs Bonsly 15 | 42 | 38 | 4 | | |
| train | Chimchar team vs Lileep 13 | 50 | 50 | | | |
| train | Piplup team vs Corsola 14 | 48 | 43 | 5 | | |
| train | Piplup team vs Shuckle 13 | 53 | 3 | | 50 | |
| train | Weak lead vs Bonsly 15 | 55 | 54 | 1 | | |
| train | Weak lead vs Lileep 13 | 50 | 49 | 1 | | |
| held out | Turtwig team vs Cranidos 16 | 46 | | | | 46 |
| held out | Chimchar team vs Gible 14 | 46 | 35 | 11 | | |
| held out | Piplup team vs Cranidos 16 | 49 | 1 | | | 48 |
| held out | Weak lead vs Gible 14 | 59 | 43 | 16 | | |

The set as written can't run the pilot:
- **The battles are too easy.** A random policy wins 87–100% of the eight
  playable training battles. With so little room above random, the pilot
  couldn't show learning.
- **Shuckle's battles end STUCK.** Shuckle knows Wrap and Encore, and the env
  models neither. Every STUCK came on turn 3 or later.
- **Cranidos ends its battles.** It knows Roar, which ends a wild battle.
  `resultMask` read 5, `BATTLE_RESULT_PLAYER_FLED` in the decomp.

Throughput was 5.4 decisions/s with 8 envs. A battle took about 9
decisions, against 4 to 6 in the milestone battles.

| Issue | Cause | Resolution |
|---|---|---|
| The plan's fix for STUCK would have rewarded it | A terminal 0 is worth more than any loss | Kept bootstrapping; the plan explains why |
| Every Cranidos battle ended after one decision as ENDED | The wild Cranidos's level-up moves include Roar, which ends a wild battle. It used Roar every time, so the hack's wild Pokémon may choose moves with an AI | The battles need another enemy, or the generator needs to set the enemy's moves (roadmap) |
| 95% of the Shuckle battles ended STUCK | Wrap traps the player, and the game refuses a switch. The 50 switch STUCKs stopped on the party menu. Encore locks a move, and the game refuses any other. The 45 move STUCKs stopped at the action menu | Needs the trapping and Encore RAM, so the mask can rule those actions out (roadmap steps 1 and 3) |
| A random policy wins almost every other battle | One wild Pokémon against a team of three at similar levels | The battles need stronger enemies before the pilot |
| The upstream bug-report drafts were lost during a trip | They were kept in a temporary folder that was cleared | Upstream was checked again for changes, and the reports were rewritten and posted the same day: [Hydr8gon/NooDS#210](https://github.com/Hydr8gon/NooDS/issues/210) and [unexploredtest/PyNDS#5](https://github.com/unexploredtest/PyNDS/issues/5) |

## 19. Setting the wild enemy's moves and held item (2026-11-16)

Goal: fix the battle set from §18. The wild enemies used their own level-up
moves, so Cranidos's Roar ended its battles and the stand-ins were far from
Roark's real team.

**What was built.** `scenario.set_enemy_moves` writes the enemy's moves at
full PP, and its held item, into both copies the battle keeps: its
`BattleMon`, which the battle and the enemy's AI use, and its party struct
in `enemyBase`, which the game later updates from the `BattleMon`.
`make_scenario` takes `enemy_moves` and `enemy_item`, `make_scenario.py`
takes `--enemy-moves` and `--enemy-item`, and a battle-set file can name
`enemy_sets` with moves and items by name.

**Verified by behavior.** A wild Delibird given only Growl and Leftovers:
- It used Growl every turn: the player's Attack stage went 6, 5, 4, 3.
- With its HP set to 10, Leftovers healed it by max HP / 16 each turn,
  10 to 11 to 12 to 13. That also confirms the `heldItem` offset, which
  had only been read as 0.

`test_set_enemy_moves_and_item_change_what_the_enemy_does` replays both. It
fails if either the moves or the item is left out of the `BattleMon` write.

**The pilot set now uses Roark's own sets** (ROM trainer 246): Bonsly,
Lileep, and Corsola in training, Gible and Cranidos held out, each with his
moves and held item. Shuckle is out: its Sand Tomb traps, which the env
can't model yet.

**Random-policy baseline,** 8 envs, 301 training and 160 held-out
episodes, 0 STUCK and 0 ENDED. "Clean win" is a win with no player faint,
what a Nuzlocke needs.

| Split | Battle | Win | Clean win | Return | Own faints |
|---|---|---|---|---|---|
| train | Turtwig team vs Bonsly | 1.00 | 0.69 | +4.86 | 0.38 |
| train | Turtwig team vs Lileep | 0.52 | 0.00 | −8.70 | 2.33 |
| train | Turtwig team vs Corsola | 0.58 | 0.08 | −6.54 | 1.96 |
| train | Chimchar team vs Bonsly | 0.96 | 0.77 | +4.35 | 0.35 |
| train | Chimchar team vs Lileep | 0.52 | 0.04 | −8.52 | 2.28 |
| train | Chimchar team vs Corsola | 0.23 | 0.06 | −13.94 | 2.52 |
| train | Piplup team vs Bonsly | 0.96 | 0.75 | +4.36 | 0.36 |
| train | Piplup team vs Corsola | 0.26 | 0.05 | −13.44 | 2.51 |
| train | Weak lead vs Bonsly | 1.00 | 1.00 | +6.00 | 0.00 |
| train | Weak lead vs Lileep | 0.16 | 0.06 | −15.45 | 2.68 |
| train | all | 0.61 | 0.37 | −4.71 | |
| held out | Chimchar team vs Gible | 0.77 | 0.00 | −3.57 | 1.97 |
| held out | Piplup team vs Cranidos | 0.54 | 0.03 | −7.77 | 2.13 |
| held out | Turtwig team vs Cranidos | 0.36 | 0.00 | −11.64 | 2.46 |
| held out | Weak lead vs Gible | 0.60 | 0.09 | −6.28 | 1.94 |
| held out | all | 0.56 | 0.03 | −7.36 | |

Apart from Bonsly, random play wins 16–77% of the battles and almost never
wins clean, so there is room above random. The clean-win rate and the
return, which counts −3 per faint, measure that better than the win rate.

| Issue | Cause | Resolution |
|---|---|---|
| Roar ended every Cranidos battle | The generator kept the wild Pokémon's level-up moves | The generator sets the enemy's moves and item; Cranidos now has Roark's Head Smash set |
| `git push` failed after the reboot | The remote is HTTPS and no credential helper was set; the earlier pushes went through the editor's login | After `gh auth login`, this repo's `credential.https://github.com.helper` uses `gh auth git-credential` |
| Bonsly faints on the first turn of `weak_lead_vs_bonsly` without hurting the lead | Not found. It knows Selfdestruct, but the Starly lead took no damage, even when the player switched | Open. Bonsly battles are near-certain wins, so they teach little about winning; their clean-win rate still leaves room |

## 20. The PPO check run (2026-11-16)

Goal: step 4 of [NEXT_PHASE.md](NEXT_PHASE.md). A short run on the 10
training battles, to check that training is healthy before the long pilot.

**The run.** 14 envs, 20,480 decisions in 20 updates, 49 minutes, with the
default settings (learning rate 2.5e-4, 1,024 decisions per update).
- 2,076 episodes, all WON or LOST: 0 STUCK and 0 ENDED.
- 6.8 to 7.1 decisions/s, and the CPU peaked at 88 °C.
- The return stayed at random play's level for 6 updates, while the
  critic learned (explained variance 0.02 to 0.32) and the policy barely
  moved (KL about 0.0002, no clipping). From update 7 it rose, and the
  last 4 updates gave returns of +0.13, −0.03, +0.63, and +1.25, with win
  rates of 0.82 to 0.87. Random play gives −4.71 and 0.61.

**Per training battle,** over the last 5 updates:

| Battle | Win (random) | Return (random) |
|---|---|---|
| Weak lead vs Lileep | 0.80 (0.16) | −1.2 (−15.5) |
| Chimchar team vs Corsola | 0.67 (0.23) | −3.2 (−13.9) |
| Piplup team vs Corsola | 0.71 (0.26) | −2.7 (−13.4) |
| Turtwig team vs Corsola | 0.90 (0.58) | +0.5 (−6.5) |
| Turtwig team vs Lileep | 0.81 (0.52) | −1.1 (−8.7) |
| Chimchar team vs Lileep | 0.39 (0.52) | −10.7 (−8.5) |
| The 4 Bonsly battles | 0.98–1.00 (0.96–1.00) | about the same |

**Held out,** the final checkpoint with `eval_ppo.py`, 42 episodes per
battle:

| Battle | Random | Sampled | Greedy |
|---|---|---|---|
| Piplup team vs Cranidos | 0.54, −7.8 | 0.83, −1.2 | 1.00, +3.4 |
| Turtwig team vs Cranidos | 0.36, −11.6 | 0.71, −3.6 | 0.76, −1.2 |
| Chimchar team vs Gible | 0.77, −3.6 | 0.79, −2.4 | 0.83, −0.8 |
| Weak lead vs Gible | 0.60, −6.3 | 0.60, −6.3 | 0.38, −11.8 |
| All | 0.56 | 0.73 | 0.74 |

Cranidos never appeared in training, so learning on the emulator
generalizes past the battles it trained on.

| Issue | Cause | Resolution |
|---|---|---|
| The policy didn't move for the first 6 updates | The critic had to learn first: the advantages that steer the policy are only as good as the value estimates | None needed; it learned once explained variance rose |
| Chimchar team vs Lileep got worse than random | Not found. A guess: a habit learned on the other battles, such as staying in to attack, costs this one | Open. Check what the policy does there |
| Greedy play on Weak lead vs Gible did worse than random | Not found. The same guess: it may not switch the weak lead out | Open. Same check |
| The training log can't show the clean-win rate | Episode records keep the outcome and return, not the player's faints | Open. Count faints per episode before the pilot |

## 21. Type matchups, a faint penalty by strength, and clean wins (2026-11-16)

Goal: three changes before the pilot. The agent had to learn the type
chart from rewards alone. Every faint cost the same, so it had no reason to
protect its strongest Pokémon. And the logs couldn't show a clean win.

**The type chart, from the ROM.** `romdata.type_chart` reads the hack's
`sTypeMatchupMultipliers` (decomp `src/battle/battle_lib.c`) from battle
overlay 16, found by searching for vanilla's first rows. It matches vanilla
Platinum byte for byte. The check in battle: Tackle did no damage to a
Gastly. With the Normal-vs-Ghost row of the table in RAM changed to super
effective, the same Tackle hit for 20, so the battle reads this table.
`romdata.type_effectiveness` multiplies the chart over a target's types.

**Matchups in the observation,** 902 values now, from 812:
- For each move: its effectiveness against the enemy's active Pokémon, as
  log2 of the multiplier over 2 (¼ reads −1, 4× reads 1, immune reads −1);
  an immune flag; and the same-type bonus.
- For each party Pokémon: how hard each of the enemy's types hits it. The
  enemy's moves are hidden, so its types stand in for them.
- For each party Pokémon: its strength, below.

**A faint penalty by strength.** A Pokémon's strength is its stat total
(max HP plus the other five stats) over the team's highest, 1 for the
strongest. A player faint costs −(1 + 7 × strength): about −2.4 for fodder
and −8 for the ace. With +5 for a win and +1 for the enemy's faint, a win
that costs fodder pays (+3.6), a win that costs the ace doesn't (−2), and a
loss (−10) is still worse than either. The agent may sacrifice fodder to
bring the ace in safely, which the forced switch makes possible. Stats are
only a stand-in for a Pokémon's value to the run: a weak Pokémon might be
the only answer to the next Gym. The gauntlet env planned for the Nuzlocke
rules should replace it with the real cost, fewer options later.

**Clean wins in the logs.** The trainer and `evaluate` count player faints
per episode, from the env's events. `episode_stats` reports the clean-win
rate (won with no player faint) and faints per episode, in
`metrics.jsonl`, the progress line, and `eval_ppo.py`.

**Tests.** The matchup features on a made-up Turtwig against Gastly, the
strength and penalty arithmetic, and faint counting in training and
evaluation on a fake env. The three env tests that assumed a flat −3 now
use the new rule. Each of two deliberate breaks of the faint counting made
a test fail. 97 tests pass.

| Issue | Cause | Resolution |
|---|---|---|
| The agent had to learn type matchups from rewards | The observation had the types but not the chart | The chart's multipliers are in the observation |
| Losing the ace cost the same as losing fodder | A flat −3 per faint | The penalty scales with strength |
| The logs couldn't show a clean win | Episode records had no faint count | The trainer and the eval count faints |
| A PPO test failed after the change | It compared whole episode records, which now have a faint count | The expected records include it |

## 22. The check run again, with matchups and the new penalty (2026-11-16)

Goal: rerun step 4 of [NEXT_PHASE.md](NEXT_PHASE.md) with §21's changes, to
see whether they help before the long pilot.

**The run.** The same 10 battles, 14 envs, 20,480 decisions, default
settings, in `runs/pilot_check2`. 0 STUCK or ENDED, 6.7 to 7.4 decisions/s,
CPU peak 87 °C. The policy started to move at update 7, as in the first
run. The last update reached a win rate of 0.91, a clean-win rate of 0.54,
and a return of −0.64. Returns don't compare with the first run's, since a
faint now costs more.

**Per training battle,** the last 5 updates of each run:

| Battle | Win: random / run 1 / run 2 | Clean win: random / run 2 |
|---|---|---|
| Chimchar team vs Lileep | 0.52 / 0.39 / 0.61 | 0.04 / 0.10 |
| Chimchar team vs Corsola | 0.23 / 0.67 / 0.86 | 0.06 / 0.39 |
| Turtwig team vs Corsola | 0.58 / 0.90 / 0.93 | 0.08 / 0.32 |
| Piplup team vs Corsola | 0.26 / 0.71 / 0.63 | 0.05 / 0.26 |
| Weak lead vs Lileep | 0.16 / 0.80 / 0.64 | 0.06 / 0.26 |
| Turtwig team vs Lileep | 0.52 / 0.81 / 0.72 | 0.00 / 0.10 |
| The 4 Bonsly battles | 0.95–1.00 throughout | about random |

**Held out,** the final checkpoint, 42 episodes per battle:

| Battle | Random: win / clean | Run 1 greedy: win | Run 2 greedy: win / clean |
|---|---|---|---|
| Weak lead vs Gible | 0.60 / 0.09 | 0.38 | 0.86 / 0.00 |
| Piplup team vs Cranidos | 0.54 / 0.03 | 1.00 | 1.00 / 0.50 |
| Turtwig team vs Cranidos | 0.36 / 0.00 | 0.76 | 0.76 / 0.33 |
| Chimchar team vs Gible | 0.77 / 0.00 | 0.83 | 0.98 / 0.07 |
| All | 0.56 / 0.03 | 0.74 | 0.90 / 0.23 |

Sampled play on the held-out battles: win 0.74, clean win 0.13.

What changed:
- Both of run 1's weak spots are fixed. Chimchar team vs Lileep now beats
  random, and greedy play on Weak lead vs Gible went from 0.38 to 0.86.
- Clean wins rose 4 to 6 times on the Corsola battles, and from 0.03 to
  0.23 on the held-out ones.
- Some win rates are below run 1's while their clean wins rose: the
  policy now gives up some wins rather than lose its strongest Pokémon,
  which is the trade the new penalty sets.

**A progress chart.** `scripts/plot_runs.py` draws the win and clean-win
rates of any runs against decisions trained, as a 3-update mean with each
update's value as a dot, and random play as a reference line. It writes a
PNG, by default `runs/progress.png`. `--state` plots one battle; `--return`
adds a return panel, which only compares runs with the same reward.
`--by-battle` draws a heatmap per run instead: a row per battle, a column
per few updates on a shared decisions scale, colored by the clean-win rate
(or `--metric win`), with each row's first and last values. It shows which
matchups are learned and when.

| Issue | Cause | Resolution |
|---|---|---|
| There was no way to see the runs improve except reading JSON lines | No chart | `scripts/plot_runs.py` |
| matplotlib wasn't installed | Nothing had plotted before | Installed, and added to `requirements.txt` |
| The first chart's labels overlapped the lines and each other | The random-play label sat where the runs start, and both runs end near 0.85 | Random play is labeled at the right end, under its line; run ends are labeled in a column to the right, with leader lines |
| The two runs' returns can't be compared | The faint penalty changed between them | The return panel is opt-in, and its title says so |
| The heatmap's runs didn't line up | Each panel drew one column per bin, so a column covered a different number of decisions in each run | Columns span the decisions they cover, on a shared axis |
| A map of where the agent goes was asked for | The agent never walks: every episode starts and ends in a battle | The per-battle heatmap shows progress for now; a map trace belongs with the overworld (roadmap step 5), where the location RAM is ready |

## 23. The pilot's first 60,000 decisions, and a missed Selfdestruct (2026-11-16)

Goal: look at the pilot's data part-way through for anything wrong, and
decide what else to track.

**Training looks healthy.** In bins of 8 updates, from the first to the
seventh: win rate 0.60 → 0.92, clean-win rate 0.35 → 0.74, faints per
episode 1.58 → 0.46, decisions per episode 10.9 → 5.3. Entropy fell
steadily from 1.52 to 0.68 without collapsing. KL stayed at 0.002–0.004
and the clip fraction at 0.03–0.05. Explained variance rose from 0.16 to
0.40 and value loss fell from 76 to 31. Throughput was 6.9–7.4
decisions/s at 74–77 °C. Every episode ended WON or LOST, with no STUCK,
TURN_CAP or ENDED.

**Per battle,** clean-win rate in the first bin → the seventh:

| Battle | Clean win | Note |
|---|---|---|
| Turtwig team vs Corsola | 0.07 → 0.92 | |
| Chimchar team vs Corsola | 0.05 → 0.84 | |
| Piplup team vs Corsola | 0.09 → 0.71 | Flat at 0.59–0.71 since the third bin |
| Turtwig team vs Lileep | 0.10 → 0.47 | |
| Weak lead vs Lileep | 0.00 → 0.42 | |
| Chimchar team vs Lileep | 0.01 → 0.13 | Wins rose from 0.27 to 0.81, but almost never clean |
| The three team-vs-Bonsly battles | 0.65–0.80 → 0.85–0.99 | |
| Weak lead vs Bonsly | 1.00 throughout | Every episode: one decision, a win, no faint, +6 |

**The Bonsly anomaly is an env bug.** In Weak lead vs Bonsly, Bonsly uses
Selfdestruct on the first turn, whatever the agent does. The game sets the
user's HP to 0 before the blast lands, and the env ends the episode as soon
as a snapshot shows a side at 0 HP. So the env records a clean win and +6.
Ticking on after the env stops shows the real turn: 200 frames later the
blast knocks out Starly, or Turtwig if the agent switched to it, and the
game records the win (`battleResult` 1) after about 740 frames. The faint,
and its penalty, never reach the agent. This battle was meant to teach
the fodder trade: keep the weak Starly in to take the blast rather than
switch in the ace. The bug hides that trade, and any Selfdestruct in the
other three Bonsly battles is missed the same way. It also inflates the
pilot's overall rates: Weak lead vs Bonsly is a tenth of all episodes.

**What the logs can't show yet.** Training logs aggregates per update, so
nothing records which moves were picked, how much PP was left, or which
Pokémon fainted. The env can write a log of every step (`log_path`), but
neither the trainer nor `eval_ppo.py` turns it on, and the step record has
the action slot but not the move or its PP. Two limits of the battle set
also came up:

- **No setup moves.** The teams' only status moves are Helping Hand,
  which fails in a single battle, Sand-Attack and Flash (accuracy drops,
  5 PP each in the hack), and PoisonPowder and Stun Spore. Nothing raises
  the user's stats, so this set can't show attack-versus-setup choices
  such as Swords Dance.
- **The agent can't see what a status move does.** The observation gives
  each move's type, power, accuracy, class, PP and type matchup, not its
  effect. A status move can only be told apart by those numbers, which
  doesn't carry over to a move it hasn't seen.

**The fix.** On a wipe, the env now runs on until the game records the
result, and takes the faints from the last snapshot before that
(`BattleEnv._await_result`). In a wild battle the result comes 300 to 800
frames after the first 0 HP. The pilot was stopped at 61,441 decisions; its
run is kept as `runs/pilot_v1` and is not comparable with later runs. The
fix changes the starting point a lot. In the first update, with a
near-uniform policy, the clean-win rate was 0.42 before the fix and 0.04 to
0.08 after. Most of random play's clean wins were Bonsly battles whose
Selfdestruct went uncounted, so the random baseline of §19 (0.37 clean) is
too high and has to be measured again.

**The game's result as a check.** Every episode now records the game's
result next to the env's outcome, and a WON or LOST that the game
contradicts is counted (`result_mismatches`). The first restart showed 2 or
3 a update, about 3% of episodes, in its first update. The cause: the wait
stopped at the first snapshot that read invalid, but the game decrypts a
party struct in place while it writes the exp after a win, so the wait
ended before the result. It now skips such reads, as the main loop does
(`ENDED_CHECKS`), and the next restart had 0 in its first updates.

**What is tracked now.** Each step's info names the decision: the move, its
PP before the turn, and its kind (an attack's type matchup against the
enemy, super, neutral, resisted or immune; a status move; a switch; a forced
switch; Struggle), and the strength of each Pokémon that fainted. Training
and `eval_ppo.py` add these up per battle in `metrics.jsonl`: `picks` and
`moves` count decisions by kind and by move, `mean_ace_faints` and
`mean_other_faints` split faints between the team's strongest Pokémon and
the rest, `pp_ran_dry` counts moves run out of PP. The step log has the
move and PP too, and `eval_ppo.py --step-log DIR` writes it.

**New charts.** `scripts/plot_runs.py --view` draws them. `health`: entropy,
KL, clip fraction, explained variance, value loss, decisions/s, CPU
temperature, and the episodes that need a look (STUCK, TURN_CAP or ENDED,
or a result mismatch), runs overlaid. `faints`: per battle, faints per
episode of the strongest Pokémon and of the rest. `picks`: per battle, the
share of decisions by kind. `moves`: per battle, a heatmap of each move's
share of the decisions. `--by-battle --metric length` shows decisions per
episode; it would have shown the Bonsly anomaly from the first update, a
battle stuck at exactly 1.

**The cost.** The wait adds a few hundred frames to every episode. The
first updates ran at 6.2 to 6.3 decisions/s, where the stopped run ran at
7.0; the gap will widen as episodes get shorter. The pilot was restarted at
1d1ec49, and 300,000 decisions should take about 14 hours.

| Issue | Cause | Resolution |
|---|---|---|
| Weak lead vs Bonsly is always a clean win in one decision | The env ends an episode at the first snapshot with a side at 0 HP; Selfdestruct zeroes the user's HP before its damage lands | On a wipe, run on until the game records the result (`battleResult`), and take the faints from then. The pilot was restarted |
| Random play's clean-win rate (§19) is too high | Measured with the Selfdestruct bug, which made most Bonsly battles clean wins | Measured again in §24: 0.06 clean on the train split |
| About 3% of episodes ended before the game recorded the result | The wait for the result stopped at the first snapshot that read invalid, as one does while the game writes the exp after a win | Invalid reads are skipped while the battle runs. Found by the new mismatch count in the first update |
| Move choice, PP and who faints weren't recorded | The trainer logged per-update aggregates; the step log was off and lacked the move and PP | Counted per battle in `metrics.jsonl`, in the step log, and charted (`--view`) |
| Episodes are slower to finish | The wait for the result | Accepted: about 10% fewer decisions/s early on. A battle command that marks the end of the turn could cut the wait; it needs the decomp's command list |
| After a trainer battle the wait runs to its 2,000-frame limit | The game records a trainer battle's result later, after the trainer's closing text | Fixed in §26: the wait was a level-up's text, which waits for a button. The env answers it |
| The battle set has no setup moves | The teams get their level-up moves, which have none at these levels | Open: give some teams a setup move, the way the generator sets the enemy's |
| Status moves are told apart only by their numbers | The observation has no move-effect field | Open: an effect category from the ROM's battle effect id |

## 24. The pilot's result (2026-11-17)

Goal: answer the pilot's question ([NEXT_PHASE.md](NEXT_PHASE.md)). Can
PPO learn battles on the emulator, or does training need a Python battle
simulator?

**The run.**
- 300,032 decisions on the 10 training battles, with 14 envs.
- It took 14.1 hours at 5.9 decisions/s; the CPU peaked at 82 °C.
- Every episode ended WON or LOST. There were no STUCK, TURN_CAP or ENDED
  episodes, and no result the game contradicted.
- Entropy fell from 1.54 to 0.15 without collapsing, and explained variance
  rose to 0.45.

**A new random baseline.** `eval_ppo.py --mode random` plays every valid
action with equal odds and reports the same numbers as a checkpoint. It was
measured with the Selfdestruct fix (§23), 60 episodes per battle:

| Split | Win | Clean win | Return | Faints per episode |
|---|---|---|---|---|
| train | 0.56 | 0.06 | −15.7 | 1.98 |
| held out | 0.65 | 0.08 | −14.3 | 1.96 |

The clean-win rate of 0.37 in §19 came from the Selfdestruct bug.

**The training battles were learned fast.** The 3-update mean of the
training win rate passed random + 0.3 (0.86) after 27,648 decisions, in
1.3 hours. The clean-win rate passed 0.5 after 32,768. After about 60,000
decisions, little changed. Checkpoints, greedy play, 50 episodes per
battle:

| Decisions | Train: win | Train: clean | Held out: win | Held out: clean |
|---|---|---|---|---|
| random play | 0.56 | 0.06 | 0.65 | 0.08 |
| 51,200 | 0.95 | 0.57 | 0.83 | 0.21 |
| 102,400 | 0.96 | 0.64 | 0.72 | 0.12 |
| 153,600 | 0.95 | 0.65 | 0.71 | 0.12 |
| 204,800 | 0.95 | 0.65 | 0.84 | 0.12 |
| 256,000 | 0.96 | 0.67 | 0.81 | 0.12 |
| 300,032 | 0.96 | 0.67 | 0.72 | 0.12 |

Sampled play gives about the same numbers. At 300,032 decisions: train
0.95 win and 0.65 clean, held out 0.77 and 0.12.

**Held out was best at 51,200 decisions, then got worse.** Per battle,
greedy, win / clean:

| Battle | Random | 51,200 | 300,032 |
|---|---|---|---|
| Piplup team vs Cranidos | 0.73 / 0.05 | 0.96 / 0.40 | 0.98 / 0.40 |
| Chimchar team vs Gible | 0.78 / 0.10 | 0.92 / 0.14 | 0.90 / 0.08 |
| Weak lead vs Gible | 0.70 / 0.12 | 0.56 / 0.00 | 0.78 / 0.00 |
| Turtwig team vs Cranidos | 0.37 / 0.05 | 0.88 / 0.32 | 0.24 / 0.00 |

Turtwig team vs Cranidos accounts for the drop, and the cause is Turtwig's
move:
- **Mega Drain** is Grass, super effective on Rock, and Turtwig's own type.
  It takes about 18 of Cranidos's 47 HP on the first turn. **Bite** takes about
  11.
- At 51,200 decisions the policy picked Mega Drain in 131 of 172 decisions.
  From 102,400 on it picked Bite, 174 of 210 decisions by the end.
- Pooled over more seeds:

  | Checkpoint | Episodes | Win | Clean win |
  |---|---|---|---|
  | 51,200 | 148 | 0.72 | 0.28 |
  | 300,032 | 120 | 0.30 | 0.00 |

  The final policy is worse than random (0.37), and Turtwig faints in every
  episode.

In training, the Turtwig teams fight Bonsly, Corsola and Lileep:
- **Bonsly** is pure Rock, like Cranidos. Turtwig used Mega Drain on it
  7,174 times out of 7,209.
- **Lileep** is Rock/Grass. Mega Drain is only neutral on it, so Turtwig
  learned Bite there.

Cranidos and Bonsly look the same to every type-matchup feature of the
observation, yet the policy treats Cranidos like Lileep. So it picks moves
by something other than the matchup, most likely the enemy's stats or
level. With three enemy species in training, nothing forces the matchup to
be what decides. This is the plan's "learns train but not held-out" case,
for one held-out battle out of four.

**What else it learned:**
- **Weak lead vs Bonsly: Sand-Attack every time,** 3,187 of 3,209 decisions
  in the second half of training. Starly moves first and lowers Bonsly's
  accuracy, and Bonsly's Selfdestruct then misses some of the time. At the
  final checkpoint, 16 of 100 episodes ended with Starly at full HP and
  Bonsly fainted. The strongest Pokémon never switched in to take the blast:
  its faints fell from 0.19 per episode to 0.
- **Chimchar team vs Lileep: 0.96 win but only 0.30 clean,** and Chimchar
  faints in 70% of episodes. Chimchar leads with Karate Chop, the team's
  only super-effective move. Lileep heals with Recover and with Giga Drain
  boosted by its Big Root, so Chimchar usually faints by its third turn and Shinx
  finishes with Bite. The penalty can't teach a fodder trade here: Chimchar
  costs −8.0, Geodude −7.82 and Shinx −7.06. The strength scale only
  separates fodder from the ace when the team has a real weak member.

**The decision: keep training on the emulator.** The 10 battles were
learned in about 30,000 decisions, an hour and a half, so emulator speed
isn't what limits this. Generalizing to new battles is. The plan's rule for
this case is "try more varied battles before blaming the emulator". A
simulator becomes worth its cost only if a varied set needs far more
decisions: at 5.9 decisions/s, a million take 47 hours. Measure that first.
The next steps are in [NEXT_PHASE.md](NEXT_PHASE.md#after-the-pilot).

| Issue | Cause | Resolution |
|---|---|---|
| Held out got worse after 51,200 decisions while train kept improving | Too few battles: Turtwig learned Bite from the Lileep battle and used it on Cranidos, where Mega Drain is far stronger | Open: more varied battles, held out evaluated during training, and the best checkpoint kept by its held-out result |
| The random baseline of §19 was too high | The Selfdestruct bug (§23) | Measured again with `eval_ppo.py --mode random`: 0.56 win and 0.06 clean on train, 0.65 and 0.08 held out |
| Random play couldn't be measured with the same numbers as a checkpoint | `rollout.py` counts outcomes only | `eval_ppo.py --mode random` |
| 50 episodes per battle give noisy results | One battle turns on a few rolls. The 51,200 checkpoint won Turtwig team vs Cranidos 44 of 50 times, then 14 of 28 and 48 of 70 with other seeds | Pool seeds, or play more episodes, for any number a decision rests on |
| The README's rules banned every bag item in battle, which rules out catching | The rule was written before catching was planned | Poké Balls are allowed for a route's first encounter; healing and battle items stay banned |
| The faint penalty doesn't separate fodder from the ace in a balanced team | Strength is the stat total over the team's highest, and the Chimchar team's totals are within 14% of each other | Open: a gauntlet env, where a faint costs options in later battles (roadmap step 2), is the real fix |

## 25. The plan after the pilot (2026-11-17)

Goal: decide, with the user, what follows the pilot. The plan is in
[NEXT_PHASE.md](NEXT_PHASE.md#after-the-pilot).

**The goal.** Beat Platinum Kaizo under the README's rules, with a model
that can then be placed in another Nuzlocke game and learn to beat that one
on its own, given time. Emerald Kaizo is the second game. A model that wins
any ROM on the first try was considered and set aside: that's beyond
anything published. Learning a new game faster than a fresh model is
realistic, and it can be measured.

**Decisions:**
- **Everything is learned in live runs,** from Twinleaf Town to Roark's
  badge. The first draft of the plan put about 500 generated battles before
  the live game, because they cover more matchups, evenly, and work now.
  The user chose live runs. Generated battles stay as a test only.
- **The rules are written out in full** in the README. Catching with Poké
  Balls is part of the first-encounter rule, and the duplicates, shiny and
  Set clauses were added.
- **The walk is scripted first, then learned.** The way to Oreburgh is close
  to linear, so a scripted walk loses nothing and gets each run to its
  battles and catches. Learned walking is rewarded once per waypoint.
- **Restart states, for training only.** A state saved before each battle
  of every run gives later battles practice while most early runs still
  die. A run that counts plays from the start.
- **Built to move to another game:** one game adapter, the rules as a
  config file, rewards from events every game has, and a game-neutral
  observation. Scripted pieces are scaffolding, to be replaced.
- **Emerald Kaizo after the Platinum loop works,** on mGBA with a Gen 3
  adapter. The transfer test trains the Platinum model and a fresh one
  there with the same budget. KP Labs' 12 trainer battles are the baseline.
- **Randomized ROMs** are a later tool for robustness, not needed now.
- **Skills in the weights, facts from the ROM.** The policy learns what
  every Pokémon game shares: matchups, switching, protecting the ace. What
  differs between games, such as route encounters, boss teams, obstacles
  and the field move that clears each, is read from the game's data and
  put in the observation, as a player uses a guide.
- **Field moves join team building.** Keep a Pokémon that can use the
  move, and a backup in case it dies. Using it in the field is scripted at
  first; none is needed before Roark.
- **The party and the PC are the agent's to manage, within the rules.** At
  each Pokémon Center it chooses which caught Pokémon to withdraw and the
  party's order. Depositing the fainted is enforced, not learned, since
  learning it would mean breaking the rule while it learned. Decided after
  the route runner's breakdown (NEXT_PHASE step 3).
- **The agent chooses its starter,** as the first decision of every run.
- **+20 for each boss beaten, with γ = 0.999 for runs,** to start. The size
  sits between an ordinary battle's reward and the cost of three strong
  faints. The discount lets a reward 250 decisions away keep 78% of its
  value, where 0.99 keeps 8%.

| Issue | Cause | Resolution |
|---|---|---|
| Live play would end within minutes | The env handles only the middle of a single wild battle. Level-up prompts, a trainer battle's late result, text, catching and trapping moves all end an episode | Steps 1 to 3 of the plan build each |
| A run meets the same trainers every time, so runs alone can't tell learning from memorizing | The game's trainers are fixed | Battles generated against Pokémon the runs never meet, as a test only |
| Scripted pieces would have to be rewritten for every new game | They encode Platinum's paths, menus and prompts | Treated as scaffolding: each gets a learned or generic replacement |

## 26. Trainer battles' results and level-up prompts (2026-11-17)

Goal: step 1 of the plan after the pilot. Make the env survive what a live
run meets, starting with the end of a trainer battle (§23).

**The cause was a level-up, not the trainer's text.** Barry 1 was played to
the end while tracing `BattleContext.command`. With no input, the battle
stopped 285 frames after the last faint, inside a battle script, and never
recorded a result. Pressing A every 30 frames got the result 920 frames
after the faint, *before* the trainer's closing text, which then ran
without input. The decomp's experience task (`BattleScript_GetExpTask`)
explains it:
- Ordinary battle messages wait for a button *or* a timeout
  (`WaitButtonABTime`), so they move on alone.
- After a level-up, the "grew to Lv. N!" message waits for A or B, and the
  two stat boxes wait for any button. X doesn't move the message on.
- A fifth move brings two yes/no prompts on the touch screen, and a screen
  to pick the move to forget.

Barry's Chimchar gives Turtwig a level. Wild battles in the pilot gave too
little EXP for one, so the problem hadn't shown up.

**The experience task in RAM.** `BattleContext.taskData` (ctx+0x178) points
to the running task, NULL when none runs. It was found as the block whose
second word points back at the context. The task's state is at +0x28, the
move to learn at +0x30 + 16, and the party slot at +0x30 + 24, all as the
decomp's structs give them (`gen4.read_script_task`, RAM_MAP.md).

**What the env does.** While a step runs and while it waits for the
result, `_answer_exp_task` reads the task:
- **Level-up text and stat boxes (states 7, 11, 13):** B. B answers no
  question in those states.
- **"Make it forget another move?" (21):** a stand-in for the agent's choice,
  `move_to_forget`. It values each attack as power × accuracy, ×1.5 in the
  Pokémon's own type, and a status move as 0. If the new move is worth more
  than the lowest-valued one, the env taps "Forget a move!", taps that move,
  then taps FORGET on its page. Otherwise it taps "Keep old moves!", then
  "Give up on" the move (34).
- Each decision is logged: the episode's final info and the step log's
  summary list each offered move and what was forgotten.

Evolution comes after a battle ends, outside the battle env, so it's left
to the route runner.

**Verified:**
- Barry 1 now ends with the game's own result (1) inside the episode, about
  1,150 frames after the last faint, for every seed tried.
  `test_barry_with_fixed_rng_is_won_in_five_turns` checks it.
- `test_a_fifth_move_replaces_the_weakest`: Turtwig, one EXP short of 15
  with Tackle, Mega Drain, Bite and Rock Throw, beats a Bidoof. The battle's
  copy of the party then reads Razor Leaf, Mega Drain, Bite, Rock Throw.
- `test_a_weaker_fifth_move_is_given_up`: Chimchar, one EXP short of 12,
  where it learns Helping Hand, keeps its four attacks.
- The generator takes `exp` in a party spec, for a Pokémon close to its next
  level. The whole suite passes, 104 tests.

| Issue | Cause | Resolution |
|---|---|---|
| A trainer battle never recorded its result | Turtwig leveled up; the level-up message and stat boxes wait for a button | The env presses B in those states of the experience task |
| A level-up in the middle of a trainer battle would hold the step until STUCK | The same wait, before the trainer's next Pokémon | The same handler runs while a step plays out, not only after a wipe |
| A fifth move needs an answer | The game asks whether to forget a move | A stand-in choice, `move_to_forget`, until the agent makes it (NEXT_PHASE step 1) |
| Tapping a move on the forget screen didn't forget it | The tap opens the move's page, which has its own FORGET button | Tap the move, wait 30 frames, tap FORGET |
| The wait for the result could run past 2,000 frames | A level-up takes about 1,150 frames; a forgotten move adds more | `END_FRAME_GUARD` is 4,000 |
| The catch animation uses the same task struct | Its states would read as the experience task's | Open: tell the two apart when the Poké Ball action comes (NEXT_PHASE step 2) |

## 27. Trapping and move locks in the action mask (2026-11-17)

Goal: step 1 of the plan after the pilot. Stop a refused action from ending
a step as STUCK, as 95% of random-play battles against a wild Shuckle did
(§18).

**What the game refuses,** from the decomp:
- **Moves** (`BattleSystem_CheckInvalidMoves`): no PP, the Disabled move,
  the last move under Torment, a status move under Taunt, every move but
  the encored one under Encore, and every move but the locked one with a
  Choice item. Also Imprison, Gravity and Heal Block. With no move left,
  FIGHT makes the game use Struggle.
- **Switching** (`Battler_IsTrapped`): bound by Wrap and the like, under
  Mean Look, Block or Spider Web, rooted by Ingrain, or held by the enemy's
  Shadow Tag, Magnet Pull (if Steel) or Arena Trap (if grounded). A held
  Shed Shell overrides all of these.
- **Under Encore, FIGHT uses the encored move at once,** with no move menu.
  The env's move route waited for that menu, so it would have stalled.

**The RAM.** The env now reads the player's active `BattleMon` at every
prompt (`gen4.read_battle_effects`). That means the types, ability, held
item, `statusVolatile`, `moveEffectsMask`, the `MoveEffectsData` bit fields,
`disabledMove`, `encoredMove` and `choiceLockedMove`, all at their decomp
offsets. It also reads `movePrevByBattler` at ctx+0x307C, and the enemy's
ability. See RAM_MAP.md.

**What the env does:**
- `Snapshot` carries `locks` (per move slot), `encored` and `trapped`.
- `action_mask` allows a move only if it has PP and no lock, and no switch
  while trapped. A forced switch is still allowed, since the trapped
  Pokémon has fainted.
- Struggle now means no move is allowed, not only no PP.
- Under Encore or Struggle, a move action taps FIGHT alone.

The hack has no Taunt and no Bind: their move ids hold Mystical Fire and
HP Dark. The Taunt check stays, since other Gen 4 games need it. Imprison,
Gravity and Heal Block aren't modeled. Before Roark, the trap and lock
moves are Wrap (wild Onix, Ekans and Bellsprout), Sand Tomb (Roark's
Shuckle) and Disable (wild Venonat). The only trap ability is Magnet Pull
(Magnemite), which holds only Steel types.

**Checked against the game.** Each test battle pits Turtwig against a slow
Shuckle that knows only the move under test. The test saves a state at
the prompt where the effect holds. From there, it tries every action
through the menus, mask or not, and the mask must say exactly which ones
the game accepts:

| Case | Mask = what the game accepts |
|---|---|
| Wrap | 4 moves yes, switch no |
| Mean Look | 4 moves yes, switch no |
| Disable (Tackle) | Tackle no, the other 3 and the switch yes |
| Torment (after Tackle) | Tackle no, the other 3 and the switch yes |
| Choice Band (after Tackle) | Tackle and the switch yes, the other 3 no |
| Encore (Tackle) | Only Tackle, through FIGHT alone: its PP fell by 1 |

`test_mask_matches_what_the_game_accepts`,
`test_encore_allows_only_the_encored_move_and_uses_it_from_fight`, and
`test_trap_rules_the_game_cant_show_here` cover them. The last checks
Shadow Tag, Arena Trap, Magnet Pull and Shed Shell, which nothing before
Roark brings. The whole suite passes, 111 tests.

**Found on the way: the enemy's first move is fixed in a saved battle
state.** In these battles the enemy did nothing on turn 1 and used its move
from turn 2. Across 10 battle seeds per state, the enemy's turn-1 move
never changed:

| State | Turn-1 move, 10 seeds |
|---|---|
| Pilot, Turtwig team vs Bonsly | Brick Break 10 times |
| Pilot, Chimchar team vs Lileep | Sludge Bomb 10 times |
| Bidoof with only Growl | nothing 10 times |

The AI must pick its turn-1 action before the state is saved, at the
first prompt: the env's random battle seed, written after the load, never
changed it. When the generator then rewrites the enemy's moves, the picked
slot holds whatever move is now there, or nothing. Every episode from a
state opens with the same enemy move, so the agent can memorize openings.
The pilot's Sand-Attack trick (§24) is likely one: Bonsly opened with
Selfdestruct every time.

| Issue | Cause | Resolution |
|---|---|---|
| A refused move or switch ended the step as STUCK | The mask knew only PP | `action_mask` reads the game's locks and traps |
| Encore would stall a step | FIGHT uses the encored move with no move menu | A move action taps FIGHT alone under Encore |
| Struggle came only from empty PP | The game's test is that no move is allowed | `is_struggling` uses the locks too |
| No Taunt or Bind in the hack to test | Their move ids were reused | Taunt's check stays untested; the rest are checked in the game |
| The enemy's first move is the same in every episode from a state | The AI picks it before the state is saved | Fixed in §28: generated states are saved before the enemy picks |

## 28. Battle states saved before the enemy picks (2026-11-17)

Goal: fix the fixed first move found in §27.

**Where the enemy picks.** In the decomp, both the wild Pokémon's random
move (`Task_TrainerShowMoveSelectMenu`, with the battle RNG) and a
trainer's AI (`TrainerAI_Main`) run during command selection, in the same
frames as the player's menu appears. A state saved at the player's prompt
already holds the choice. The env writes its random battle seed after
loading, too late to change it. In a generated battle the generator also
rewrites the enemy's moves after that point, so the picked slot held
another move, or none: a one-move enemy did nothing on turn 1.

**The fix.** The generator now stops before command selection. A trace of
`BattleContext.command` through a wild battle's intro shows it is 21 for
about 560 frames, then 2, 3, 4 and 5 on four frames in a row, with the
prompt 12 frames after 4 (INIT_COMMAND_SELECTION). The env's reset runs
the rest. The enemy's moves are written before the state is saved, so the
enemy picks among them.

**One frame is unsafe to save.** A state saved on the frame `command`
reads 4 reloaded differently after another battle had run in the same
emulator. Between 165 and 336 bytes of main RAM differed, all around
0x0222C894. Two fresh emulators agreed. Saved 1, 2, 5, 10, 30 or 60
frames earlier, the same battle reloaded identically. Command 4 can't be
seen coming, so `make_scenario` plays the battle twice from the same start,
which the emulator repeats exactly. The first time finds the frame command
selection begins, the second stops `SAVE_MARGIN` (10) frames before it.

**Verified:**
- Roark's Bonsly set, over 20 seeds, opened with Stealth Rock 7 times,
  Brick Break 5, Accelerock 4 and Selfdestruct 4. Saved the old way, it
  opened with the same move every time.
- A one-move Bidoof used Growl on turn 1 in 20 of 20 seeds, where before it
  did nothing.
- A new state reloads identically after another battle (0 bytes differ),
  and passes `check_state`.
- `test_the_enemys_first_move_follows_the_battle_seed` checks the first
  point. `test_a_state_loads_the_same_whatever_ran_before`, now on a state
  built the new way, checks the reload. The whole suite passes, 112
  tests.

**Tests that changed.** Rebuilt test battles play out differently, since
the enemy now acts on turn 1:
- The turn-cap test hard-coded 7 turns before the forced switch. It now
  measures them.
- The Struggle test's Turtwig fainted on the Struggle turn, so it is level
  16 now. The test checks that Struggle hit, not that nothing else happened.
- Two tests assumed a loaded state is at the prompt. They now run on to it.

**What it means for the pilot.** Every pilot battle had a fixed enemy
opening, so part of what the pilot learned may be memorized openings, on
the held-out battles as much as the training ones. Its states are kept as
they were, as a record. The milestone states are still saved at the
prompt. That matters little for Barry 1, whose Chimchar knows only Scratch,
but any new state should be saved the new way. That includes the restart
states of the live runs (NEXT_PHASE step 3), which must also pass the
reload check.

| Issue | Cause | Resolution |
|---|---|---|
| The enemy's first move was the same in every episode from a state | It picks during command selection, before the state was saved | States are saved before command selection, and the env's reset runs on to the prompt |
| A one-move enemy did nothing on turn 1 | Its moves were written after it had picked a slot | Its moves are written before the save, so it picks among them |
| A state saved on the frame command selection begins reloaded differently after another battle | Some emulator state outside the save file is in flight on that frame | Saved 10 frames earlier, by playing the battle twice |
| Rebuilt test battles broke three tests' fixed numbers | The enemy now acts on turn 1 | The tests measure or check what they mean, not exact counts |

## 29. Roar and Whirlwind end a wild battle as FLED (2026-11-17)

Goal: step 1 of the plan after the pilot. A wild Pokémon's Roar or
Whirlwind ends the battle, and a live run goes on from there.

**What the game does.** A Bidoof that knows only Roar, or only Whirlwind,
ended the battle on its first turn in 3 of 3 seeds each. The game recorded
`resultMask` 5, the decomp's `BATTLE_RESULT_PLAYER_FLED`. A Turtwig using
Roar or Whirlwind on a wild Pokémon recorded the same 5. Either way the env
already ended the episode without getting stuck: the battle memory is freed
and the episode ends as ENDED, with 0 reward. That was the cause of §18's
Cranidos battles that all ended.

**The change.** ENDED was the env's catch-all for a battle that stopped
with neither side wiped, and the health chart counts it among the episodes
that need a look. In a live run, being blown away is normal play. When the
game's result reads 5, the episode now ends as FLED: 0 reward, terminated,
and not counted as an anomaly. Faints before it still count. Escaping a
wild battle with Roar or Whirlwind is legal play. Under the Nuzlocke rules
the route's encounter is then lost, which is bookkeeping for step 2.

`test_roar_or_whirlwind_ends_a_wild_battle_as_fled` covers both sides. The
whole suite passes, 114 tests.

| Issue | Cause | Resolution |
|---|---|---|
| Roar or Whirlwind ended a wild battle as ENDED, among the anomalies | ENDED covered every end with neither side wiped | FLED when the game records a flee (5); ENDED is left for anything else |

## 30. No double battle before Roark (2026-11-17)

Goal: the last item of step 1. Find where the one early double battle in
the ROM (Interviewers Roxy & Oli, trainer 368, Magnemite and Ralts at level
6) happens, and whether a run to Roark meets it.

**It is never fought.** In the decomp's trainer list, id 368 is
`TRAINER_INTERVIEWERS_ROXY_AND_OLI_UNUSED`. The interviewers the game uses
are 883 and their rematches, which the hack puts at levels 23, 35 and 47,
all past Roark's cap of 16. All nine double battles in the ROM at level 16
or below are vanilla's dummy or unused entries: 368, and eight pairs of
level-5 Rattata.

**A cross-check.** Every trainer the hack's author uses has hand-set moves:
Youngster Tristan, Worker Colin, Roark, Lucas in Jubilife City, and the
rest. Every early trainer without them is a vanilla `_UNUSED` entry: 368,
369 to 371 (the TV crew), 431 and 465. None of the nine early double
battles has hand-set moves.

This rests on the vanilla scripts and that pattern. The hack's own map
scripts weren't parsed, so a double battle the runner meets would still be
a surprise to handle then.

**Correction, found in the survey (3.1): there is one, in Jubilife City.**
Vanilla names trainers 414 and 415 `GALACTIC_GRUNT_JUBILIFE_CITY_1` and `_2`,
and 613 to 618 `LUCAS_JUBILIFE_CITY_*` and `DAWN_JUBILIFE_CITY_*`. That is
Platinum's multi battle: the player and the professor's assistant, an AI
partner whose team depends on the player's starter, against two Galactic
grunts. The hack gives all of them hand-set moves (grunts at level 16, the
partner at 15 and 16), so it uses them. The check above missed it because a
multi battle is set up by the map's script, not by the trainer's double flag.
The battle env plays single battles only: in a 2-against-2 battle, each move
first asks which enemy to target.

**Second correction (§33): it comes after Roark.** Its trigger needs a story
var that only the Oreburgh Gym's script sets.

| Issue | Cause | Resolution |
|---|---|---|
| A level-6 double battle looked like it might be on the way to Roark | Trainer 368 is in the ROM with a party | It is vanilla's unused entry; the real interviewers come at level 23 |
| "No double battle before Roark" was wrong | A multi battle is set by the map's script, not the trainer's double flag | Jubilife City's multi battle against two Galactic grunts, with an AI partner, is on the way. Open: NEXT_PHASE step 1 |

## 31. A Poké Ball action (2026-11-17)

Goal: step 2 of the plan after the pilot, its first part. Let the agent
throw a Poké Ball, when the rules allow a catch.

**The screens,** mapped with screenshots:
1. BAG on the action menu, at (40, 172).
2. The bag's four pockets: POKé BALLS at (193, 48).
3. The ball list, two across: the first ball at (64, 40).
4. That ball's page: USE at (100, 172).

`curCommandState[0]` reads 8 on every bag screen (the decomp's
`ITEM_SELECT`) and changes once the ball is thrown. A tap dropped inside the
bag can't be retried in place, since the same spot on another bag screen
picks something else. So a throw that doesn't leave the bag backs out with
B and walks the route again.

**The catch,** traced with the script task's state (the decomp's
`CatchMonTaskState`) and screenshots:
- A Poké Ball at a full-HP Bidoof shook three times and broke free (states
  28 to 31). The turn went on as usual.
- A Master Ball caught it. "Gotcha! BIDOOF was caught!" (9) waits for A or
  B. The new Pokédex entry (13) waits for A or a tap, and 5,000 frames of B
  did nothing. "Give a nickname?" (19) is a yes/no that B answers no. The
  game then recorded `resultMask` 4, ended the battle, and Bidoof joined
  the party.
- With six in the party, "... was transferred to the PC" (24) waits for B,
  and the catch went to box 1. That was the first real deposit read back:
  `gen4.read_box` returned Bidoof with 27 EXP, its Growl and a good
  checksum. A boxed Pokémon keeps no level, so the level comes from EXP.

**What the env does:**
- **Action 9** throws the first ball in the Poké Balls pocket. Which ball
  to throw can become the agent's choice later.
- **It is allowed** only when the caller passes `catch` at reset and the
  battle's bag holds a ball, and never at a forced switch. The caller is
  the route runner, from the rules (first encounter, duplicates, shiny).
- **While a ball is in flight,** `_answer_task` answers the catch task: B
  for the text and the nickname, a tap for the Pokédex entry. Otherwise it
  answers the experience task, as before. The two share their struct and
  their state numbers overlap.
- **A catch ends the episode as CAUGHT,** read from the game's result 4,
  with 0 reward. What a catch is worth shows up in later battles, which
  the run sees and this env doesn't.
- The action space grows from 9 actions to 10, so the pilot's checkpoints
  no longer fit the env. They are kept as a record of the pilot.

`test_a_ball_is_offered_only_when_the_caller_allows_a_catch`,
`test_a_master_ball_catches_and_ends_the_battle_as_caught` and
`test_a_catch_with_a_full_party_goes_to_the_pc` cover it, along with the
mask rules without an emulator. The whole suite passes. The Pokédex screen
and the nickname are only answered, never chosen: the nickname is always
declined.

| Issue | Cause | Resolution |
|---|---|---|
| The level-up handler would misread the catch | The catch and experience tasks share a struct, and their state numbers overlap | The env answers the catch task only while its ball is in flight |
| B never closed the new Pokédex entry | That screen takes A or a tap | A tap |
| A dropped tap in the bag can't be retried in place | Every bag screen reads the same, and a spot means something else on each | Back out with B and walk the route again |
| A boxed Pokémon read level 0 | The box struct has no level field | The level comes from EXP (`romdata.level_for_exp`) |
| The pilot's checkpoints no longer fit the env | The action space grew to 10 | Kept as a record; live runs train from scratch |

## 32. The Nuzlocke rules as bookkeeping (2026-11-17)

Goal: step 2 of the plan after the pilot, its second part. Decide when a
catch is allowed, and keep what the rules need over a run.

**`src/nuzlocke.py`** has no emulator in it. The route runner reads the
facts from the game and asks a `Run` what the rules allow:
- `encounter(route, species, shiny)`, when a wild battle starts, says
  whether the Pokémon may be caught. That is the `catch` the battle env
  takes at reset. It also uses up the route if this is the encounter that
  counts there.
- `caught(species)`, `fainted(pid)` and `boss_beaten(boss)` record the run.
- `level_cap()` and `over_cap(levels)` give the cap of the next boss not
  yet beaten.

**The rules, as the README states them:**
- **Only a route's first encounter counts,** caught or not. A route is the
  location name the game shows ("Route 201", "Oreburgh Mine B1F"), the
  usual Nuzlocke reading.
- **Duplicates clause:** an encounter from an evolution line already caught
  may not be caught, and leaves the route open. A line is named by its
  first species (`line_of`). It follows the ROM's evolutions backward, so
  Raichu and Pikachu belong to Pichu, Flareon to Eevee, Staraptor to
  Starly.
- **Shiny clause:** a shiny may always be caught, and uses up nothing.
- **Level caps follow bosses, not badges.** Barry's third and fifth fights
  come between gyms, so badges alone can't tell 42 from 47. The cap is that
  of the next boss on the README's list not yet beaten.
- **A Pokémon that faints is gone for good.** The run keeps its PID. Keeping
  it out of the party, by boxing it, is the route runner's job.

`Rules` holds these as data (`first_encounter_only`, `duplicates_clause`,
`shiny_clause`, `level_caps`), so another game or ruleset can change them,
from a JSON file for example. That is the plan's rules-as-config.
`tests/test_nuzlocke.py` covers each rule and switching them off, 7 tests.

| Issue | Cause | Resolution |
|---|---|---|
| Badge count can't give the level cap | Two of the caps are Barry's fights between gyms | The cap follows the bosses beaten, in the README's order |
| A duplicate shouldn't use up a route | The clause lets the player try for another | `encounter` returns False for it without recording the route |

## 33. The playthrough to the Oreburgh Gym (2026-11-17)

Goal: the second half of step 3.1. Play from the state after the first rival
battle to the Oreburgh Gym, and through it, with scripted inputs, save a milestone state at
each story beat, and confirm the route survey. The findings are in
[ROUTE_TO_ROARK.md](ROUTE_TO_ROARK.md).

**How it was played.** A scratch driver built on `src/drive.py` added a few
tokens: walk a path to a tile, press B (or A) until the scene ends, talk to a
person, and play a battle through the battle env with a greedy policy (the
move with the most power × accuracy × own-type bonus × type effectiveness).
Every battle on the way went through the env.

**A survey party, not a legit one.** A wild Ledyba, level 5 on Route 202,
beat the level-7 Turtwig in two turns, and the player whited out. A lone
starter can't carry a survey through Kaizo trainers, and the survey is about
the map, not the battles. So the party was rewritten at state 04 with
`scenario.build_mon`: Garchomp, Gyarados, Lucario, Alakazam, Arcanine and
Turtwig, all level 16, with the player's original-trainer fields so they
obey. EXP raised them past Roark's cap, so the party was written again at
level 16 before the gym. Milestones 06 to 14 hold this party: they are
fixtures for the overworld primitives (step 3.2), not run starts.

**RAM signals for the overworld** (RAM_MAP.md):
- **`FieldSystem.task`** is non-zero while a script, a warp or a battle
  runs, and 0 when the player can walk. The `FieldSystem` pointer sits at
  0x21C07DC in every state tried. This is the signal step 3.2 needed: press
  B until it reads 0. B never starts a new talk, which A does once the text
  ends. `gen4.field_task`.
- **Story vars and event flags** (`gen4.read_var`, `gen4.read_flag`). Each
  map trigger in the ROM names a var and a value, so the vars say which
  triggers are armed. A set flag hides a person.

**The map's facts from the ROM** (`src/fieldmap.py`): the map headers'
matrices, the tile attributes (collision, grass, ledges), and each map's
events: people with their scripts, sight ranges and hide flags, warps, signs,
and triggers. A path finder walks the cheapest way (grass costs more),
and `forced_trainers` says which trainers no walk can avoid. A sight
trainer's script is 2999 plus its trainer id, which named every trainer met.

**What the playthrough found:**
- The story order holds, with differences from vanilla: no catching lesson
  on Route 202; no need to go home before Route 202; Looker holds the east
  exit of Jubilife until the Parcel and the Pokétch; the Pokétch clowns ask
  a quiz, then battle.
- **The Jubilife multi battle comes after Roark.** Its trigger needs var
  16503 = 3, and only the Oreburgh Gym's script sets it. With the var written
  to 3 in a test copy, the trigger led into the battle against trainer 414.
- **The gym's shortcut is closed, not its way.** The first walk of the gym
  reached only its lower floor, and a Rock Smash boulder stood at the foot
  of the stairs up. Rock Smash is refused without the Coal Badge and works
  with its bit set, so the gym looked unbeatable. Bulbapedia's walkthrough
  (found by the user) says vanilla's gym has two ways up: past the two
  trainers, or by stairs and a bridge that skip them. The boulder closes the
  shortcut. The trainers' way runs over a raised walkway that the first
  walk of the gym had missed (see the issues). No field move is needed
  before Roark, as §25 said.
- **Unavoidable trainers:** all three on Route 202, Barry and two of five on
  Route 203, both in the Oreburgh Gate, both Workers in the mine, both gym
  trainers. Lass Madeline is unavoidable only because her sight covers the
  gate's door.
- **Roark** (246) won, with the survey party at level 16. The Coal Badge and
  TM39 (vanilla gives TM76) followed, and var 16503 became 3.
- **The battle env in live play:** 16 trainer battles and 14 wild battles,
  every one WON, none STUCK, and 3 more trainer battles in the gym. These include multi-Pokémon trainer battles in
  Set style, forced switches, and level-ups, so Set style is now tested in
  trainer battles.

**Milestones** (in `states/milestones/`, not in git): 06 the lab after the
Pokédex, 07 Jubilife's arrival trigger, 08 after the Parcel, 09 after the
Pokétch, 10 Barry's trigger on Route 203, 11 Oreburgh's edge, 12 healed in
its Pokémon Center, 13 after Roark's mine scene, 14 inside the gym's door,
15 in front of Roark, 16 with the Coal Badge.
They were made with the scratch driver, so no input script rebuilds them
yet; the driver's tokens become step 3.2's primitives.

**Verified:** `tests/test_fieldmap.py` checks the Route 201 ledge and the
person the screen showed, the trainers' names from their scripts, the
unavoidable trainers of four maps, and where var 16503 becomes 3.
`test_b_until_no_field_task_ends_a_scene_and_frees_the_player` and
`test_story_vars_and_event_flags` check the RAM readers on milestone states.

| Issue | Cause | Resolution |
|---|---|---|
| A level-7 Turtwig lost to a level-5 wild Ledyba, and the run whited out | Kaizo's wild Pokémon | A survey party at level 16, documented as such; milestones 06 to 14 aren't run starts |
| Pressing A to get through text started the same talk again | A on a person after the text ends talks to them again | Press B until `FieldSystem.task` reads 0 |
| Rowan asked the same question for 1,499 presses of B | B answers no to a yes/no the story needs answered yes | A for scenes with a required yes |
| The path finder walked into a sign, which opened its text | Signs and people aren't in the collision layer | Sign and person tiles from the map's events are blocked |
| The way out of the mine read as blocked after Roark's scene | The ROM lists people the story has hidden, like the boulder Roark smashed | People whose event flag is set are left out |
| Lass Madeline was counted as avoidable | The check dropped the goal tile from her sight, and she sees the gate's door | A goal or start tile in a trainer's sight makes the trainer unavoidable |
| The gym's collision showed open floor the game refused | The gym has raised floors, and `fieldmap` reads no heights | The gym's walkable tiles were found by stepping every tile in the emulator. Heights stay unread |
| The emulator walk of the gym missed the way to Roark | It counted each (x, z) once, and a raised walkway passes over floor tiles with the same (x, z). The floor was walked first | Walked again from Jonathon's platform, which reaches the walkway. A walk that tells floors apart needs the player's height, still to read |
| §30 put the Jubilife multi battle before Roark | The trainers' names and levels fit, but the trigger's var is set in the gym | Corrected: it comes after Roark |
| The boulder in the Oreburgh Gym looked like it blocked the way to Roark | It closes vanilla's shortcut past the trainers; Rock Smash needs the Coal Badge | The way past both trainers reaches Roark |

## 34. Floor height and each map's walkable graph (2026-11-17)

Goal: steps 3.2.1 and 3.2.2 of the plan. Walk the overworld on maps whose
floors have heights, and walk around people who get in the way.

**The height.** The player's map object holds its tile as x, height and z
(RAM_MAP.md, `gen4.read_player_tile`). Its x and z match `location` on every
state tried. The height reads 0 on the Oreburgh Gym's floor and 4 on its
walkway, and climbs 0, 1, 3, 4 up its stairs. It isn't counted from the
ground: Jubilife's street reads 4.

**Exploring a map** (`overworld.explore`). From a state where the player can
walk, it steps every direction from every tile it reaches, from a state saved
on that tile, and records what each step did: moved to a tile (x, z, height),
was blocked, left the map (to which map), or started a scene. The wild
encounter rate is set to 0 while it explores, so grass doesn't start battles.
The result is a `WalkGraph`, saved as JSON.

**The route's 18 maps** were explored from start states taken from the
playthrough, with each map's trainers beaten so their sight doesn't cut the
walk short (`states/walk/start/`, not in git).
`scripts/explore_maps.py --jobs 8` took 25 minutes, with the CPU at 97 °C at
its peak. The graphs run from 63 tiles (the player's house) to 1,376
(Jubilife City). They are in `states/walk/<map id>.json`, not in git, since
they're made from local states. The gym's graph has the walkway: x = 4 to 7
at z = 17 exist at height 4 above floor tiles at height 0.

**Walking** (`overworld.walk_to`) plans the fewest steps on the graph, takes
one, and plans again from the tile the player is on. A blocked step waits
half a second and tries again, up to 10 times.

**Verified:**
- On each of the 18 maps, the graph's path from the start state to its
  farthest tile, stepped blindly, ended on that tile on 17. In Oreburgh City a
  wandering worker blocked a step and left the player a tile off.
  `walk_to` reached that tile.
- `test_the_gym_graph_walks_from_the_door_over_the_walkway_to_roark` and
  `test_walking_past_the_people_of_oreburgh` do this in the game.
  Three tests without the emulator check that a path climbs stairs to a
  walkway over the floor, that a ledge is one way, and that a graph survives
  JSON.

| Issue | Cause | Resolution |
|---|---|---|
| The first walk of the gym missed its walkway | It counted each (x, z) once, and the walkway passes over floor tiles with the same (x, z) | A tile is (x, z, height) |
| The explorer recorded no doors | Walking into a door starts its warp on the mat, so the player never leaves the tile within the step | A field task starting counts as a step; the warp is then waited out |
| Grass battles would stop the exploration at every patch | Wild encounters | The current map's encounter rate is set to 0 while exploring |
| Holding a direction for 40 frames walked up to 3 tiles | Walking takes 16 frames a tile | A step lets go as soon as the tile changes |
| A planned walk in Oreburgh ended a tile short | A wandering worker stepped into the way | `walk_to` plans again after every step and waits when blocked |
| The graphs and their start states aren't in git | They're made from local save states | The milestone rebuild (3.2.6) will make the start states reproducible |
| `test_a_worker_crash_raises_instead_of_hanging` failed 3 times in 20 (found in this section's full test run; the pool wasn't changed) | When a worker's sentinel closed, the pool read its exit code before the process had exited, and got None | Wait for the process (`join(1)`) first, as the pool's other two checks did. 60 of 60 passed after |

## 35. Text, people, doors, trainers and whiteouts (2026-11-17)

Goal: steps 3.2.3 to 3.2.5 of the plan, the rest of the overworld
primitives, moved over from the playthrough's scratch driver
(`src/overworld.py`).

**The primitives:**
- **`advance_text`** presses B every 20 frames while a field task runs, and
  is done once none has run for 40 frames. B never starts a new talk. A
  question the story needs answered yes, like Rowan's, loops on B, so
  `yes=True` presses A instead. It returns "battle" when a battle starts, and
  carries a battle that was already running, and a whiteout, through to the
  overworld.
- **`talk_from`** walks to a tile, turns with a short press, and presses A.
  **`talk_to`** picks the nearest tile beside a person. The nurse stands
  behind her counter, two tiles away, so she takes `talk_from`.
- **`take_exit`** finds the nearest step in the walkable graph that leads
  to a given map, takes it, and waits out the warp.
- **`spotted_by`** names the trainers whose sight covers the player's tile,
  among those not hidden. A scene that starts there is a trainer walking up.
- **A whiteout** is a battle the env reports LOST. `advance_text` then
  carries the closing text through, and the player wakes at home before any
  Pokémon Center, with the party healed.

**Fixtures** for the tests, made from the playthrough's states, in
`states/fixtures/` (not in git): Rowan's question, the entrance of Route 202
with its trainers unbeaten, Oreburgh's Pokémon Center with a fainted
Pokémon, and the wild Ledyba that beat the legit Turtwig.

**Verified** in the game (`tests/test_overworld.py`):
- B gets stuck on Rowan's question for 3,000 frames; A then finishes the
  scene, in the lab with the Pokédex given (var 16497 = 1).
- Walking north on Route 202 stops at (166,818), where Youngster Tristan
  (trainer 1) spots the player; the text leads into the battle.
- The nurse heals a party with a fainted Pokémon.
- The Trainers' School's door leads to Jubilife City at (168,777).
- The level-7 Turtwig loses to the Ledyba and wakes at home, at (8,8) in
  the house, healed.

What's left of step 3.2 is the milestone rebuild (3.2.6).

| Issue | Cause | Resolution |
|---|---|---|
| B through Rowan's question looped forever | B answers no, and he asks again | `advance_text(yes=True)` for scenes that need a yes |
| A text helper that stopped at any battle would stop inside the battle it should finish | The battle's closing text and a whiteout run while the battle is still up | `advance_text` returns "battle" only for a battle that starts while it runs |
| The nurse can't be talked to from a tile beside her | She stands behind a counter | `talk_from` takes the tile and the direction to face |

## 36. Milestones 06 to 16 rebuilt by a script (2026-11-17)

Goal: step 3.2.6 of the plan. Make the milestones, the map start states and
the test fixtures on any machine that has milestone 04.

**`scripts/make_milestones.py`** plays from milestone 04 to Roark's badge with
the survey party, from a list of actions: walk to a tile, advance text (with
yes or no), take a door, talk to a person or from a tile, take fixed steps,
rewrite the party, save. Battles go through the battle env with the greedy
policy of the playthrough. It takes 10 minutes.

**Breaking a loop.** `walk_to` plans on a map's walkable graph, the graphs
come from the start states, and on a new machine the start states come from
this script. So the script plans on the ROM's collision layer instead:
`walk_to`, `talk_to` and `take_exit` now take no graph and use `fieldmap`,
with signs and visible people blocked, the map's warp events for doors, and
the walk going on across a map's edge into the next map of the same matrix.
That worked on every map of the playthrough but the Oreburgh Gym, whose
raised floors the ROM's collision can't see. There the script takes fixed
steps, from the gym's graph; no one wanders there, so they replay exactly.
Wild encounters are off. The Ledyba fixture comes from the scenario
generator: the level-7 Turtwig against a forced level-5 Ledyba in Route
201's grass, keeping the first battle seed the Ledyba wins.

**Verified:**
- The script won all 19 trainer battles and saved every milestone, start
  state and fixture.
- Each rebuilt milestone matches the playthrough's in map, tile, story vars
  and badges, but 09, where the player spoke to the president from
  (173,771) instead of (174,770).
- The playthrough's states were kept in `states/playthrough_backup/` and the
  rebuilt ones put in their place. The overworld and RAM tests pass on them.
- The maps explored again from the rebuilt start states came out within a
  few tiles of the first exploration (Jubilife 1,375 against 1,376,
  Oreburgh 1,219 against 1,223): people wander. The CPU peaked at 90 °C.

| Issue | Cause | Resolution |
|---|---|---|
| On a new machine there's no walkable graph to walk with | The graphs are explored from start states that this script makes | Plan on the ROM's collision layer, and take fixed steps in the gym |
| The walk to the first clown stayed blocked | The clown who opened the campaign stood still in the planned path | `walk_to` plans around a tile after 3 blocked tries, and forgets such tiles if that leaves no way |
| The script's first run stopped at Rowan's scene | My bug: `("text", "yes")` passed "no" as the frame limit | Fixed before the full run |
| Milestones 00 to 04 still have no input script, except 05 | They were made by hand before the scripted driver | Open: the runs start at milestone 01, so it matters for other machines |

## 37. A whole run as one episode (2026-11-17)

Goal: steps 3.3 to 3.5 of the plan, and the starter decision of 3.8. Play
a run from the starter choice to Roark's badge under the README's rules,
with the agent making every battle and catch decision.

**Where a run starts.** Milestone 01 turned out to come after the choice:
the hack opens a PC box screen with the new starter in it. The new milestone
`01_starter_choice` is Rowan's briefcase, with its cursor on the first ball.
`make_milestones.py` makes it from milestone 00:
- Every tile around the bed starts the opening; B carries it to Route 201.
- Barry's scene on Route 201 must take A. **Answering one of his questions
  no rolls the hack's joke ending:** the Hall of Fame and the credits, then
  the game resets.
- The briefcase opens from (112,854). Its text, pressed with A every 20
  frames 14 times, leaves the cursor up; the cursor ignores the D-pad while
  text prints. These are the playthrough's own inputs, which the emulator
  repeats exactly, and the script checks that each ball gives its starter.
- After the choice: A on the ball, A on "Will you take this Pokémon?", then
  B closes the box screen (A opens its menu, where STORE is refused for the
  last Pokémon), then A through Rowan's text into Barry's first battle. Barry's
  team follows the choice: Turtwig meets trainer 851, Chimchar 852, Piplup 850.

**The route** (`src/route.py`) is the way to Roark as data, as
`make_milestones.py` plays it, plus the Pokémon Centers of Sandgem Town,
Jubilife City and Oreburgh City. Its runner is a generator: it plays the
route and stops at each decision, `("starter",)` and `("battle",)`, taking
back the choice or the battle's outcome. A wild battle or a trainer during a
walk pauses the walk. After a battle the text goes on with A, since B would
stop an evolution.

**Battles inside a run.** `BattleEnv` takes an emulator at construction and
`reset(options={"attach": True})`, which plays the battle already running
there instead of loading a state. Attached to Barry's first battle it reached
the first prompt and won it.

**The rules in the run** (`src/run_env.py`, `RunEnv`):
- When a wild battle starts, `nuzlocke.Run.encounter` gets the location's
  name, the wild species and whether it's shiny, and its answer is the battle
  env's `catch`.
- After each battle the run records the fainted, the catch, and a boss beaten
  (+20 for Roark).
- **At each Pokémon Center the fainted go to the PC before the nurse heals,**
  so the rule holds. `scenario.deposit` writes them into the first empty box
  slots and closes up the party. A box slot is the party struct's first 136
  bytes. This stands in for the PC's screens until they're mapped (3.6).
- A lost battle ends the run as a wipe.

**The episode.** One step is one decision, with the battle env's observation
and 10 actions, so one policy plays both. The first decision is the starter:
its observation shows the three as a party, each at level 5 with its
level-up moves, and actions 0 to 2 pick one. A run ends on Roark's badge, a
wipe, the route ending without the badge (Roark turns down a party over his
cap), a budget of 3,000 decisions, a battle the env couldn't play, or a route
step that failed. Battle seeds come from the run's seed.

**Verified:**
- A greedy run: Turtwig, Barry won, then the wild Delibird of Route 201 won
  and wiped the run. A random run: Piplup, Barry won, Route 201's Delibird
  caught, a wild battle won, then a Burmy on Route 202 wiped it.
- `tests/test_run_env.py`: the starter is the first decision and the ball
  gives its starter and Barry's matching team; a run plays its battles and
  ends on a wipe, with Route 201's encounter counted; a fainted Pokémon goes
  to the PC and the nurse heals the other five.

| Issue | Cause | Resolution |
|---|---|---|
| Milestone 01 isn't the starter choice | The hack opens a PC box screen with the starter just after the choice | New milestone `01_starter_choice` at the briefcase |
| B through Barry's scene rolled the credits and reset the game | The hack's joke ending for answering him no | His scene takes A |
| The briefcase's cursor didn't move | It ignores the D-pad while the text prints | The choice state is saved 150 frames after the last press |
| The first rebuilt starter choice picked nothing | My presses came at another cadence than the playthrough's | The script replays the playthrough's inputs and checks each ball |
| `field_task` raised in the middle of a fade | The location address `resolve` follows jumped for one frame | It checks only that the FieldSystem pointer is in main RAM |
| A wild battle met on a walk was pressed through with A | The runner waited for the battle, then called `advance_text`, which reports only a battle that starts while it runs | The runner hands a battle that is already up to the agent |
| The nurse would bring the dead back | She heals the whole party | The runner deposits the fainted first |

## 38. Evolution, timing, faster walking, and training on runs (2026-11-17)

Goal: steps 3.7, 3.9 and 3.10 of the plan, and a check that the run's route
works all the way.

**The whole route works.** One run was played with the survey party, written
after Barry's first battle and again before Roark, and the greedy policy.
It won all 32 battles, every trainer from Barry's first to Roark, healed at
the three Pokémon Centers (moving its fainted to the PC first), and ended on
Roark's badge with a return of 273, the +20 for Roark included: 118
decisions in 508 seconds. A first try that reset the party before the gym's
two trainers ended "no_badge": their EXP took the party over Roark's cap,
and he turned it down, which the env reads from the badge.

**Evolution after a battle (3.7).** The text after a battle takes A, since B
stops an evolution. A Kricketot one EXP short of level 10 won a battle and
became a Kricketune. With four moves, the evolution's new move (False
Swipe) replaced the first move slot: A answers yes to forgetting, then picks
the first move. That is a stand-in, as the in-battle choice is (§26), to
become the agent's.

**Timing runs (3.9).** `scripts/time_runs.py` plays random allowed actions on
14 envs:

| | Runs | Runs/h | Decisions/s | Decisions per run | Battles per run | Furthest |
|---|---|---|---|---|---|---|
| First | 100 | 210 | 1.3 | 21.2 | 4.0 | route step 10 of 55 (Route 202) |
| Faster walking | 50 | 186 | 1.6 | 27.9 | 4.6 | route step 10 of 55 |

Every random run wiped on Route 201 or 202; Barry's first battle was won in
all of them, with each starter. A profile of one run put 96% of its time in
the emulator, so the cost is frames:
- **Walking** took 56 frames a tile: `step` waits 40 frames after each tile
  for a scene to start. `walk` now holds the key along each straight stretch
  of the plan, 16.7 frames a tile, and holds B too, which runs with the
  Running Shoes the player has from Twinleaf: 9.7 frames a tile. That came
  after the second timing.
- **The rest** is battles' intros and ends, and the opening every run plays:
  the choice, the box screen, Barry's battle and Mom's scene. Runs that die
  after four or five battles pay it each time; restart states skip it.
- The save's text speed is already fast (its options word, version + 0x78,
  reads 0x42).

**Restart states (3.10).** With `restart_dir` set, a run saves every battle
it meets as it starts, with a JSON of its bookkeeping: the rules' record, the
route action and the step inside a list of steps, the starter, the trainers
beaten. At most 20 are kept per route step, the oldest dropped. A reset
starts from one with probability `restart_share`: a route step picked at
random among those with restarts, so later battles get practice while most
runs still die early, then a state of that step. The runner then plays the
saved battle first and resumes the route action it interrupted: a walk or a
door from where the player stands, a list of steps from the next step.

**Training on runs.** `train_ppo.py --runs` trains the same masked PPO on
`RunEnv` workers, with a discount of 0.999 and half the episodes from restart
states by default, kept in `RUN_DIR/restarts`. A run's end is its episode
outcome, and the metrics add the mean and furthest route step. A smoke run
of 256 decisions on 4 envs played 7 runs and saved restart states.

**The first training run** (`runs/runs1`, not in git) started on 2026-11-17
at 6:30 PM Eastern: `train_ppo.py --runs --envs 14 --total-decisions 200000`.
Its first two updates ran at 1.8 to 1.9 decisions a second, with the CPU at
76 °C. All 54 runs so far wiped, at route step 6.4 on average and 10 at most.
At this speed the 200,000 decisions take about 30 hours; the same command
resumes it to a higher total.

**Verified:** `test_a_run_leaves_restart_states_and_a_reset_resumes_one`;
the overworld and run tests pass with running.

| Issue | Cause | Resolution |
|---|---|---|
| Walking cost 56 frames a tile | `step` waits 40 frames after every tile | `walk` holds the key along straight stretches, and runs: 9.7 frames a tile |
| Random runs never pass Route 202 | Kaizo's early wild Pokémon | Expected; restart states give later battles practice once runs reach them |
| The trainer's episode records had no outcome for a run | A run's final info had `end`, not `outcome` | `outcome` is the run's end, and the route step is recorded |
| Roark turns down a party over his cap, and nothing in a run can bring it under | The agent has no PC decisions yet (3.6) | Open: a run ends "no_badge", paid as a loss since §45 |
| An evolution's fifth move replaces the first slot | A on the forget screen picks the first move | `move_to_forget` answers it, as in battle (§40) |
| Milestone 00 has no input script from boot | The new game's intro and naming were played by hand | `boot` in `make_milestones.py` plays it from power-on (§41) |

## 39. Runs stalled on Route 202: training up, and healing between trainers (2026-11-17)

Goal: the first training run's runs never got past Route 202. Find out why,
and fix it.

**The stall.** After 19 updates, about 20,000 decisions and 1,000 runs, every
run had wiped, at route step 10 at most: the walk across Route 202. All 20
restart states kept for that step were the battle with Tristan, its first
trainer. A run gets there with its starter alone at level 7, healed at
Sandgem. The route then walked it into all three trainers, ten Pokémon at
levels 5 to 7 with perfect IVs and held items, with no heal between them.

**How strong the starter must be.** Greedy play from a step-10 restart lost
to Tristan in 12 of 12 seeds. Then a lone starter was written into the Route
202 fixture at a set level and played the three trainers back to back,
greedy, 4 seeds each. Runs that beat all three:

| Starter | Level 9 | 11 | 13 | 16 |
|---|---|---|---|---|
| Turtwig | 0 | 0 | 2 | 4 |
| Chimchar | 0 | 4 | 4 | not run |
| Piplup | 0 | 0 | 3 | 3 |

A level-13 Turtwig that lost had beaten Tristan, then met Natalie at 29 of
39 HP: her Sunkern has Protect, Toxic, Leech Seed and an Oran Berry. So the
route needed two things a player does: training up before the trainers, and
healing between them.

**Training up (`grind`).** A new route action fights wild battles in Route
202's grass south of the first ledge, out of every trainer's sight, pacing
between two tiles until a party Pokémon reaches the level (11). The agent
plays every one of those battles, and the first can be its Route 202 catch.
Between battles, a party with any damage walks to Sandgem's Pokémon Center
and back. The first version healed under half HP; a greedy Chimchar then
lost to a level-5 Sentret from 20 of 26 HP. Kaizo's wild Pokémon beat a
lone starter from three quarters of its HP.

**Heal trips.** A heal trip is a list of route actions: walk to the town,
enter the Pokémon Center, heal, leave. Two uses:
- A walk can carry one. After a battle on the way, a party under half HP
  takes the trip first, then the walk goes on. Under half, not any damage:
  the walk north crosses grass that can't be avoided, and topping up after
  every wild battle there could keep a run walking back and forth.
- `mend` takes the trip if the party has any damage. The walk across Route
  202 is now split at a tile past each trainer's sight, with a `mend` after
  Tristan and Natalie. Each of the three clowns in Jubilife comes after a
  `mend` at Jubilife's Pokémon Center.

The same goes for the rest of the route:

| Where | Split at | Heals at |
|---|---|---|
| Route 203, after Barry's second battle and on the way past its trainers | | Jubilife, walking back west |
| Oreburgh Gate, between Curtis and Diana | (20,22) | Jubilife, by Route 203: Oreburgh's center is nearer, but entering Oreburgh plays its arrival scene |
| Oreburgh Mine B2F, above the ledge down to the Workers' corridor | (13,16) | Oreburgh |
| Before the gym, after Jonathon, and before Roark | | Oreburgh |

In the gym the trip retraces the fixed steps back to the door, since the
ROM's collision can't see the raised floors, and climbs them again after.
A heal trip can meet wild battles of its own, in grass or in the mine; the
agent plays them. The mine's two Workers are the one pair with no heal
between them: the corridor between them is entered down a one-way ledge,
and Roark's boulders close its other end until his demonstration. The first
version split there, at (5,27), and a full-route check stopped on it: the
walk out planned through the boulders, which are objects, not collision.

**Greedy full runs** on the route with training up (before the split): of 4
seeds for each starter, Turtwig wiped 4 times by its first Route 202 battle,
Piplup 3 times on Route 201 and once at Natalie. One Chimchar beat 14
trainers, from Barry's first to Curtis in the Oreburgh Gate, and wiped
against Diana there: 35 battles, 10 heals, return 224. Greedy isn't the
agent; these runs show where the route stops a run, not how far a trained
policy gets.

**Greedy on the finished route.** A greedy Chimchar run (seed 0) on the route
with every heal trip got to route step 66 of 73: it beat every trainer
through Jonathon in the gym and wiped against Darius, the second. 46
battles, 18 heals, 145 decisions, in 1,594 seconds on one core, about 11
seconds a decision, as in training. A profile of it put 97% of the time in
the emulator's frames:

| Part | Seconds | Share |
|---|---|---|
| Battles (the env's steps and resets) | 677 | 42% |
| Text, scenes and the nurse | 431 | 27% |
| Walking | 364 | 23% |
| Heal trips (inside the walking and text) | 281 | 18% |
| The nurse's healing alone | 136 | 8.5% |

Battles already run with the battle scene off and fast text
(`fast_battles`), so their cost is intros, endings and each turn's text.

**Roark's level cap.** The first Chimchar run above reached the gate as a
level-22 Monferno. The hack's bosses refuse to battle while any party
Pokémon is over their cap, 16 for Roark. The trainers that can't be avoided give a lone Pokémon about
11 levels between Route 202 and the gate. A run that reaches Roark must have
shared its EXP over several Pokémon and leave the ones over the cap in the
PC. As a stand-in for step 3.6's PC decisions, the trip before Roark leaves
every Pokémon over his cap in the PC, as long as one able to battle stays.
It comes after the gym's two trainers, whose EXP can push the party over
again.

**Restart states and route changes.** A restart state names its route step by
index, so inserting route actions moved every later step under the saved
states. Each restart now saves its route action too. A reset drops a restart
whose action isn't at its step any more.

**A resumed run's route step.** A run resumed from a restart that ended in
that first battle reported route step 0, so the metrics undercounted how far
restarted runs got. The runner now takes the restart's step before playing
its battle.

**The whole route, checked as in §38.** The survey party was written after
Barry's first battle, and its Garchomp raised to level 18 just before the
trip before Roark. Greedy play ended on Roark's badge: 36 battles won, 12
heals, return 281.4, in 125 decisions. Garchomp was left in the PC, and the
other five beat Roark.

**Verified:** `test_grinding_fights_wild_battles_until_the_level`,
`test_a_hurt_party_goes_to_the_pokemon_center_before_grinding`,
`test_a_hurt_party_heals_before_a_clown`,
`test_a_heal_trip_heals_and_comes_back` (Route 203, the gate, the mine),
`test_before_roark_the_party_heals_and_leaves_the_pokemon_over_his_cap`,
`test_a_restart_saved_on_another_route_is_dropped`, and the restart test now
checks the resumed step.

| Issue | Cause | Resolution |
|---|---|---|
| Every training run wiped by Route 202 | A lone level-7 starter met Route 202's three trainers back to back | `grind` trains to level 11 first, and the walk heals between trainers |
| A grind battle lost from three quarters of the starter's HP | Healing waited until under half | Grinding heals after any damage |
| A run resumed from a restart reported route step 0 | The runner set its step only after the resumed battle | It takes the restart's step first |
| Restart states pointed at the wrong route step after the route changed | They named the step only by its index | They save the route action, and a mismatch is dropped |
| The test fixture's Turtwig won or lost by chance | `build_mon` draws a random personality, and so a nature, each call | The fixture passes a seeded `rng` |
| Two or more trainers in a row with no heal: Route 202, the clowns, the gate, the mine, the gym | The route healed only at fixed points | Heal trips after battles on a walk, and `mend` before each trainer |
| The heal trip between the mine's Workers had no way out | A one-way ledge in, and Roark's boulders (objects the ROM's collision doesn't show) out | The check moved above the ledge; the two Workers stay back to back |
| Three env workers kept running at full CPU after the trainer was stopped | `kill` ended the trainer with no cleanup, so the pool never closed its daemon workers | `train_ppo.py` turns SIGTERM into an exit, which closes the pool; checked: a 2-env trainer's workers were gone within 6 seconds of `kill` |
| A run can't get under Roark's cap | Unavoidable trainers' EXP | The trip before Roark leaves the Pokémon over his cap in the PC; whom to raise stays the agent's, and the PC choices are step 3.6 |

## 40. The move to forget on evolution (2026-11-18)

After a battle, an evolution can offer a fifth move. Section 38 answered it
with A, which always forgot the first slot. The route now answers it with
`battle_env.move_to_forget`, the choice the battle env uses in battle.

**The screens.** The evolution is a field screen, not the battle UI, and
none of it is on the touch screen. In order:
- Text: "wants to learn False Swipe. However, it already knows four moves."
- A YES/NO box on the top screen, "Should a move be deleted?" The cursor
  starts on YES. A answers yes. Down, then A, answers no.
- After yes, a blue move list with the cursor on the first move. Down moves
  it one move at a time, and A forgets the one it is on.
- After no, a second YES/NO box, "Stop trying to teach it?" A (on YES) gives
  up the move and keeps the four.

`advance_text` takes a `forget` function for this. It reads the YES/NO box
and the blue list from the screen's pixels, since the game's task struct for
this screen is not mapped, and presses the keys above. It answers one box
once, then waits for it to close. The runner passes `forget` only for text
after a battle, so story yes/no boxes still get A.

**Which Pokémon.** The party is not updated until the evolution ends: it
still holds the old species, level and EXP when the question comes. So the
runner takes the Pokémon with four moves that has a level evolution within
three levels, and the move is what the evolution learns at that level. If
none matches, the box isn't an evolution's, and it takes A as before: a
story question answered no can end the game (Barry's, §37).

**Verified:** `test_an_evolutions_fifth_move_replaces_the_weakest` (a
Kricketot with Tackle, Growl, Leer and Bite, one EXP short of level 10: Growl
is replaced by False Swipe, where A alone replaced Tackle) and
`test_an_evolution_keeps_four_better_moves` (Slash, Karate Chop, Brick Break
and Bug Buzz are kept). Both failed before the change.

| Issue | Cause | Resolution |
|---|---|---|
| An evolution's fifth move always replaced the first slot | A answers yes, then picks the cursor's first move | The box and list are answered with `move_to_forget`'s choice |
| The evolution's new move can't be read from the game | Its task struct is not mapped | Taken from the evolution's learnset at the level it evolves |
| The party shows the old level and EXP during the question | The party is written when the evolution ends | The Pokémon is found by its level evolution coming within three levels |
| Down on the move list did nothing | The list ignores keys for a moment after it appears | Wait 30 frames before pressing |
| A box seen twice would be answered twice | The box stays up for a few frames after A | Each box is answered once and the next waits for it to close |
| A YES/NO box after a battle that isn't an evolution's would have been answered no | "No evolution found" and "keep the old moves" were the same answer | "keep" answers no; no evolution found presses A as before |
| Two moves offered at one level are not told apart | Only the first new move is looked up | Open: rare, and the choice is made for the first |

## 41. Milestone 00 from power-on (2026-11-18)

Goal: build every milestone from the ROM alone, so a new machine needs no
hand-made state. Milestone 00 (the player free in the Twinleaf bedroom, no
party) was the last one played by hand.

**The intro.** `boot` in `scripts/make_milestones.py` powers on and plays
these screens. Each press is A held 4 frames, then a wait, unless noted.

1. Power on and run 1,500 frames: the legal screen, the logos and the title.
2. A, 18 times, 110 frames apart: the title, Rowan's greeting, "Is this your
   first adventure?", the control info, to "Please touch a button".
3. Touch YES at (119, 82): "Do you understand everything so far?". The
   touch screen holds the buttons; A does nothing there.
4. A twice, then down twice (30 frames each), then A: the "Would you like to
   know more" menu, NO INFO NEEDED.
5. A three times to "Touch the button on the middle of the Poké Ball", then
   touch (128, 98).
6. A 16 times: Rowan's talk and "Are you a boy?". The cursor starts on boy,
   so A answers it. "So you're a boy?" takes A on YES.
7. The name keyboard: wait 120 frames, A (it only wakes the cursor), A
   (types A), down, right 7 times, A (types R), START (OK). The name is AR.
8. A 7 times: "Your name is AR?" (YES), Rowan, and the rival's menu.
9. Down (Barry is the second entry), then A 8 times. The rival is Barry.
10. A until the player is free in map 415, then 60 frames.

**Checked.** The state is map 415 at tile (4, 6), facing 0, with no party and no
field task, the same as the hand-made one. `boot` then `starter_choice` run on
a scratch root: 01_starter_choice was made from the new 00 and all three balls
gave their starters. The name (AR), the boy sprite and Barry match the
hand-made state's save screen. The two 00 states differ in the trainer ID (the
u32 after the name block: 0x182A8B45 by hand, 0x99E93A96 from boot) and in
the RNG seed word beside the clock; every other word of the save block matches
once the heap shift of 0x54 bytes is allowed for. Pokémon made later carry
the new trainer ID as their OT, and shininess depends on it. The battle env
and `scenario` write their own seeds and take the OT from the starter, so the
tests do not read it; milestones 06 to 16 start from 04 and are unchanged.

| Issue | Cause | Resolution |
|---|---|---|
| The title showed CONTINUE, not the intro | The emulator loads the `.sav` beside the ROM, and a machine that has played the game has one | `boot` links the ROM into an empty folder, so no save is found, as on a new machine |
| `field_task` raised during the intro | No FieldSystem exists until the bedroom loads | The wait for the bedroom treats that error as "not free yet" |
| A did nothing at "Do you understand" and "Please touch" | These take the touch screen | Touch YES at (119, 82) and the Poké Ball at (128, 98) |
| A looped through the info menu | The menu's first entry shows more info and returns | Down twice to NO INFO NEEDED |
| The first name came out as R, not AR | The first A on the keyboard only wakes its cursor | Wait 120 frames and press A twice before the first letter |
| The emulator ran at 4 frames a second beside training | Its threads fight the 15 training workers for the cores | Pin the run to a free core (`taskset -c 1`): about 190 frames a second |
| 00 built on one machine may carry another trainer ID | The ID comes from the clock and the frame count of the intro | Fixed by the inputs: every machine with this ROM gets the same ID, which differs from the hand-made one |

## 42. An emulator beside training, and why runs end on a route error (2026-11-18)

Goal: two things the night's training showed. Building milestone 00 (§41)
found the emulator crawling beside training. And runs3 began ending 1 or 2
runs an update with `route_error`, whose message the trainer didn't keep.

**The emulator's threads.** An emulator started beside training's 14
workers ran at 2 frames a second. The same process pinned to one core
(`taskset -c 15`), a core a worker was also using, ran at 119. Unpinned it
had 20 threads; pinned, 6, so some of its threads are sized by the cores it
may use. They hand every frame between them, and spread over busy cores,
each handoff waits on the scheduler.

**Training's workers aren't slowed by it.** The pool was changed to give
each worker a core of its own, and runs3 restarted on it at update 40. It
ran at 1.3 and 1.4 decisions a second, as before: each worker already had a
core. The slowdown hits a process that squeezes in beside them. So the pool
change was taken back out, and a job run beside training is pinned instead:
`taskset -c 1 python ...`.

**Route errors in the metrics.** Each episode record keeps the run's error
message, and the metrics count them by message (`errors`), so a route error
can be found from the trainer's log alone.

**What the route errors were.** The first update with the new metric
(update 41) showed three: twice "stuck walking to (27, 22)" with the player
on Route 203, and once "no way into map 198" from map 198. All three were
runs resumed from a restart state saved during a wild battle inside a heal
trip. A restart replays its route action from that action's start, and a
trip half done can't be: the gate's top-up found the party healthy and
skipped the rest of its trip back, and the mine's began again with an exit
to the floor the player was already on. Now no restart state is saved
inside a heal trip; its battles are still played. And a restart that ends
in a route error in the very action it resumed is dropped, so the bad ones
already saved go away.

**Verified:** `test_episode_stats_count_why_runs_ended_on_a_route_error`,
`test_a_battle_inside_a_heal_trip_leaves_no_restart_state`,
`test_a_restart_that_ends_in_a_route_error_is_dropped`.

| Issue | Cause | Resolution |
|---|---|---|
| An emulator beside training ran at 2 frames a second | Its threads, spread over busy cores, wait on the scheduler at every handoff | Pin a side job to one core with `taskset`: 119 frames a second |
| Pinning each training worker didn't speed training | Each worker already had a core of its own | Taken back out |
| Runs ended `route_error` with no way to see why | The episode record dropped the run's error message | The record keeps it, and the metrics count errors by message |
| Runs resumed from some restart states ended `route_error` | They were saved inside a heal trip, which can't be resumed halfway | No restart is saved inside a trip; one that fails in its own route action is dropped |

## 43. Battle effects in RAM (2026-11-18)

Goal: the first part of NEXT_PHASE step 4. The battle observation can't
see effects such as Stealth Rock, Light Screen, Sand Tomb's trap or Curse,
and Roark's Pokémon use them. This finds where the game keeps them. Putting
them in the observation comes next. It changes the network's input size,
so it waits for the switch from runs3 (§42).

**Where they are.** In the battle context, the struct the env already
reads for the menu state. The decomp's layout gives the offsets. The
fields just before them already matched this hack: `taskData` at 0x178,
and `totalTurns` at 0x150 counts the turns.

- `fieldConditionsMask` at 0x180: the weather, and the turns left of
  Gravity (bits 12-14) and Trick Room (bits 16-18).
- `weatherTurns` at 0x184: the turns left of a move's weather.
- `sideConditionsMask[2]` at 0x1BC, one per side, the player's first:
  which screens and hazards are up, and Tailwind's turns (bits 8-9).
- `SideConditions[2]` at 0x1C4, 8 bytes per side: the turns left of
  Reflect, Light Screen, Mist and Safeguard, and the layers of Spikes and
  Toxic Spikes.
- Each Pokémon's `statusVolatile`, already read for the action mask, holds
  the rest: the turns left of Sand Tomb's trap (bits 13-15), Curse (bit
  28), confusion's turns (bits 0-2) and Substitute (bit 24).

`gen4.read_field_effects` reads the field and both sides.

**Curse from Shuckle is a stat change.** Curse used by a Pokémon that isn't
a Ghost raises its Attack and Defense and lowers its Speed. Those stages
are already in the observation. Only a Ghost's Curse sets the bit.

**How it was checked.** Each effect got a wild battle against an enemy
that knew only the effect's move. Turtwig used Withdraw, so the battle
lasted, and the fields were read after each turn. All ran beside training,
pinned to one core.

| Move | Where it showed | What changed each turn |
|---|---|---|
| Light Screen | The enemy's side, mask bit 1 | Turns 4, 3, 2, 1, then the bit cleared |
| Reflect | The enemy's side, mask bit 0 | Turns 4, 3, 2, 1, then cleared |
| Safeguard | The enemy's side, mask bit 3 | Turns 4, 3, 2, 1, then cleared |
| Tailwind | The enemy's side, mask bits 8-9 | Turns 2, 1, then cleared |
| Stealth Rock | The player's side, mask bit 7 | Stayed |
| Spikes | The player's side, mask bit 2 | Layers 1, 2, 3, then no more |
| Toxic Spikes | The player's side, mask bit 10 | Layers 1, 2, then no more |
| Sandstorm, Rain Dance | The field mask | Turns 4, 3, 2, 1, then cleared |
| Trick Room | The field mask, bits 16-18 | Turns 4, 3, 2, 1 |
| Sand Tomb | Turtwig's volatile bits 13-15 | Turns 3, 2, 1, then free |
| Curse, from Gastly | Turtwig's volatile bit 28 | Stayed, and Gastly lost half its HP |
| Confuse Ray | Turtwig's volatile bits 0-2 | Turns 5, 4, 3, 2, 1 |
| Substitute | The enemy's volatile bit 24 | Stayed, and the enemy lost a quarter of its HP |

Not checked: Mist and Gravity (same layout as their checked neighbours),
the weather an ability starts, and Leech Seed, which fails on a Grass type.

**Verified:** `test_field_and_side_effects_are_read_from_ram` (Light Screen,
Stealth Rock, Spikes, Sandstorm).

| Issue | Cause | Resolution |
|---|---|---|
| The observation can't see screens, hazards, weather or traps | Nothing read them from RAM | Found in the battle context; `read_field_effects` reads them |
| Light Screen and Reflect seemed to last 4 turns | The read comes after the turn the move was used, which counts as one of its 5 | Expected |
| Leech Seed set nothing | Turtwig is a Grass type, which Leech Seed can't seed | Left unchecked |

## 44. Battle effects in the observation (2026-11-18)

Goal: the rest of NEXT_PHASE step 4. The effects found in §43 go into the
observation, and a run's checkpoint carries over to the wider observation,
so a new run doesn't start from scratch.

**What the observation gains.** 32 values, after all the old ones:

- The weather, one of rain, sand, sun, hail or fog, and its turns left.
- The turns left of Trick Room and Gravity.
- For each side: the turns left of Reflect, Light Screen, Safeguard, Mist
  and Tailwind; the layers of Spikes and Toxic Spikes; and Stealth Rock.
- For each side's active Pokémon: the turns left of a trap such as Sand
  Tomb, a Ghost's Curse, confusion's turns left, and a Substitute.

Each count is divided by the most it usually reaches (5 turns, 3 layers of
Spikes), and capped at 1. The observation grows from 902 values to 934.

**Why they go last.** The old observation is then the first 902 values of
the new one. `ppo.widen_checkpoint` gives the new inputs zero weights in
the first layer of the policy and of the value, so the widened net plays
exactly as the old one did, then learns what the new values mean. Their
running mean starts at 0 and variance at 1; Adam's moments for the new
weights start at 0. `scripts/widen_checkpoint.py` writes a run's newest
checkpoint, widened, into a new run directory, which `train_ppo.py` then
resumes from.

**Checked on runs3.** Its checkpoint 120, widened, gives the same action
probabilities as the original (largest difference 0.0).

**The switch to it isn't made yet.** runs3 trains on the old observation.
To switch: widen runs3's newest checkpoint into a new run directory, copy
its restart states, and start training there on this code.

**Verified:** `test_a_widened_checkpoint_plays_as_before_and_trains_on`,
`test_observation_of_battle_effects_for_a_made_up_snapshot`,
`test_a_trap_or_a_curse_on_the_player_shows_in_the_observation` (Sand Tomb,
Gastly's Curse), and `test_field_and_side_effects_are_read_from_ram`, which
now also checks the battle snapshot.

| Issue | Cause | Resolution |
|---|---|---|
| The agent fought blind to screens, hazards, weather and traps | The observation had no values for them | 32 values from the battle context and each active Pokémon's volatile status |
| A wider observation meant training from scratch | Resuming refuses a checkpoint with another observation size | The new values go last, and `widen_checkpoint` pads the first layers with zero weights |

## 45. Roark refused every run that reached him, and restart states inside a mend (2026-11-19)

Goal: two things runs3 showed overnight, fixed before the switch to the
wider observation (§44), since that restarts training anyway.

**Runs reached Roark, and he turned every one down.** From about update
80, 1 to 5 runs an update reached Roark's talk (route step 70) and ended
`no_badge`. The restart states at the gym show why: 19 of 20 are a lone
Monferno at level 24 or 25, with nothing caught. The agent picked the ball
about once in 600 decisions. Roark's cap is 16, and the mend before him
leaves over-cap Pokémon in the PC only if one able to battle at or under
the cap stays (§39). A lone starter can't be left, so Roark refuses it and
the route ends.

**A refusal is now paid as a loss.** It cost nothing before. A wipe costs
the loss (−10) and each faint, so to the agent, reaching Roark this way
was the best ending a run could have. Now the route ending without the
badge pays `NO_BADGE_REWARD`, a lost battle's −10. Catching stays the
agent's choice, as the plan has it: it has to find that a team caught on
the way, under the cap, is what gets the badge.

**Restart states inside a mend never went away.** Route errors kept
coming, 1 or 2 every few updates: "stuck walking to (27, 22)" from
Route 203, and "stuck walking to (17, 28)" or "no way into map 198" in the
mine. All came from restart states at steps 45 and 56, the mends before
the gate's and the mine's trainers. Every battle in a mend happens inside
its heal trip, so these states were all saved before §42 ruled that out.
For the same reason no new state there ever replaced them. Resumed with a
healthy party, the mend skips its trip, and the next action fails, from
Route 203 or the mine's first floor. §42 drops only a restart that fails
in its own action, so these stayed. Now a restart is also dropped when the
run ends in a route error before its next battle. Step 12, Route 202's
mend, has old states too, but its trip starts with a walk on the same
map, so they resume.

**Verified:** `test_a_run_that_ends_without_the_badge_is_paid_as_a_loss`,
and `test_a_restart_that_ends_in_a_route_error_is_dropped`, now also for a
failure in the action after the resumed one, with wild battles switched
off in the restart state so none comes between.

| Issue | Cause | Resolution |
|---|---|---|
| Every run that reached Roark ended `no_badge` | A lone starter at level 24-25, far over his cap of 16, with nothing caught | Expected for a policy that never catches |
| Reaching Roark over the cap cost nothing | `no_badge` had no reward | It pays a lost battle's −10 |
| Route errors at the gate and in the mine kept coming | Restart states saved inside a mend's trip fail in the action after the mend, which §42's rule missed, and nothing replaces them | A restart is also dropped when the run ends in a route error before its next battle |
| The new test's run wiped before the broken action | More wild battles on Route 201 after the resumed one | Wild encounters switched off in the test's restart state |

## 46. The PC choice is the agent's, within the rules (2026-11-19)

Goal: at each Pokémon Center, the agent decides which living Pokémon come
along and which stay in the PC. The rules are hard limits, Roark's level
cap among them.

**Why.** Until now the runner decided. It left every fainted Pokémon in the
PC, and, before Roark, the ones over his cap if one under it stayed (§39).
Nothing ever came back out of the PC, so the agent had no say in its team.
Now a Pokémon caught on the way can wait in the PC, at its level, for Roark.

**How it works.**
- At each heal the route asks `("pc", cap)` before the nurse, and the run
  env answers.
- A fainted Pokémon is dead. It goes to the PC, and the run's dead list
  keeps it out of every later choice.
- The agent is asked about each living Pokémon in turn: the party's
  first, then up to six in the PC, in box order. Action 0 takes it along;
  action 1 leaves it in the PC.
- The rules are masks (`run_env.pc_options`). The party holds 1 to 6.
  On the trip before Roark, a Pokémon over 16 can't come along while one
  at or under it can.
- When the rules leave only one option, the agent isn't asked. A lone
  starter is never asked.
- The mend before Roark now goes to the center whenever a party Pokémon is
  over the cap. So a lone starter over it can be swapped for a Pokémon
  waiting in the PC. If no Pokémon meets the cap, nothing changes, and
  Roark turns the party down as before.
- The observation gains 878 values at its end (934 to 1812): a PC flag,
  six PC slots with the same features as a party slot, the Pokémon asked
  about, the ones taken so far, and the next boss's cap. They are zero in
  battle, so a widened checkpoint plays the same (§44).
- The move itself still writes the party and the box in RAM
  (`scenario.pc_swap`), as the deposit did (§37). A Pokémon taken out gets
  its party data as the game's withdraw makes it: the level from its EXP,
  its stats from the hack's tables, and full HP.
- The party's order isn't learned yet. The Pokémon kept stay in order, and
  those taken out come after them.

**Verified:**
- `test_the_pc_rules` checks the masks.
- `test_a_pokemon_taken_out_of_the_pc_is_the_one_put_in` checks that a
  Pokémon taken out has the level, stats and moves it went in with.
- `test_before_roark_a_lone_pokemon_over_his_cap_stays_and_the_agent_picks_from_the_pc`
  plays the trip before Roark: the starter over the cap stays in the PC,
  and the agent's choices pick who comes out.
- `test_a_fainted_pokemon_stays_in_the_pc_and_is_never_offered` plays two
  visits.
- `test_observation_of_a_pc_choice` checks the new observation values.

| Issue | Cause | Resolution |
|---|---|---|
| The agent had no say in its team | The runner left fainted and over-cap Pokémon in the PC itself, and never took one out | A PC choice at each center, with the rules as masks |
| A lone starter over the cap couldn't be swapped for a Pokémon in the PC | The mend before Roark went to the center only if a Pokémon under the cap was in the party | It goes whenever a party Pokémon is over the cap |

## 47. A higher entropy bonus, so the agent keeps trying the ball (2026-11-20)

Goal: get the agent to find catching by its own play. It is what Roark's
badge needs (§45, §46).

**What runs5 showed.** Over its first 96 updates (about 98,000 decisions)
no run got the badge. Roark turned down 16 to 17% of runs, almost all a
lone starter over his cap. The agent threw a ball 32 times, fewer per
update as training went on: 0.36 overnight, then 0.26. The policy's
entropy had fallen to about 0.3, from about 0.8 early in runs3. The policy
was settling on habits, and a ball it rarely throws is a choice it
rarely learns from. The −10 for a refusal (§45) wasn't enough on its own.

**The change.** `train_ppo.py --ent-coef` sets PPO's entropy bonus, which
was fixed at `ppo.Config`'s 0.01. Runs train on from runs5's checkpoint
with 0.03. A higher bonus keeps more weight on the moves the agent
rarely picks, so it keeps trying them. It changes how the agent learns,
not the game or the rewards. The checkpoint doesn't carry the bonus: a
resumed run uses the one it is given.

| Issue | Cause | Resolution |
|---|---|---|
| Catching got rarer as runs5 trained, and no run got the badge | The policy's entropy fell to about 0.3, so it stopped trying the ball | `--ent-coef`, and the next run trains with 0.03 instead of 0.01 |

## 48. runs6: the higher entropy bonus didn't teach catching (2026-11-22)

Goal: see whether §47's bonus of 0.03 gets the agent catching, and the
badge.

**The run.** runs6 trained from runs5's checkpoint 340 to update 489,
with 500,736 decisions in all, over 2,367 runs. runs5 was stopped at
update 346, so the 6 updates after its last checkpoint were lost.

**What it showed.** No run got the badge.

| Updates | Wipes | Roark refused | Balls per update | PC take / leave | Entropy |
|---|---|---|---|---|---|
| 341–424 | 85.1% | 14.8% | 0.15 | 7 / 4 | 0.44 |
| 425–449 | 90.1% | 9.7% | 0.32 | 11 / 10 | 0.50 |
| 450–489 | 83.6% | 16.0% | 0.07 | 0 / 0 | 0.49 |

Entropy rose from 0.27 to about 0.5, as intended, and training stayed
steady (KL about 0.003). Catching didn't follow. There was a rise in
updates 425 to 449, and then it faded: 24 balls in 149 updates, fewer
per update than runs5 (0.26 to 0.36). Mean return stayed at about 117.
The bonus is averaged over every decision, and almost all decisions are
move choices (in updates 425 to 449: about 17,700 moves, 8 balls). So
the extra entropy mostly went to the moves.

Four runs ended in a route error, none of them seen more than once:
"no way into map 198" from (199, 15, 3) and from (199, 28, 21), "nobody
to talk to from (17, 28) facing right", and "text stuck at (199, 3, 24)".

| Issue | Cause | Resolution |
|---|---|---|
| Catching stayed rare, and no run got the badge | Likely: the bonus is spread over every decision, and nearly all of them are move choices | Open: the next approach is the user's choice |
| 6 updates lost when runs5 was stopped | Checkpoints come every 10 updates, and a stopped run saves none | runs6 started from checkpoint 340 |
| 4 route errors in 2,367 runs | Not looked into yet; each appeared once | Open |

## 49. A ball-only entropy bonus, and a reward for catching (2026-11-22)

Goal: get the agent catching, after §48 showed the plain entropy bonus
went to the moves. The user asked for both changes below.

**Why catching was the worse choice.** A wild battle won by a knockout
pays 6: 1 for the faint and 5 for the win. A catch ends the battle with
neither, and paid 0. Its worth (a second Pokémon, a way past Roark's
cap) only shows battles later. So, in the short run, every catch cost
the agent 6.

**The catch reward.** `run_env.CATCH_REWARD` pays 10 for each catch (20 from §50),
more than a knockout would. The agent doesn't need to learn the Nuzlocke
rules to earn it within them. At the start of each wild battle,
`nuzlocke.Run.encounter` says whether the rules allow a catch: only a
route's first encounter, no Pokémon from a line already caught, and a
shiny always. When they don't, the ball is masked out, so it can't be
thrown. The reward can only be paid about once per route. The first
encounter uses the route up whether or not it is caught.

**The ball's own entropy bonus.** `train_ppo.py --ball-ent-coef` adds
an entropy bonus only at decisions where the ball is legal. At those
decisions the bonus counts `ent_coef + ball_ent_coef`; elsewhere it
counts `ent_coef`. So the push to explore lands where the ball can be
tried, not on all the move choices. It changes how the agent learns,
not the game. Each update logs `ball_chances` (decisions in the rollout
where a ball was legal) and `ball_prob` (the policy's mean chance of
the ball there), to show whether it works.

runs7 trains on from runs6's checkpoint 489, with `--ent-coef 0.03`
and `--ball-ent-coef 0.1`.

| Issue | Cause | Resolution |
|---|---|---|
| A catch paid 0, while a knockout of the same Pokémon paid 6 | The catch's worth only shows battles later | `CATCH_REWARD` of 10 for each catch; the rules' mask keeps it to the encounters the rules allow |
| The plain entropy bonus went to the move choices (§48) | It is averaged over every decision, and nearly all are moves | `--ball-ent-coef`: an extra bonus only where a ball can be thrown, with `ball_prob` logged |

## 50. Why the agent stopped throwing: a throw-or-fight test (2026-11-23)

Goal: find out why runs7 learned to throw less, although a catch now
pays 10 and the ball has its own entropy bonus (§49). In runs7 the
policy's chance of the ball, where it was legal, went from 0.16% to 0.70%
in 18 updates, then fell to about 0.10%.

**The test.** A one-off script, run beside training, took the 51
restart states (of 436) at a wild battle the rules let the agent catch.
For 50 of them it played the battle twice with the same seed, using
runs7's checkpoint 590. In one, the agent threw at every chance. In the
other it only fought.

| | Throw at every chance | Only fight |
|---|---|---|
| Caught | 44 (88%), 3.1 throws each | — |
| Won | — | 50 (100%) |
| Lost (the run is over) | 3 (6%) | 0 |
| Ended as fled (each an Onix) | 3 | 0 |
| Mean reward in the battle | 7.7 | 6.0 |
| Party HP left | 87% | 93% |

A throw usually works, and pays more in the battle. But the lone
starter takes hits while it throws, and 3 runs in 50 ended there: a
Zigzagoon on Route 201 (after 12 throws), a Psyduck in Oreburgh Gate,
and a Rhyhorn in the mine.
The policy's value at these battles is about 64. So a wipe costs about
74 (the −10 and the run's future). Over 50 tries that is about 3.8 per
try, more than the 1.7 a throw gains. Throwing at every chance loses
about 2 per battle. The policy learned to stop. By this count a catch
reward above about 12 would make it pay.

**The change.** `CATCH_REWARD` goes from 10 to 20, so trying to catch
gains about 7 a battle by the same count, even throwing at every chance.
runs8 trains on from runs7's newest checkpoint, with the same entropy
bonuses (0.03, and 0.1 at ball chances).

**A bigger gap.** No run in runs5, runs6 or runs7 has started Roark's
battle. The furthest restart state is at step 66, the gym's last trainer.
The starter is level 21 by Route 203 (step 40), far over Roark's cap of
16. A caught Pokémon is level 4 to 10 and gets no experience unless it
is sent into battle. The agent switches about once in 25 updates. So
even with catches, the badge needs the caught Pokémon raised to at most
16 and strong enough to beat Roark.

| Issue | Cause | Resolution |
|---|---|---|
| runs7 learned to throw less, despite §49 | A throw risks a wipe (6% when throwing every turn), which costs more than the catch reward of 10 gains | `CATCH_REWARD` from 10 to 20 (the user's call); a reward above about 12 makes throwing pay |
| No run has ever fought Roark | The starter is over his cap by Route 203, and caught Pokémon stay at their catch level unless they fight | Open: the badge needs a caught team raised to his cap |

## 51. The agent picks the lead at each Pokémon Center (2026-11-24)

Goal: give caught Pokémon battles. The party's first Pokémon starts every
battle, and the agent rarely switches (8 switches in runs8's 138
updates). So a caught Pokémon stays at the level it was caught at, 4 to
10, while the starter passes Roark's cap of 16 by Route 203 (§50). A
Pokémon only gains experience from a battle it takes part in. Leading
with a caught Pokémon is the simplest way to raise one to the cap.

**The choice.** After the take-along choices at each Pokémon Center
(§46), if the new party has more than one Pokémon, the agent picks which
one leads. Action k puts the k-th Pokémon first; the others keep their
order. A party of one is not asked. `scenario.pc_swap` makes the move in
RAM, as the party menu's switch would. It is a stand-in, like the PC's
deposit and withdraw, until those screens are mapped.

**The observation.** `battle_env.lead_observation` shows the new party in
its order, the next boss's level cap, and two flags: `pc` and `lead`.
`lead` is one new value at the end of the observation (1812 to 1813), so
runs8's checkpoint can be widened for it (`scripts/widen_checkpoint.py`).
Each choice is logged as `pick.lead_kept` (the first stays first) or
`pick.lead_changed`.

| Issue | Cause | Resolution |
|---|---|---|
| Caught Pokémon never fought, so they never neared Roark's cap | The party's first Pokémon starts every battle, and the agent rarely switches | The lead choice after each PC choice |
| Four tests stopped at the new question | They answered only the take-along choices | They answer the lead too (`take_all` and the PC tests) |

## 52. runs8: a catch reward of 20 didn't stick either (2026-11-25)

Goal: see whether §50's catch reward of 20 gets the agent catching.

**The run.** runs8 trained from runs7's checkpoint 640 to update 873,
with 893,952 decisions in all, over 3,365 runs. It was stopped about
7,000 decisions short of its budget, since catching had faded. The 3
updates after checkpoint 870 were lost.

**What it showed.** No run got the badge.

| Updates | Wipes | Roark refused | Balls | Throw odds at a chance | PC take / leave | Entropy |
|---|---|---|---|---|---|---|
| 641–717 | 85.2% | 14.8% | 1 | 0.26% | 60 / 0 | 0.56 |
| 718–794 | 82.1% | 17.6% | 20 | 0.76% | 65 / 11 | 0.62 |
| 795–873 | 82.6% | 17.4% | 19 | 0.55% | 33 / 8 | 0.66 |

Mean return rose from 122 to 134, and training stayed steady (KL about
0.003). Throwing came in short bursts that the next update undid. At
update 857 the agent threw at 13% of its chances (10 balls), and at
update 858 at 0.08%. In the last 10 updates it threw at 0.09% of them.
Only 2 of the 440 restart states hold a caught Pokémon.

**The change.** The user: "catching should be a priority thing to learn
you need multiple pokemons to even try to win the first battle".
`CATCH_REWARD` goes from 20 to 50, the user's choice over a training
bonus for trying throws. A catch is then worth more than beating Roark
(`BOSS_REWARD` 20), as for a player who always tries for each route's
catch. The rules still allow one catch per route. runs9 trains on from
runs8's checkpoint 870, widened for §51's lead choice, with the same
entropy bonuses.

| Issue | Cause | Resolution |
|---|---|---|
| Catching stayed rare, and no run got the badge | Likely: throws are so rare that each burst was undone by the next update | `CATCH_REWARD` from 20 to 50 (the user's call), in runs9 |
| 3 updates lost when runs8 was stopped | Checkpoints come every 10 updates, and a stopped run saves none | runs9 starts from checkpoint 870 |
| 4 route errors, all "text stuck": 3 at (199, 10, 29), 1 at (258, 24, 22) | Not looked into yet | Open: (199, 10, 29) came up 3 times in one run |

## 53. A review of the method, and papers for the next steps (2026-11-26)

Goal: check whether the method is sound and the rules are learnable, and
find well-known papers for what holds the agent back.

**What holds.** The PPO core is correct. The rules are hard masks
(permadeath, first encounter, duplicates and shiny clauses, the level cap
at the PC), so the agent can't break one while it learns. Huang and
Ontañón's study backs masks over penalties.

**What holds it back.** Each was checked against the code, runs8's
metrics and its checkpoint 870:

- Catching is an exploration problem as much as a price problem. runs8
  threw 40 balls in 12,995 chances, about one in 300.
- The ball's output row still holds what it learned when a catch paid 0.
  The same network was carried from runs5 through three reward changes
  (0, 10, 20, 50). Its bias is −0.32 and its weights are the largest of
  any action.
- The battle observation has no catch-allowed flag, route progress or
  level cap. The critic can't tell a catchable battle from another.
- The critic explains about two thirds of the return's variance (0.67 on
  average; value loss about 457). Returns reach about 130 and aren't
  scaled. Advantages are normalized per minibatch, so this slows the
  critic, not the policy directly.
- The agent switched 14 times in about 165,000 move choices, and the
  switch outputs to party slots 4 to 6 are untrained. Caught Pokémon get
  little experience; §51's lead choice is the first fix.

**Papers.** Fourteen papers, picked by problem, each checked on arXiv
for its title, authors and year, are now in
[REFERENCES.md](REFERENCES.md), and `scripts/fetch_references.sh`
downloads them. The plan built on them is NEXT_PHASE step 3.11.

| Issue | Cause | Resolution |
|---|---|---|
| The ball's output row is still pushed down | One network carried through three reward changes, from a catch reward of 0 | Planned: reset that row at the switch (NEXT_PHASE 3.11 c, the user's call) |
| Throws are tried about once in 300 chances | Few catchable battles in the restart mix, and the row above | Planned: start more restart episodes at catchable battles (3.11 a) |
| The critic can't see a catch chance, the route progress or the cap in battle | They aren't in the battle observation | Planned: append them (3.11 b) |
| The critic explains about two thirds of the variance | Unscaled returns of about 130, and a small critic | Planned: PopArt, if 3.11 b doesn't help (3.11 d) |
| Switch outputs to slots 4 to 6 never trained | Parties have stayed small | Later: one encoder for all party slots (Deep Sets) |
| A comment says returns reach about 13 | Written for battle-only training | Fixed with 3.11 b |

## 54. Catchable restarts, the run in the observation, and a ball reset (2026-11-26)

Goal: build NEXT_PHASE 3.11 a to c, so the agent tries throws often
enough to learn what a catch is worth (§53). The user: "yes lets do them
all".

**Catchable restarts.** A restart state is saved as its battle starts.
When the rules allow a catch there and the bag has a ball, its name ends
in `_catch` (`run_env.CATCH_TAG`). `--catch-restart-share` sends that
share of restarted runs to those states, instead of to a random route
step. The bookkeeping saved with a state is from before the battle's
encounter, so the route's catch is open again when a run resumes there.
States saved before this have no tag; new ones replace them as runs go.

**The run in the observation.** Three values at the end (1813 to 1816):
whether this battle allows a catch, how far along the route the run is,
and the next boss's level cap. `RunEnv` sets them at every decision; the
battle env alone leaves them at 0. The critic can now tell a catchable
battle from another. A widened checkpoint gives them zero weights, so the
policy starts as it was.

**The ball reset.** `widen_checkpoint.py --reset-ball`
(`ppo.reset_action`) draws the ball's row of the policy's output layer
again as when training began, with its bias at 0 and its Adam moments
cleared. The other actions' outputs don't change. On 25 catchable
battles from §50's throw test, runs9's checkpoint 890 threw with a mean
chance of 0.12%. After the reset it was 14.1% (11% to 17%), close to an
even pick among the legal actions.

**The switch.** If runs9 still throws at under 1% of its chances at
about update 950, its newest checkpoint is widened with `--reset-ball`
into runs10, which trains with `--catch-restart-share 0.5`.

| Issue | Cause | Resolution |
|---|---|---|
| Few runs start at a battle that allows a catch | A restart picks a route step at random, and catchable battles are a small part of each | Tagged restart states, and `--catch-restart-share` |
| Tagging a state needs the encounter's answer, but the saved bookkeeping must come from before it | The encounter uses up the route | The bookkeeping is copied before the encounter and saved with the state after it; the encounter only reads the game |
| The critic couldn't see a catch chance, the route progress or the cap in battle | They weren't in the battle observation | Three values appended (1813 to 1816) |
| The throw odds stayed near 0.1% at catchable battles | The ball's output row kept what it learned when a catch paid 0 | `--reset-ball`: about 14% after it |
| A comment said returns reach about 13 | Written for battle-only training | It now says about 130 |

## 55. Every battle's last decision in the logs, and metrics for catching (2026-11-26)

Goal: count catches, and log what the next run needs to show whether
catching takes hold. The user: "yes add that to the branch before the
switch", then "can we also add the extra logging we mentioned above".

**A gap in the logs.** When a battle ended, `RunEnv.step` returned the
info of the next decision, from `_advance`, and the battle's last decision
was never tallied. So the logs missed the throw that made each catch, the
move that won each battle, and the last faint in each lost battle. runs9
had 745 wipes in 910 runs, and its logged faints came to 0.001 a run.
`picks.ball` in runs5 to runs9 counts only throws that didn't end the
battle. Training and rewards weren't affected, since the rollout keeps
every decision. `ball_chances` and `ball_prob` come from the rollout, so
they were always right. Now the battle's last decision goes with the next
decision's info, with how the battle ended. From the next run on, ball
picks and faint counts read higher, and don't compare with earlier runs.

**New metrics.** Each line of `metrics.jsonl` gains:
- `catch_battles`: how each battle where a ball could be thrown ended
  (CAUGHT, WON, LOST, FLED). A battle counts when the ball is legal at its
  first decision. Its CAUGHT count is the run's catches.
- `ball_throws` and `ball_adv`: the throws in the update's rollout, and
  their mean advantage in standard deviations from the rollout's mean.
  `picks.ball` counts a run's throws only when the run ends, often many
  updates later. Below 0, the
  update makes the ball less likely where it was thrown. This tests why
  bursts of throws were undone the next update (§52, §56).
- The per-state stats (`states`) split runs by how they started: `fresh`,
  `restart` or `catch_restart`. All runs shared one key before. With
  `--catch-restart-share`, a share of runs start at a catchable battle,
  and that mix alone would shift the overall rates.
- `mean_caught_alive`, `max_caught_level` and `boss_fights`: at each run's
  end, the caught Pokémon still alive, the highest level any caught one
  reached, and the boss battles fought. They show whether caught Pokémon
  near Roark's cap of 16 (NEXT_PHASE 3.11 e and f), and whether a run
  ever fights Roark instead of being turned away.

**Verified:** `test_a_catch_is_paid_and_the_rules_mask_a_second_one_on_the_route`
now checks that the catching throw is logged, then plays the run out and
checks the caught Pokémon's level and life at its end.
`test_a_battle_that_allows_a_catch_shows_it_and_leaves_a_tagged_restart`
checks `catch_chance` and how each run started.
`test_a_run_that_ends_without_the_badge_is_paid_as_a_loss` checks the new
end fields, `test_the_ball_bonus_raises_the_balls_odds_only_where_it_can_be_thrown`
the sign of `ball_adv`, and `test_episode_stats_split_faints_by_strength_and_flag_results_the_game_contradicts`
the tally and the new summaries.

| Issue | Cause | Resolution |
|---|---|---|
| A battle's last decision was missing from the logs | `_advance`'s info, for the next decision, replaced the battle's | The battle's last decision and its outcome go with the next decision's info |
| Catches weren't counted | Only throws were logged | `catch_battles`, whose CAUGHT count is the catches |
| No way to tell why bursts of throws were undone | How the update weighed the throws wasn't logged | `ball_adv` |
| Runs started at catchable battles would shift the overall rates | All runs shared one key in the per-state stats | Stats per start: `fresh`, `restart`, `catch_restart` |
| No sign of whether caught Pokémon near Roark's cap | Nothing about the team was logged at a run's end | `mean_caught_alive`, `max_caught_level`, `boss_fights` |
| The catch test's battle had no ball at its start | Its Master Balls are written after the battle starts | It starts with 5 Poké Balls, and the Master Balls replace them |
| A test of battle episodes' records failed | The run's end fields were added to battle episodes too, as None | They are added only when the run reports them |

## 56. runs9: a catch reward of 50 didn't stick either (2026-11-26)

Goal: see whether §52's catch reward of 50 gets the agent catching.

**The run.** runs9 trained from runs8's checkpoint 870, widened for the
lead choice, to update 937, with 959,488 decisions in all, over 910 runs.
The user stopped it there: "once added stop the training runs so we can
re evaluate because catching is still too low". The 7 updates after
checkpoint 930 were lost.

**What it showed.** No run got the badge.

| Updates | Wipes | Roark refused | Balls | Throw odds at a chance | PC take / leave | Entropy |
|---|---|---|---|---|---|---|
| 871–892 | 83.0% | 17.0% | 5 | 0.64% | 6 / 6 | 0.66 |
| 893–914 | 82.1% | 17.9% | 4 | 0.50% | 2 / 2 | 0.68 |
| 915–937 | 80.7% | 19.0% | 5 | 0.37% | 4 / 2 | 0.67 |

The ball counts miss the throw that made each catch (§55). Throw odds
fell through the run, to 0.19% in its last 10 updates. As in runs8,
throwing came in bursts that the next update undid: 8.6% at update 888,
then 0.10%; 5.7% at 903, then 0.18%; 3.9% at 918, then 0.24%. The lead
choice came up 5 times and changed the lead once. Only 2 of the 441
restart states hold a caught Pokémon, as at runs8's end. Training stayed
steady (KL about 0.002), and the critic explained 0.67 of the return's
variance, as before. Mean return fell from 138 to 126.

**Where the throws are.** Two checks on the 51 catchable battles from
§50's throw test, after the run:
- The same 25 battles, scored with each checkpoint from 870 to 930: the
  mean throw odds at a battle's first decision stayed between 0.08% and
  0.33%, and no battle passed 1.3%. No checkpoint shows a burst.
- All 51, played on without throwing by checkpoint 930, three times each:
  253 decisions with a ball chance, at a mean of 0.07% and at most 0.87%.
  The odds fall as the battle goes on, from 0.10% at the first decision
  to 0.02% by the third, and fall as the wild Pokémon is hurt. A player
  throws more once it is weak.

So the policy throws at about 0.1% wherever it can be checked. The
bursts come from battles unlike these, such as a run with a caught
Pokémon at its next route, or from one update's policy that the next
undid. Also, `picks.ball` counts a run's throws when it ends, so an
update with 9% odds could log no throws. §55's `ball_throws` and
`ball_adv` count the update's own.

At these odds the reward can't be what holds catching back. By §50's
count, at a catch reward of 50, throwing at every chance beats fighting
by about 33 a battle. The agent throws about once in 12 updates, and
PPO's clip lets one throw raise the ball's odds there by at most about
20%. The gains never add up. This is what §54's ball reset (about 14% at
the start) and catchable restarts are for.

| Issue | Cause | Resolution |
|---|---|---|
| Catching stayed rare, and no run got the badge | Likely as in runs8: throws are so rare that each burst is undone by the next update, and a reward of 50 didn't change that | Open: the user stopped runs9 to re-evaluate; §54's restarts and ball reset and §55's metrics are ready |
| An update showed 9% throw odds and logged no throws | `picks.ball` counts a run's throws when the run ends, many updates later | `ball_throws` counts the update's own (§55) |
| 7 updates lost when runs9 was stopped | Checkpoints come every 10 updates, and a stopped run saves none | The next run starts from checkpoint 930 |
| 1 route error: "no way into map 198 from (199, 26, 20)" | Not looked into yet; like two in runs6 | Open |

## 57. A second review: what a catch is for, and Roark's real team (2026-11-26)

Goal: test the premise behind §47 to §52, and pick the next steps. The
user pasted a second outside review, then: "impllement based on your
recommendations after the coding is done kick off the next run with our
changes and new metrics tracking".

**The review's point.** The entropy bonuses and the catch rewards of 10,
20 and 50 all assumed that a throw priced right would be found and kept.
But a catch isn't useful yet. A caught Pokémon stays at its catch level
unless it fights, and the starter still takes the experience and passes
Roark's cap. The badge needs a chain: catch, keep, raise to the cap,
leave the starter in the PC, and beat Roark. No run has shown that chain
is possible here.

**Checked.**
- Roark (ROM trainer 246) has six Pokémon at levels 13 to 16, each with
  a held item: Bonsly (Focus Sash; Stealth Rock, Selfdestruct, Brick
  Break, Accelerock), Lileep (Big Root; Sludge Bomb, Giga Drain,
  AncientPower, Recover), Gible (Chesto Berry; DragonBreath,
  Flamethrower, Thunder Fang, Earth Power), Corsola (Rindo Berry;
  Recover, Water Pulse, Light Screen, Accelerock), Shuckle (Berry Juice;
  Toxic, Accelerock, Curse, Sand Tomb) and Cranidos at 16 (Lum Berry;
  Head Smash, Zen Headbutt, Crunch, Rock Polish).
- The agent has no item action in battle, only moves, switches and the
  ball. Items are the roadmap's step 5.
- The route's only grind trains to level 11, on Route 202. The starter
  passes 16 on the experience of the battles it must fight, since it
  leads them all.

**What we do now.**
- runs10 trains with §54 and §55, which the review backs: from runs9's
  checkpoint 930 widened with `--reset-ball`, with
  `--catch-restart-share 0.5` and runs9's restart states.
- The review's catch test. From each of the 51 catchable battles of §50,
  the run is played to its end twice with runs9's policy: once throwing
  at every chance in that battle, once never throwing in it. The return
  after that battle shows whether a catch helps the rest of the run,
  apart from its own reward. It runs beside runs10, on two cores.
- Not now: ending a run once no living Pokémon is at or under the cap.
  It changes when a run ends, and so its rewards, which is the user's
  call. It would also blur what runs10 shows about the ball reset. A
  narrower reading would end it only once, also, no route before the
  boss can still give a catch: the badge is then out of reach, as after
  a wipe.
- Next: an existence proof, one run that takes Roark's badge under the
  rules with the agent's own actions. Without items in battle, Roark's
  team may be out of reach at 16. Whether items come first is the
  user's call.

| Issue | Cause | Resolution |
|---|---|---|
| Five changes for catching failed the same way | Each priced the throw, but the agent almost never tries one, and a catch does nothing for the run yet | runs10 with §54's reset and restarts; the catch test measures what a catch does for the rest of a run |
| No run has shown the badge is possible here | No run has fought Roark | Open: an existence proof, after the user's call on items |
| Roark's team may be out of reach without items | The agent has no item action in battle | Open: the user's call |
| An over-cap starter earns about 100 before its run ends `no_badge` | The cap is only checked at Roark | Open: the user's call on ending such a run sooner |

## 58. A catch costs the rest of the run about 43 (2026-11-26)

Goal: the second review's test (§57). Does a catch help the rest of a
run, apart from its own reward?

**The test.** From each of the 51 catchable battles of §50, runs9's
checkpoint 930, widened without the ball reset, played the run to its
end twice with the same seed: once throwing at every chance in that
battle, once never throwing in it. All 102 runs finished.

| | Throw | Fight |
|---|---|---|
| Caught in that battle | 45 of 51 | — |
| Return in that battle | 42.7 | 5.9 |
| Return after it | 21.3 | 64.6 |
| Route step reached | 52.6 | 60.2 |
| Ended as a wipe / `no_badge` | 48 / 3 | 38 / 13 |

Throwing came out ahead in 10 of the 51 pairs. Even with the catch
reward of 50, it nets about −6.5 a battle. Of the 45 pairs with a catch,
16 runs died within 3 route steps of it after throwing, against 3 after
fighting. So, under the current policy, the agent is right not to catch.

**Why.** Two of those runs, replayed decision by decision:
- Route 201 (step 3). Throwing took several turns, so Chimchar left the
  battle at 10 HP, and the route walked on into more wild battles with
  no heal. Chimchar fainted two battles later, and the caught Zigzagoon
  lost the next one.
- Route 203 (step 44). The starter won a trainer battle with most of its
  HP. At the next Pokémon Center, the agent left it, a level-22
  Monferno, in the PC (it chose "leave" at 25% odds) and took only the
  level-5 Chingling. The next trainer's level-10 Eevee won in one turn.

A lone starter is never asked at the PC, so these choices only come up
after a catch, and the policy has rarely made them. §50's party HP after
throwing (87%) also counted the caught Pokémon's full HP, so it
understated what throwing costs the starter.

**runs10's first 62 updates.** From update 931 to 992, over 921 runs:
- Throw odds were 9.6% at first and 2% to 3% from update 939 on: 138
  throws in 4,005 chances (3.45%), against runs9's 0.5%.
- 46 catches in 1,784 battles with a chance. `ball_adv` averaged −0.55
  and was above 0 in 18 of 44 updates.
- The starter was left in the PC 16 times in 281 choices, and the lead
  changed twice in 130. No caught Pokémon passed level 12, almost none
  was alive at a run's end, and no run fought Roark.
- Fresh runs wiped 92% of the time, restarts 69%, and catch restarts 73%.
  43 of the 443 restart states are tagged, and 13 hold a caught Pokémon.

runs10 was stopped at update 992 to give the test the whole machine,
but the test had already finished on two cores. 2 updates were lost.

| Issue | Cause | Resolution |
|---|---|---|
| A catch cost the rest of the run about 43 | Throwing drains the starter and no heal comes before the next battles; and the PC choice, only asked after a catch, sometimes leaves the starter behind | Open: the user's call on healing after a draining battle; runs10 keeps training the PC choice |
| §50's party HP after throwing understated its cost | It counted the caught Pokémon's full HP | The replays check the starter's own HP |
| runs10's throw odds fell from 10% to 2% | Under the current policy, a throw nets about −6.5 a battle | Open: as above |
| runs10 was stopped for the test after the test had finished | Its progress wasn't checked first | 2 updates lost; runs10 resumes from checkpoint 990 |

## 59. A scripted player, and three route bugs it found (2026-11-27)

Goal: the second review's existence proof (§57). Can a player with
fixed rules take Roark's badge, using only the agent's actions?

**The player.** `scripts/scripted_run.py` acts only through
`RunEnv.step`, and reads the game to decide. Its rules:
- Moves: a sure knockout with the most accurate move, else the highest
  expected damage.
- Catching: at a catchable wild battle, weaken the foe to half its HP
  (or put it to sleep, or paralyze it), then throw up to 6 times. It
  stops while its own Pokémon is under 55% HP.
- Experience: on a battle's first turn, the strongest healthy Pokémon
  goes in, so the weak lead still shares the experience.
- Switching: a Pokémon under 30% HP that can't finish the foe gives way
  to a healthy one with a better matchup.
- PC: take everyone. The weakest Pokémon under the cap leads, except on
  Roark's trip, where the strongest does.

**Runs.** 17 runs: three starters, seeds 0 to 4, over five versions of
the rules. All 17 wiped, and none reached Roark.

| Furthest route step | Runs | Where |
|---|---|---|
| 3 | 2 | Route 201: a wild Zigzagoon, against Turtwig |
| 10 | 4 | The grind: a wild Burmy, 3 of them against Turtwig |
| 11 | 6 | Tristan (3) and Natalie (3) |
| 25 | 2 | A Jubilife clown |
| 38 | 2 | Barry's second battle |
| 46 | 1 | Diana, in the Oreburgh Gate |

**How the runs ended.**
- Burmy knows Leech Life, which is super effective on Turtwig, so it
  heals by more than Tackle takes off. Turtwig lost 12 HP a turn while
  Burmy stayed at full HP.
- Tristan's three level-5s use Sand-Attack and Mud-Slap. A lone
  level-11 Piplup met him at 27 to 35 of its 35 HP and still lost.
  Natalie was fought just after Tristan, with no heal between: in two
  of her wins the party was at 6 HP or 2 HP.
- Further on, a lone level-15 Burmy that only knew Leech Life lost to
  Barry's six. A level-22 Monferno at full HP lost to Diana's Hypnosis,
  Lovely Kiss and Destiny Bond. Without items in battle, sleep has no
  answer.
- Caught Pokémon rarely lasted. Route 201's walk (step 3) has no heal
  trip, so a Zigzagoon weakened for the catch walks on to Sandgem
  hurt. A Burmy caught on Route 202 reached levels 11 to 15 in some
  runs.
- The starter passes the cap of 16 on Route 203. A run with no caught
  Pokémon alive at or under 16 would end as `no_badge` at Roark.

**Three route bugs.** Four of runs10's step-11 restart states were each
saved at Tristan's battle. After it, the scripted player went to heal
each time, and met Natalie on the way, at 8 to 15 of its 33 to 35 HP.
The ROM's sight tiles (`fieldmap.sight`) show why. Tristan stands at
(166, 813) and looks down to z 818. Natalie stands at (181, 818) and
looks down to (181, 822).
1. `SANDGEM_HEAL`'s way from north of the first ledge crosses Natalie's
   sight. So after Tristan, the party walked into her on the way to
   heal. That is the scripted runs' "Natalie just after Tristan".
2. A restart plays its saved battle, then the walk it interrupted, from
   the walk's start. It skipped the walk's heal check after a battle,
   so a party under half its HP walked on unhealed.
3. The grind stopped as soon as a Pokémon reached level 11, before its
   heal check. So a fresh run met Tristan, on the next walk, still hurt
   from the grind.

All three break the route's own rule that each trainer is met healed.
They are bugs, not new heals: the open question of healing after a
draining battle (§58) is still the user's call. The fixes:
- Steps 11 and 12 heal by `ROUTE202_HEAL`: back to the grind's grass
  first, which no trainer sees, then to Sandgem.
- After a restart's saved battle, a walk runs its heal check, as it
  does after its own battles.
- The grind's heal check comes before its level check, so the grind
  ends healed.

A test covers each, and each test fails on the old route code and
passes on the new. Restart states saved at steps 11 and 12 have the old
action, so `_load_restart` drops them.

runs10 was stopped at update 1010, just after its checkpoint. runs11
trains from that checkpoint with these fixes, runs10's flags and a copy
of its restart states.

**What the runs say.** No fixed rules got past step 46, and Roark's fight
was never tested. Beyond the bugs, three things look like limits of the
rules and actions rather than of the method. The user decides each:
- No items in battle, so sleep, confusion and Destiny Bond have no
  answer (roadmap step 5).
- The cap: a caught Pokémon has to survive and grow to about 16 while
  the starter is benched.
- No heal after a draining catch on Route 201 (§58).

| Issue | Cause | Resolution |
|---|---|---|
| No scripted run got past step 46 of 71 | Kaizo's trainers beat a lone Pokémon, and a catch rarely lives to grow | Open: the user's calls on items in battle, the cap, and healing after a catch |
| A restart walked on hurt after its saved battle | `play()` replayed the battle, then the walk, but not the walk's heal check | The heal check runs after the saved battle too; a test |
| Natalie was fought hurt, just after Tristan | `SANDGEM_HEAL`'s way from north of the first ledge crosses her sight | Steps 11 and 12 heal by `ROUTE202_HEAL`, through the grass first; a test |
| A fresh run met Tristan hurt from the grind | The grind checked the level before its heal check | The heal check comes first; the grind test checks the HP |
| The probes first seemed to show Tristan met on the way to heal | They printed the battle that ended with the tile where the next one began | The ROM's sight tiles settled which trainer sees where |
| The first report put the step-11 losses on low HP at Tristan | It mixed up Tristan's battle and Natalie's | Checked against the logs: in the fresh runs, Tristan was met at 27 to 35 of 35 HP, and Natalie hurt |
| The scripted trace named the next battle's foes | It read them after the step, when a battle that followed at once was already up | It reads them from the ended battle's last decision |

## 60. The whole team trains, and what the scripted player met next (2026-11-27)

Goal: a third review of the open calls in §59. The user's calls, from it:
- Items in battle stay banned. The README's rules already say so, and
  held items still work.
- Ending a run that can't meet the cap comes later, once a team can
  live to Roark. Alone, it would take away the one plan that works now,
  a lone starter, and leave nothing.
- No heal after a Route 201 catch. The agent can learn that Route 201
  is a bad place to throw.
- First, the review's fourth question: let the whole team train up, as
  a player grinds each Pokémon to the cap before a boss. Then rerun the
  scripted player until it takes the badge, and only then train.

**The change.**
- The grind went on until any one Pokémon reached its level, so a catch
  met the route's trainers far under them. It now goes on until every
  party Pokémon has the level, within the same 60 battles. A caught
  Pokémon still gains experience only in battles it is sent into.
- A second grind, at step 71 of 80, after the gym's trainers. From
  Roark's tile, the gym's steps back to the door, then Oreburgh Mine
  B1F. It has no trainers, and its wild Pokémon are at level 10. The
  grind goes on until every party Pokémon is at Roark's cap of 16, with
  heal trips to Oreburgh's Pokémon Center, and then the steps go back
  up. It comes after the gym's trainers because their ten Pokémon at 11
  to 15 would push a team already at 16 over the cap. The mend before
  Roark is unchanged: it still leaves a Pokémon over the cap in the PC.
- Two tests. In one, a Garchomp over the level ended the old grind at
  once, and the new grind fights until the Gyarados under it gets
  there. The other walks the new steps from milestone 15: out to the
  mine, a Gyarados one win from 16, then back to Roark with a Garchomp
  over the cap left in the PC.

runs11 was stopped at update 1050, after its checkpoint, because the
route it trained on had changed.

**The scripted player on the new route.** 15 runs: three starters, seeds
0 to 4. 14 wiped and one was stopped for heat at step 14. None got past
step 38, Barry's second battle, so none reached the mine grind.

| Step | Runs | What ended it |
|---|---|---|
| 3 | 1 | Route 201: a level-6 Turtwig lost to a wild Zigzagoon |
| 10 | 5 | Route 202's grind: a wild Burmy beat Turtwig in four runs. In one, a Sentret beat Chimchar, and later another beat the Burmy left |
| 13 | 1 | Natalie, against a lone Burmy at 11 |
| 15 | 3 | Logan, against a lone Piplup at 13 (twice) and a lone Burmy at 12 |
| 25 | 1 | Clown Moe, against a lone Burmy at 13 |
| 38 | 3 | Barry's second battle, against a lone Prinplup at 16 to 17 |

**Why.**
- Turtwig can't beat a wild Burmy. Leech Life is super effective and
  heals Burmy by more than Tackle takes off. A player would run, but
  the agent's actions have no Run.
- A grind with a weak catch now lasts longer, and each Kaizo wild
  battle is a risk. In the Chimchar runs the grind went on for 19 to 57
  battles. And the scripted player leads with its weakest Pokémon: a
  level-4 Zigzagoon from Route 201 died leading against Burmy in three
  Turtwig runs.
- Logan's Kricketot knows Bide, which hits back with double the damage
  it takes. The scripted player kept attacking into it.
- Barry's second team has six Pokémon at 9 and 10, with Fake Out,
  U-turn, a Choice Band, two Expert Belts, Thunder Wave, and a Turtwig
  with Razor Leaf. It beat a lone level-17 Prinplup from full HP.
- The team grind did what it is for once. In a Chimchar run, the
  Zigzagoon caught on Route 201 went from level 4 to 11 in Route 202's
  grind, before the run was stopped for heat.

**Heat.** 15 runs at once took the CPU over 99 °C for more than 30
seconds, and the watch stopped them. Two runs ignored the stop: a
process started in the background from a script ignores SIGINT. They
were stopped with SIGTERM. The full test suite, on one core, was then
stopped the same way: with no project process running, the CPU was
already at 91 to 92 °C.

**The scripted player's rules, changed.** Two of the deaths came from its
own rules, not the route:
- On the first turn of a catchable battle, the catch rule came before
  the switch-in. So a weak lead wore the foe down alone. Route 201's
  Zigzagoon at 4 did so against Burmy, and died. The switch-in now comes
  first.
- Bide: while the foe stores energy (`statusVolatile` bits 8 and 9),
  it uses a status move, unless an attack knocks the foe out.
These changes haven't been run yet. The agent's own observation shows
confusion, binding, Substitute and Curse, but not Bide.

**The bag.** From Route 201 on, every run carries 10 Rare Candies and a
Chilan Berry, and a White Herb by Barry's second battle (read from
runs11's restart states). The rules ban items in battle, not outside it,
and held items work. But the agent has no action that uses an item
outside battle, so none of these has ever been used. Ten Rare Candies
would take a level-5 catch to 15.

**What is next.** The scripted player hasn't taken the badge. The review
named held items as the next thing to look at. The runs point at these:
- Run, in wild battles. It is within the rules, and it is what a player
  does against a Burmy. It would add an action to the agent's.
- The bag outside battle: Rare Candies and held items. It would add a
  decision, as the PC did.
- The scripted player's own rules: Bide, and switching a weak catch in
  rather than leading with it.

| Issue | Cause | Resolution |
|---|---|---|
| A caught Pokémon met the route's trainers far under them | The grind stopped when any one Pokémon reached its level | It stops when every party Pokémon has the level; a test |
| No grind before Roark | The route had one grind, on Route 202 | A grind in Oreburgh Mine B1F after the gym's trainers, to Roark's cap; a test |
| No scripted run got past step 38 of 80 | Deaths before the grinds could help: Turtwig against Burmy with no Run, Bide, and Barry's second team against a lone Pokémon | Open: Run, the bag outside battle, the scripted rules |
| 10 Rare Candies have gone unused in every run | The agent has no action for the bag outside battle | Open: a bag decision, the user's call |
| 15 runs at once took the CPU over 99 °C | Every core busy | The watch stopped them; run fewer at once |
| Two runs ignored the stop | A process started in the background from a script ignores SIGINT | Stopped with SIGTERM |
| A weak lead wore down a catch alone, and died | The catch rule came before the first turn's switch-in | The switch-in comes first; not yet rerun |
| The scripted player attacked into Bide | It had no rule for it | A status move while the foe stores energy; not yet rerun |
| The full suite couldn't run within the heat limit | The CPU was at 91 to 92 °C before it started: a system process held one core at full speed | Once it was restarted, the suite ran within the limit, paused by a heat governor when needed (§61) |

## 61. Run, Rare Candies and held items (2026-11-27)

Goal: the user's calls on §60's open questions. "yes the agent should be
able to run from wild battles". Rare Candies and held items are "fair
game", but no potions or other healing items. The README's rules now say
so.

**Run.** Action 10 taps RUN on the action menu, at (128, 176). It is
masked outside a wild battle, at a forced switch, and when the active
Pokémon is trapped, by the same rule that stops a switch. A run that gets
away ends the battle as FLED, with no reward. The route's first encounter
is used up all the same: `run.encounter` marks it when the battle starts.
A run that fails costs the turn. The observation gains a `wild` value.

**The bag.** After each nurse visit, the agent is asked:
- A Rare Candy for which party Pokémon, or none (action 6). Asked again
  after each candy, until it picks none or the candies run out.
- Then each held item in the bag, the Chilan Berry and the White Herb, for
  which party Pokémon, or none. These are the only two a run gets before
  Roark. Giving one to a Pokémon that holds the other swaps them.

A fainted Pokémon is no choice, nor a candy for one at level 100. The cap
isn't masked: a candy can take a Pokémon over it. The observation shows
the cap, the candies left, the item asked about, and which of the two
items each party Pokémon holds.

`src/bag.py` works the field menu, the bag and the party screen by
buttons alone, as a player does, with no writes to the game. The screens
keep no address that reads live, so it tells them apart by their pixels,
and it checks the result in RAM: the bag's counts, and the party's level,
species and held item. A candy's new move is answered by the route's
`move_to_forget` rule, and an evolution is left to play. A subagent wrote
it from probes; its eight tests cover a candy, a fifth move both ways, an
evolution, a level-100 Pokémon, a missing item, and a swap of held items.

**Checkpoints.** `ppo.widen_checkpoint` now adds actions too. Each new row
of the policy's output layer starts as `reset_action` draws it, with its
logit near 0. Where a new action is masked, the policy plays exactly as
before. `scripts/widen_checkpoint.py` widens both the observation and the
actions.

The full suite passed, 194 tests. It ran one process at a time under a
heat governor that pauses it at 97 °C and resumes it at 93, since
parallel runs took the CPU over 99 °C even while paused.

**The scripted player** got the same tools:
- Run, in a wild battle, from a foe that would knock the active Pokémon
  out before it could knock the foe out, once no catch is under way.
- A Rare Candy for the weakest Pokémon under the cap, while it is 4 or
  more levels under the strongest. At the boss's PC, candies for the
  weakest under the cap until all reach it.
- A held item for the weakest Pokémon that holds none.

| Issue | Cause | Resolution |
|---|---|---|
| The agent couldn't run from a wild battle | No action for RUN | Action 10, masked outside wild battles and when trapped; tests |
| Every run carried 10 Rare Candies and two held items it couldn't use | No decision for the bag outside battle | A candy choice and a hold choice after each nurse visit, worked by the bag's menus (`bag.py`); tests |
| A checkpoint from before couldn't load | The output layer has one more action, and the observation more values | `widen_checkpoint` adds actions; a test |
| Tests stepped through heals expecting the run to end | A heal now asks about the bag | Their helpers answer the bag with none. One test answered every choice but a battle's with action 0: at a bag choice that fed the starter candies to the grind's level, and the route ended |
| The bag's cursor has no live address | The saved cursor in RAM changes only once the bag closes | `bag.py` reads the screens' pixels, and reaches an item by pressing Up past the top, then Down |
