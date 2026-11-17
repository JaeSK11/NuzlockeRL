"""The way from the starter choice to Roark's badge in Platinum Kaizo, as data, and a runner
that plays it on an emulator, pausing at every decision for the caller.

This is the scripted walk of NEXT_PHASE step 3: scaffolding that gets each run to its battles
and catches, to be replaced by learned walking (step 5). Tiles and triggers are from
ROUTE_TO_ROARK.md. Walks plan on the ROM's collision layer (overworld.walk_to with no graph),
so a run needs no explored map; the Oreburgh Gym, whose raised floors that layer can't see, is
crossed with fixed steps.
"""
from __future__ import annotations

import gen4
import overworld as O
import scenario

GYM_DOOR_TO_JONATHON = ["up"] * 3 + ["left"] * 3 + ["up"] * 3 + ["right", "up"]
GYM_JONATHON_TO_DARIUS = ["right"] * 5 + ["up"] * 5 + ["left"]
GYM_DARIUS_TO_ROARK = ["left", "up", "up", "up", "left"] + ["up"] * 5
NURSE = ((8, 6), "up")          # every Pokémon Center on the way: face the nurse across her counter
ROARK = 246

# From states/milestones/01_starter_choice: the briefcase, its cursor on the first ball.
ROUTE = [
    ("starter",),                                      # the agent's choice; then Barry's first battle
    ("text", "yes"),                                   # Barry, Mom, Barry's mom with the Parcel
    ("exit", 411),
    ("walk", (164, 843)), ("text", "yes"),             # Sandgem's entrance, to the lab: Rowan's Pokédex needs a yes
    ("exit", 418), ("text", "yes"),                    # the scene outside the lab
    ("exit", 420), ("heal",), ("exit", 418),
    ("walk", (173, 796)), ("text", "yes"),             # Route 202's three trainers; Jubilife's arrival
    ("exit", 29), ("talk", (6, 3)), ("text", "yes"),   # Barry takes the Parcel
    ("exit", 3), ("walk", (174, 776)), ("text", "yes"),  # the Pokétch campaign
    ("talk", (183, 769)), ("text", "yes"),             # each clown: a quiz, a battle, a coupon
    ("talk", (143, 754)), ("text", "yes"),
    ("talk", (164, 752)), ("text", "yes"),
    ("talk", (174, 771)), ("text", "yes"),             # the Pokétch; the east exit opens
    ("exit", 6), ("heal",), ("exit", 3),
    ("walk", (197, 758)), ("text", "yes"),             # Barry's second battle
    ("walk", (246, 749)), ("exit", 258),               # Route 203's trainers; the gate
    ("walk", (7, 22)), ("text", "yes"),                # the hiker's HM06
    ("walk", (27, 22)), ("exit", 45),                  # Curtis and Diana
    ("walk", (303, 757)), ("text", "yes"),             # a local walks the player to the gym
    ("exit", 48), ("heal",), ("exit", 45),
    ("exit", 198), ("exit", 199), ("walk", (17, 28)),  # both Workers
    ("talk_from", (17, 28), "right"), ("text", "yes"),  # Roark's Rock Smash demonstration
    ("exit", 198), ("exit", 45), ("exit", 47),
    ("steps", GYM_DOOR_TO_JONATHON), ("steps", GYM_JONATHON_TO_DARIUS), ("steps", GYM_DARIUS_TO_ROARK),
    ("talk_from", (5, 4), "up"), ("text", "yes"),      # Roark
]


class RouteError(Exception):
    """The script couldn't go on: a walk or a talk failed where the route expects it to work."""


class RunOver(Exception):
    """The run ended inside the route: "wipe", a lost battle."""


