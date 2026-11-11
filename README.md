# NuzlockeRL

Reinforcement learning for Pokémon Platinum Kaizo, played under Hardcore
Nuzlocke rules: a fainted Pokémon is gone for good, you may only catch the
first encounter on each route, and the hack's level caps apply.

The plan follows the only public attempt we know of, KP Labs' Emerald Kaizo
agent: **learn battles first**, starting each battle from an emulator save
state, then add encounters, team building and overworld movement later.

## Status (2026-11-11)

| Area | State |
|---|---|
| DS emulator from Python | ✅ PyNDS (NooDS core), built from source. Headless, ~650–1000 fps per process |
| Inputs (buttons and touch) | ✅ All tested on the Kaizo ROM |
| Save states | ✅ ~5.5 MB, ~2.7 ms to load |
| Party and battle RAM | ✅ Pointer chain and Gen 4 decryption verified on the hack, covered by tests |
| "Waiting for input", battle result, effects, weather | ⏳ Next. See [docs/ROADMAP.md](docs/ROADMAP.md) |
| Gym environment and RL training | ⏳ Not started |

## Documentation

| Doc | Contents |
|---|---|
| [docs/PROGRESS.md](docs/PROGRESS.md) | What has been done so far, in order, and why each decision was made |
| [docs/ROADMAP.md](docs/ROADMAP.md) | What to do next, in priority order |
| [docs/RAM_MAP.md](docs/RAM_MAP.md) | Verified memory addresses, the Gen 4 decryption, and caveats |
| [docs/EMULATOR.md](docs/EMULATOR.md) | PyNDS setup, test results, input timing, emulator quirks |
| [docs/REFERENCES.md](docs/REFERENCES.md) | Papers, repositories, libraries and videos used, and why |

## Layout

```
src/gen4.py         Gen 4 RAM layout + Pokémon decryption (party, battle, scan)
src/drive.py        Scripted input driver for exploring the game and making save states
src/d               Shell wrapper for drive.py
tests/              Regression tests against milestone save states
emu_tests/          Original PyNDS smoke tests (boot, speed, touch, memory)
scripts/            Environment setup and reference fetching
docs/               Documentation
```

Not in git, for copyright reasons or because they belong to someone else:
`roms/` (the game), `states/` (save states contain game memory), `repos/`
(third-party code; see `scripts/fetch_references.sh`), `papers/` (PDFs;
fetched by the same script), and game screenshots.

## Setup

Requires Linux, Python 3.12, a C++20 compiler and git.

```bash
sudo apt install libportaudio2          # pynds imports sounddevice
scripts/setup_env.sh                    # venv at ~/venvs/nuzlockerl + PyNDS built from source
scripts/fetch_references.sh             # optional: reference repos and papers
```

Supply your own legally obtained copy of Pokémon Platinum, apply the
Platinum Kaizo patch, and put it at
`roms/plat-kaizo-nightmare-update-final.nds`. The build used for development
has SHA-1 `e8d13c6504406324a4a9ea9daf8d6bd409f8a644`; RAM addresses were
verified against it.

```bash
~/venvs/nuzlockerl/bin/python -m pytest -q tests   # skipped without the ROM/states
src/d - mystate "w900 a*10 w120"                   # boot, press A, save state + screenshot
```

## Hack notes

Pokémon Platinum Kaizo by SinisterHoodedFigure, Final (Nightmare Update,
2026-04-16). Built-in Hardcore Nuzlocke soft level caps (a Gym Leader or Barry
refuses to battle if any party Pokémon is over the cap): Roark 16,
Gardenia 28, Fantina 38, Barry #3 42, Maylene 47, Wake 54, Barry #5 63,
Byron 65, Candice 74, Volkner 84, Elite Four 100.

## License

[GPL-3.0](LICENSE). This matches PyNDS, NooDS and NDS-Ironmon-Tracker (the
source of the RAM offsets), which are all GPL-3.0. Pokémon is © Nintendo /
Creatures Inc. / GAME FREAK inc. No game files are included.
