"""Evaluate a PPO checkpoint on battle states, without learning.

  python scripts/eval_ppo.py --run-dir runs/pilot --states states/generated/pilot/heldout/*.state

Plays --episodes episodes on each state, once with the policy sampled as in training and once
always taking the most likely valid action (--mode sample, greedy, or both). --mode random
plays every valid action with equal odds and needs no checkpoint: the random-play baseline,
with the same numbers as the policy's. Prints the win
rate, the clean-win rate (won with no player faint), faints, mean return, and mean length per
state, and with --json writes the per-state numbers, which also count each decision's kind and
move, and the ace's and the other Pokémon's faints (ppo.episode_stats). --step-log writes every
step of every episode, with the move and its PP, one JSONL file per env and mode.
Uses the newest checkpoint in --run-dir unless --checkpoint names one. Stops early if the CPU
stays above --max-temp for more than --hot-seconds, as training does.
"""
import argparse, functools, json, math, os, sys
import torch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from battle_env import BattleEnv
from thermal import ThermalGuard


class UniformPolicy:
    """Every valid action equally likely: random play."""

    def log_probs(self, obs, mask):
        return torch.log_softmax(torch.zeros(mask.shape).masked_fill(~mask, -torch.inf), dim=-1)


def main():
    import ppo      # imported here, as in train_ppo.py: env workers re-import this file

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--states", nargs="+", required=True)
    ap.add_argument("--run-dir", default=os.path.join(ROOT, "runs", "ppo"))
    ap.add_argument("--checkpoint", help="a checkpoint file; default: the newest in --run-dir")
    ap.add_argument("--episodes", type=int, default=50, help="per state and mode")
    ap.add_argument("--mode", choices=("sample", "greedy", "both", "random"), default="both")
    ap.add_argument("--envs", type=int, default=max(1, (os.cpu_count() or 1) - 2))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--json", help="write the per-state results here")
    ap.add_argument("--step-log", help="a directory for the step logs")
    ap.add_argument("--max-temp", type=float, default=99.0)
    ap.add_argument("--hot-seconds", type=float, default=30.0)
    args = ap.parse_args()

    if args.mode == "random":
        path, agent, norm = "random play", UniformPolicy(), lambda x: x
    else:
        path = args.checkpoint or ppo.latest_checkpoint(args.run_dir)
        if not path:
            sys.exit(f"no checkpoint in {args.run_dir}")
        agent, norm = ppo.load_policy(path)
    states = [os.path.abspath(s) for s in args.states]
    per_state = max(1, args.envs // len(states))            # each env plays one state
    env_states = [s for s in states for _ in range(per_state)]
    if args.step_log:
        os.makedirs(args.step_log, exist_ok=True)

    def env_fns(mode):
        log = (lambda i: os.path.join(args.step_log, f"{mode}_{i:02d}.jsonl")) if args.step_log else (lambda i: None)
        return [functools.partial(BattleEnv, [s], log_path=log(i)) for i, s in enumerate(env_states)]
    guard = ThermalGuard(args.max_temp, args.hot_seconds)
    guard.start()

    out = {"checkpoint": path}
    for mode in (("sample", "greedy") if args.mode == "both" else (args.mode,)):
        episodes = ppo.evaluate(agent, norm, env_fns(mode), math.ceil(args.episodes / per_state),
                                greedy=mode == "greedy", seed=args.seed, guard=guard)
        stats = ppo.episode_stats(episodes)
        out[mode] = stats
        print(f"\n{mode}: {stats['episodes']} episodes, win rate {stats.get('win_rate', 0):.2f}, "
              f"clean-win rate {stats.get('clean_win_rate', 0):.2f}  ({path})")
        for state, s in stats["states"].items():
            print(f"  {state:32} win {s['win_rate']:.2f}  clean {s['clean_win_rate']:.2f}  faints {s['mean_faints']:.2f} "
                  f"(ace {s['mean_ace_faints']:.2f})  "
                  f"return {s['mean_return']:+6.2f}  length {s['mean_length']:4.1f}  {s['outcomes']}")
        if guard.tripped.is_set():
            print(f"stopped early: CPU above {args.max_temp:.0f} C for more than {args.hot_seconds:.0f} s")
            break
    if args.json:
        with open(args.json, "w") as f:
            json.dump(out, f, indent=1)
    sys.exit(1 if guard.tripped.is_set() else 0)


if __name__ == "__main__":
    main()
