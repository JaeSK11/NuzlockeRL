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
| After a trainer battle the wait runs to its 2,000-frame limit | The game records a trainer battle's result later, after the trainer's closing text | Open: wild battles only for now; needs a better end signal before trainer battles |
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
| The faint penalty doesn't separate fodder from the ace in a balanced team | Strength is the stat total over the team's highest, and the Chimchar team's totals are within 14% of each other | Open: a gauntlet env, where a faint costs options in later battles (roadmap step 2), is the real fix |
