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
import nuzlocke
import overworld as O
import romdata
import scenario

GYM_DOOR_TO_JONATHON = ["up"] * 3 + ["left"] * 3 + ["up"] * 3 + ["right", "up"]
GYM_JONATHON_TO_DARIUS = ["right"] * 5 + ["up"] * 5 + ["left"]
GYM_DARIUS_TO_ROARK = ["left", "up", "up", "up", "left"] + ["up"] * 5
NURSE = ((8, 6), "up")          # every Pokémon Center on the way: face the nurse across her counter
ROARK = 246
ROARK_CAP = dict(nuzlocke.PLATINUM_KAIZO_CAPS)["Roark"]
OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left"}

# Heal trips: route actions that go to a Pokémon Center, heal, and leave by its door.
SANDGEM_HEAL = (("walk", (184, 845)), ("exit", 420), ("heal",), ("exit", 418))
JUBILIFE_HEAL = (("exit", 6), ("heal",), ("exit", 3))
ROUTE203_HEAL = (("walk", (186, 758)),) + JUBILIFE_HEAL
# From the Oreburgh Gate, back west: Oreburgh's center is nearer, but entering Oreburgh plays its arrival scene.
GATE_HEAL = (("exit", 344),) + ROUTE203_HEAL + (("walk", (246, 749)), ("exit", 258))
OREBURGH_HEAL = (("exit", 48), ("heal",), ("exit", 45))
MINE_HEAL = (("exit", 198), ("exit", 45)) + OREBURGH_HEAL + (("exit", 198), ("exit", 199))


def gym_trip(*walked, cap=None):
    """From partway up the gym, after the step lists `walked`: the same steps back to the door
    (the ROM's collision can't see the gym's raised floors), Oreburgh's Pokémon Center, and the
    steps up again. With cap, the Pokémon Center also leaves the Pokémon over it in the PC."""
    back = [OPPOSITE[d] for steps in reversed(walked) for d in reversed(steps)]
    heal = ("heal", cap) if cap else ("heal",)
    return (("steps", back), ("exit", 45), ("exit", 48), heal, ("exit", 45), ("exit", 47)) + tuple(("steps", w) for w in walked)
ROUTE202_GRASS = ((175, 827), (178, 827))   # south of Route 202's first ledge, out of every trainer's sight
GRIND_BATTLES = 60      # wild battles at most in one grind; past it the route goes on
GRIND_PACES = 200       # paces in the grass with no battle before the script gives up


def needs_heal(nds, hp_share: float = 0.5) -> bool:
    """What sends a player back to the Pokémon Center: a party Pokémon under hp_share of its HP
    (a fainted one too), with a status condition, or with under a quarter of its PP left."""
    for m in gen4.read_party(nds):
        full_pp = sum(romdata.move(x).pp for x in m.moves if x)
        if m.hp < hp_share * m.max_hp or m.status or sum(m.pp) * 4 < full_pp:
            return True
    return False

# From states/milestones/01_starter_choice: the briefcase, its cursor on the first ball.
ROUTE = [
    ("starter",),                                      # the agent's choice; then Barry's first battle
    ("text", "yes"),                                   # Barry, Mom, Barry's mom with the Parcel
    ("exit", 411),
    ("walk", (164, 843)), ("text", "yes"),             # Sandgem's entrance, to the lab: Rowan's Pokédex needs a yes
    ("exit", 418), ("text", "yes"),                    # the scene outside the lab
    ("exit", 420), ("heal",), ("exit", 418),
    ("grind", 11, ROUTE202_GRASS, SANDGEM_HEAL),       # a run comes at level 7; Route 202's trainers need more
    ("walk", (170, 815), SANDGEM_HEAL), ("mend", SANDGEM_HEAL),  # past Tristan; each trainer is met healed
    ("walk", (183, 820), SANDGEM_HEAL), ("mend", SANDGEM_HEAL),  # past Natalie
    ("walk", (173, 796), SANDGEM_HEAL), ("text", "yes"),  # past Logan; Jubilife's arrival
    ("exit", 29), ("talk", (6, 3)), ("text", "yes"),   # Barry takes the Parcel
    ("exit", 3), ("walk", (174, 776)), ("text", "yes"),  # the Pokétch campaign
    ("mend", JUBILIFE_HEAL), ("talk", (183, 769)), ("text", "yes"),  # each clown: a quiz, a battle, a coupon
    ("mend", JUBILIFE_HEAL), ("talk", (143, 754)), ("text", "yes"),
    ("mend", JUBILIFE_HEAL), ("talk", (164, 752)), ("text", "yes"),
    ("talk", (174, 771)), ("text", "yes"),             # the Pokétch; the east exit opens
    ("exit", 6), ("heal",), ("exit", 3),
    ("walk", (197, 758)), ("text", "yes"), ("mend", ROUTE203_HEAL),  # Barry's second battle
    ("walk", (246, 749), ROUTE203_HEAL), ("exit", 258),  # Route 203's trainers; the gate
    ("walk", (7, 22)), ("text", "yes"),                # the hiker's HM06
    ("walk", (20, 22), GATE_HEAL), ("mend", GATE_HEAL),  # past Curtis
    ("walk", (27, 22)), ("exit", 45),                  # past Diana
    ("walk", (303, 757)), ("text", "yes"),             # a local walks the player to the gym
    ("exit", 48), ("heal",), ("exit", 45),
    ("exit", 198), ("exit", 199),
    ("walk", (13, 16), MINE_HEAL), ("mend", MINE_HEAL),  # above the ledge down to the Workers' corridor
    ("walk", (17, 28)),        # past Mason and Colin: the ledge and Roark's boulders leave no way out between them
    ("talk_from", (17, 28), "right"), ("text", "yes"),  # Roark's Rock Smash demonstration
    ("exit", 198), ("exit", 45), ("mend", OREBURGH_HEAL), ("exit", 47),
    ("steps", GYM_DOOR_TO_JONATHON), ("mend", gym_trip(GYM_DOOR_TO_JONATHON)),
    ("steps", GYM_JONATHON_TO_DARIUS), ("steps", GYM_DARIUS_TO_ROARK),
    ("mend", gym_trip(GYM_DOOR_TO_JONATHON, GYM_JONATHON_TO_DARIUS, GYM_DARIUS_TO_ROARK, cap=ROARK_CAP), ROARK_CAP),
    ("talk_from", (5, 4), "up"), ("text", "yes"),      # Roark
]


