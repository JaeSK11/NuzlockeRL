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
