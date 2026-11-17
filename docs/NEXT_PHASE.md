# Next phase: the PPO pilot

Written 2026-11-12 as a plan to pick up later. Steps 1 to 4, and the STUCK
question under "Before starting", were done on 2026-11-16 (PROGRESS.md §18
to §22). The pilot (step 5) started on 2026-11-16 and was restarted the same
day after a Selfdestruct bug (§23). It finished on 2026-11-17. The result and
the decision are in §24, and the next steps under
[After the pilot](#after-the-pilot).

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
4. **A stopped run resumes.** Rerunning the same command continues from the
   last checkpoint.

## Steps

1. **Build the battle set, and check each state.** Done:

   ```bash
   ~/venvs/nuzlockerl/bin/python scripts/make_battle_set.py scripts/pilot_battles.json
   ```

   It builds `states/generated/pilot/<split>/<name>.state` from
   `scripts/pilot_battles.json`, and checks each state in a fresh env
   (`scenario.check_state`). The party gets its level-up moves. The enemy
   gets Roark's own moves and held item (ROM trainer 246), at his level:

   | Split | Party | Enemy |
   |---|---|---|
   | train | Turtwig 14, Shinx 13, Starly 13 | Bonsly 15 |
   | train | Turtwig 14, Machop 13, Budew 12 | Lileep 13 |
   | train | Turtwig 14, Shinx 13, Budew 12 | Corsola 14 |
   | train | Chimchar 14, Psyduck 13, Budew 12 | Bonsly 15 |
   | train | Chimchar 14, Geodude 13, Shinx 13 | Lileep 13 |
   | train | Chimchar 14, Machop 13, Starly 13 | Corsola 14 |
   | train | Piplup 14, Shinx 13, Budew 12 | Bonsly 15 |
   | train | Piplup 14, Machop 13, Starly 13 | Corsola 14 |
   | train | Starly 12 (weak lead), Turtwig 14, Machop 13 | Bonsly 15 |
   | train | Shinx 12 (weak lead), Piplup 14, Machop 13 | Lileep 13 |
   | held out | Turtwig 14, Machop 13, Shinx 13 | Cranidos 16 |
   | held out | Chimchar 14, Psyduck 13, Starly 13 | Gible 14 |
   | held out | Piplup 14, Geodude 13, Budew 12 | Cranidos 16 |
   | held out | Budew 12 (weak lead), Chimchar 14, Geodude 13 | Gible 14 |

   The party species come from Route 201–204 and Oreburgh Gate in the
   hack, within Roark's level cap of 16. Cranidos and Gible never appear in
   training. Shuckle is left out: its Sand Tomb traps, which the env can't
   model yet.

2. **Measure a random baseline.** Done, and measured again after the
   Selfdestruct fix with `eval_ppo.py --mode random`
   ([PROGRESS.md §24](PROGRESS.md#24-the-pilots-result-2026-11-17)). Random
   play wins 56% of the training battles but wins clean, with no faint, only
   6%, and 8% of the held-out ones. Judge the pilot by the
   clean-win rate and the return, which counts −3 per faint, more than by
   the win rate.

3. **An evaluation script.** Done. `scripts/eval_ppo.py` loads a checkpoint
   and plays `--episodes` episodes per state, with the policy sampled and
   with the most likely valid action every time:

   ```bash
   ~/venvs/nuzlockerl/bin/python scripts/eval_ppo.py --run-dir runs/pilot \
       --states states/generated/pilot/heldout/*.state --json runs/pilot/eval.json
   ```

4. **Short run first.** Done, see
   [PROGRESS.md](PROGRESS.md#20-the-ppo-check-run-2026-11-16): the win rate
   went from 0.61 to 0.87 in 20,000 decisions, and the held-out win rate
   from 0.56 to 0.73. Before the pilot, count faints per episode so the
   logs show the clean-win rate, and look at the two battles that got
   worse. It ran 20,000 decisions on the train split with 14 envs, in 49
   minutes. A second check run, with the type matchups, the faint penalty by
   strength, and faint counting, fixed both of those battles and took the
   held-out clean-win rate from random's 0.03 to 0.23 (§22). The command:

   ```bash
   ~/venvs/nuzlockerl/bin/python scripts/train_ppo.py --states <train states> \
       --total-decisions 20000 --run-dir runs/pilot_check
   ```

   Check that decisions/s stays near 7.8, the CPU stays below the thermal
   guard's limit, entropy doesn't collapse in the first updates, and no
   episode ends STUCK.

5. **The pilot run.** Done: 300,032 decisions in 14.1 hours (§24).

   ```bash
   ~/venvs/nuzlockerl/bin/python scripts/train_ppo.py --states <train states> \
       --total-decisions 300000 --run-dir runs/pilot
   ```

   Evaluate the checkpoints at about every 50,000 decisions on both splits
   with `eval_ppo.py`.

6. **Decide.** Done: keep training on the emulator, and make the battles
   more varied (§24, and [After the pilot](#after-the-pilot)).

## How the battle set was revised

The first set, with the wild Pokémon's own moves, couldn't run the pilot
(§18): random play won 87–100% of most battles, Shuckle's Wrap and Encore
ended 95% of its battles STUCK, and Cranidos's Roar ended all of its. The
generator now sets the enemy's moves and item (§19), so the enemies use
Roark's sets, and Shuckle is out until trapping is modeled. One open
question was why Bonsly faints on the first turn against the Starly lead
without hurting it: it's Selfdestruct, whose damage the env misses
(PROGRESS.md §23).

## What to watch

`scripts/plot_runs.py runs/pilot` draws the win and clean-win rates against
decisions trained, as `runs/progress.png`. For the random-play baseline
of step 2, pass `--baseline-win 0.56 --baseline-clean 0.06`, the train
split's (PROGRESS.md §24). The other charts, each with `--out`:

| Command | Shows | Look for |
|---|---|---|
| `--view health` | Entropy, KL, clip fraction, explained variance, value loss, decisions/s, CPU temperature, episodes to look at | The table below. Episodes to look at (STUCK, TURN_CAP, ENDED, or a result the game contradicts) should stay 0 |
| `--by-battle` | Each battle's clean-win rate (`--metric win`, `length`, `dry`) | Battles that stay light. With `--metric length`, a battle stuck at 1 decision: nothing the agent does matters there |
| `--view faints` | Per battle, faints per episode of the strongest Pokémon and of the rest | The strongest's line falling below the others': the fodder trade |
| `--view picks` | Per battle, decisions by kind: attacks by type matchup, status moves, switches, Struggle | Immune picks near 0; super-effective picks rising where the team has them |
| `--view moves` | Per battle, each move's share of the decisions | One move used everywhere, or Helping Hand, which fails in a single battle, not dying out |

`runs/<run>/metrics.jsonl` has one line per update:

| Field | Healthy |
|---|---|
| `win_rate`, and `states.<state>.win_rate` | Rising above the random baseline on every train state, not only the easy ones |
| `entropy` | Falls slowly. Near 0 early means the policy collapsed; raise `ent_coef` |
| `approx_kl`, `clip_frac` | Small and steady. Large jumps mean the learning rate is too high |
| `explained_variance` | Rises toward 1 as the value function learns |
| `decisions_per_s` | About 6 with 14 envs, since episodes wait for the game's result (PROGRESS.md §23). A drop means STUCK episodes or CPU throttling |
| `cpu_temp` | Below the guard's 99 °C |
| `result_mismatches` | 0. A WON or LOST that the game's own result contradicts |
| `states.<state>.picks`, `.moves` | Decisions by kind and by move |
| `states.<state>.mean_ace_faints`, `.mean_other_faints` | Faints per episode of the strongest Pokémon and of the rest |
| `states.<state>.pp_ran_dry` | Moves run out of PP, a baseline for the gauntlet, where PP carries over |

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

- **Wild battles only.** The enemies have Roark's moves and held items
  (§19), but each fights alone, as a wild Pokémon. His real team fights in a
  row: Bonsly 15
  (Stealth Rock, Selfdestruct), Lileep 13 (Giga Drain, Recover), Gible 14
  (Flamethrower, Earth Power), Corsola 14 (Recover, Light Screen), Shuckle
  13 (Toxic, Curse, Sand Tomb), and Cranidos 16 (Head Smash, Rock Polish),
  all with held items. Trainer battles need the walk to each trainer, or a
  way to start one from RAM (roadmap step 3).
- **Effects aren't in the observation.** Stealth Rock, Light Screen,
  Sand Tomb's trapping, and Curse need roadmap step 1's RAM first.
- **No double battles.** 55 trainers in the hack fight doubles.

## After the pilot

The pilot learned its 10 training battles in about 30,000 decisions. The
held-out battles gained less, and one got worse with more training
(PROGRESS.md §24). The emulator stays. The goal from here is a run from
Twinleaf Town to Roark's badge under the README's rules, with the agent
first fighting, then catching, then walking. Decided on 2026-11-17, in order:

1. **A varied battle set.** Hundreds of battles instead of 10, so that no
   single matchup can be memorized. `scenario.py` can already make any party
   against any wild enemy, with any moves and held item.
   - **Enemies:** the Pokémon of the real trainers before Roark
     (`romdata.trainer`, every Pokémon at level 16 or below): 159 sets of
     102 species, almost all with their own moves and items, fought as wild
     Pokémon. Roark's team is in the pool like any other. Leave out Roark's
     Shuckle, whose Sand Tomb traps, until trapping is modeled.
   - **Held out:** a random fifth of the enemy species, with every set of
     each.
   - **Parties:** 3 Pokémon catchable before Roark (Routes 201–204, Lake
     Verity, Oreburgh Gate and Oreburgh Mine, about 60 species), or a
     starter, at levels 12 to 14, with their level-up moves. Give some
     parties a clearly weak member, so the faint penalty separates fodder
     from the ace (§24), and some a setup move (§23).
   - **A fixed set:** about 500 battles, generated once at about a second
     each, and each checked as it's saved (`make_battle_set.py`). About
     2.7 GB. A failed state can't stop a run, and runs are reproducible.
2. **Evaluate the held-out battles during training.** `train_ppo.py` sees
   only the train split, so the pilot's held-out drop showed up only after
   the run. Every few updates, play the held-out battles without learning,
   log their win and clean-win rates in `metrics.jsonl`, and keep the
   checkpoint with the best held-out clean-win rate. The evaluation costs
   training time. About 20 episodes per held-out battle every 20 updates
   would be a few percent of the run. Pool several evaluations before
   trusting one number: the same checkpoint won one battle 44 of 50 times
   in one sample and 14 of 28 in another (§24).
3. **Measure, then decide on a simulator.** Train on the varied set and count
   the decisions until the held-out clean-win rate stops rising. If that
   takes more than about a million decisions (47 hours at 5.9 decisions/s),
   plan the Python battle simulator for training, and keep the emulator for
   evaluation. If variety doesn't fix generalization, find what lets the
   policy tell battles apart. The enemy's stats and level may matter more
   to it than the type matchups (§24). Try training with those features
   noisy or removed.
4. **Roark's real fight.**
   - **Effects in the observation** (roadmap step 1): Stealth Rock, Light
     Screen, Sand Tomb's trapping, and Curse.
   - **Trapping and Encore in the action mask** (roadmap step 3).
   - **An end signal for trainer battles.** The game records a trainer
     battle's result only after the trainer's closing text (§23).
   - **A state at Roark's battle:** his 6 Pokémon in a row, against a party
     like the one a run would bring.
5. **Catching and the Nuzlocke rules in the env.**
   - **A Poké Ball action,** allowed only in a route's first wild encounter
     and only while the bag has a ball. The catch result is already read
     (`battleResult` 4, roadmap step 4).
   - **Bookkeeping:** the first encounter per route, the duplicates clause
     from evolution lines, a fainted Pokémon out for good, and the level cap
     for the badge count.
6. **A scripted route runner to Roark.** Scripted inputs walk a fixed path
   from Twinleaf Town to the Oreburgh Gym, through the real encounters,
   trainers and story events, and heal at each Pokémon Center. The agent
   makes the decisions that matter: each battle, and whether to catch a
   route's first encounter. An episode is a run, from the start to Roark's
   badge or a wipe. The runner must handle what a single battle never shows:
   - **Level-up prompts.** Almost every win brings one: learn a new move, or
     evolve. The env ends these as STUCK today. Script the answers first
     (evolve; learn a move in place of the weakest one), and make them the
     agent's choice later.
   - **Text and story scenes,** and healing at each Pokémon Center.
   - **The one early double battle** in the ROM (Interviewers Roxy & Oli,
     trainer 368, level 6). Find where it is; if it's on the path and can't
     be avoided, script it.

   From here on, the live game is the main source of battle experience:
   - **Keep training the policy from step 3,** rather than starting over, on
     the battles the run meets, with the team it caught.
   - **Save a state before each battle of every run, and start some episodes
     from those states.** Under permadeath most early runs die on the first
     routes. Restarting from those states gives later battles, Roark's above
     all, enough practice anyway. As the policy gets through the early
     routes reliably, more runs reach Roark on their own, so lower the share
     of restarted episodes with it. Some restarts stay useful even then:
     survival multiplies over the 25 or so battles before Roark, so 98% per
     battle still brings only about 60% of runs to him. This is for training
     only: a run that counts plays from the start, with no restarts.
7. **Learned walking.** Replace the scripted walk with learned movement.
   Reward each waypoint of the runner's path once per run, the first time
   it's reached, so the walk can't be farmed and doesn't need a novelty
   reward. Then let it choose the parts of the walk that are real choices:
   optional trainers, training up to the level cap, items and detours (the
   roadmap's Items, step 5).

Generated battles (steps 1 to 3) come before the live game (step 6) for
three reasons:
- **They are live-game battles.** They run in the game itself, against the
  real trainers' Pokémon with their moves and items. Only the setup is a
  shortcut: the party is written into memory and the enemy is forced, which
  takes a second instead of a walk.
- **They cover more, and evenly.** A run meets the same 25 or so trainers
  every time. Early deaths spend most of the practice on the first routes,
  and nothing is held out to tell learning from memorizing.
- **They work now.** The live game needs catching, trainer battles and the
  runner first.

The walk is scripted before it's learned because the way to Oreburgh is close
to linear. Learning it costs a lot of steps and doesn't make the run better.
The choices that matter on the way are the battles and the catches. A
scripted walk gets every run to them quickly.

## Work that can run alongside

These need little CPU, so they can run while the pilot trains.
- **Effects RAM** (roadmap step 1): the rest of `BattleMon.statusVolatile`,
  `moveEffectsMask`, weather and field effects, and entry hazards. Verify
  them with `scripts/ram_audit.py --probe`, as stat stages were.
- **Trainer battles** for the early bosses (roadmap step 3).
