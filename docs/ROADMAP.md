# Roadmap

In priority order. The first goal is a **battle-only environment**: load a
save state before a battle, let the agent pick moves and switches, and end
the episode on win or wipe.

## 0. Quick win

- [ ] In the in-game Options, set **battle scene (animations) off** and
      **text speed fast**, then re-save the milestone states. Every battle
      gets much shorter in frames, so training is faster for free.

## 1. RAM still needed for battles

- [ ] **Waiting-for-input signal.** Detect when the game shows "What will X
      do?" and the move or switch menus. This is the hardest and most
      important one. Search for a RAM byte that changes when the prompt
      appears; matching the screen image is the fallback.
- [ ] **Battle result:** win, loss, blackout, flee.
- [ ] **Active battler's party slot**, for switching and for knowing which
      Pokémon fainted.
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
- [ ] Extract species base stats, types, abilities, movesets, moves (power,
      type, accuracy, effect) and trainer teams from the hack's ROM files.
- [ ] Decide what the agent may see. `enemyBase` contains the opponent's
      full moveset. Showing it gives the agent more than a human sees; KP
      Labs didn't. Both are worth trying.

## 3. Battle environment and first training run

- [ ] Gymnasium env: reset loads a battle save state. Action is move 1–4 or
      switch to slot 1–5, executed as timed inputs. Observation is a
      structured vector from RAM, not pixels.
- [ ] Reward: +KO, +win, −Pokémon lost, large −wipe. **No damage-dealt
      reward** (KP Labs' stalling hack).
- [ ] Parallel environments across CPU cores. Put save states on tmpfs.
- [ ] Baseline: PPO, after drubinstein/pokemonred_puffer (PufferLib).
- [ ] Battle states for the early bosses (Barry 1, Roark, …) and some
      generated encounters.

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

## Open questions

- Should permadeath be handled as a constraint (constrained RL / CVaR), or
  through reward shaping?
- Can Metamon-style offline battle data warm-start the battle policy, even
  though the mechanics differ (Showdown vs. a Gen 4 Kaizo hack)?
- If DS emulation speed is the bottleneck, fall back to a Python battle
  simulator for training and use the emulator only to evaluate.
