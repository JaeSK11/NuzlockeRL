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
- [ ] **Switch menu signal.** The `curCommandState` values for the
      POKéMON menu and the forced switch after a faint aren't mapped yet.
- [x] **Battle result:** `resultMask` reads 1 after a win and 2 after a
      loss.
- [ ] **Flee and capture results.** The decomp's values (4 = captured,
      combined bits for fleeing) haven't been seen in RAM yet.
- [ ] **Active battler's party slot**, for switching and for knowing which
      Pokémon fainted. The env matches the active PIDs to party slots, but
      that's untested with 2+ Pokémon.
- [ ] **Double battles:** a battle-type flag and two active Pokémon per side.
- [ ] **Temporary effects:** confusion, Leech Seed, Substitute, Protect,
      trapping, Taunt, Encore, and so on.
- [ ] **Weather and field effects:** weather, Trick Room, Reflect and Light
      Screen, entry hazards.
- [ ] **Verify** that status and stat-stage fields change correctly (all
      that has been seen so far is neutral values).
- [ ] **Ability and held item** on both sides, in the battle copy.

## 2. Game data from the ROM (not RAM)

The hack changed abilities, so assume it changed more.
- [x] Extract species base stats, types, abilities, movesets, moves (power,
      type, accuracy, effect), trainer teams, and encounters from the hack's
      ROM files (`src/romdata.py`). The summary of how they differ from
      vanilla is in [HACK_DATA.md](HACK_DATA.md).
- [ ] Add move type, power, and accuracy from `romdata` to the battle
      observation, so the agent can learn type matchups instead of
      memorizing move ids.
- [ ] Decide what the agent may see. `enemyBase` contains the opponent's
      full moveset. Showing it gives the agent more than a human sees; KP
      Labs didn't. Both are worth trying.

## 3. Battle environment and first training run

- [x] Gymnasium env (`src/battle_env.py`). Reset loads a battle save
      state. An action is a move slot (0–3) or a switch (4–8), tapped on
      the touchscreen when the game waits for a command. The observation is
      a 111-value vector from RAM: the player's party in full, the enemy's
      active Pokémon, and which enemy slots have fainted. It shows no enemy
      moves.
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
- [ ] Baseline: PPO, after drubinstein/pokemonred_puffer (PufferLib).
- [ ] Battle states for the early bosses (Barry 1, Roark, …) and some
      generated encounters. Barry 1 and a wild Delibird exist so far.

### Gaps in the env

- [ ] **Switches.** Write a switch macro and verify it on a state with 2+
      party Pokémon. Until then the env masks switches off.
- [ ] **Move slots 2 and 3.** Their tap positions, (64, 115) and
      (192, 115), are guesses until a Pokémon with 3+ moves is tested.
- [ ] **Prompts the env doesn't model.** These are the forced switch
      after a faint, the trainer's "Will you switch?" question in Shift
      style, and move-learn and evolution questions. Today they end the
      episode as STUCK.
- [ ] **No PP left.** The action mask goes all False, but the game uses
      Struggle. Give that case one valid action.
- [ ] **Lockstep stepping wastes CPU.** Gymnasium's vector env waits for the
      slowest battle at every step. 14 envs averaged only 7.3 busy cores.
      An asynchronous env pool, such as PufferLib's, should win most of it
      back.
- [ ] **Save states on tmpfs.** Loading a state takes about 2.7 ms, so this
      matters only if profiling shows state loads.

## 4. Nuzlocke rules

- [ ] Location/map ID, for one encounter per route
- [ ] Caught or seen flags, for the duplicates clause
- [ ] Badges (address exists, not verified), for level caps
- [ ] PC boxes, for catches when the party is full and for boxing the dead
- [ ] Catch success, from party or box count changes
- [ ] Bag, for healing-item counts

## 5. Team building and overworld (later)

- [ ] Encounter choice and team-building policy, possibly a higher-level
      planner over the battle policy
- [ ] Player position, map, facing direction, story flags, defeated-trainer
      flags, open menu
- [ ] Overworld navigation, if it proves worth it at DS emulation speed

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
  simulator for training and use the emulator only to evaluate.
