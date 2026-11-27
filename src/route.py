"""The way from the starter choice to Roark's badge in Platinum Kaizo, as data, and a runner
that plays it on an emulator, pausing at every decision for the caller.

This is the scripted walk of NEXT_PHASE step 3: scaffolding that gets each run to its battles
and catches, to be replaced by learned walking (step 5). Tiles and triggers are from
ROUTE_TO_ROARK.md. Walks plan on the ROM's collision layer (overworld.walk_to with no graph),
so a run needs no explored map; the Oreburgh Gym, whose raised floors that layer can't see, is
crossed with fixed steps.
"""
from __future__ import annotations

import bag
import battle_env
import gen4
import nuzlocke
import overworld as O
import romdata
import scenario

GYM_DOOR_TO_JONATHON = ["up"] * 3 + ["left"] * 3 + ["up"] * 3 + ["right", "up"]
GYM_JONATHON_TO_DARIUS = ["right"] * 5 + ["up"] * 5 + ["left"]
GYM_DARIUS_TO_ROARK = ["left", "up", "up", "up", "left"] + ["up"] * 5
LEVEL_EVOLUTION = romdata.EVO_METHODS.index("level")
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
MINE_B1F_HEAL = (("exit", 45),) + OREBURGH_HEAL + (("exit", 198),)


def gym_back(*walked):
    """The steps back to the gym's door after the step lists `walked` (the ROM's collision
    can't see the gym's raised floors)."""
    return [OPPOSITE[d] for steps in reversed(walked) for d in reversed(steps)]


def gym_trip(*walked, cap=None):
    """From partway up the gym, after the step lists `walked`: the same steps back to the door,
    Oreburgh's Pokémon Center, and the steps up again. With cap, the Pokémon Center also leaves
    the Pokémon over it in the PC."""
    heal = ("heal", cap) if cap else ("heal",)
    return (("steps", gym_back(*walked)), ("exit", 45), ("exit", 48), heal, ("exit", 45), ("exit", 47)) + tuple(("steps", w) for w in walked)
ROUTE202_GRASS = ((175, 827), (178, 827))   # south of Route 202's first ledge, out of every trainer's sight
MINE_FLOOR = ((12, 4), (12, 7))   # Oreburgh Mine B1F, by the door: no trainers, wild Pokémon at level 10
# From north of the ledge, before Natalie is beaten: back by the grass. SANDGEM_HEAL's own way
# from there crosses her sight, so after Tristan she was fought hurt on the way to heal.
ROUTE202_HEAL = (("walk", ROUTE202_GRASS[0]),) + SANDGEM_HEAL
GRIND_BATTLES = 60      # wild battles at most in one grind; past it the route goes on
GRIND_PACES = 200       # paces in the grass with no battle before the script gives up


def bag_count(nds, item: int) -> int:
    return sum(n for pocket in gen4.read_bag(nds, from_battle=False).values() for i, n in pocket if i == item)


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
    ("grind", 11, ROUTE202_GRASS, SANDGEM_HEAL),       # the party to 11: a run comes at level 7; Route 202's trainers need more
    ("walk", (170, 815), ROUTE202_HEAL), ("mend", ROUTE202_HEAL),  # past Tristan; each trainer is met healed
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
    # Past Darius, out to the mine: the party trains to Roark's cap once the gym's trainers can't push it over
    ("steps", gym_back(GYM_DOOR_TO_JONATHON, GYM_JONATHON_TO_DARIUS, GYM_DARIUS_TO_ROARK)), ("exit", 45), ("exit", 198),
    ("grind", ROARK_CAP, MINE_FLOOR, MINE_B1F_HEAL),
    ("exit", 45), ("exit", 47), ("steps", GYM_DOOR_TO_JONATHON), ("steps", GYM_JONATHON_TO_DARIUS), ("steps", GYM_DARIUS_TO_ROARK),
    ("mend", gym_trip(GYM_DOOR_TO_JONATHON, GYM_JONATHON_TO_DARIUS, GYM_DARIUS_TO_ROARK, cap=ROARK_CAP), ROARK_CAP),
    ("talk_from", (5, 4), "up"), ("text", "yes"),      # Roark
]


class RouteError(Exception):
    """The script couldn't go on: a walk or a talk failed where the route expects it to work."""


class RunOver(Exception):
    """The run ended inside the route: "wipe", a lost battle."""