def _over_cap(party, cap) -> list[int]:
    """The party slots over cap, if some Pokémon able to battle would stay; else none, as the
    PC can't take the whole party."""
    over = [k for k, m in enumerate(party) if m.level > cap]
    return over if any(m.hp and m.level <= cap for m in party) else []


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
        self.heals = 0                                  # nurse visits
        self.at = 0                                     # the route action playing now: how far the run got
        self.sub = 0                                    # the step playing now, inside a fixed list of steps

    def play(self, resume: tuple[int, int] | None = None):
        """Play the route. resume=(at, sub) restarts a run from a state saved at a battle's start
        (a restart state): the battle comes first, then the route action it interrupted, from
        its start (a walk or a door is position-aware) or, in a list of steps, from the next one."""
        start, sub = 0, 0
        if resume:
            start, sub = resume
            self.at, self.sub = start, sub
            yield from self._battle()
            yield from self._text("yes")
            if self.route[start][0] == "starter":
                start += 1
            else:
                sub += 1
        for self.at in range(start, len(self.route)):
            action, *args = self.route[self.at]
            if action == "steps":
                yield from self._steps(args[0], sub if self.at == start else 0)
            else:
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

    def _walk(self, goal, heal_trip=()):
        """Walk to goal, playing the battles on the way. With heal_trip, a party hurt by one
        (needs_heal) goes to heal first, and the walk goes on from the Pokémon Center."""
        while True:
            outcome = O.walk_to(self.nds, None, goal)
            if (yield from self._battle_or_scene(outcome)):
                if heal_trip and needs_heal(self.nds):
                    yield from self._trip(heal_trip)
                continue
            if outcome == "stuck":
                raise RouteError(f"stuck walking to {goal} at {gen4.read_player_tile(self.nds)}")
            return

    def _mend(self, heal_trip, cap=None):
        """Before the next trainer: a heal trip if the party has any damage, or, with cap, a
        Pokémon over the boss's level cap."""
        if needs_heal(self.nds, hp_share=1.0) or (cap and _over_cap(gen4.read_party(self.nds), cap)):
            yield from self._trip(heal_trip)

    def _trip(self, actions):
        for action, *args in actions:
            yield from getattr(self, "_" + action)(*args)

    def _grind(self, level, tiles, heal_trip):
        """Wild battles in the grass, pacing between two tiles, until a party Pokémon reaches
        `level` (or GRIND_BATTLES are fought). Between battles, a party with any damage goes
        on heal_trip: Kaizo's wild Pokémon beat a lone starter from three quarters of its HP."""
        for _ in range(GRIND_BATTLES):
            if max(m.level for m in gen4.read_party(self.nds)) >= level:
                return
            if needs_heal(self.nds, hp_share=1.0):
                yield from self._trip(heal_trip)
            for k in range(GRIND_PACES):
                outcome = O.walk_to(self.nds, None, tiles[k % 2])
                if (yield from self._battle_or_scene(outcome)):
                    break
                if outcome != "arrived":
                    raise RouteError(f"grinding: {outcome} walking to {tiles[k % 2]} at {gen4.read_player_tile(self.nds)}")
            else:
                raise RouteError(f"no wild battle in {GRIND_PACES} paces between {tiles}")

    def _steps(self, dirs, first: int = 0):
        for self.sub in range(first, len(dirs)):
            d = dirs[self.sub]
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

    def _heal(self, cap=None):
        """The rule first: a fainted Pokémon goes to the PC for good. With cap, the Pokémon over
        it go to the PC too, since the boss refuses a party with one; a stand-in for the agent's
        PC decisions (NEXT_PHASE step 3.6)."""
        party = gen4.read_party(self.nds)
        leave = [k for k, m in enumerate(party) if m.hp == 0]
        if cap:
            leave = sorted(set(leave) | set(_over_cap(party, cap)))
        if leave:
            scenario.deposit(self.nds, leave)
        yield from self._talk_from(*NURSE)
        yield from self._text("yes")
        self.heals += 1

    def _call(self, fn):
        """fn(nds): a hook for checks and fixtures, such as writing a party."""
        fn(self.nds)
        yield from ()

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
