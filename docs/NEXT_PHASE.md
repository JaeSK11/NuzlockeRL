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
(PROGRESS.md §24). The emulator stays.

**The goal:** beat Platinum Kaizo under the README's rules, with a model
that can then be placed in another Nuzlocke game and learn to beat that one
on its own, given time. Emerald Kaizo is the second game (step 7). So the
system is built to move (see [Built to move](#built-to-move-to-another-game)).

Decided on 2026-11-17 (PROGRESS.md §25): **the agent learns everything in
live runs**, from Twinleaf Town to Roark's badge under the README's rules.
Generated battles are no longer a training source; they stay only as a test
(step 6). The walk is scripted at first, which teaches nothing; it only gets
each run to the decisions. In order:

1. **The live game's battles in the env.** A run meets what a generated
   wild battle never shows, and each of these ends an episode today:
   - **Trainer battles.** Done (PROGRESS.md §26). The wait was a level-up's
     text, not the trainer's; Barry 1 now ends on the game's own result.
   - **Level-up prompts.** Done in battle (§26): B through the level-up text
     and stat boxes, and a stand-in choice for a fifth move (forget the
     lowest-valued move if the new one is worth more). Make it the agent's
     choice later. Evolution comes after the battle, so it belongs to the
     route runner (step 3).
   - **Trapping and Encore** in the action mask. Done (PROGRESS.md §27),
     checked action by action against what the game accepts.
   - **A wild Pokémon's Roar or Whirlwind** ends the battle, and the run
     goes on. Done (PROGRESS.md §29): the episode ends as FLED, read from
     the game's result, with 0 reward.
   - **The enemy's first move is fixed in a saved battle state.** Done for
     generated battles (PROGRESS.md §28): they are saved 10 frames before
     the enemy picks. The restart states of step 3 must be saved before a
     battle's command selection too, and checked to reload the same after
     another battle.
   - **The one early double battle** in the ROM (Interviewers Roxy & Oli,
     trainer 368, level 6) is vanilla's unused entry (PROGRESS.md §30).
   - **The Jubilife City multi battle** comes after Roark (PROGRESS.md
     §33): its trigger arms only once the Oreburgh Gym's script runs. The
     env needs it for the second gym, not the first: the target screen, and
     the second enemy and the partner in the snapshot.
2. **Catching and the Nuzlocke rules.**
   - **A Poké Ball action,** allowed only in a wild encounter the rules let
     it catch (a route's first new species, or a shiny), and only while the
     bag has a ball. Done in the battle env (PROGRESS.md §31): the caller
     passes `catch` at reset, which the bookkeeping below will decide. It taps through the bag by touch and handles the catch
     flow: the Pokédex entry, the nickname prompt, and the PC when the party
     is full. The catch result is already read (`battleResult` 4, roadmap
     step 4).
   - **Bookkeeping:** the first encounter per route, the duplicates clause
     from evolution lines, the shiny clause (`scenario.is_shiny` already
     tells a shiny from its PID), a fainted Pokémon out for good, and the
     level cap. Done (PROGRESS.md §32): `src/nuzlocke.py`. Its `encounter`
     answers the `catch` the battle env takes at reset.
3. **A scripted route runner to Roark.** Scripted inputs walk a fixed path
   from Twinleaf Town to the Oreburgh Gym, through the real encounters,
   trainers, text and story scenes, and heal at each Pokémon Center. An
   episode is a run, from the start to Roark's badge or a wipe. The agent
   learns, from scratch, every battle and every catch decision the run
   brings. In order:
   1. **Survey the way to Roark in this hack.** The story beats, the
      battles that can't be avoided, the trainers in the way, the Pokémon
      Centers, and where the player gets Poké Balls. Sources: the decomp's
      scripts for the vanilla order, the hack's trainers (`romdata.trainer`),
      and a playthrough with `src/drive.py` that saves a milestone state at
      each beat, after the existing 00 to 05. The hack may have moved things.
      Done (PROGRESS.md §33), in [ROUTE_TO_ROARK.md](ROUTE_TO_ROARK.md),
      with milestones 06 to 16, through Roark's badge.
   2. **Overworld primitives** (`src/overworld.py`), moved over from the
      playthrough's scratch driver (§33) and each checked on milestones 04
      to 16. In order:
      1. **Floor height first.** Done (PROGRESS.md §34). The player's tile
         is read as (x, z, height) (`gen4.read_player_tile`), and
         `overworld.explore` walks every tile of a map that way. The 18 maps
         of the route each have a walkable graph (`scripts/explore_maps.py`).
         Exploring from the ROM's height data was set aside: the emulator's
         answer is exact, and the method carries to Emerald wherever the
         player's height can be read.
      2. **Walking to a tile** on that graph, and retrying when a person
         blocks the way. Done (§34): `overworld.walk_to` plans again after
         every step and waits when blocked.
      3. **Advancing text** until the scene ends: B until `gen4.field_task`
         reads 0 (§33). B never starts a new talk. A yes/no that must be yes
         loops on B, so those take A: Rowan's Pokédex and the clowns'
         quizzes. Done (§35): `overworld.advance_text`.
      4. **Talking to a person** (stand next to them, face them, A), and
         **entering a door** (walk into it from the street, or on toward the
         wall from an exit mat). Done (§35): `talk_to`, `talk_from` (the
         nurse, across her counter), and `take_exit`, which finds the step
         to a map in the walkable graph.
      5. **Detecting a battle's start** (`gen4.in_battle`), **a trainer
         spotting the player** (a field task on a tile in a trainer's
         sight), and **a whiteout** (the player is sent home before any
         Pokémon Center, to the last one after, with the party healed).
         Done (§35): `spotted_by`, and `advance_text` returns "battle" when
         one starts and carries a lost battle through to the whiteout.
      6. **Rebuilding the milestones** 06 to 16 from input scripts made of
         these primitives, so another machine can make them. They keep the
         survey party: they're fixtures for these primitives, not run starts.
         Done (§36): `scripts/make_milestones.py`, with the map start states
         and the test fixtures.
   3. **Battles inside a run.** The battle env attaches to a battle already
      running in the runner's emulator, instead of loading a state. The
      attach is done (PROGRESS.md §37); the restart states come with training
      (sub-step 10):
      - When a battle starts, the runner saves its restart state at once,
        long before the enemy picks its first move. The state must pass
        §28's check that it reloads the same after another battle.
      - The runner hands the emulator to the battle env, which runs on to
        the first prompt as its reset does now. The playthrough instead
        saved a state at each battle and reset the env from it, which works
        but writes a state file per battle.
      - When the battle ends (WON, FLED, CAUGHT or LOST), the script goes
        on.
   4. **The route script:** done (§37), `src/route.py`. Segments from Twinleaf Town to the Oreburgh Gym,
      one per row of the order in [ROUTE_TO_ROARK.md](ROUTE_TO_ROARK.md),
      each a list of waypoints and story actions ending at a checkpoint (a
      map and a tile). The script is position-aware, so a wild or trainer
      battle anywhere in a segment only pauses it. It includes visits to
      the Pokémon Centers in Sandgem Town, Jubilife City and Oreburgh City.
      Since §39 it also trains up on Route 202 to level 11 and heals between
      trainers, since a lone level-7 starter can't pass Route 202. These are
      scripted like the walk, and step 5 makes them choices.
   5. **The rules in the run.** Done (§37), in `src/run_env.py`.
      - `nuzlocke.Run` gets the route's name from `gen4.read_location`, and
        the wild Pokémon's species and shininess (`scenario.is_shiny`).
        `encounter()` becomes the battle's `catch` option.
      - The run records catches, faints and bosses beaten.
      - Until the next Pokémon Center, a fainted Pokémon stays in the party
        but out of battle: no switch to its PID.
      - A wipe, or a whiteout, ends the run.
   6. **The party and the PC at each Pokémon Center.** Two kinds of change:
      - **Enforced by the rules:** the runner deposits every fainted
        Pokémon in the PC, where it stays for good. Done (§37), by writing
        the box and the party in RAM until the PC's screens are mapped. It isn't left to the
        agent, which would otherwise break the rule while it learned.
      - **Learned by the agent:** which caught Pokémon to withdraw from the
        PC into the open slots, and the party's order, which sets the lead.
        Both are new decisions, besides the battle actions: a choice among
        the boxed Pokémon for each open slot, one slot at a time, then the
        order. The observation for them shows the party and the box
        (`gen4.read_box`), the same features as in battle.
      - This needs the PC's deposit and withdraw screens and the overworld
        party menu mapped, as the battle bag was. It is the first part of the
        roadmap's team-building policy (step 5).
   7. **After battles.** Move learning is handled in battle (§26). An
      evolution scene after a battle is let run: the Pokémon evolves. Done
      (§38): the text after a battle takes A. A fifth move offered on
      evolution then replaces the first move slot, a stand-in to become the
      agent's choice.
      Picking up items is left out for now (the roadmap's Items).
   8. **The episode.**
      - One episode is a run from the starter choice, to Roark's badge, a
        wipe, or a step budget.
      - **The starter is the agent's first decision** (done, §37): one of the three in
        Rowan's briefcase, each shown with the same features as in battle
        (types, stats and moves, from the ROM). The milestone state
        `01_starter_turtwig_box_screen` is at that screen; the choice and its
        confirmation get mapped like the other screens. Its payoff shows
        only over the whole run, so it is learned slowly, as a choice among
        three over many runs.
      - The rewards are the battle rewards of now, plus **+20 for each boss
        beaten**, to start with:
        - Beating Roark is already worth about +11 in battle rewards (his 6
          faints and the win). The badge should be the run's biggest single
          reward, above any ordinary battle's +6 to +10.
        - +20 is about the cost of three strong faints (−8, −7, −6). The
          agent will spend fodder (−2.4 each) for a badge, but not trade its
          best team for one, and it needs that team at the next gym.
        - The swing at Roark is then about +31 for a win against about −30
          for a wipe.
      - **The discount must rise with the episode.** At PPO's γ = 0.99, a
        reward 250 decisions away keeps 8% of its value, so the badge would
        barely reach the starter choice. Runs use γ = 0.999 (78% over 250
        decisions). The timing run (sub-step 9) shows how long a run really
        is; tune both then.
      - The decisions are the starter, the battle actions, the ball where
        the rules allow it, and the party and PC choices at each Pokémon
        Center.
   9. **Time one run first.** Before building training on it, play a few
      runs with random battle actions. Measure the frames, the battles and
      the decisions per run, and the runs per hour on 14 envs, to know what
      training will cost. Done (§38): `scripts/time_runs.py`.
   10. **Train.** Built (§38): `train_ppo.py --runs`. PPO over runs, with restart states. Every battle of every
      run leaves a restart state; start some episodes from them, so that
      later battles, Roark's above all, get practice while most early runs
      still die on the first routes. As the policy gets through the early
      routes reliably, more runs reach Roark on their own, so lower the
      share of restarted episodes with it. Some restarts stay useful even
      then: survival multiplies over the 25 or so battles before Roark, so
      98% per battle still brings only about 60% of runs to him. This is
      for training only: a run that counts plays from the start, with no
      restarts.
4. **Roark's real fight.** Effects in the observation (roadmap step 1):
   Stealth Rock, Light Screen, Sand Tomb's trapping, and Curse. Runs reach
   Roark without them, but the agent then fights him blind to those effects.
5. **Learned walking.** Replace the scripted walk with learned movement.
   Reward each waypoint of the runner's path once per run, the first time
   it's reached, so the walk can't be farmed and doesn't need a novelty
   reward. Then let it choose the parts of the walk that are real choices:
   optional trainers, training up to the level cap, items and detours (the
   roadmap's Items, step 5).
6. **Measure.**
   - **Counted runs,** from the start with no restarts: how far each run
     gets, badges, and Pokémon lost.
   - **A generalization test.** Every run meets the same trainers, so
     nothing in the runs tells learning from memorizing them (§24). Battles
     generated against Pokémon the runs never meet test that, used only to
     evaluate, never to train.
   - **The simulator question.** Count the decisions a run takes and the
     runs it takes to reach Roark reliably. If that is weeks of emulator
     time, plan a Python battle simulator for training.
7. **Emerald Kaizo, the transfer test.** Once the Platinum loop works, put
   the model in a second game and measure the goal directly.
   - **A second stack:** a GBA emulator from Python (mGBA; PyBoy runs only
     Game Boy games), a Gen 3 adapter for the RAM layout and decryption,
     and button menus instead of touch. Gen 3 mechanics differ: a move is
     physical or special by its type, not by the move.
   - **The test:** train the Platinum model and a fresh one on Emerald Kaizo
     with the same budget. How much faster the Platinum model learns is the
     transfer. KP Labs' agent won 12 trainer battles there; that's the
     baseline to beat.
   - GBA hardware is far simpler to emulate than the DS, so Emerald runs
     should cost less. Not measured here yet.

### Built to move to another game

Everything specific to Platinum is something a human must redo for the next
game, so keep it in one place and keep it small:
- **Skills in the weights, facts from the ROM.** The policy learns what
  every Pokémon game shares: type matchups, when to switch, protecting the
  ace, spending fodder, PP and HP. What differs between games is read from
  the game's data while it plays and put in the observation: which Pokémon
  live on which route, the next boss's team, the obstacles ahead and the
  field move that clears each. In a new game the same model reads that
  game's facts, the way a player uses a guide, instead of discovering each
  one by losing runs.
- **One game adapter:** memory reads, inputs, ROM data, and the route ID
  behind one interface. The env and the policy use only that interface.
- **The rules as a config file,** read by the action mask and the rewards,
  so each game can come with its own rules.
- **Rewards from events every game has:** a faint, a win, a badge, a catch.
- **A game-neutral observation.** It already uses no species or move IDs.
  Add each move's effect, so a move it has never seen still makes sense.
- **Scripted pieces are scaffolding.** The walk (step 5), the level-up
  answers (step 1) and the text handling (step 3) each get replaced by a
  learned or generic version, since a new game would need them written
  again.
- **Memorizing doesn't transfer.** Knowledge of Platinum Kaizo's trainers
  is useless in Emerald. General battle skill is what shortens learning
  there, so the generalization test of step 6 matters here too.
- **Randomized ROMs are a later tool for robustness:** a randomizer such as
  the Universal Pokémon Randomizer, which supports Platinum, gives
  different trainers and wild Pokémon on the same maps. Not needed now.

What this order costs: no training runs until steps 1 to 3 work, and the
first runs learn slowly, since a run meets each trainer once and early
deaths spend most of the practice on the first routes. The restart states
soften that.

The walk is scripted before it's learned because the way to Oreburgh is close
to linear. Learning it costs a lot of steps and doesn't make the run better.
The choices that matter on the way are the battles and the catches. A
scripted walk gets every run to them quickly.
