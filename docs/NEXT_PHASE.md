# Next phase: the PPO pilot

Written 2026-11-12 as a plan to pick up later. Steps 1 to 3, and the STUCK
question under "Before starting", were done on 2026-11-16 (see
[PROGRESS.md](PROGRESS.md#18-getting-the-ppo-pilot-ready-2026-11-16)). The
short run (step 4) and the pilot (step 5) have not been run.

## The question

How many decisions does masked PPO need to learn a real battle on the
emulator? The answer settles the roadmap's open question: keep training on
the emulator, or build a Python battle simulator for training and use the
emulator only to evaluate.

## What is ready

- The battle env plays moves, switches, the forced switch, and Struggle.
  See [PROGRESS.md](PROGRESS.md#14-switches-the-forced-switch-struggle-and-a-richer-observation-2026-11-12).
- `scripts/train_ppo.py` trains masked PPO over the async env pool. It
  checkpoints and resumes when rerun. On a one-move smoke battle the win rate
  went from 0.55 to 1.00 in 2,000 decisions (§15).
- The emulator is deterministic: a fixed DS clock (§16), and state loads
  that don't depend on what ran before (§17). Both matter for training, since
  every reset loads a state right after an episode ends.
- Throughput: about 7.8 decisions/s with 14 envs on an 8-core CPU, which is
  about 28,000 an hour.

## Before starting

1. **On a new machine,** run `scripts/setup_env.sh`. It applies both NooDS
   patches. Then run `pytest -q tests`, and make sure
   `test_clock_is_fixed` and `test_a_state_loads_the_same_whatever_ran_before`
   pass. A PyNDS built without the patches fails them.
2. **How STUCK counts: settled, no change.** STUCK is a truncation, so it
   bootstraps from the value of its last state. That values a STUCK like
   playing on from there, neither rewarded nor punished. Ending it as a
   terminal step with 0 reward, as this plan first said, would make a STUCK
   worth more than any loss, and the agent could learn to cause one, for
   example by switching while trapped. The fix for agent-caused STUCK is to
   mask switches while trapped and moves under Encore (roadmap step 3).
3. **Make a worker error survivable, or rule it out.** Any worker error
   stops training (`WorkerError`). Step 1 below checks every state up
   front. Optionally, let the trainer restart a failed worker and log it.
4. **Keep the machine awake for long runs.** If it stops anyway, rerunning
   the same command resumes from the last checkpoint.

## Steps

1. **Build the battle set, and check each state.** Done:

   ```bash
   ~/venvs/nuzlockerl/bin/python scripts/make_battle_set.py scripts/pilot_battles.json
   ```

   It builds `states/generated/pilot/<split>/<name>.state` from
   `scripts/pilot_battles.json`, and checks each state in a fresh env
   (`scenario.check_state`). Each species gets its level-up moves at that
   level. The set, with wild battles standing in for Roark:

   | Split | Party | Enemy |
   |---|---|---|
   | train | Turtwig 14, Shinx 13, Starly 13 | Bonsly 15 |
   | train | Turtwig 14, Machop 13, Budew 12 | Lileep 13 |
   | train | Turtwig 14, Shinx 13, Budew 12 | Corsola 14 |
   | train | Turtwig 13, Machop 13, Starly 13 | Shuckle 13 |
   | train | Chimchar 14, Psyduck 13, Budew 12 | Bonsly 15 |
   | train | Chimchar 14, Geodude 13, Shinx 13 | Lileep 13 |
   | train | Piplup 14, Machop 13, Starly 13 | Corsola 14 |
   | train | Piplup 14, Budew 12, Geodude 13 | Shuckle 13 |
   | train | Starly 12 (weak lead), Turtwig 14, Machop 13 | Bonsly 15 |
   | train | Shinx 12 (weak lead), Piplup 14, Machop 13 | Lileep 13 |
   | held out | Turtwig 14, Machop 13, Shinx 13 | Cranidos 16 |
   | held out | Chimchar 14, Psyduck 13, Starly 13 | Gible 14 |
   | held out | Piplup 14, Geodude 13, Budew 12 | Cranidos 16 |
   | held out | Budew 12 (weak lead), Chimchar 14, Geodude 13 | Gible 14 |

   The party species come from Route 201–204 and Oreburgh Gate in the
   hack. The enemies are Roark's species at his levels. Cranidos and Gible
   never appear in training.

2. **Measure a random baseline.** Done; the numbers are in
   [PROGRESS.md](PROGRESS.md#18-getting-the-ppo-pilot-ready-2026-11-16). The
   pilot is judged against them.

3. **An evaluation script.** Done. `scripts/eval_ppo.py` loads a checkpoint
   and plays `--episodes` episodes per state, with the policy sampled and
   with the most likely valid action every time:

   ```bash
   ~/venvs/nuzlockerl/bin/python scripts/eval_ppo.py --run-dir runs/pilot \
       --states states/generated/pilot/heldout/*.state --json runs/pilot/eval.json
   ```

   **The baseline found that the set can't run the pilot yet.** A random
   policy wins 87–100% of the playable training battles. Shuckle's Wrap
   and Encore end 95% of its battles STUCK. Cranidos's Roar ends every one
   of its battles. Fix these before step 4; the options are below, under
   "Revising the battle set".

4. **Short run first.** About 20,000 decisions on the train split with 14
   envs, roughly 45 minutes:

   ```bash
   ~/venvs/nuzlockerl/bin/python scripts/train_ppo.py --states <train states> \
       --total-decisions 20000 --run-dir runs/pilot_check
   ```

   Check that decisions/s stays near 7.8, the CPU stays below the thermal
   guard's limit, entropy doesn't collapse in the first updates, and no
   episode ends STUCK.

5. **The pilot run.** About 300,000 decisions, roughly 11 hours:

   ```bash
   ~/venvs/nuzlockerl/bin/python scripts/train_ppo.py --states <train states> \
       --total-decisions 300000 --run-dir runs/pilot
   ```

   Evaluate the checkpoints at about every 50,000 decisions on both splits
   with `eval_ppo.py`.

6. **Decide.** Write the result up in PROGRESS.md as its own section.

## Revising the battle set

- **Make the battles harder,** so that a random policy wins about 20–50%.
  Raise the enemies' levels, or lower the team's, and measure again.
- **Control the enemy's moves in the generator** (roadmap step 3). This
  removes Roar, and lets a wild battle use a trainer's real movesets, such
  as Roark's Stealth Rock and Head Smash. A closer stand-in for the real
  fight would also be harder.
- **Shuckle:** leave it out until the trapping and Encore RAM is mapped and
  the mask rules out a refused switch or move. Or keep it only once the
  enemy's moves can be set without Wrap and Encore.

## What to watch

`runs/<run>/metrics.jsonl` has one line per update:

| Field | Healthy |
|---|---|
| `win_rate`, and `states.<state>.win_rate` | Rising above the random baseline on every train state, not only the easy ones |
| `entropy` | Falls slowly. Near 0 early means the policy collapsed; raise `ent_coef` |
| `approx_kl`, `clip_frac` | Small and steady. Large jumps mean the learning rate is too high |
| `explained_variance` | Rises toward 1 as the value function learns |
| `decisions_per_s` | Near 7.8 with 14 envs. A drop means STUCK episodes or CPU throttling |
| `cpu_temp` | Below the guard's 99 °C |

## How to decide

These are proposals. Set the final numbers once the baseline is known.

- **Count the decisions to a threshold.** For example, the decisions until
  the train split's win rate is 0.3 above random. This is the number that
  compares the emulator with a simulator.
- **Learns within budget, and held-out improves too:** keep training on the
  emulator. Move on to the real bosses (see below).
- **Learns train but not held-out:** it memorizes matchups. Try more
  varied battles before blaming the emulator.
- **Flat near random after 300,000 decisions:** first look for bugs in the
  observation, the mask, or the rewards. Only then plan a Python battle
  simulator for training, keeping the emulator for evaluation.

## Limits of this pilot

- **Wild battles only.** The enemies use their wild level-up moves, not
  Roark's sets, and hold no items. His real team is far harder: Bonsly 15
  (Stealth Rock, Selfdestruct), Lileep 13 (Giga Drain, Recover), Gible 14
  (Flamethrower, Earth Power), Corsola 14 (Recover, Light Screen), Shuckle
  13 (Toxic, Curse, Sand Tomb), and Cranidos 16 (Head Smash, Rock Polish),
  all with held items. Trainer battles need the walk to each trainer, or a
  way to start one from RAM (roadmap step 3).
- **Effects aren't in the observation.** Stealth Rock, Light Screen,
  Sand Tomb's trapping, and Curse need roadmap step 1's RAM first.
- **No double battles.** 55 trainers in the hack fight doubles.

## Work that can run alongside

These need little CPU, so they can run while the pilot trains.
- **Effects RAM** (roadmap step 1): the rest of `BattleMon.statusVolatile`,
  `moveEffectsMask`, weather and field effects, and entry hazards. Verify
  them with `scripts/ram_audit.py --probe`, as stat stages were.
- **Trainer battles** for the early bosses (roadmap step 3).
