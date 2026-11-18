"""Rebuild milestone 00 from power-on (if missing), 01_starter_choice from 00, and 06 to 16 from 04, with the map start states and test fixtures.

  python scripts/make_milestones.py [--root states]

Plays from state 04 (after Barry 1) to Roark's badge with the survey party (PROGRESS.md §33),
following ROUTE: walks planned on the ROM's collision layer, text, talks, doors, and battles
played by the battle env with a greedy policy. Wild encounters are off, so a state saved on a
route has its encounter rate at 0 until the next map change. In the Oreburgh Gym, whose raised
floors the ROM's collision can't see, it takes fixed steps (from its walkable graph, §34).
Writes ROOT/milestones/*.state, ROOT/walk/start/*.state and ROOT/fixtures/*.state.
"""
import argparse
import os
import random
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import gen4
import pynds
import romdata as R
import scenario
import battle_env as BE
import overworld as O

ROM = os.environ.get("NUZLOCKERL_ROM", os.path.join(ROOT, "roms/plat-kaizo-nightmare-update-final.nds"))
START = os.path.join(ROOT, "states/milestones/04_after_barry1_home.state")

SURVEY_LEVEL = 16      # Roark's cap
SURVEY_TEAM = [(445, (337, 424, 242, 444)),    # Garchomp: Dragon Claw, Fire Fang, Crunch, Stone Edge
               (130, (127, 423, 242, 424)),    # Gyarados: Waterfall, Ice Fang, Crunch, Fire Fang
               (448, (396, 430, 370, 245)),    # Lucario: Aura Sphere, Flash Cannon, Close Combat, ExtremeSpeed
               (65, (94, 247, 411, 412)),      # Alakazam: Psychic, Shadow Ball, Focus Blast, Energy Ball
               (59, (53, 245, 242, 370)),      # Arcanine: Flamethrower, ExtremeSpeed, Crunch, Close Combat
               (387, (75, 402, 242, 444))]     # Turtwig, the starter: Razor Leaf, Seed Bomb, Crunch, Stone Edge

GYM_DOOR_TO_JONATHON = ["up"] * 3 + ["left"] * 3 + ["up"] * 3 + ["right", "up"]
GYM_JONATHON_TO_DARIUS = ["right"] * 5 + ["up"] * 5 + ["left"]
GYM_DARIUS_TO_ROARK = ["left", "up", "up", "up", "left"] + ["up"] * 5

ROUTE = [
    ("party",),
    ("text",),                                            # Mom, then Barry's mom with the Parcel
    ("start", "414_twinleaf_player_house"),
    ("exit", 411), ("start", "411_twinleaf_town"),
    ("walk", (146, 852)), ("start", "342_route_201"),
    ("walk", (164, 843)),                                 # Sandgem's entrance: the assistant's scene
    ("text", "no", 12000), ("fixture", "rowan_question"),  # B answers no to Rowan, who asks again
    ("text", "yes"),
    ("save", "06_sandgem_lab_pokedex"), ("start", "422_sandgem_lab"),
    ("exit", 418), ("text", "yes"),                       # the scene outside the lab
    ("start", "418_sandgem_town"),
    ("exit", 420), ("start", "420_sandgem_pokecenter"), ("exit", 418),
    ("walk", (184, 831)), ("fixture", "route202_entrance"),
    ("walk", (173, 800)), ("start", "343_route_202"),     # past Tristan, Natalie and Logan
    ("walk", (173, 796)), ("save", "07_jubilife_arrival"), ("text", "yes"),
    ("exit", 29), ("talk", (6, 3)), ("text", "yes"),      # Barry takes the Parcel
    ("save", "08_jubilife_school_parcel"), ("start", "029_trainers_school"),
    ("exit", 3), ("walk", (174, 776)), ("text", "yes"),   # leaving the school starts the Pokétch campaign
    ("talk", (183, 769)), ("text", "yes"),                # each clown: a quiz, a battle, a coupon
    ("talk", (143, 754)), ("text", "yes"),
    ("talk", (164, 752)), ("text", "yes"),
    ("talk", (174, 771)), ("text", "yes"),                # the president swaps the coupons for the Pokétch
    ("save", "09_jubilife_poketch"), ("start", "003_jubilife_city"),
    ("exit", 8), ("start", "008_poketch_co"), ("exit", 3),
    ("exit", 6), ("start", "006_jubilife_pokecenter"), ("exit", 3),
    ("walk", (197, 758)), ("save", "10_route203_barry2"), ("text", "yes"),
    ("walk", (246, 749)), ("start", "344_route_203"),     # five trainers; Madeline sees the gate's door
    ("exit", 258), ("walk", (7, 22)), ("text", "yes"),    # the hiker gives HM06
    ("walk", (27, 22)), ("start", "258_oreburgh_gate"),   # Curtis and Diana
    ("exit", 45), ("save", "11_oreburgh_arrival"),
    ("walk", (303, 757)), ("text", "yes"),                # a local walks the player to the gym
    ("start", "045_oreburgh_city"),
    ("exit", 48), ("faint",), ("fixture", "oreburgh_pokecenter_fainted"),
    ("talk_from", (8, 6), "up"), ("text", "yes"),         # the nurse, across her counter
    ("save", "12_oreburgh_pokecenter"), ("start", "048_oreburgh_pokecenter"),
    ("exit", 45), ("exit", 198), ("start", "198_oreburgh_mine_b1f"),
    ("exit", 199), ("walk", (17, 28)),                    # past both Workers
    ("talk_from", (17, 28), "right"), ("text", "yes"),    # Roark's Rock Smash demonstration
    ("save", "13_oreburgh_mine_roark"), ("start", "199_oreburgh_mine_b2f"),
    ("exit", 198), ("exit", 45),
    ("party",),                                           # back under Roark's cap
    ("exit", 47), ("save", "14_oreburgh_gym"),
    ("steps", GYM_DOOR_TO_JONATHON), ("steps", GYM_JONATHON_TO_DARIUS), ("steps", GYM_DARIUS_TO_ROARK),
    ("party",), ("save", "15_oreburgh_gym_before_roark"), ("start", "047_oreburgh_gym"),
    ("talk_from", (5, 4), "up"), ("text", "yes"),         # Roark
    ("save", "16_coal_badge"),
]


