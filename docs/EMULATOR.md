# Emulator: PyNDS

[unexploredtest/PyNDS](https://github.com/unexploredtest/PyNDS) is a
PyBoy-style Python interface to the [NooDS](https://github.com/Hydr8gon/NooDS)
Nintendo DS emulator, built for RL and bots. This project uses it **built from
source at commit 5a40a52**. The pip wheel (0.0.4) can't read memory.

## Why PyNDS

PyBoy is Game Boy only. Among DS options, PyNDS gives frames, buttons, touch,
memory reads and writes, and save states directly from Python, with an API
modeled on PyBoy. That makes the reference projects' design (a Gym env over
an emulator with RAM-based rewards) easy to port. py-desmume is the fallback.
See [PROGRESS.md](PROGRESS.md#2-choosing-the-game-and-emulator) for the full
comparison.

## Install

`scripts/setup_env.sh` does all of this:

```bash
sudo apt install libportaudio2
python3 -m venv ~/venvs/nuzlockerl
~/venvs/nuzlockerl/bin/pip install numpy pillow pytest cmake ninja nanobind setuptools wheel
git clone https://github.com/unexploredtest/PyNDS.git && cd PyNDS
git checkout 5a40a52 && git submodule update --init --recursive
PATH=~/venvs/nuzlockerl/bin:$PATH ~/venvs/nuzlockerl/bin/pip install --no-build-isolation .
```

## Test results on the Kaizo ROM (2026-11-11, 32-core machine)

| Check | Result |
|---|---|
| Boots headless without BIOS or firmware files | ✅ |
| Speed, one process, `tick()` with frame copy | ~650–1000 fps (11–17× real time) |
| Save state | ~5.5 MB, ~2.7 ms to load (file-based; use tmpfs for training) |
| Buttons (A, B, X, Y, L, R, Start, Select, D-pad) | ✅ |
| Touch | ✅ Required: the intro and box screens use touch |
| Memory reads, pip 0.0.4 | ❌ Every address returns 0 |
| Memory reads, source build | ✅ 100k `read_u32` calls in ~11 ms |

## API notes

```python
import pynds
nds = pynds.PyNDS("roms/plat-kaizo-nightmare-update-final.nds")
nds.tick()                                    # advance one frame (and consume it)
top, bottom = nds.get_frame()                 # (192, 256, 4) uint8 each
nds.button.press_key("a"); nds.button.release_key("a")
nds.button.set_touch(x, y); nds.button.touch(); nds.button.release_touch()
nds.memory.read_u32(False, addr)              # arm7=False → ARM9 bus
nds.save_state_to_file(p); nds.load_state_from_file(p)
```

- **Always use `tick()`.** `_nds.run_until_frame()` returns immediately until
  the previous frame is consumed with `get_frame()`, so benchmarks that call
  it alone measure nothing.
- **Audio:** `import pynds` needs PortAudio. Sound only plays after
  `nds.open_audio()`; otherwise there's no extra cost. For machines without
  PortAudio, `emu_tests/stub/sounddevice.py` is a stand-in
  (`PYTHONPATH=emu_tests/stub`).
- For headless runs, set `SDL_VIDEODRIVER=dummy`. pygame is imported.

## Input timing (important for the action space)

- Taps closer than **~25–30 frames** apart are dropped during text and
  screen fades. The TV scene in the intro looked frozen until presses were
  spaced out.
- Some menus need B **held** for ~20 frames.
- So an RL action should be a timed macro, "hold for N frames, then wait M
  frames", or better, an action submitted only when a "waiting for input"
  signal is set (see the [roadmap](ROADMAP.md)).

## Compatibility with known Platinum Kaizo emulator problems

- **"Only Start works in Twinleaf"** (Reddit, on melonDS and DeSmuME): not
  reproduced in PyNDS. All buttons and touch work there.
- **"melonDS cores can't save"** (developer FAQ): doesn't matter here,
  because emulator save states are used, not in-game saves. The hack's
  non-retail game code (`JAK7`) is the likely cause of emulator save-type
  detection problems.

## Driver

`src/drive.py` (wrapped by `src/d`) runs scripted inputs from a save state
and writes a new state plus a screenshot:

```bash
src/d milestones/03_barry1_battle_turn1 test "a w40 a w600 battle party"
```

Tokens: `a b x y l r start select up down left right`, `a*20`,
`hold:b:20`, `w120` (wait frames), `t128,81` (touch), `shot:name`,
`party`, `battle`.
