"""A whole run as one episode (run_env.py, route.py), and the pieces it rests on.
Run: ~/venvs/nuzlockerl/bin/python -m pytest -q tests/test_run_env.py"""
import os
import sys
import numpy as np
import pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import gen4

ROM = os.environ.get("NUZLOCKERL_ROM", os.path.join(ROOT, "roms/plat-kaizo-nightmare-update-final.nds"))
CHOICE = os.path.join(ROOT, "states/milestones/01_starter_choice.state")
FAINTED = os.path.join(ROOT, "states/fixtures/oreburgh_pokecenter_fainted.state")
ENTRANCE = os.path.join(ROOT, "states/fixtures/route202_entrance.state")
needs_choice = pytest.mark.skipif(not (os.path.exists(ROM) and os.path.exists(CHOICE)),
                                  reason="needs the ROM and milestone 01_starter_choice (scripts/make_milestones.py)")
needs_entrance = pytest.mark.skipif(not (os.path.exists(ROM) and os.path.exists(ENTRANCE)),
                                    reason="needs the Route 202 fixture (scripts/make_milestones.py)")


def first_move(info):
    return next(a for a in range(len(info["action_mask"])) if info["action_mask"][a])


def lone_turtwig(tmp_path, level=7, hp=None):
    """The Route 202 fixture with a lone Turtwig, as a run brings it there, and the route's wild
    encounters back on (the milestone script turns them off)."""
    import random
    import pynds
    import romdata as R
    import scenario
    nds = pynds.PyNDS(ROM)
    nds.load_state_from_file(ENTRANCE)
    nds.tick(2)
    mon = scenario.build_mon(387, level, R.default_moves(387, level), ivs=15,
                             trainer=scenario.Trainer.from_mon(scenario.read_party_data(nds)[0]), rng=random.Random(0))
    if hp is not None:
        mon["hp"] = hp
    scenario.write_party(nds, [mon])
    nds.memory.write_u32(False, gen4.resolve(nds)["_version"] + scenario.ENCOUNTER_OFFSET, R.encounters_for_map(343).grass_rate)
    path = str(tmp_path / "lone_turtwig.state")
    nds.save_state_to_file(path)
    return path


def play_out(env, info):
    done = False
    while not done:
        obs, reward, term, trunc, info = env.step(first_move(info))
        done = term or trunc
    return info


@needs_choice
def test_a_restart_saved_on_another_route_is_dropped(tmp_path):
    """Route actions move when the route changes; a restart whose action is no longer at its
    step would resume the wrong part of the route."""
    import json
    import shutil
    import run_env as RE
    meta = {"at": 3, "sub": 0, "action": repr(("walk", (0, 0))), "starter": 387, "trainers_beaten": [],
            "run": {"routes": {}, "caught_lines": [], "dead": [], "beaten": []}}
    (tmp_path / "003_old.json").write_text(json.dumps(meta))
    shutil.copy(CHOICE, tmp_path / "003_old.state")
    env = RE.RunEnv(restart_dir=str(tmp_path), restart_share=1.0)
    obs, info = env.reset(seed=0)
    assert not info["restart"] and info["decision"] == "starter"
    assert not list(tmp_path.glob("003_old.*"))


SCHOOL = os.path.join(ROOT, "states/milestones/08_jubilife_school_parcel.state")


@pytest.mark.skipif(not (os.path.exists(ROM) and os.path.exists(SCHOOL)), reason="needs milestone 08 (scripts/make_milestones.py)")
def test_a_hurt_party_heals_before_a_clown(tmp_path):
    """Jubilife's Pokémon Center during the Pokétch campaign: a party with any damage goes to heal
    before the next clown, and one with none goes straight on."""
    import pynds
    import route
    import run_env as RE
    import scenario
    nds = pynds.PyNDS(ROM)
    nds.load_state_from_file(SCHOOL)
    nds.tick(2)
    party = scenario.read_party_data(nds)
    party[0]["hp"] = 1
    scenario.write_party(nds, party)
    path = str(tmp_path / "hurt.state")
    nds.save_state_to_file(path)
    campaign = [("exit", 3), ("walk", (174, 776)), ("text", "yes"), ("mend", route.JUBILIFE_HEAL), ("mend", route.JUBILIFE_HEAL)]
    env = RE.RunEnv(start_state=path, route_actions=campaign)
    env.reset(seed=0)
    assert env.end == "no_badge" and env.runner.heals == 1           # the second mend found nothing to heal
    assert gen4.read_location(env.nds).map_id == 3
    assert all(m.hp == m.max_hp for m in gen4.read_party(env.nds))