class Runner:
    """Plays ROUTE on nds. `play()` is a generator: it yields ("starter",) and takes back the
    choice (0 Turtwig, 1 Chimchar, 2 Piplup), yields ("battle",) whenever a battle is up and
    takes back its outcome (WON, LOST, CAUGHT, FLED, ...), and yields ("pc", cap) at each
    Pokémon Center and takes back (party slots to leave, box slots to take). A LOST raises
    RunOver("wipe")."""

    def __init__(self, nds, route=ROUTE):
        self.nds, self.route = nds, route
        self.trainers_beaten: list[int] = []
        self.heals = 0                                  # nurse visits
        self.in_trip = 0                                # heal trips under way (a trip can't be resumed halfway)
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
            yield from self._text("yes", after_battle=True)
            action, *args = self.route[start]
            if action == "walk" and len(args) > 1 and needs_heal(self.nds):   # as _walk does after its battles
                yield from self._trip(args[1])
            if action == "starter":
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

    def _text(self, answer="no", limit=O.TEXT_LIMIT, after_battle=False):
        """Advance text; every battle it leads to is played. After a battle the text goes on
        with A, since B would stop an evolution, and an evolution's fifth move is answered by
        move_to_forget as in battle."""
        yes = answer == "yes"
        while (r := O.advance_text(self.nds, yes, limit, self._evolution_forget if after_battle else None)) == "battle":
            yield from self._battle()
            yes = after_battle = True
        if r == "stuck":
            raise RouteError(f"text stuck at {gen4.read_location(self.nds)[:3]}")

    def _evolution_forget(self):
        """The slot of the move to forget for an evolution's fifth move, or "keep" for the old four.
        The party still holds the old form at its old level and EXP until the evolution ends, so
        the Pokémon is the one with four moves whose level evolution comes within three levels,
        and the move is what the evolution learns at that level. None when no Pokémon matches:
        then the YES/NO box isn't an evolution's, and takes A as before (a story question answered
        no can end the game: Barry's)."""
        for mon in gen4.read_party(self.nds):
            for evo in romdata.evolutions(mon.species):
                if evo.method != LEVEL_EVOLUTION or not 0 < evo.param - mon.level <= 3:
                    continue
                new = [m for lv, m in romdata.learnset(evo.target) if lv == evo.param and m not in mon.moves]
                if new and all(mon.moves):
                    slot = battle_env.move_to_forget(mon.moves, romdata.species(evo.target).types, new[0])
                    return "keep" if slot is None else slot
        return None

    def _battle_or_scene(self, outcome):
        """After a step that started a scene: a wild battle or a trainer who saw the player is
        played, or a sign walked into is read, and the walk goes on (True); a story scene is
        left to the route's next action."""
        if outcome != "scene":
            return False
        spotted = O.spotted_by(self.nds)
        for _ in range(150):                            # a wild battle's transition before in_battle reads True
            if gen4.in_battle(self.nds):
                break
            self.nds.tick(1)
        if gen4.in_battle(self.nds):                    # a wild battle, already up: advance_text wouldn't report it
            yield from self._battle()
            yield from self._text("yes", after_battle=True)
            return True
        if not spotted and not O.reading_sign(self.nds):
            return False
        yield from self._text()                         # the trainer walks up and talks, and the battle follows; or a sign's text closes
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
        Pokémon over the boss's level cap, for the PC."""
        if needs_heal(self.nds, hp_share=1.0) or (cap and any(m.level > cap for m in gen4.read_party(self.nds))):
            yield from self._trip(heal_trip)

    def _trip(self, actions):
        self.in_trip += 1
        try:
            for action, *args in actions:
                yield from getattr(self, "_" + action)(*args)
        finally:
            self.in_trip -= 1

    def _grind(self, level, tiles, heal_trip):
        """Wild battles in the grass or a cave, pacing between two tiles, until every party
        Pokémon has reached `level` (or GRIND_BATTLES are fought), so a caught Pokémon trains up
        too. It gains experience only in the battles the player sends it into. Between
        battles, and after the last, a party with any damage goes on heal_trip: Kaizo's wild
        Pokémon beat a lone starter from three quarters of its HP, and the route's next trainer
        is met healed."""
        for i in range(GRIND_BATTLES + 1):
            if needs_heal(self.nds, hp_share=1.0):
                yield from self._trip(heal_trip)
            if i == GRIND_BATTLES or min(m.level for m in gen4.read_party(self.nds)) >= level:
                return
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
        """The PC, then the nurse, then the bag (_bag). The caller answers ("pc", cap) with the party slots to leave in
        the PC, the (box, slot)s to take out of it, and which Pokémon of the new party leads:
        run_env applies the rules (a fainted Pokémon stays in the PC for good; with cap, the
        boss's level cap) and asks the agent the rest."""
        leave, take, lead = yield ("pc", cap)
        if leave or take or lead:
            scenario.pc_swap(self.nds, leave, take, lead)
        yield from self._talk_from(*NURSE)
        yield from self._text("yes")
        self.heals += 1
        yield from self._bag()

    def _bag(self):
        """Rare Candies, then each held item in the bag, each the caller's choice. ("candy",) takes
        back a party slot or None to stop, and ("hold", item) a party slot or None to keep the item.
        bag.py works the bag's menus, as a player does. Healing items are left alone: the rules
        allow none in battle, and the nurse heals."""
        while bag_count(self.nds, battle_env.RARE_CANDY):
            slot = yield ("candy",)
            if slot is None:
                break
            if (out := bag.use_item(self.nds, battle_env.RARE_CANDY, slot, self._candy_forget(slot))) != "used":
                raise RouteError(f"a Rare Candy on party slot {slot}: {out}")
        for item in battle_env.HOLD_ITEMS:
            if bag_count(self.nds, item):
                slot = yield ("hold", item)
                if slot is not None and (out := bag.give_item(self.nds, item, slot)) != "given":
                    raise RouteError(f"{romdata.item_name(item)} to party slot {slot}: {out}")

    def _candy_forget(self, slot):
        """bag.use_item's forget for a Rare Candy on party slot `slot`: the slot of the move to
        forget for a new move at the new level, by move_to_forget, or None to keep the old four.
        The move may come from the Pokémon's level evolution, if the candy starts one."""
        def forget():
            mon = gen4.read_party(self.nds)[slot]
            forms = [mon.species] + [e.target for e in romdata.evolutions(mon.species) if e.method == LEVEL_EVOLUTION]
            new = [m for f in forms for lv, m in romdata.learnset(f) if lv == mon.level and m not in mon.moves]
            if not new:
                return None
            return battle_env.move_to_forget(mon.moves, romdata.species(mon.species).types, new[0])
        return forget

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
