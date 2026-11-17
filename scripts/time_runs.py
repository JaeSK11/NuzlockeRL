"""Time runs played with random actions (NEXT_PHASE step 3.9): what training on runs will cost.

  python scripts/time_runs.py [--runs 100] [--envs 14] [--out runs/timing]

Every decision takes a random allowed action, on an asynchronous pool of RunEnv workers. Each
finished run is appended to OUT/runs.jsonl; the totals are printed at the end: runs per hour,
decisions and battles per run, how runs end and how far along the route they get. Stops if the
CPU stays too hot (src/thermal.py).
"""
import argparse
import collections
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import gen4  # noqa: F401  (fixes the DS clock before any emulator starts)
from pool import AsyncEnvPool
from thermal import ThermalGuard


def make_env():
    import run_env
    return run_env.RunEnv()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=100)
    ap.add_argument("--envs", type=int, default=14)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=os.path.join(ROOT, "runs/timing"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    rng = np.random.default_rng(a.seed)
    guard = ThermalGuard()
    guard.start()
    runs, decisions, t0 = [], 0, time.time()
    with AsyncEnvPool([make_env] * a.envs, seed=a.seed, timeout=900) as pool, \
            open(os.path.join(a.out, "runs.jsonl"), "a") as log:
        while len(runs) < a.runs:
            if guard.tripped.is_set():
                sys.exit(f"stopped: the CPU stayed above {guard.max_temp} °C (peak {guard.peak:.0f} °C)")
            batch = pool.recv()
            for info in batch.final_infos:
                if info is not None:
                    run = {k: info[k] for k in ("end", "decisions", "run_return", "route_step", "route_steps",
                                                "caught", "dead", "routes", "location")}
                    run["battles"] = len(info["battles"])
                    run["trainers"] = [b["trainer"] for b in info["battles"] if b["trainer"] and b["outcome"] == "WON"]
                    run["error"] = info.get("error")
                    runs.append(run)
                    log.write(json.dumps(run) + "\n")
                    print(f"run {len(runs)}: {run['end']} at route step {run['route_step']}/{run['route_steps']}, "
                          f"{run['decisions']} decisions, {run['battles']} battles, {time.time() - t0:.0f} s", flush=True)
            decisions += len(batch)
            pool.send(batch.env_ids, [rng.choice(np.flatnonzero(m)) for m in batch.action_masks])
    hours = (time.time() - t0) / 3600
    steps = [r["route_step"] for r in runs]
    print(f"\n{len(runs)} runs in {hours * 60:.1f} min on {a.envs} envs: {len(runs) / hours:.0f} runs/h, "
          f"{decisions / hours / 3600:.1f} decisions/s; CPU peak {guard.peak:.0f} °C")
    print(f"per run: {np.mean([r['decisions'] for r in runs]):.1f} decisions, {np.mean([r['battles'] for r in runs]):.1f} battles "
          f"(median {np.median([r['battles'] for r in runs]):.0f})")
    print("ends:", dict(collections.Counter(r["end"] for r in runs)))
    print("route step reached: median", np.median(steps), "max", max(steps), "of", runs[0]["route_steps"])
    print("trainers beaten:", dict(collections.Counter(t for r in runs for t in r["trainers"])))
    print("errors:", [r["error"] for r in runs if r["error"]][:5])


if __name__ == "__main__":
    main()
