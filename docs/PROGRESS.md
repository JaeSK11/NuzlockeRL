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
