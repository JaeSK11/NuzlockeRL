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