def greedy(snap, mask, forced):
    """The strongest-looking move: power x accuracy x own-type bonus x type effectiveness."""
    if forced:
        slots = snap.slots()
        return max((a for a in range(4, 9) if mask[a]), key=lambda a: snap.player[slots[a - 3]].hp)
    me = snap.player[snap.player_active]
    foe = snap.enemy[snap.enemy_active] if snap.enemy_active is not None else None
    types = R.species(me.species).types

    def value(a):
        mv = me.moves[a]
        hit = R.type_effectiveness(R.move(mv).type, R.species(foe.species).types) if foe else 1
        return BE.move_value(mv, types) * hit
    moves = [a for a in range(4) if mask[a]]
    return max(moves, key=value) if moves else next(a for a in range(BE.N_ACTIONS) if mask[a])


class Run:
    def __init__(self, root: str):
        self.root, self.env, self.map_id = root, None, None
        self.nds = pynds.PyNDS(ROM)
        self.nds.load_state_from_file(START)
        self.nds.tick(2)

    def save(self, folder: str, name: str):
        path = os.path.join(self.root, folder, name + ".state")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.nds.save_state_to_file(path)
        loc = gen4.read_location(self.nds)
        print(f"  saved {folder}/{name}: map {loc.map_id} ({loc.x},{loc.z})", flush=True)

    def encounters_off(self):
        loc = gen4.read_location(self.nds)
        if loc.map_id != self.map_id:
            self.map_id = loc.map_id
            O.no_encounters(self.nds)

    def fight(self):
        tmp = os.path.join(self.root, "fixtures", ".battle.state")
        os.makedirs(os.path.dirname(tmp), exist_ok=True)
        self.nds.save_state_to_file(tmp)
        if self.env is None:
            self.env = BE.BattleEnv([tmp], rom=ROM)
        _, info = self.env.reset(options={"state": tmp, "keep_rng": True})
        self.nds = self.env.nds
        trainer = self.nds.memory.read_u16(False, gen4.resolve(self.nds)["enemyTrainerID"])
        done = False
        while not done:
            _, _, term, trunc, info = self.env.step(greedy(self.env.snap, info["action_mask"], self.env.forced))
            done = term or trunc
        os.remove(tmp)
        print(f"  battle with trainer {trainer}: {info['outcome']}", flush=True)
        if info["outcome"] != "WON":
            raise SystemExit(f"the survey party didn't win against trainer {trainer}")

    def text(self, yes=False, limit=O.TEXT_LIMIT):
        while (r := O.advance_text(self.nds, yes, limit)) == "battle":
            self.fight()
        return r

    def through_trainers(self, outcome: str) -> bool:
        """After a step or walk that started a scene: if a trainer saw the player, battle and
        return True so the walk goes on. A scene of the story returns False."""
        if outcome == "scene" and O.spotted_by(self.nds):
            self.text()
            return True
        return False

    def walk(self, goal):
        while True:
            outcome = O.walk_to(self.nds, None, goal)
            self.encounters_off()
            if not self.through_trainers(outcome):
                if outcome == "stuck":
                    raise SystemExit(f"stuck walking to {goal} at {gen4.read_player_tile(self.nds)}")
                return outcome

    def steps(self, dirs):
        for d in dirs:
            outcome = O.step(self.nds, d)
            if outcome == "blocked" or (outcome == "scene" and not self.through_trainers(outcome)):
                raise SystemExit(f"step {d} at {gen4.read_player_tile(self.nds)}: {outcome}")

    def party(self):
        old = scenario.read_party_data(self.nds)
        starter = next(m for m in old if m["species"] == 387)
        trainer, rng = scenario.Trainer.from_mon(starter), random.Random(0)
        scenario.write_party(self.nds, [scenario.build_mon(sp, SURVEY_LEVEL, mv, trainer=trainer, rng=rng,
                                                           pid=starter.pid if sp == 387 else None)
                                        for sp, mv in SURVEY_TEAM])

    def faint(self):
        mons = scenario.read_party_data(self.nds)
        mons[0]["hp"] = 0
        scenario.write_party(self.nds, mons)

    def run(self):
        for action, *args in ROUTE:
            if action == "party":
                self.party()
            elif action == "faint":
                self.faint()
            elif action == "text":
                self.text(bool(args) and args[0] == "yes", args[1] if len(args) > 1 else O.TEXT_LIMIT)
            elif action == "walk":
                self.walk(args[0])
            elif action == "steps":
                self.steps(args[0])
            elif action == "exit":
                if O.take_exit(self.nds, None, args[0]) != "arrived":
                    raise SystemExit(f"no way into map {args[0]} from {gen4.read_location(self.nds)}")
                self.encounters_off()
            elif action == "talk":
                if O.talk_to(self.nds, None, *args[0]) != "talking":
                    raise SystemExit(f"nobody to talk to at {args[0]}")
            elif action == "talk_from":
                if O.talk_from(self.nds, None, args[0], args[1]) != "talking":
                    raise SystemExit(f"nobody to talk to from {args[0]} facing {args[1]}")
            elif action == "save":
                self.save("milestones", args[0])
            elif action == "start":
                self.save("walk/start", args[0])
            elif action == "fixture":
                self.save("fixtures", args[0])


