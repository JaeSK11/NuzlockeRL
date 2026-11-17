"""Hardcore Nuzlocke bookkeeping for one run: which wild encounters may be caught, which Pokémon
are gone for good, and the level cap.

No emulator here. The route runner reads the facts from the game (the location's name, the wild
Pokémon and whether it is shiny, faints, bosses beaten) and asks a Run what the rules allow. The
rules are the README's; Rules holds them as data, so another game or ruleset can change them,
for example from a JSON file: Rules(**json.load(f)).

A "route" is the location name the game shows ("Route 201", "Oreburgh Mine B1F"), the usual
Nuzlocke reading of "each route".
"""
import functools
from dataclasses import dataclass, field

import romdata

NATIONAL_DEX = 493                  # species 1..493; the ROM's later entries are alternate forms
# The hack's built-in caps (README, Hack notes): a boss refuses to battle while any party
# Pokémon is over its cap. Barry's fights sit between gyms, so the cap follows bosses, not badges.
PLATINUM_KAIZO_CAPS = (("Roark", 16), ("Gardenia", 28), ("Fantina", 38), ("Barry 3", 42),
                       ("Maylene", 47), ("Wake", 54), ("Barry 5", 63), ("Byron", 65),
                       ("Candice", 74), ("Volkner", 84), ("Elite Four", 100))


@dataclass(frozen=True)
class Rules:
    first_encounter_only: bool = True   # only a route's first wild encounter may be caught
    duplicates_clause: bool = True      # an encounter from an evolution line already caught doesn't count
    shiny_clause: bool = True           # a shiny may always be caught, and uses up nothing
    level_caps: tuple = PLATINUM_KAIZO_CAPS   # (boss, cap) in the order they are fought


@functools.cache
def _parents() -> dict[int, int]:
    """Species -> the species it evolves from, over every evolution in the ROM."""
    parents = {}
    for species in range(1, NATIONAL_DEX + 1):
        for evo in romdata.evolutions(species):
            if evo.target:
                parents.setdefault(evo.target, species)
    return parents


def line_of(species: int) -> int:
    """The first species of an evolution line, which stands for the whole line."""
    parents, seen = _parents(), {species}
    while species in parents and parents[species] not in seen:
        species = parents[species]
        seen.add(species)
    return species


@dataclass
class Run:
    rules: Rules = field(default_factory=Rules)
    routes: dict = field(default_factory=dict)      # route -> species of its encounter that counted
    caught_lines: set = field(default_factory=set)  # line_of() of every Pokémon caught
    dead: set = field(default_factory=set)          # PIDs of Pokémon that fainted
    beaten: set = field(default_factory=set)        # bosses from rules.level_caps already beaten

    def encounter(self, route: str, species: int, shiny: bool = False) -> bool:
        """Call when a wild battle starts. Returns whether this Pokémon may be caught, and uses
        up the route if this is the encounter that counts there."""
        if self.rules.shiny_clause and shiny:
            return True
        if self.rules.duplicates_clause and line_of(species) in self.caught_lines:
            return False                            # doesn't count: the route stays open
        if not self.rules.first_encounter_only:
            return True
        if route in self.routes:
            return False
        self.routes[route] = species
        return True

    def caught(self, species: int):
        self.caught_lines.add(line_of(species))

    def fainted(self, pid: int):
        self.dead.add(pid)

    def boss_beaten(self, boss: str):
        if boss not in dict(self.rules.level_caps):
            raise ValueError(f"{boss} is not one of the capped bosses")
        self.beaten.add(boss)

    def level_cap(self) -> int | None:
        """The cap of the next boss not yet beaten, None once all are."""
        return next((cap for boss, cap in self.rules.level_caps if boss not in self.beaten), None)

    def over_cap(self, levels) -> bool:
        cap = self.level_cap()
        return cap is not None and any(level > cap for level in levels)
