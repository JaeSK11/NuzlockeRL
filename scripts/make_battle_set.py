"""Build a set of battle states from a JSON file, and check each one.

  python scripts/make_battle_set.py scripts/pilot_battles.json [--out states/generated/pilot]

The file maps each split to a list of battles, as in scripts/pilot_battles.json:
{"train": [{"name": ..., "party": ["Turtwig:14", ...], "enemy": "Bonsly:15", "seed": 1}], ...}.
Species, moves, and items are given by name. Each party Pokémon gets its level-up moves at that
level in the hack. "enemy" is SPECIES:LEVEL, which keeps the wild Pokémon's own moves, or a key
of "enemy_sets": {"key": {"enemy": "Bonsly:15", "moves": [...], "item": "Focus Sash"}}.
A battle becomes OUT/<split>/<name>.state, and an existing state is kept. Every state is then
checked in a fresh env (scenario.check_state); the script exits 1 if any fails.
"""
import argparse, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import romdata as R
import scenario

SPECIES = {R.species_name(i).lower(): i for i in range(1, 494)}
MOVES = {R.move_name(i).lower(): i for i in range(1, len(R.all_moves())) if R.move_name(i)}
ITEMS = {R.item_name(i).lower(): i for i in range(1, 600) if R.item_name(i)}


def species_level(text: str) -> tuple[int, int]:
    name, level = text.rsplit(":", 1)
    return SPECIES[name.lower()], int(level)


def mon(text: str) -> dict:
    species, level = species_level(text)
    return {"species": species, "level": level, "moves": list(R.default_moves(species, level))}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec")
    ap.add_argument("--out", default=os.path.join(ROOT, "states/generated/pilot"))
    args = ap.parse_args()
    with open(args.spec) as f:
        spec = json.load(f)
    sets, splits = spec.get("enemy_sets", {}), {k: v for k, v in spec.items() if isinstance(v, list)}
    failed = 0
    for split, battles in splits.items():
        for b in battles:
            path = os.path.join(args.out, split, b["name"] + ".state")
            if not os.path.exists(path):
                enemy = sets.get(b["enemy"], {"enemy": b["enemy"]})
                moves = [MOVES[m.lower()] for m in enemy["moves"]] if "moves" in enemy else None
                item = ITEMS[enemy["item"].lower()] if "item" in enemy else None
                scenario.make_scenario([mon(m) for m in b["party"]], path, b["seed"],
                                       enemy=species_level(enemy["enemy"]), enemy_moves=moves, enemy_item=item)
            result = scenario.check_state(path)
            failed += result != "ok"
            print(f"{split:8} {b['name']:28} {result}", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