class Runner:
    """Plays ROUTE on nds. `play()` is a generator: it yields ("starter",) and takes back the
    choice (0 Turtwig, 1 Chimchar, 2 Piplup), and yields ("battle",) whenever a battle is up and
    takes back its outcome (WON, LOST, CAUGHT, FLED, ...). A LOST raises RunOver("wipe")."""

    def __init__(self, nds, route=ROUTE):
        self.nds, self.route = nds, route
        self.trainers_beaten: list[int] = []

    def play(self):
        for action, *args in self.route:
            yield from getattr(self, "_" + action)(*args)
        return "done"

    def _battle(self):
        trainer = self.nds.memory.read_u16(False, gen4.resolve(self.nds)["enemyTrainerID"])
        outcome = yield ("battle",)
        if outcome == "LOST":
            raise RunOver("wipe")
        if trainer and outcome == "WON":
            self.trainers_beaten.append(trainer)

    def _text(self, answer="no", limit=O.TEXT_LIMIT):
        """Advance text; every battle it leads to is played. After a battle the text goes on
        with A, since B would stop an evolution."""
        yes = answer == "yes"
        while (r := O.advance_text(self.nds, yes, limit)) == "battle":
            yield from self._battle()
            yes = True
        if r == "stuck":
            raise RouteError(f"text stuck at {gen4.read_location(self.nds)[:3]}")

    def _battle_or_scene(self, outcome):
        """After a step that started a scene: a wild battle or a trainer who saw the player is
        played and the walk goes on (True); a story scene is left to the route's next action."""
        if outcome != "scene":
            return False
        spotted = O.spotted_by(self.nds)
        for _ in range(150):                            # a wild battle's transition before in_battle reads True
            if gen4.in_battle(self.nds):
                break
            self.nds.tick(1)
        if gen4.in_battle(self.nds):                    # a wild battle, already up: advance_text wouldn't report it
            yield from self._battle()
            yield from self._text("yes")
            return True
        if not spotted:
            return False
        yield from self._text()                         # the trainer walks up and talks; the battle follows
        return True

    def _walk(self, goal):
        while True:
            outcome = O.walk_to(self.nds, None, goal)
            if (yield from self._battle_or_scene(outcome)):
                continue
            if outcome == "stuck":
                raise RouteError(f"stuck walking to {goal} at {gen4.read_player_tile(self.nds)}")
            return

    def _steps(self, dirs):
        for d in dirs:
            outcome = O.step(self.nds, d)
            if outcome == "blocked" or (outcome == "scene" and not (yield from self._battle_or_scene(outcome))):
                raise RouteError(f"step {d} at {gen4.read_player_tile(self.nds)}: {outcome}")

    def _exit(self, dest):
        while True:
            outcome = O.take_exit(self.nds, None, dest)
            if outcome == "arrived":
                return
            if not (yield from self._battle_or_scene(outcome)):
                raise RouteError(f"no way into map {dest} from {gen4.read_location(self.nds)[:3]}")

    def _talk(self, xz):
        if O.talk_to(self.nds, None, *xz) != "talking":
            raise RouteError(f"nobody to talk to at {xz}")
        yield from ()

    def _talk_from(self, tile, direction):
        if O.talk_from(self.nds, None, tile, direction) != "talking":
            raise RouteError(f"nobody to talk to from {tile} facing {direction}")
        yield from ()

    def _heal(self):
        """The rule first: a fainted Pokémon goes to the PC for good. Then the nurse."""
        dead = [k for k, m in enumerate(gen4.read_party(self.nds)) if m.hp == 0]
        if dead:
            scenario.deposit(self.nds, dead)
        yield from self._talk_from(*NURSE)
        yield from self._text("yes")

    def _starter(self):
        choice = yield ("starter",)
        for _ in range(choice):
            O.press(self.nds, "right", 8)
            self.nds.tick(40)
        O.press(self.nds, "a")                          # this ball
        self.nds.tick(90)
        O.press(self.nds, "a")                          # yes, take it; the hack then opens a PC box screen
        self.nds.tick(150)
        for _ in range(6):                              # B closes the box screen; A would open its menu
            O.press(self.nds, "b")
            self.nds.tick(40)
        yield from self._text("yes")                    # Rowan, then Barry's first battle
