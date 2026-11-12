"""Random-policy rollout over parallel BattleEnvs, for throughput and sanity checks.

  python scripts/rollout.py [--pool async|gym] [--envs N] [--episodes 200] [--states S ...]
                            [--log-dir DIR] [--seed N] [--max-temp 99] [--hot-seconds 30]

--pool async (default) uses src/pool.py, which acts on whichever envs are ready.
--pool gym uses gymnasium's AsyncVectorEnv, which waits for every env at every step.
--envs defaults to the number of hardware threads minus 2: throughput stops rising at
one emulator per hardware thread, and the main process needs some room.
Each env process logs to its own file in --log-dir (default: a fresh dir under /tmp).
The run stops early if the hottest CPU sensor stays above --max-temp for more than
--hot-seconds.

The clock starts once every env has finished its first reset, so process startup is not
in the rates. "busy cores" is the env processes' CPU time divided by the wall time.
"waiting for a CPU" is the time they were runnable but another process had the core.
The rest of their time they were idle, waiting for an action.
"""
import argparse, collections, functools, os, sys, tempfile, time
import numpy as np
import gymnasium as gym

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from battle_env import BattleEnv
from pool import AsyncEnvPool
from thermal import ThermalGuard

STATES = [os.path.join(ROOT, "states/milestones", s)
          for s in ("03_barry1_battle_turn1.state", "05_route201_wild_battle.state")]
TICKS_PER_SECOND = os.sysconf("SC_CLK_TCK")


def cpu_seconds(pids) -> float:
    """User plus system CPU time the processes have used so far."""
    total = 0
    for pid in pids:
        with open(f"/proc/{pid}/stat") as f:
            fields = f.read().rsplit(")", 1)[1].split()
        total += int(fields[11]) + int(fields[12])
    return total / TICKS_PER_SECOND


def runqueue_seconds(pids) -> float:
    """Time the processes' main threads have spent runnable but waiting for a CPU."""
    total = 0
    for pid in pids:
        with open(f"/proc/{pid}/schedstat") as f:
            total += int(f.read().split()[1])
    return total / 1e9


def clocks(pids) -> tuple:
    return time.time(), cpu_seconds(pids), runqueue_seconds(pids), time.process_time()


class Tally:
    def __init__(self):
        self.decisions = self.frames = 0
        self.outcomes = collections.defaultdict(collections.Counter)
        self.turns = []

    @property
    def episodes(self) -> int:
        return len(self.turns)

    def episode(self, info: dict):
        self.outcomes[os.path.basename(info["state"])][info["outcome"]] += 1
        self.turns.append(int(info["turn"]))


def random_actions(rng, masks) -> np.ndarray:
    return np.array([rng.choice(np.flatnonzero(m)) for m in masks])


def run_gym(env_fns, args, guard, tally):
    envs = gym.vector.AsyncVectorEnv(env_fns)
    rng = np.random.default_rng(args.seed)
    _, infos = envs.reset(seed=args.seed)
    pids = [p.pid for p in envs.processes]
    start = clocks(pids)
    # Default autoreset is next-step: the step after an episode ends resets that env and
    # ignores its action, so it adds frames but no decision.
    resetting = np.zeros(len(env_fns), dtype=bool)
    while tally.episodes < args.episodes and not guard.tripped.is_set():
        _, _, term, trunc, infos = envs.step(random_actions(rng, infos["action_mask"]))
        tally.decisions += int((~resetting).sum())
        tally.frames += int(infos["frames"][infos["_frames"]].sum())
        resetting = term | trunc
        for i in np.flatnonzero(resetting):
            tally.episode({k: infos[k][i] for k in ("state", "outcome", "turn")})
    end = clocks(pids)
    envs.close()
    return start, end


def run_async(env_fns, args, guard, tally):
    with AsyncEnvPool(env_fns, seed=args.seed) as pool:
        rng = np.random.default_rng(args.seed)
        batch = pool.recv(min_ready=len(env_fns))
        start = clocks(pool.pids)
        while tally.episodes < args.episodes and not guard.tripped.is_set():
            pool.send(batch.env_ids, random_actions(rng, batch.action_masks))
            batch = pool.recv()
            tally.decisions += len(batch)
            for info, final in zip(batch.infos, batch.final_infos):
                tally.frames += info["frames"]
                if final:
                    tally.frames += final["frames"]
                    tally.episode(final)
        end = clocks(pool.pids)
    return start, end


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", choices=("async", "gym"), default="async")
    ap.add_argument("--envs", type=int, default=max(1, (os.cpu_count() or 1) - 2))
    ap.add_argument("--episodes", type=int, default=200)
    ap.add_argument("--states", nargs="+", default=STATES)
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

    states = [os.path.abspath(s) for s in args.states]
    env_fns = [functools.partial(BattleEnv, states, log_path=os.path.join(log_dir, f"env{i:02d}.jsonl"))
               for i in range(args.envs)]
    tally = Tally()
    start, end = (run_async if args.pool == "async" else run_gym)(env_fns, args, guard, tally)
    wall, env_cpu, env_waiting, main_cpu = (b - a for a, b in zip(start, end))

    print(f"pool {args.pool}  envs {args.envs}  episodes {tally.episodes}  decisions {tally.decisions}  "
          f"wall {wall:.1f}s  {tally.decisions / wall:.2f} decisions/s  {tally.episodes / wall:.2f} episodes/s  "
          f"{tally.frames / wall:,.0f} emulated frames/s  {tally.frames / max(tally.decisions, 1):.0f} frames/decision  "
          f"busy cores {env_cpu / wall:.2f}  waiting for a CPU {env_waiting / wall:.2f} cores  main process {main_cpu / wall:.2f} cores  "
          f"mean turns {np.mean(tally.turns):.2f}")
    for state, c in sorted(tally.outcomes.items()):
        print(f"  {state}: {dict(c)}")
    print(f"STUCK {sum(c['STUCK'] for c in tally.outcomes.values())}  peak CPU {guard.peak:.0f} C  logs in {log_dir}")
    if guard.tripped.is_set():
        print(f"stopped early: CPU above {args.max_temp:.0f} C for more than {args.hot_seconds:.0f} s")
        sys.exit(1)


if __name__ == "__main__":
    main()
