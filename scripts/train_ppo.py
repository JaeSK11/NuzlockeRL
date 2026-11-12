"""Train masked PPO on BattleEnv battles with an asynchronous env pool.

  python scripts/train_ppo.py --states states/generated/solo_turtwig10.state \
      --envs 4 --total-decisions 20000 --run-dir runs/smoke

Run the same command again to resume: training continues from the newest checkpoint
in --run-dir, up to --total-decisions. Each update appends one JSON line to
RUN_DIR/metrics.jsonl. --envs defaults to the number of hardware threads minus 2.
The run saves a checkpoint and stops if the hottest CPU sensor stays above --max-temp
for more than --hot-seconds.
"""
import argparse, functools, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from battle_env import BattleEnv
from thermal import ThermalGuard


def main():
    # Imported here, not at the top: each env worker re-imports this file, and torch
    # would cost every worker its import time and memory.
    import ppo

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--states", nargs="+", required=True, help="battle save states; each reset picks one at random")
    ap.add_argument("--envs", type=int, default=max(1, (os.cpu_count() or 1) - 2))
    ap.add_argument("--total-decisions", type=int, default=1_000_000)
    ap.add_argument("--run-dir", default=os.path.join(ROOT, "runs", "ppo"))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--rollout", type=int, default=ppo.Config.rollout, help="decisions per update")
    ap.add_argument("--lr", type=float, default=ppo.Config.lr)
    ap.add_argument("--checkpoint-every", type=int, default=ppo.Config.checkpoint_every, help="updates")
    ap.add_argument("--max-temp", type=float, default=99.0)
    ap.add_argument("--hot-seconds", type=float, default=30.0)
    args = ap.parse_args()

    guard = ThermalGuard(args.max_temp, args.hot_seconds)
    if not guard.paths:
        print("no CPU temperature sensor found; running without the thermal guard")
    guard.start()
    states = [os.path.abspath(s) for s in args.states]
    env_fns = [functools.partial(BattleEnv, states) for _ in range(args.envs)]
    cfg = ppo.Config(rollout=args.rollout, lr=args.lr, checkpoint_every=args.checkpoint_every)
    decisions = ppo.train(env_fns, args.run_dir, args.total_decisions, args.seed, cfg, guard)
    print(f"{decisions} decisions trained  peak CPU {guard.peak:.0f} C  run dir {args.run_dir}")
    if guard.tripped.is_set():
        print(f"stopped early: CPU above {args.max_temp:.0f} C for more than {args.hot_seconds:.0f} s")
        sys.exit(1)


if __name__ == "__main__":
    main()
