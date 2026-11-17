# Roadmap

In priority order. The first goal is a **battle-only environment**: load a
save state before a battle, let the agent pick moves and switches, and end
the episode on win or wipe.

## 0. Quick win

- [x] **Battle scene (animations) off**, **text speed fast**, and **battle
      style Set**. `BattleEnv(fast_battles=True)` writes these into the
      Options the running battle reads, so no state is re-saved. With
      animations off, Barry 1 takes 28% fewer frames and the wild battle
      54% fewer. Set style is written but untested, because no state has a
      multi-Pokémon trainer battle yet.

## 1. RAM still needed for battles

- [x] **Waiting-for-input signal.** `gen4.waiting_for_command()` reads
      `BattleContext.command` and `curCommandState`, which also mark the
      move menu. See [RAM_MAP.md](RAM_MAP.md#battle-system).
- [x] **Switch menu signal.** `curCommandState[0]` reads 10 while the
      party menu is up, and the forced switch is `command` 21 with the
      player's `SWITCHING` flag set.
- [x] **Battle result:** `resultMask` reads 1 after a win and 2 after a
      loss.
- [x] **Flee and capture results.** 4 after a catch (step 4), and 5
      (`PLAYER_FLED`) after Roar or Whirlwind ends a wild battle, used by
      either side (PROGRESS.md §29). 6 (`ENEMY_FLED`) hasn't been seen.
- [x] **Active battler's party slot.** `partyOrder` maps party-menu
      positions to party slots, and position 0 is the active Pokémon.
      Verified on teams of 2 to 6.
- [ ] **Double battles:** a battle-type flag and two active Pokémon per side.
      None comes before Roark (PROGRESS.md §30); the hack's real
      interviewers, trainer 883, fight one at level 23.
- [ ] **Temporary effects:** confusion, Leech Seed, Substitute, Protect,
      and so on. Confusion, flinch, binding, Mean Look and Torment are
      mapped in `BattleMon.statusVolatile`, and Disable, Encore and the
      Choice lock in `MoveEffectsData`; see [RAM_MAP.md](RAM_MAP.md#battle-system).
      The action mask uses them, but the observation doesn't show them yet.
- [ ] **Weather and field effects:** weather, Trick Room, Reflect and Light
      Screen, entry hazards.
- [x] **Verify** that status and stat-stage fields change correctly.
      `scripts/ram_audit.py --probe` forces status and stat moves onto the
      player, and every major status and stage change read correctly.
- [ ] **Ability and held item** on both sides, in the battle copy.

## 2. Game data from the ROM (not RAM)

The hack changed abilities, so assume it changed more.
- [x] Extract species base stats, types, abilities, movesets, moves (power,
      type, accuracy, effect), trainer teams, and encounters from the hack's
      ROM files (`src/romdata.py`). The summary of how they differ from
      vanilla is in [HACK_DATA.md](HACK_DATA.md).
- [x] Add move type, power, accuracy, and class from `romdata` to the
      battle observation, so the agent can learn type matchups instead of
      memorizing move ids. Species and move ids are left out.
- [x] Type matchups in the observation, from the hack's type chart
      (`romdata.type_chart`): each move's effectiveness against the enemy,
      immunity, and same-type bonus, and how hard the enemy's types hit
      each party Pokémon.
- [x] A faint costs more the stronger the Pokémon: −(1 + 7 × its stat
      total over the team's highest), so fodder costs about −2.4 and the
      ace −8. Each Pokémon's strength is in the observation. A later
      gauntlet env, where a death costs options in later battles, should
      replace this stand-in.
- [ ] Decide what the agent may see. `enemyBase` contains the opponent's
      full moveset. Showing it gives the agent more than a human sees; KP
      Labs didn't. Both are worth trying.

## 3. Battle environment and first training run

- [x] Gymnasium env (`src/battle_env.py`). Reset loads a battle save
      state. An action is a move slot (0–3) or a switch (4–8), tapped on
      the touchscreen when the game waits for a command. The observation is
      812 values: each party slot's types, level, HP, status, and moves
      (type, power, accuracy, class, PP), then the enemy's active Pokémon,
      which enemy slots have fainted, both sides' stat stages, the turn, and
      whether this is a forced switch. It shows no enemy moves.
- [x] Reward from events only: +1 per enemy faint, −3 per own faint, +5
      win, −10 loss. **No damage-dealt reward** (KP Labs' stalling hack).
      Nothing comes from a total that can go down, such as party size or
      summed levels. The Pokémon Red agent lost a huge one-time reward when
      it deposited a Pokémon, and it learned to avoid Pokémon Centers.
- [x] A turn cap (default 100) ends the episode as a loss, so stalling
      never pays.
- [x] Randomize the battle RNG at reset. A battle save state fixes the
      battle's luck, so without this the agent could memorize one battle,
      as the Pokémon Red agent memorized a button sequence that caught its
      first Pokémon. The env writes a random `seedRandNext` after each
      load. See [PROGRESS.md](PROGRESS.md#8-battle-environment-2026-11-11).
- [x] Parallel environments: `scripts/rollout.py` runs one env per hardware
      thread, minus 2, with NooDS's render threads off. It stops if the CPU
      stays above 99 °C for 30 s.
- [x] Log every step and every episode as JSON lines.
- [x] PPO training: `src/ppo.py` (masked PPO, after CleanRL) over
      `src/pool.py`, run by `scripts/train_ppo.py`, which resumes from its
      last checkpoint. PufferLib doesn't install next to this project's
      gymnasium and numpy. On a one-move smoke battle the win rate went
      from 0.55 to 1.00 in 2,000 decisions.
- [x] PPO pilot on generated battles. Its 10 training battles were learned
      in about 30,000 decisions, so the emulator stays. The held-out
      battles gained less, and one got worse with more training. See
      [PROGRESS.md](PROGRESS.md#24-the-pilots-result-2026-11-17).
- [ ] Live runs to Roark: the agent learns every battle and catch in real
      runs from Twinleaf Town, with a scripted walk at first. The steps are
      in [NEXT_PHASE.md](NEXT_PHASE.md#after-the-pilot).
- [x] Generated wild battles: `src/scenario.py` writes any party and any
      wild enemy into RAM and saves a battle state at the first prompt.
- [ ] Trainer battles for the early bosses (Roark, Barry 2, Galactic). The
      generator makes wild battles only; trainer battles need the walk to
      each trainer, or a way to start one from RAM.

### Gaps in the env

- [x] **Switches.** Actions 4–8 switch to party-menu positions 1–5,
      verified on a team of 6 (28 switches, each to the right Pokémon).
- [x] **Move slots 2 and 3.** Tapping (64, 115) and (192, 115) drops
      exactly that slot's PP, verified on a generated Pokémon with 4 moves.
- [x] **The forced switch after a faint.** It is a decision but not a
      turn: the mask allows only living teammates, the reward is 0, and the
      turn counter doesn't move.
- [ ] **Prompts the env doesn't model.** The trainer's "Will you switch?"
      question in Shift style; the env sets Set style, but no
      multi-Pokémon trainer state exists yet to test it. Level-up text and
      move learning are handled (PROGRESS.md §26), and evolution happens
      after a battle, outside this env.
- [x] **Switching while trapped** (Wrap, Mean Look, Arena Trap) and **move
      locks** (Disable, Torment, Encore, Choice items) are in the action
      mask, read from the active `BattleMon` and checked action by action
      against what the game accepts (PROGRESS.md §27). Before, a refused tap
      ended the step as STUCK: against a wild Shuckle, which knows Wrap and
      Encore, 95% of random-policy battles did.
- [x] **The enemy's first move was fixed in a saved battle state.** Its AI
      picked before the state was saved, so the env's random battle seed
      didn't change it. Generated states are now saved 10 frames before the
      first command selection (PROGRESS.md §28). The milestone states, and
      the pilot's, are still saved at the prompt.
- [x] **No PP left.** The mask allows action 0 only, which taps a move
      and makes the game use Struggle. Switching is masked off in that case
      for now; allowing it is a one-line change in `action_mask`.
- [x] **Lockstep stepping wastes CPU.** `src/pool.py` steps each env as
      soon as it's ready: 1.30× more decisions per second with 14 envs,
      and 13.2 busy cores instead of 8.3.
- [x] **Check generated states when they are saved.**
      `scenario.check_state` loads a state in a fresh env and plays one
      decision. `make_scenario.py` and `make_battle_set.py` exit 1 when a
      state fails, so a bad state stops generation instead of a training
      run.
- [x] **Control the wild enemy's moves and held item.**
      `scenario.set_enemy_moves` writes them into the enemy's `BattleMon`
      and party struct at the first prompt. The generator's own level-up
      moves could end a wild battle: Roar ended every battle against a wild
      Cranidos 16 on the first turn. With this, a wild battle can use a
      trainer's real sets, as the pilot does with Roark's.
- [ ] **Save states on tmpfs.** Loading a state takes about 2.7 ms, so this
      matters only if profiling shows state loads.

## 4. Nuzlocke rules

- [x] Location: `gen4.read_location` gives the map header ID, position,
      and facing. `romdata.encounters_for_map` maps the ID to its encounter
      table, and `platinum_locations` gives the name.
- [x] Caught and seen flags (`gen4.read_pokedex`), for the duplicates clause.
- [x] Badges (`gen4.read_badges`), for level caps.
- [ ] PC boxes (`gen4.read_box`): the layout matches the decomp, but no real
      deposit has been read. That needs a Pokémon Center.
- [x] Catch success: a caught Pokémon sets `battleResult` to 4, joins the
      party, and gets its caught flag.
- [x] Bag (`gen4.read_bag`), for healing-item counts.
- [ ] Rule bookkeeping in the env: first encounter per route, the
      fainted and boxed list, and the level cap for the current badge count
      (the caps are in the README).
- [ ] Lookups the rules need: which items heal, and each species'
      evolution line for the duplicates clause (from `romdata.evolutions`).
- [ ] Check that the map ID changes on seamless route-to-route crossings.
      Only town-to-route crossings have been seen.

## 5. Team building and overworld (later)

- [ ] Encounter choice and team-building policy, possibly a higher-level
      planner over the battle policy
- [ ] Field moves (Rock Smash, Cut, Surf, Strength, and so on) as part of
      team building. The obstacles ahead and the move that clears each come
      from the ROM's map data, and which team members can use it from their
      learnsets; both go in the observation. The policy learns to keep a
      Pokémon that can use the move, and a backup in case it dies. Using
      the move in the field is scripted at first. None is needed before
      Roark.
- [ ] Player position, map, facing direction, story flags, defeated-trainer
      flags, open menu
- [ ] Overworld navigation: first a scripted route runner from Twinleaf
      Town to Roark, then learned walking rewarded once per waypoint of its
      path ([NEXT_PHASE.md](NEXT_PHASE.md#after-the-pilot), steps 6 and 7)

### Items

The rules ban healing and battle items from the bag in battle (see the
README), so those are used only between battles. The battle env's only bag
action will be a Poké Ball, for an encounter the rules allow catching
([NEXT_PHASE.md](NEXT_PHASE.md#after-the-pilot), step 5). Movement alone won't make the agent pick items up: it must be able
to use them and see them first. The payoff of a pickup comes hundreds of
decisions later, when a heal before a fight saves a Pokémon in it, and PPO
learns poorly from rewards that late. Build it in this order:

1. [ ] **Use items between battles.** Healing from the Medicine pocket
       between battles, and the bag's healing items in the observation. An
       item is then worth the faints it prevents in the next fight, through
       the battle rewards the env already gives. It matters most in a run of
       trainers with no Pokémon Center between them. Needs step 4's lookup
       of which items heal.
2. [ ] **Pick items up.** Either script the pickups along the route from the
       item locations in the ROM, with no learning, or reward the first time
       each item ball's flag is set. One reward per flag, so pickups can't be
       farmed (see the Magikarp lesson below). Needs the item locations and
       their flags from the ROM. Hidden items, found with the Dowsing app,
       can't be seen on screen, so script those.
3. [ ] **Choose detours.** The planner above decides whether an area is worth
       exploring: its items and its one catch, against the time it takes and
       the risk, since every wild encounter can cost a Pokémon for good. It
       uses the position and map from `gen4.read_location` (step 4).

## 6. A second game (later)

The goal is a model that, once it beats Platinum Kaizo, can learn another
Nuzlocke game on its own. See
[NEXT_PHASE.md](NEXT_PHASE.md#built-to-move-to-another-game).

- [ ] A game adapter: memory reads, inputs, ROM data and route IDs behind
      one interface, which the env and the policy use instead of `gen4`
      directly
- [ ] The rules as a config file, read by the action mask and the rewards
- [ ] Emerald Kaizo on mGBA: a Gen 3 adapter, then the transfer test,
      Platinum model against a fresh one

## Later, as the project matures

Ideas from the Pokémon Red agent (PWhiddy's PokemonRedExperiments video)
that are too early now:

- **A novelty reward for the overworld.** It rewards new screens and needs a
  high enough threshold that animated water and NPCs don't count.
- **Map and movement visualizations** built from the per-step logs. They
  showed the Pokémon Red agent's habits, such as walking the map edges
  counterclockwise.
- **Level rewards for team building.** Reward only increases, and watch
  for proxy hacks, like buying the level-5 Magikarp 10,000 times.
- **World models (DreamerV3).** They learn from far less game time, which
  matters at DS emulation speed. Try one once a PPO baseline exists.
- **Pretrained or transfer models.** A model trained on broad game data
  could shorten training for new battles.
- **Hierarchical RL.** A planner for encounters and team building on top of
  the battle policy, as step 5 describes.

## Open questions

- Should permadeath be handled as a constraint (constrained RL / CVaR), or
  through reward shaping?
- Can Metamon-style offline battle data warm-start the battle policy, even
  though the mechanics differ (Showdown vs. a Gen 4 Kaizo hack)?
- If DS emulation speed is the bottleneck, fall back to a Python battle
  simulator for training and use the emulator only to evaluate. Not yet:
  the pilot learned 10 battles in about 30,000 decisions (PROGRESS.md §24).
  Live runs will tell.
