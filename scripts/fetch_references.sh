#!/usr/bin/env bash
# Clone reference repositories into repos/ and download papers into papers/.
# Neither is committed (third-party code and PDFs). See docs/REFERENCES.md.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/repos" "$ROOT/papers"
cd "$ROOT/repos"
clone() {  # repo [commit]
  local name="${1#*/}"
  [ -d "$name" ] || git clone -q "https://github.com/$1.git" "$name"
  if [ -n "${2:-}" ]; then git -C "$name" checkout -q "$2"; fi
  echo "repos/$name @ $(git -C "$name" rev-parse --short HEAD)"
}
clone PWhiddy/PokemonRedExperiments 5fa47ef
clone MarcoMeter/neroRL 8dd62bd
clone UT-Austin-RPL/metamon 0a00a75
clone reddheeraj/PokemonRL 7a6710d
clone hsahovic/poke-env f34a404
clone Brian0255/NDS-Ironmon-Tracker
clone drubinstein/pokemonred_puffer
if [ ! -d pokeplatinum ]; then
  git clone -q --filter=blob:none --sparse https://github.com/pret/pokeplatinum.git
  git -C pokeplatinum sparse-checkout set include src/battle
fi
cd "$ROOT/papers"
get() { [ -f "$1" ] || curl -sSfL -o "$1" "$2"; echo "papers/$1"; }
get pleines2025_pokemon_red_rl_2502.19920.pdf https://arxiv.org/pdf/2502.19920
get grigsby2025_metamon_offline_rl_2504.04395.pdf https://arxiv.org/pdf/2504.04395
get pokerl_2604.10812.pdf https://arxiv.org/pdf/2604.10812
get stanford_aa228_2018_battle_strategy_rl.pdf https://web.stanford.edu/class/aa228/reports/2018/final151.pdf
get ecoffet2019_go_explore_1901.10995.pdf https://arxiv.org/pdf/1901.10995
get ecoffet2021_first_return_then_explore_2004.12919.pdf https://arxiv.org/pdf/2004.12919
get salimans2018_montezuma_single_demo_1812.03381.pdf https://arxiv.org/pdf/1812.03381
get florensa2017_reverse_curriculum_1707.05300.pdf https://arxiv.org/pdf/1707.05300
get jiang2020_prioritized_level_replay_2010.03934.pdf https://arxiv.org/pdf/2010.03934
get burda2018_random_network_distillation_1810.12894.pdf https://arxiv.org/pdf/1810.12894
get arjona_medina2018_rudder_1806.07857.pdf https://arxiv.org/pdf/1806.07857
get vanhasselt2016_popart_1602.07714.pdf https://arxiv.org/pdf/1602.07714
get hafner2023_dreamerv3_2301.04104.pdf https://arxiv.org/pdf/2301.04104
get andrychowicz2020_what_matters_on_policy_2006.05990.pdf https://arxiv.org/pdf/2006.05990
get nikishin2022_primacy_bias_2205.07802.pdf https://arxiv.org/pdf/2205.07802
get openai2019_dota2_1912.06680.pdf https://arxiv.org/pdf/1912.06680
get huang2020_invalid_action_masking_2006.14171.pdf https://arxiv.org/pdf/2006.14171
get zaheer2017_deep_sets_1703.06114.pdf https://arxiv.org/pdf/1703.06114
