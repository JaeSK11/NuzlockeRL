# emu_tests

The first PyNDS smoke tests, kept for reference. See docs/EMULATOR.md.

- `smoke.py ROM OUTDIR`: boots, measures fps, saves a state, times state loads
- `touch.py ROM [STATE]`: tests touch input and memory reads
- `memtest.py ROM`: checks memory reads (game header, main RAM, read speed)
- `stub/sounddevice.py`: stand-in for machines without PortAudio
  (`PYTHONPATH=emu_tests/stub`)

Run headless with `SDL_VIDEODRIVER=dummy`.
