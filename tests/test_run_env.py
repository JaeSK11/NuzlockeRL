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
needs_choice = pytest.mark.skipif(not (os.path.exists(ROM) and os.path.exists(CHOICE)),
                                  reason="needs the ROM and milestone 01_starter_choice (scripts/make_milestones.py)")


def first_move(info):
    return next(a for a in range(len(info["action_mask"])) if info["action_mask"][a])


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
    env = RE.RunEnv(restart_dir=str(tmp_path), restart_share=1.0)
    obs, info = env.reset(seed=1)
    assert info["restart"] and info["decision"] == "battle"           # the run starts at the saved battle
    assert len(list(tmp_path.glob("*.json"))) == len(saved)           # and doesn't save it again
    done = False
    while not done:
        obs, reward, term, trunc, info = env.step(first_move(info))
        done = term or trunc
    assert info["end"] in ("wipe", "badge", "no_badge")
