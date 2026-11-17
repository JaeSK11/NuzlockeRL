"""Find each map's walkable graph by walking it (overworld.explore), several maps at a time.

  python scripts/explore_maps.py [--starts states/walk/start] [--out states/walk] [--jobs 6]

Each start state is a state where the player can walk on one map, with that map's trainers
already beaten, so their sight doesn't cut the walk short. Writes OUT/<map id>.json, one
WalkGraph per map. Stops if the CPU stays too hot (src/thermal.py).
"""
import argparse
import glob
import json
import multiprocessing as mp
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import gen4  # noqa: F401  (fixes the DS clock before any emulator starts)
from thermal import ThermalGuard

ROM = os.environ.get("NUZLOCKERL_ROM", os.path.join(ROOT, "roms/plat-kaizo-nightmare-update-final.nds"))


def explore_one(args):
    start, out = args
    import pynds
    import overworld
    t = time.time()
    nds = pynds.PyNDS(ROM)
    work = os.path.join(out, "work", os.path.basename(start).removesuffix(".state"))
    g = overworld.explore(nds, start, work)
    with open(os.path.join(out, f"{g.map_id}.json"), "w") as f:
        json.dump(g.to_json(), f)
    nodes = set(g.edges) | {n for e in g.edges.values() for n in e.values()}
    return (f"{os.path.basename(start)}: map {g.map_id}, {len(nodes)} tiles, "
            f"{sum(len(e) for e in g.exits.values())} exits, {sum(len(s) for s in g.scenes.values())} scene steps, "
            f"{time.time() - t:.0f} s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--starts", default=os.path.join(ROOT, "states/walk/start"))
    ap.add_argument("--out", default=os.path.join(ROOT, "states/walk"))
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()
    starts = sorted(glob.glob(os.path.join(a.starts, "*.state")))
    os.makedirs(a.out, exist_ok=True)
    guard = ThermalGuard()
    guard.start()
    with mp.Pool(a.jobs) as pool:
        pending = [pool.apply_async(explore_one, ((s, a.out),)) for s in starts]
        while pending:
            if guard.tripped.is_set():
                pool.terminate()
                sys.exit(f"stopped: the CPU stayed above {guard.max_temp} °C (peak {guard.peak:.0f} °C)")
            for r in [r for r in pending if r.ready()]:
                print(r.get(), flush=True)
                pending.remove(r)
            time.sleep(1)
    print(f"done; CPU peak {guard.peak:.0f} °C")


if __name__ == "__main__":
    main()
