"""overworld.py: walk graphs, and walking them in the game.
Run: ~/venvs/nuzlockerl/bin/python -m pytest -q tests/test_overworld.py"""
import json
import os
import sys
import pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import gen4
import overworld as O

ROM = os.environ.get("NUZLOCKERL_ROM", os.path.join(ROOT, "roms/plat-kaizo-nightmare-update-final.nds"))
GYM_START = os.path.join(ROOT, "states/walk/start/047_oreburgh_gym.state")
GYM_GRAPH = os.path.join(ROOT, "states/walk/47.json")


def stairs_and_walkway():
    """Floor (0,0)-(1,0)-(2,0) at height 0; stairs up from (2,0); a walkway back over (1,0) at
    height 4; a ledge that drops from (0,0) to (0,2) and can't be climbed."""
    g = O.WalkGraph(0, (0, 0, 0))
    both = [((0, 0, 0), "right", (1, 0, 0)), ((1, 0, 0), "right", (2, 0, 0)),
            ((2, 0, 0), "up", (2, -1, 4)), ((2, -1, 4), "left", (1, -1, 4)), ((1, -1, 4), "down", (1, 0, 4))]
    back = {"right": "left", "left": "right", "up": "down", "down": "up"}
    for a, d, b in both:
        g.edges.setdefault(a, {})[d] = b
        g.edges.setdefault(b, {})[back[d]] = a
    g.edges[(0, 0, 0)]["down"] = (0, 2, 0)
    return g


def test_a_path_climbs_the_stairs_to_the_walkway_over_the_floor():
    g = stairs_and_walkway()
    assert g.path((0, 0, 0), (1, 0, 4)) == ["right", "right", "up", "left", "down"]
    assert g.path((0, 0, 0), (1, 0)) == ["right"]           # any height: the floor tile is nearer


def test_a_ledge_is_one_way():
    g = stairs_and_walkway()
    assert g.path((0, 0, 0), (0, 2)) == ["down"]
    assert g.path((0, 2, 0), (0, 0)) is None


def test_a_walk_graph_survives_json():
    g = stairs_and_walkway()
    g.exits[(0, 0, 0)] = {"left": 3}
    g.scenes[(2, 0, 0)] = ["right"]
    assert O.WalkGraph.from_json(json.loads(json.dumps(g.to_json()))) == g


@pytest.mark.skipif(not (os.path.exists(ROM) and os.path.exists(GYM_START) and os.path.exists(GYM_GRAPH)),
                    reason="needs the ROM, the gym's start state and its graph (scripts/explore_maps.py)")
def test_the_gym_graph_walks_from_the_door_over_the_walkway_to_roark():
    import pynds
    g = O.WalkGraph.from_json(json.load(open(GYM_GRAPH)))
    nds = pynds.PyNDS(ROM)
    nds.load_state_from_file(GYM_START)
    nds.tick(2)
    tiles = []
    for goal in ((5, 24), (5, 4)):                          # to the door's mat, then up to Roark
        for d in g.path(gen4.read_player_tile(nds), goal):
            assert O.step(nds, d) == "moved"
            tiles.append(gen4.read_player_tile(nds))
        assert gen4.read_player_tile(nds)[:2] == goal
    walkway = [t for t in tiles if t[1] == 17 and t[2] == 4]
    assert walkway and any(t[:2] == w[:2] and t[2] == 0 for t in g.edges for w in walkway)


OREBURGH_START = os.path.join(ROOT, "states/walk/start/045_oreburgh_city.state")
OREBURGH_GRAPH = os.path.join(ROOT, "states/walk/45.json")


@pytest.mark.skipif(not (os.path.exists(ROM) and os.path.exists(OREBURGH_START) and os.path.exists(OREBURGH_GRAPH)),
                    reason="needs the ROM, Oreburgh's start state and its graph (scripts/explore_maps.py)")