def hurt_state(tmp_path, start):
    import pynds
    import scenario
    nds = pynds.PyNDS(ROM)
    nds.load_state_from_file(start)
    nds.tick(2)
    party = scenario.read_party_data(nds)
    party[0]["hp"] = 1
    scenario.write_party(nds, party)
    path = str(tmp_path / "hurt.state")
    nds.save_state_to_file(path)
    return path


@pytest.mark.parametrize("start, trip, back_in", [
    ("states/walk/start/344_route_203.state", "ROUTE203_HEAL", 3),     # Route 203 to Jubilife's Pokémon Center
    ("states/walk/start/258_oreburgh_gate.state", "GATE_HEAL", 258),   # the gate, by Route 203, and back
    ("states/walk/start/199_oreburgh_mine_b2f.state", "MINE_HEAL", 199),  # the mine to Oreburgh's, and back
])
def test_a_heal_trip_heals_and_comes_back(tmp_path, start, trip, back_in):
    import route
    import run_env as RE
    start = os.path.join(ROOT, start)
    if not (os.path.exists(ROM) and os.path.exists(start)):
        pytest.skip("needs the map start states (scripts/make_milestones.py)")
    env = RE.RunEnv(start_state=hurt_state(tmp_path, start), route_actions=[("mend", getattr(route, trip))])
    obs, info = env.reset(seed=0)
    if not env.end:                                                   # wild battles on the way (the mine's)
        play_out(env, info)
    assert env.end == "no_badge" and env.runner.heals == 1
    assert gen4.read_location(env.nds).map_id == back_in
    party = gen4.read_party(env.nds)
    assert party[0].hp > 1                                            # the lead had 1 HP
    if not env.battles:                                               # else a wild battle after the nurse
        assert all(m.hp == m.max_hp for m in party)


BEFORE_ROARK = os.path.join(ROOT, "states/milestones/15_oreburgh_gym_before_roark.state")


@pytest.mark.skipif(not (os.path.exists(ROM) and os.path.exists(BEFORE_ROARK)), reason="needs milestone 15 (scripts/make_milestones.py)")
def test_before_roark_the_party_heals_and_leaves_the_pokemon_over_his_cap(tmp_path):
    """The gym's steps back to the door, Oreburgh's Pokémon Center, and the steps up again: the
    party is healed, a Pokémon over Roark's cap goes to the PC, and the player is back at Roark."""
    import pynds
    import romdata as R
    import route
    import run_env as RE
    import scenario
    nds = pynds.PyNDS(ROM)
    nds.load_state_from_file(BEFORE_ROARK)
    nds.tick(2)
    party = scenario.read_party_data(nds)
    party[0]["level"], party[0]["exp"] = 17, R.exp_for_level(party[0]["species"], 17)
    party[1]["hp"] = 1
    scenario.write_party(nds, party)
    path = str(tmp_path / "over_cap.state")
    nds.save_state_to_file(path)
    env = RE.RunEnv(start_state=path, route_actions=[route.ROUTE[-3]])        # the mend before Roark
    env.reset(seed=0)
    assert env.end == "no_badge" and env.runner.heals == 1
    assert gen4.read_location(env.nds).map_id == 47 and gen4.read_player_tile(env.nds)[:2] == (5, 4)
    left = gen4.read_party(env.nds)
    assert len(left) == 5 and all(m.level <= 16 and m.hp == m.max_hp for m in left)
    assert party[0].pid in [m.pid for m in gen4.read_box(env.nds, 0) if m]


@needs_entrance
def test_grinding_fights_wild_battles_until_the_level(tmp_path):
    import route
    import run_env as RE
    env = RE.RunEnv(start_state=lone_turtwig(tmp_path), route_actions=[("grind", 8, route.ROUTE202_GRASS, route.SANDGEM_HEAL)])
    obs, info = env.reset(seed=0)
    assert info["decision"] == "battle" and env.trainer == 0          # a wild battle in the grass
    info = play_out(env, info)
    assert info["end"] == "no_badge"                                  # the route (one grind) played to its end
    assert [m.level for m in gen4.read_party(env.nds)] == [8]
    assert info["battles"] and all(b["trainer"] == 0 and b["outcome"] in ("WON", "CAUGHT", "FLED") for b in info["battles"])