def boot(root: str):
    """Milestone 00_twinleaf_bedroom_no_party, from power-on: the title, Rowan's talk, the
    player AR (a boy) and the rival Barry, to the free player in the bedroom. The ROM is linked
    into an empty folder so no save file beside it turns the title into CONTINUE. Every press is
    A held 4 frames, then a wait; touches hold 8 frames. The first A on the keyboard only wakes
    its cursor, so each name takes a wait and a second A. The emulator repeats the inputs
    exactly. Checked: the bedroom tile, no party, and the player free."""
    def press(key, wait=110):
        O.press(nds, key)
        nds.tick(wait)

    def tap(x, y, wait=110):
        nds.button.set_touch(x, y)
        nds.button.touch()
        nds.tick(8)
        nds.button.release_touch()
        nds.tick(wait)

    def free():
        try:                                # no FieldSystem exists until the bedroom loads
            return gen4.read_location(nds).map_id == 415 and not gen4.field_task(nds)
        except RuntimeError:
            return False

    with tempfile.TemporaryDirectory() as tmp:
        rom = os.path.join(tmp, "rom.nds")
        os.symlink(os.path.abspath(ROM), rom)
        nds = pynds.PyNDS(rom)
        nds.tick(1500)
        for _ in range(18):                 # title, Rowan's greeting, to "Please touch a button"
            press("a")
        tap(119, 82)                        # YES: "Do you understand everything so far?"
        press("a")
        press("a")
        press("down", 30)                   # the menu: NO INFO NEEDED
        press("down", 30)
        for _ in range(3):
            press("a")
        tap(128, 98, 150)                   # the middle of the Poké Ball
        for _ in range(7 + 9):              # Rowan's talk, the boy (the default), to the name's keyboard
            press("a")
        nds.tick(120)
        press("a", 60)                      # wakes the cursor
        press("a", 60)                      # A
        press("down", 20)
        for _ in range(7):
            press("right", 20)
        press("a", 60)                      # R
        press("start", 60)                  # OK
        for _ in range(7):                  # "Your name is AR?" YES, Rowan, then the rival's menu
            press("a")
        press("down", 30)                   # Barry
        for _ in range(8):
            press("a")
        for _ in range(60):                 # the rest of the talk, the bedroom
            if free():
                break
            press("a")
        nds.tick(60)
        loc = gen4.read_location(nds)
        if (loc.map_id, gen4.read_player_tile(nds)) != (415, (4, 6, 0)) or gen4.field_task(nds) \
                or gen4.read_party(nds):
            raise SystemExit(f"the intro didn't end free in the bedroom: {loc}")
        path = os.path.join(root, "milestones", "00_twinleaf_bedroom_no_party.state")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        nds.save_state_to_file(path)
    print("  saved milestones/00_twinleaf_bedroom_no_party", flush=True)