def test_walking_past_the_people_of_oreburgh():
    """Following the planned steps blindly was blocked here by a wandering worker."""
    import pynds
    g = O.WalkGraph.from_json(json.load(open(OREBURGH_GRAPH)))
    nds = pynds.PyNDS(ROM)
    nds.load_state_from_file(OREBURGH_START)
    nds.tick(2)
    O.no_encounters(nds)
    assert O.walk_to(nds, g, (316, 796, 2)) == "arrived"
    assert gen4.read_player_tile(nds) == (316, 796, 2)


FIXTURES = os.path.join(ROOT, "states/fixtures")      # situations from the playthrough (PROGRESS.md §35), made locally


def needs(*paths):
    return pytest.mark.skipif(not all(os.path.exists(os.path.join(ROOT, p)) for p in (ROM, *paths)),
                              reason=f"needs {', '.join(paths)} (local states, not in git)")


def game(state):
    import pynds
    nds = pynds.PyNDS(ROM)
    nds.load_state_from_file(os.path.join(ROOT, state))
    nds.tick(2)
    return nds


def graph(map_id):
    return O.WalkGraph.from_json(json.load(open(os.path.join(ROOT, f"states/walk/{map_id}.json"))))


@needs("states/fixtures/rowan_question.state")
def test_b_loops_a_question_that_needs_yes_and_a_answers_it():
    nds = game("states/fixtures/rowan_question.state")
    assert O.advance_text(nds, limit=3000) == "stuck"
    assert O.advance_text(nds, yes=True) == "done"
    assert gen4.read_location(nds).map_id == 422 and gen4.read_var(nds, 16497) == 1   # in the lab, Pokédex given


@needs("states/fixtures/route202_entrance.state", "states/walk/343.json")
def test_a_trainer_spotting_the_player_stops_the_walk_and_leads_to_battle():
    nds = game("states/fixtures/route202_entrance.state")
    O.no_encounters(nds)
    assert O.walk_to(nds, graph(343), (173, 800)) == "scene"
    assert O.spotted_by(nds) == [1]                      # Youngster Tristan
    assert O.advance_text(nds) == "battle"


@needs("states/fixtures/oreburgh_pokecenter_fainted.state", "states/walk/48.json")
def test_the_nurse_heals_the_party():
    nds = game("states/fixtures/oreburgh_pokecenter_fainted.state")
    assert any(m.hp == 0 for m in gen4.read_party(nds))
    assert O.talk_from(nds, graph(48), (8, 6), "up") == "talking"   # across the counter
    assert O.advance_text(nds, yes=True) == "done"
    assert all(m.hp == m.max_hp for m in gen4.read_party(nds))


@needs("states/walk/start/029_trainers_school.state", "states/walk/29.json")
def test_a_door_leads_to_the_next_map():
    nds = game("states/walk/start/029_trainers_school.state")
    assert O.take_exit(nds, graph(29), 3) == "arrived"
    assert gen4.read_location(nds)[:3] == (3, 168, 777) and gen4.field_task(nds) == 0


@needs("states/fixtures/route202_ledyba_whiteout.state")
def test_a_lost_battle_whites_out_to_home_with_the_party_healed():
    import battle_env as BE
    state = os.path.join(ROOT, "states/fixtures/route202_ledyba_whiteout.state")
    env = BE.BattleEnv([state], rom=ROM)
    _, info = env.reset(options={"state": state, "keep_rng": True})
    done = False
    while not done:
        _, _, term, trunc, info = env.step(next(a for a in range(BE.N_ACTIONS) if info["action_mask"][a]))
        done = term or trunc
    assert info["outcome"] == "LOST"
    assert O.advance_text(env.nds) == "done"
    assert gen4.read_location(env.nds)[:3] == (414, 8, 8)               # home: no Pokémon Center visited yet
    assert all(m.hp == m.max_hp for m in gen4.read_party(env.nds))
