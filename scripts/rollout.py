"""Random-policy rollout over parallel BattleEnvs, for throughput and sanity checks.

  python scripts/rollout.py [--envs N] [--episodes 200] [--log-dir DIR] [--seed N]
                            [--max-temp 99] [--hot-seconds 30]

--envs defaults to the number of hardware threads minus 2: throughput stops rising at
one emulator per hardware thread, and the main process needs some room.
Each env process logs to its own file in --log-dir (default: a fresh dir under /tmp).
The run stops early if the hottest CPU sensor stays above --max-temp for more than
--hot-seconds.
"""
import argparse, collections, glob, os, sys, tempfile, threading, time
import numpy as np
import gymnasium as gym

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from battle_env import BattleEnv

STATES = [os.path.join(ROOT, "states/milestones", s)
          for s in ("03_barry1_battle_turn1.state", "05_route201_wild_battle.state")]


def make_env(i: int, log_dir: str):
    return lambda: BattleEnv(STATES, log_path=os.path.join(log_dir, f"env{i:02d}.jsonl"))


CPU_SENSORS = ("k10temp", "zenpower", "coretemp")    # AMD, AMD (alternative driver), Intel


class ThermalGuard(threading.Thread):
    """Samples the hottest CPU package sensor once a second. Sets self.tripped once it has
    stayed above max_temp for more than hot_seconds. Does nothing if no sensor is found,
    as in many containers and VMs."""

    def __init__(self, max_temp: float, hot_seconds: float):
        super().__init__(daemon=True)
        self.paths = [os.path.join(os.path.dirname(p), "temp1_input")
                      for p in glob.glob("/sys/class/hwmon/hwmon*/name")
                      if open(p).read().strip() in CPU_SENSORS]
        self.max_temp, self.hot_seconds = max_temp, hot_seconds
        self.peak, self.tripped = 0.0, threading.Event()

    def run(self):
        hot_since = None
        while self.paths and not self.tripped.is_set():
            t = max(int(open(p).read()) for p in self.paths) / 1000
            self.peak = max(self.peak, t)
            hot_since = (hot_since or time.time()) if t > self.max_temp else None
            if hot_since and time.time() - hot_since > self.hot_seconds:
                self.tripped.set()
            time.sleep(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--envs", type=int, default=max(1, (os.cpu_count() or 1) - 2))
    ap.add_argument("--episodes", type=int, default=200)
    ap.add_argument("--log-dir", default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--max-temp", type=float, default=99.0)
    ap.add_argument("--hot-seconds", type=float, default=30.0)
    args = ap.parse_args()
    log_dir = args.log_dir or tempfile.mkdtemp(prefix="nuzlockerl_rollout_")
    os.makedirs(log_dir, exist_ok=True)
    guard = ThermalGuard(args.max_temp, args.hot_seconds)
    if not guard.paths:
        print("no CPU temperature sensor found; running without the thermal guard")
    guard.start()

    t0 = time.time()
    envs = gym.vector.AsyncVectorEnv([make_env(i, log_dir) for i in range(args.envs)])
    rng = np.random.default_rng(args.seed)
    _, infos = envs.reset(seed=args.seed)
    frames = int(infos["frames"].sum())
    outcomes = collections.defaultdict(collections.Counter)
    turns, done = [], 0
    # Default autoreset is next-step: the step after an episode ends resets that env and
    # ignores its action, so it adds frames but no turn and no episode.
    while done < args.episodes and not guard.tripped.is_set():
        masks = infos["action_mask"]
        actions = np.array([rng.choice(np.flatnonzero(m)) for m in masks])
        _, _, term, trunc, infos = envs.step(actions)
        frames += int(infos["frames"][infos["_frames"]].sum())
        for i in np.flatnonzero(term | trunc):
            if done == args.episodes:
                break
            outcomes[os.path.basename(infos["state"][i])][infos["outcome"][i]] += 1
            turns.append(int(infos["turn"][i]))
            done += 1
    wall = time.time() - t0
    envs.close()

    print(f"envs {args.envs}  episodes {done}  wall {wall:.1f}s  {done / wall:.2f} episodes/s  "
          f"{frames / wall:,.0f} emulated frames/s  mean turns {np.mean(turns):.2f}")
    for state, c in sorted(outcomes.items()):
        print(f"  {state}: {dict(c)}")
    print(f"STUCK {sum(c['STUCK'] for c in outcomes.values())}  peak CPU {guard.peak:.0f} C  logs in {log_dir}")
    if guard.tripped.is_set():
        print(f"stopped early: CPU above {args.max_temp:.0f} C for more than {args.hot_seconds:.0f} s")
        sys.exit(1)


if __name__ == "__main__":
    main()