def starter_choice(root: str):
    """Milestone 01_starter_choice, from milestone 00: the opening, Barry on Route 201, then
    Rowan's briefcase with its cursor on the first ball, where every run starts. A question of
    Barry's answered no rolls the hack's joke credits and resets the game, so his scene takes A.
    The briefcase's text is pressed through with A every 20 frames, 14 times; these are the
    playthrough's own inputs, which the emulator repeats exactly. Checked: each ball gives its
    starter."""
    nds = pynds.PyNDS(ROM)
    nds.load_state_from_file(os.path.join(root, "milestones", "00_twinleaf_bedroom_no_party.state"))
    nds.tick(2)
    for action, arg in (("step", "down"), ("text", "no"), ("text", "no"), ("step", "up"), ("text", "yes"),
                        ("step", "down"), ("text", "no")):
        if action == "step":
            O.step(nds, arg)
        elif O.advance_text(nds, arg == "yes") != "done":
            raise SystemExit(f"the opening's text didn't end at {gen4.read_location(nds)[:3]}")
    if O.talk_to(nds, None, 112, 854) != "talking":             # the briefcase
        raise SystemExit("no briefcase at (112,854)")
    presses, frame = 0, 0
    while True:
        if gen4.field_task(nds) and frame % 20 == 0:
            if presses == 14:
                break
            O.press(nds, "a")
            presses += 1
        nds.tick(1)
        frame += 1
    nds.tick(152)
    path = os.path.join(root, "milestones", "01_starter_choice.state")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    nds.save_state_to_file(path)
    for k, species in enumerate((387, 390, 393)):
        nds.load_state_from_file(path)
        nds.tick(2)
        for _ in range(k):
            O.press(nds, "right", 8)
            nds.tick(40)
        O.press(nds, "a")
        nds.tick(90)
        O.press(nds, "a")
        nds.tick(150)
        if [m.species for m in gen4.read_party(nds)] != [species]:
            raise SystemExit(f"ball {k} didn't give species {species} from the rebuilt starter choice")
    print("  saved milestones/01_starter_choice", flush=True)


def ledyba_fixture(root: str):
    """The wild Ledyba that beat the legit level-7 Turtwig (§33), in Route 201's grass, before
    any Pokémon Center: the first battle seed it wins is kept."""
    out = os.path.join(root, "fixtures", "route202_ledyba_whiteout.state")
    turtwig = [{"species": 387, "level": 7, "moves": [33, 72]}]
    for seed in range(20):
        scenario.make_scenario(turtwig, out, seed=seed, rom=ROM, enemy=(165, 5))
        env = BE.BattleEnv([out], rom=ROM)
        _, info = env.reset(options={"state": out, "keep_rng": True})
        done = False
        while not done:
            _, _, term, trunc, info = env.step(next(a for a in range(BE.N_ACTIONS) if info["action_mask"][a]))
            done = term or trunc
        if info["outcome"] == "LOST":
            os.remove(out + ".json")
            print(f"  saved fixtures/route202_ledyba_whiteout: seed {seed}", flush=True)
            return
    raise SystemExit("the Ledyba never won in 20 seeds")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.join(ROOT, "states"))
    root = ap.parse_args().root
    if not os.path.exists(os.path.join(root, "milestones", "00_twinleaf_bedroom_no_party.state")):
        boot(root)
    starter_choice(root)
    Run(root).run()
    ledyba_fixture(root)
