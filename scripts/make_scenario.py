"""Make a wild-battle save state with a chosen player party.

  make_scenario.py --out states/generated/team.state \
      --mon 390:12:52,10,43,183 --mon 393:11:55,1,145,64 --enemy 396:8 --seed 2
  make_scenario.py --out states/generated/x.state --spec party.json

--mon is SPECIES:LEVEL:MOVE,MOVE,... with numeric ids (species 1..493 as in the hack's
tables). A JSON spec is either a list of mons or {"party": [...], "enemy": [species, level]};
each mon takes species, level, moves and optionally pid, ivs, evs, nature, ability_slot, item.
Without --enemy the game picks from Route 201's table.
"""
import argparse, json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import scenario


def parse_mon(text: str) -> dict:
    species, level, moves = text.split(":")
    return {"species": int(species), "level": int(level), "moves": [int(m) for m in moves.split(",")]}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="state file to write; a .json record goes beside it")
    ap.add_argument("--mon", action="append", default=[], type=parse_mon, metavar="SPECIES:LEVEL:MOVES")
    ap.add_argument("--spec", help="JSON file with the party, and optionally the enemy")
    ap.add_argument("--enemy", metavar="SPECIES:LEVEL", help="force every grass encounter to this Pokémon")
    ap.add_argument("--seed", type=int, default=0, help="picks PIDs and the idle time before walking")
    ap.add_argument("--rom", default=scenario.DEFAULT_ROM)
    ap.add_argument("--base-state", help="overworld state to start from (default: the Route 201 grass state)")
    args = ap.parse_args()

    party, enemy = list(args.mon), None
    if args.spec:
        with open(args.spec) as f:
            spec = json.load(f)
        party += spec if isinstance(spec, list) else spec["party"]
        enemy = tuple(spec["enemy"]) if isinstance(spec, dict) and spec.get("enemy") else None
    if args.enemy:
        enemy = tuple(int(v) for v in args.enemy.split(":"))
    if not party:
        ap.error("give --mon or --spec")
    record = scenario.make_scenario(party, args.out, args.seed, args.rom, args.base_state, enemy)
    print(json.dumps(record))


if __name__ == "__main__":
    main()
