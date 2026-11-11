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
