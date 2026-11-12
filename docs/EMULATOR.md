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
for p in /path/to/nuzlockeRL/patches/noods-*.patch; do git -C externals/NooDS apply "$p"; done
PATH=~/venvs/nuzlockerl/bin:$PATH ~/venvs/nuzlockerl/bin/pip install --no-build-isolation .
```

### The fixed clock

NooDS sets the DS clock from the host's local time, and Platinum's
overworld changes with the time of day. The same walk from
`04_after_barry1_home.state` ended two tiles apart at noon and at night,
so tests and generated states depended on the hour and the time zone.

`patches/noods-fixed-rtc.patch` makes NooDS read the time from
`NOODS_RTC_EPOCH` (seconds since 1970, read as UTC) when it is set, and
the clock then stays at that time. `src/gen4.py` sets it to Wednesday
2026-11-11 22:00:00, night in Platinum, unless it is already set. Every
module that creates an emulator imports `gen4` first, and spawned workers
inherit it. `tests/test_gen4.py::test_clock_is_fixed` fails on a build
without the patch.

### The state-load fix

NooDS restores every component from a save state, but it picks the
function that runs the two CPUs before it restores their halt flags. That
choice followed the CPUs from before the load. If the ARM7 was halted then
and running in the saved state, the ARM7 stayed stopped after the load. The
ARM7 reads the touchscreen, so the game ignored every tap.

A battle that just ended often leaves the ARM7 halted, so resetting the env
after a WON or LOST hit this. On one generated state, 9 of 10 resets after
a finished battle ended STUCK, with the action menu up and no tap taking.
`patches/noods-load-state-run-function.patch` picks the run function again
once every component is loaded. After it, a load gives the same RAM, byte
for byte, whatever ran before.
`tests/test_battle_env.py::test_a_state_loads_the_same_whatever_ran_before`
fails without the patch.

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

## Parallel speed on an 8-core CPU (Ryzen 7 7840U, 2026-11-11)

The 7840U has 8 cores and 16 threads. Each run loads
`03_barry1_battle_turn1.state` and calls `tick()` 3000 times per process.
The table gives total fps across all processes, as the range of 3
interleaved runs.

| Processes | Default render threads | Render threads off |
|---|---|---|
| 1 | 590–597 | 475–484 |
| 8 | 2720–2763 | 2968–2986 |
| 16 | 1693–1780 | 3386–3407 |

NooDS draws on extra threads by default (`threaded2D` and `threaded3D`),
so each process uses about 1.7 cores. With more threads than cores, the
render wait loops spin on `std::this_thread::yield()`, and the total at 16
processes falls below the total at 8. With render threads off, each process
uses exactly one core. Frames and RAM are byte-identical either way.

To run many emulators in parallel, turn the render threads off before you
create each emulator:

```python
pynds.config.set_threaded_2d(0)
pynds.config.set_threaded_3d(0)
nds = pynds.PyNDS(rom)
```

Keep the defaults for a single process, such as `src/drive.py`.

Throughput stops rising at 16 processes, one per hardware thread. Runs at
20, 24, and 32 processes gave 3031–3369 fps, inside the run-to-run
spread at 16. That total is about 57× real time. Each process uses about
95 MiB of RAM (proportional set size), so 16 processes need about 1.5 GiB.

## How many emulators to run

`scripts/rollout.py` and `scripts/train_ppo.py` default to the number of
hardware threads minus 2. Throughput stops rising at one emulator per
hardware thread, and the main process needs some room. Pass `--envs` to
change it.

Both use `src/pool.py`, which steps each env as soon as its result arrives
instead of waiting for the slowest battle. On the 7840U with 14 envs it
made 1.30× more decisions per second than gymnasium's `AsyncVectorEnv`
(median of 3 runs each, random policy, Barry 1 and the wild battle):

| Stepping | Decisions/s | Frames/s | Busy cores |
|---|---|---|---|
| `AsyncVectorEnv`, lockstep | 6.02 | 2,206 | 8.3 |
| `src/pool.py` | 7.83 | 2,862 | 13.2 |

The gain is below 13.2/8.3 because 14 emulators share 8 physical cores, so
each runs fewer frames per busy second. `rollout.py --pool gym` runs the
lockstep path for comparison.

Each script stops if the hottest CPU sensor stays above `--max-temp`
(default 99 °C) for more than `--hot-seconds` (default 30 s). It reads the
`k10temp` or `zenpower` sensors (AMD) and `coretemp` (Intel). Without one,
as in many containers and VMs, it prints a warning and runs unguarded.

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
- Battle menus have two input modes, touch and buttons. In touch mode,
  the first button press only shows the red cursor and selects nothing,
  so from `03_barry1_battle_turn1.state` a move takes three A presses. A
  tap selects in either mode. From the "What will X do?" prompt, a tap on
  **FIGHT** at (128, 87) and then a tap on the first move at (64, 40) uses
  that move. Use touch only. Then each menu takes one tap, whatever mode
  the state was saved in, and the choice doesn't depend on where the
  cursor was left. The mode byte is listed in [RAM_MAP.md](RAM_MAP.md).
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