@needs_entrance
def test_a_hurt_party_goes_to_the_pokemon_center_before_grinding(tmp_path):
    import route
    import run_env as RE
    env = RE.RunEnv(start_state=lone_turtwig(tmp_path, hp=5), route_actions=[("grind", 8, route.ROUTE202_GRASS, route.SANDGEM_HEAL)])
    obs, info = env.reset(seed=0)
    assert info["decision"] == "battle" and env.trainer == 0
    assert env.runner.heals == 1                                      # healed at Sandgem before the first wild battle
    turtwig = env.battle.snap.player[0]
    assert turtwig.hp == turtwig.max_hp


@needs_choice
def test_the_starter_is_the_first_decision_and_picks_the_ball():
    import run_env as RE
    env = RE.RunEnv()
    obs, info = env.reset(seed=0)
    assert info["decision"] == "starter" and list(np.flatnonzero(info["action_mask"])) == [0, 1, 2]
    obs, reward, term, trunc, info = env.step(1)                     # Chimchar
    assert info["decision"] == "battle" and env.trainer == 852       # Barry's first team for a Chimchar player
    assert [m.species for m in gen4.read_party(env.nds)] == [390]


@needs_choice
def test_a_run_plays_its_battles_and_ends_on_a_wipe():
    """Turtwig against Barry, then Route 201's first wild Pokémon, with the env's first allowed
    action each time: the run's rules count the route, and a loss ends the run as a wipe."""
    import run_env as RE
    env = RE.RunEnv()
    obs, info = env.reset(seed=0)
    done = False
    while not done:
        obs, reward, term, trunc, info = env.step(first_move(info))
        done = term or trunc
    assert info["battles"][0] == {"trainer": 851, "outcome": "WON", "turns": info["battles"][0]["turns"]}
    assert info["end"] == "wipe" and term and not trunc
    assert "Route 201" in info["routes"] and info["dead"] >= 1


@pytest.mark.skipif(not (os.path.exists(ROM) and os.path.exists(FAINTED)), reason="needs the fainted fixture (scripts/make_milestones.py)")
def test_a_fainted_pokemon_goes_to_the_pc_and_the_rest_are_healed():
    import pynds
    import overworld as O
    import scenario
    nds = pynds.PyNDS(ROM)
    nds.load_state_from_file(FAINTED)
    nds.tick(2)
    dead = gen4.read_party(nds)[0]
    assert dead.hp == 0
    assert scenario.deposit(nds, [0]) == [(0, 0)]
    boxed = gen4.read_box(nds, 0)[0]
    assert boxed.pid == dead.pid and boxed.checksum_ok
    assert O.talk_from(nds, None, (8, 6), "up") == "talking"
    assert O.advance_text(nds, yes=True) == "done"
    party = gen4.read_party(nds)
    assert len(party) == 5 and dead.pid not in [m.pid for m in party]
    assert all(m.hp == m.max_hp and m.checksum_ok for m in party)


@needs_choice
def test_a_run_leaves_restart_states_and_a_reset_resumes_one(tmp_path):
    import json
    import run_env as RE
    env = RE.RunEnv(restart_dir=str(tmp_path))
    obs, info = env.reset(seed=0)
    done = False
    while not done:
        obs, reward, term, trunc, info = env.step(first_move(info))
        done = term or trunc
    saved = sorted(p.name for p in tmp_path.glob("*.json"))
    assert len(saved) == len(info["battles"])                       # one per battle the run met
    barry = json.loads((tmp_path / saved[0]).read_text())
    assert barry["at"] == 0 and barry["starter"] == 387               # Barry's first battle, inside the starter's action
    for path in tmp_path.glob(saved[0].removesuffix(".json") + ".*"):  # resume from a later step
        path.unlink()
    env = RE.RunEnv(restart_dir=str(tmp_path), restart_share=1.0)
    obs, info = env.reset(seed=1)
    assert info["restart"] and info["decision"] == "battle"           # the run starts at the saved battle
    assert len(list(tmp_path.glob("*.json"))) == len(saved) - 1       # and doesn't save it again
    resumed_at = json.loads((tmp_path / (info["restart"] + ".json")).read_text())["at"]
    assert resumed_at > 0 and env.runner.at == resumed_at            # the run counts as that far from its first battle
    done = False
    while not done:
        obs, reward, term, trunc, info = env.step(first_move(info))
        done = term or trunc
    assert info["end"] in ("wipe", "badge", "no_badge")
    assert info["route_step"] >= resumed_at
