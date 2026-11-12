# Hack data: how Platinum Kaizo differs from vanilla

`src/romdata.py` reads the hack's own game data out of the ROM:
- species
- moves
- learnsets
- evolutions
- trainers
- wild encounters
- names

`scripts/hack_diff.py` compares that data with vanilla Platinum, which comes
from the pret/pokeplatinum decomp's data files. Run it to regenerate the full
report:

```bash
git -C repos/pokeplatinum sparse-checkout add res generated tools/dataproc tools/msgenc
~/venvs/nuzlockerl/bin/python scripts/hack_diff.py    # writes roms/extracted/hack_diff.txt
```

The report and every extracted table stay under `roms/`, which is not in
git, because they are game data. This page gives a summary only.

## How much changed

| Data | Changed in the hack |
|---|---|
| Species base stats | 208 of 493 |
| Species types | 0 |
| Species abilities | 355 |
| EV yields | All 493 are now zero, so battles give no EVs |
| Level-up learnsets | 487 species |
| Evolutions | 113 species (trade evolutions replaced by levels or items) |
| Moves | power 156, accuracy 124, PP 117, type 33, effect 96 |
| Move identities | 26 move ids are different moves now, such as Comet Punch becoming Water Ball and Rollout becoming Accelerock |
| Trainers | 864 of 927 have a changed party, class, AI, or items |
| Encounter tables | 144 of 158 have different grass or water slots |

Vanilla meanings of move ids, learnsets, and encounter tables don't
transfer. Code that needs game data must read it through `romdata`.

## Early-game notes for a Nuzlocke

- **Starters.** Turtwig has Overgrow or Shell Armor, learns Mega Drain at
  Lv6, and evolves at Lv16 instead of 18. Chimchar learns Ember at Lv6 and
  evolves at Lv15. Piplup's Attack and Special Attack are swapped (61 and
  51) and it evolves at Lv14.
- **Route 201** has Igglybuff, Delibird, Venonat, Vulpix, and seven more
  species at Lv4–5. Vanilla has Starly, Bidoof, and Kricketot at Lv2–3.
  Routes 202–204 are new too, up to Lv14 on Route 204 North.
- **Barry 1** brings one Lv5 starter that knows only its first move. Vanilla
  Chimchar also knows Leer. **Barry 2** brings 6 Pokémon at Lv9–10 with held
  items.
- **Roark** brings 6 Pokémon at Lv13–16 with held items and near-perfect
  IVs. That includes a Focus Sash Bonsly and a Cranidos with Head Smash.
  His AI adds the "risky" flag. Vanilla Roark has 3 Pokémon at Lv12–14.
- **Galactic.** The Jubilife grunts bring 4 Pokémon at Lv16 with held items
  and Selfdestruct.
- **Double battles.** 55 trainers fight double battles, 3 of them Galactic
  teams. The env handles single battles only (roadmap step 1).
- **Moves.** Tackle has 100 accuracy (95 in vanilla). Leech Life, Poison
  Sting, and Bubble are much stronger, and Absorb is a 60-power Dark move.
  Swords Dance has 2 PP.

## Verified against the running game

`tests/test_romdata.py` checks the extracted data against values read from
RAM in the milestone states:
- Turtwig's ability and stats at Lv5 and Lv6.
- Barry's Chimchar, including its exact PID.
- The Route 201 table that produced the Delibird.
- Delibird's moves.

## Open

- Alternate forms (ids 494–507) are loaded but not compared with vanilla.
- The rival's trainer name reads "Cedric" in the ROM. Where the game gets
  "Barry" is not traced.
- The map-header table's address in the ARM9 binary is hardcoded. It
  matched all 593 decomp headers, and the reader raises if it stops looking
  right.
- Some tables hold unusual entries, such as a Lv75 Rhydon in Wayward Cave
  1F. They are parsed as stored and not checked in the game.
