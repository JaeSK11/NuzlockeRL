"""Carry a run's newest checkpoint over to the current battle observation and actions, which
have new values and actions at their ends (src/battle_env.py OBS_FIELDS, N_ACTIONS). Starts a
new run directory from it:

  python scripts/widen_checkpoint.py runs/old runs/new
  python scripts/train_ppo.py --runs --run-dir runs/new ...   # resumes from the widened checkpoint

The policy starts exactly as the old one played where the new actions are masked
(ppo.widen_checkpoint); with --reset-ball, except that the ball starts over as when training began. Restart states don't
depend on the observation: copy runs/old/restarts to runs/new/restarts to keep them."""
import argparse, os, sys

import torch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
import battle_env
import ppo


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("old_run_dir")
    ap.add_argument("new_run_dir")
    ap.add_argument("--reset-ball", action="store_true",
                    help="also draw the ball action's output row again, as when training began (ppo.reset_action)")
    args = ap.parse_args()
    src = ppo.latest_checkpoint(args.old_run_dir)
    if src is None:
        sys.exit(f"no checkpoint in {args.old_run_dir}")
    if ppo.latest_checkpoint(args.new_run_dir):
        sys.exit(f"{args.new_run_dir} already has a checkpoint")
    os.makedirs(args.new_run_dir, exist_ok=True)
    ckpt = ppo.widen_checkpoint(torch.load(src, weights_only=True), battle_env.OBS_SIZE, battle_env.N_ACTIONS)
    if args.reset_ball:
        ckpt = ppo.reset_action(ckpt, battle_env.BALL_ACTION)
    print(f"{src}: {ckpt['update']} updates, {ckpt['decisions']} decisions -> {battle_env.OBS_SIZE} "
          f"observation values, {battle_env.N_ACTIONS} actions; wrote {ppo.save_checkpoint(args.new_run_dir, ckpt)}")


if __name__ == "__main__":
    main()
