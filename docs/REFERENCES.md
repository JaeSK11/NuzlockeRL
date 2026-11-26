# References

Everything used so far, and why. `scripts/fetch_references.sh` clones the
repositories at the listed commits into `repos/` and downloads the papers
into `papers/`. Neither directory is committed.

## Papers

| Paper | Why it matters here |
|---|---|
| Pleines et al., *Pokemon Red via Reinforcement Learning*, [arXiv 2502.19920](https://arxiv.org/abs/2502.19920) (2025) | A clean PPO baseline and minimal PyBoy environment for early-game Red, with reward ablations. Template for the env and reward design. |
| Grigsby et al., *Human-Level Competitive Pokémon via Scalable Offline RL*, [arXiv 2504.04395](https://arxiv.org/abs/2504.04395) (2025), [metamon.tech](https://metamon.tech) | State of the art for battle-only agents (Showdown). Possible warm start or architecture reference for the battle policy. |
| *PokeRL*, Texas A&M, [arXiv 2604.10812](https://arxiv.org/abs/2604.10812) | A modular deep-RL system for early-game Red tasks. More env and reward design ideas. |
| *Optimal Battle Strategy in Pokémon using Reinforcement Learning*, [Stanford AA228 2018](https://web.stanford.edu/class/aa228/reports/2018/final151.pdf) | Small-scale battle Q-learning; softmax exploration did best. A simple baseline for battles. |

For the training problems found in [PROGRESS.md §53](PROGRESS.md), and the
plan in [NEXT_PHASE.md](NEXT_PHASE.md) step 3.11:

| Paper | Why it matters here |
|---|---|
| Ecoffet et al., *Go-Explore: a New Approach for Hard-Exploration Problems*, [arXiv 1901.10995](https://arxiv.org/abs/1901.10995) (2019), and its Nature version, *First return, then explore*, [arXiv 2004.12919](https://arxiv.org/abs/2004.12919) (Nature 590, 2021) | Return to a saved state, then explore from it. The restart states already return; the paper also chooses which states to return to. |
| Salimans and Chen, *Learning Montezuma's Revenge from a Single Demonstration*, [arXiv 1812.03381](https://arxiv.org/abs/1812.03381) (Deep RL Workshop, NeurIPS 2018) | Episodes start near the goal on one demonstration, and the start moves back as the agent succeeds. A way to reach Roark once runs bring caught teams to him. |
| Florensa et al., *Reverse Curriculum Generation for Reinforcement Learning*, [arXiv 1707.05300](https://arxiv.org/abs/1707.05300) (CoRL 2017) | The same backward idea with no demonstration. It keeps the start states the agent wins from sometimes, but not always. |
| Jiang et al., *Prioritized Level Replay*, [arXiv 2010.03934](https://arxiv.org/abs/2010.03934) (2020) | Picks start states by how much is left to learn there, measured by the size of their advantages. A principled weight for the restart pool. |
| Burda et al., *Exploration by Random Network Distillation*, [arXiv 1810.12894](https://arxiv.org/abs/1810.12894) (2018) | The standard novelty bonus. Not planned: it adds a reward, and the gap here is one action at known states, not unseen states. |
| Arjona-Medina et al., *RUDDER: Return Decomposition for Delayed Rewards*, [arXiv 1806.07857](https://arxiv.org/abs/1806.07857) (2018) | Moves a delayed reward back to the action that caused it, as a catch's worth shows only at Roark. Not planned: the catch reward already pays at the catch. |
| van Hasselt et al., *Learning values across many orders of magnitude* (PopArt), [arXiv 1602.07714](https://arxiv.org/abs/1602.07714) (NIPS 2016) | Normalizes the value targets and corrects the critic's last layer so its outputs stay the same. Fits a resumed checkpoint whose returns reach about 130. |
| Hafner et al., *Mastering Diverse Domains through World Models* (DreamerV3), [arXiv 2301.04104](https://arxiv.org/abs/2301.04104) (2023) | Its symlog transform and return scaling, a simpler option than PopArt. Not for the world model. |
| Andrychowicz et al., *What Matters In On-Policy Reinforcement Learning? A Large-Scale Empirical Study*, [arXiv 2006.05990](https://arxiv.org/abs/2006.05990) (2020) | A large study of PPO's settings. A checklist for `ppo.Config`, such as the critic's width. |
| Nikishin et al., *The Primacy Bias in Deep Reinforcement Learning*, [arXiv 2205.07802](https://arxiv.org/abs/2205.07802) (ICML 2022) | Networks overfit to early experience, and resetting the last layers undoes it. Backs resetting the ball's output row, which kept what it learned when a catch paid 0. |
| OpenAI et al., *Dota 2 with Large Scale Deep Reinforcement Learning*, [arXiv 1912.06680](https://arxiv.org/abs/1912.06680) (2019) | Its "surgery" carried one policy through months of changing observations and rewards. `scripts/widen_checkpoint.py` is the same idea. |
| Huang and Ontañón, *A Closer Look at Invalid Action Masking in Policy Gradient Algorithms*, [arXiv 2006.14171](https://arxiv.org/abs/2006.14171) (FLAIRS 2022) | The theory for the masks in `src/ppo.py`, with evidence that masks beat penalties. Backs keeping the rules as masks. |
| Zaheer et al., *Deep Sets*, [arXiv 1703.06114](https://arxiv.org/abs/1703.06114) (NIPS 2017) | One encoder shared across party slots. It would train the switch outputs no party has used yet, and suits the move to Emerald Kaizo. |

## Repositories

| Repository | Commit | Used for |
|---|---|---|
| [unexploredtest/PyNDS](https://github.com/unexploredtest/PyNDS) | 5a40a52 | **Dependency.** The DS emulator interface, built from source |
| [Hydr8gon/NooDS](https://github.com/Hydr8gon/NooDS) (via PyNDS's fork, a submodule) | — | The emulator core inside PyNDS |
| [Brian0255/NDS-Ironmon-Tracker](https://github.com/Brian0255/NDS-Ironmon-Tracker) | latest at fetch time | **Source of the Gen 4 pointer chain and battle offsets** (`constants/MemoryAddresses.lua`) and the decryption reference (`PokemonDataReader.lua`) |
| [pret/pokeplatinum](https://github.com/pret/pokeplatinum) | latest at fetch time | Platinum decompilation; struct layouts (sparse checkout of `include/` and `src/battle/`) |
| [PWhiddy/PokemonRedExperiments](https://github.com/PWhiddy/PokemonRedExperiments) | 5fa47ef | The original PPO-plays-Red project. Env and swarm design reference |
| [MarcoMeter/neroRL](https://github.com/MarcoMeter/neroRL) | 8dd62bd | Code for Pleines et al. |
| [drubinstein/pokemonred_puffer](https://github.com/drubinstein/pokemonred_puffer) | not cloned yet | Beats Red with PPO + PufferLib ([write-up](https://drubinstein.github.io/pokerl/)). Planned baseline for training infrastructure |
| [UT-Austin-RPL/metamon](https://github.com/UT-Austin-RPL/metamon) | 0a00a75 | Code for Grigsby et al. |
| [hsahovic/poke-env](https://github.com/hsahovic/poke-env) | f34a404 | Python interface to Showdown, which Metamon builds on |
| [reddheeraj/PokemonRL](https://github.com/reddheeraj/PokemonRL) | 7a6710d | Code for PokeRL |

## Python libraries

| Library | Why |
|---|---|
| `pynds` (from source) | The emulator: frames, input, memory, save states |
| `numpy` | Frame arrays; observations later |
| `pillow` | Screenshots from the driver and tests |
| `pytest` | Regression tests against save states |
| `cmake`, `ninja`, `nanobind`, `setuptools`, `wheel` | Building PyNDS from source |
| `sounddevice` + system `libportaudio2` | Imported by pynds (audio unused by default) |
| `pygame` | Pulled in by pynds for its optional window |

Planned: `gymnasium` (env API), `torch` + PufferLib or another PPO
implementation (training).

## Video and other sources

- pChal, [*So Someones Teaching An AI How To Nuzlocke...*](https://www.youtube.com/watch?v=uJoB6Oa5Ewk)
  (2024-05-30). Covers KP Labs' Emerald Kaizo battle-only RL agent
  ([twitch.tv/kp_labs](https://www.twitch.tv/kp_labs)). The source for the
  battle-first plan and the reward-hacking lesson. See
  [PROGRESS.md](PROGRESS.md#1-survey-of-prior-work-2026-11-11).
- [*The RL Environment Field Guide*](https://tokens-for-thoughts.notion.site/the-rl-environment-field-guide).
  General RL-environment design. Notion page, not archived.
- Platinum Kaizo developer FAQ (quoted on Reddit): DeSmuME recommended;
  melonDS cores can't save in-game.
- [Bulbapedia's Platinum walkthrough, part 3](https://bulbapedia.bulbagarden.net/wiki/Walkthrough:Pok%C3%A9mon_Platinum/Part_3).
  Vanilla's Oreburgh Gym has a way past both trainers and a shortcut that
  skips them. That told the playthrough the hack's boulder closes only the
  shortcut ([PROGRESS.md §33](PROGRESS.md)).
