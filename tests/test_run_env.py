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


def lone_turtwig(tmp_path, level=7, hp=None, species=387, moves=None, exp=None):
    """The Route 202 fixture with a lone Turtwig, as a run brings it there, and the route's wild
    encounters back on (the milestone script turns them off). `species`, `moves` and `exp` set
    another Pokémon in its place."""
    import random
    import pynds
    import romdata as R
    import scenario
    nds = pynds.PyNDS(ROM)
    nds.load_state_from_file(ENTRANCE)
    nds.tick(2)
    mon = scenario.build_mon(species, level, moves or R.default_moves(species, level), ivs=15,
                             trainer=scenario.Trainer.from_mon(scenario.read_party_data(nds)[0]), rng=random.Random(0))
    if hp is not None:
        mon["hp"] = hp
    if exp is not None:
        mon["exp"] = exp
    scenario.write_party(nds, [mon])
    nds.memory.write_u32(False, gen4.resolve(nds)["_version"] + scenario.ENCOUNTER_OFFSET, R.encounters_for_map(343).grass_rate)
    path = str(tmp_path / "lone_turtwig.state")
    nds.save_state_to_file(path)
    return path


def take_all(env, info):
    """Answer each PC choice with "take along", so the party stays as it is."""
    while info["decision"] == "pc":
        _, _, _, _, info = env.step(0)                                  # run_env.PC_TAKE
    return info


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
    take_all(env, env.reset(seed=0)[1])
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
    _, info = env.reset(seed=0)
    asked = 0
    while info["decision"] == "pc":                                         # the five under the cap
        asked += 1
        _, _, _, _, info = env.step(RE.PC_TAKE)
    assert asked == 5 and env.end == "no_badge" and env.runner.heals == 1
    assert gen4.read_location(env.nds).map_id == 47 and gen4.read_player_tile(env.nds)[:2] == (5, 4)
    left = gen4.read_party(env.nds)
    assert len(left) == 5 and all(m.level <= 16 and m.hp == m.max_hp for m in left)
    assert party[0].pid in [m.pid for m in gen4.read_box(env.nds, 0) if m]


def test_the_pc_rules():
    """pc_options: (may take along, may leave in the PC) for the k-th living Pokémon."""
    import run_env as RE
    assert RE.pc_options([10], 0, [], None) == (True, False)                # a party never runs empty
    assert RE.pc_options([10, 12], 0, [], None) == (True, True)
    assert RE.pc_options([10, 12], 1, [False], None) == (True, False)
    assert RE.pc_options([10] * 7, 6, [True] * 6, None) == (False, True)    # six at most
    assert RE.pc_options([24, 10], 0, [], 16) == (False, True)              # over the cap: to the PC
    assert RE.pc_options([10, 24], 0, [], 16) == (True, False)              # the one under it comes along
    assert RE.pc_options([10, 24], 1, [True], 16) == (False, True)
    assert RE.pc_options([24], 0, [], 16) == (True, False)                  # none meets the cap: Roark turns it down


@pytest.mark.skipif(not (os.path.exists(ROM) and os.path.exists(BEFORE_ROARK)), reason="needs milestone 15 (scripts/make_milestones.py)")
def test_a_pokemon_taken_out_of_the_pc_is_the_one_put_in():
    """pc_swap's withdraw rebuilds the party struct from the box's 136 bytes: the level from EXP,
    the stats from the hack's tables. It must match what the game had computed."""
    import pynds
    import scenario
    nds = pynds.PyNDS(ROM)
    nds.load_state_from_file(BEFORE_ROARK)
    nds.tick(2)
    party = gen4.read_party(nds)
    assert scenario.pc_swap(nds, [0, 2]) == [(0, 0), (0, 1)]
    assert sorted(scenario.read_box_data(nds)) == [(0, 0), (0, 1)]
    assert scenario.pc_swap(nds, [], [(0, 1)]) == []
    after = gen4.read_party(nds)
    assert [m.pid for m in after] == [party[k].pid for k in (1, 3, 4, 5, 2)]
    back, before = after[-1], party[2]
    assert back.checksum_ok and (back.level, back.max_hp, back.stats, back.moves) == (
        before.level, before.max_hp, before.stats, before.moves)
    assert back.hp == back.max_hp and sorted(scenario.read_box_data(nds)) == [(0, 0)]


@pytest.mark.skipif(not (os.path.exists(ROM) and os.path.exists(BEFORE_ROARK)), reason="needs milestone 15 (scripts/make_milestones.py)")
def test_before_roark_a_lone_pokemon_over_his_cap_stays_and_the_agent_picks_from_the_pc(tmp_path):
    """The cap is a hard rule: the Pokémon over it can't come along while one under it can. The
    agent picks which of the PC's Pokémon come out; it sees them and the cap."""
    import pynds
    import battle_env as BE
    import romdata as R
    import route
    import run_env as RE
    import scenario
    nds = pynds.PyNDS(ROM)
    nds.load_state_from_file(BEFORE_ROARK)
    nds.tick(2)
    party = scenario.read_party_data(nds)
    party[0]["level"], party[0]["exp"] = 17, R.exp_for_level(party[0]["species"], 17)
    scenario.write_party(nds, party)
    scenario.deposit(nds, [1, 2, 3, 4, 5])
    path = str(tmp_path / "lone_over_cap.state")
    nds.save_state_to_file(path)
    env = RE.RunEnv(start_state=path, route_actions=[route.ROUTE[-3]])
    obs, info = env.reset(seed=0)
    assert info["decision"] == "pc"
    assert obs[BE.OBS_SLICES["pc_asked"]].tolist() == [0] * 6 + [1] + [0] * 5      # the PC's first
    assert obs[BE.OBS_SLICES["level_cap"]][0] == pytest.approx(0.16)
    assert [obs[BE.OBS_SLICES[f"box{i}.alive"]][0] for i in range(6)] == [1] * 5 + [0]
    asked = 0
    for action in (RE.PC_LEAVE,) + (RE.PC_TAKE,) * 4:
        asked += 1
        _, _, _, _, info = env.step(action)
        if info["decision"] != "pc":
            break
    assert asked == 5 and env.end == "no_badge"
    team = gen4.read_party(env.nds)
    assert [m.pid for m in team] == [party[k].pid for k in (2, 3, 4, 5)]
    assert all(m.level <= 16 and m.hp == m.max_hp and m.checksum_ok for m in team)
    assert {party[0].pid, party[1].pid} <= {m.pid for m in gen4.read_box(env.nds, 0) if m}


@pytest.mark.skipif(not (os.path.exists(ROM) and os.path.exists(FAINTED)), reason="needs the fainted fixture (scripts/make_milestones.py)")
def test_a_fainted_pokemon_stays_in_the_pc_and_is_never_offered():
    import run_env as RE
    env = RE.RunEnv(start_state=FAINTED, route_actions=[("heal",), ("heal",)])
    _, info = env.reset(seed=0)
    asked = 0
    while info["decision"] == "pc":
        asked += 1
        _, _, _, _, info = env.step(RE.PC_TAKE)
    assert asked == 10 and env.runner.heals == 2                        # five living, twice
    box = [m for m in gen4.read_box(env.nds, 0) if m]
    assert len(box) == 1 and box[0].pid in env.run.dead
    assert len(gen4.read_party(env.nds)) == 5


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
def test_a_run_that_ends_without_the_badge_is_paid_as_a_loss(tmp_path, monkeypatch):
    import route
    import run_env as RE
    monkeypatch.setattr(RE, "NO_BADGE_REWARD", -1000.0)               # far below any battle's reward
    env = RE.RunEnv(start_state=lone_turtwig(tmp_path), route_actions=[("grind", 8, route.ROUTE202_GRASS, route.SANDGEM_HEAL)])
    obs, info = env.reset(seed=0)
    rewards, done = [], False
    while not done:
        obs, reward, term, trunc, info = env.step(first_move(info))
        rewards.append(reward)
        done = term or trunc
    assert info["end"] == "no_badge" and rewards[-1] < -900 and all(r > -900 for r in rewards[:-1])
    assert info["run_return"] == pytest.approx(sum(rewards))


@needs_entrance
def test_a_catch_is_paid_and_the_rules_mask_a_second_one_on_the_route(tmp_path, monkeypatch):
    """The rules, not the agent, keep catches to one per route: after Route 202's first wild
    Pokémon is caught, the ball is masked in the route's next wild battle, balls or not."""
    import battle_env as BE
    import route
    import run_env as RE
    monkeypatch.setattr(RE, "CATCH_REWARD", 1000.0)                  # far above any battle's reward
    env = RE.RunEnv(start_state=lone_turtwig(tmp_path), route_actions=[("grind", 8, route.ROUTE202_GRASS, route.SANDGEM_HEAL)])
    obs, info = env.reset(seed=0)
    assert info["decision"] == "battle" and env.trainer == 0 and env.battle.catch_allowed
    off = 4 * sum(n for _, n in gen4.BAG_POCKETS[:6])                 # the Poké Balls pocket
    for bag in ("bag", "bagBattle"):                                  # five Master Balls (item 1), first in it
        env.nds.memory.write_u16(False, env.battle.addrs[bag] + off, 1)
        env.nds.memory.write_u16(False, env.battle.addrs[bag] + off + 2, 5)
    obs, reward, term, trunc, info = env.step(BE.BALL_ACTION)
    assert env.battles[-1]["outcome"] == "CAUGHT" and reward == pytest.approx(1000.0)
    assert len(env.run.caught_lines) == 1 and "Route 202" in env.run.routes
    info = take_all(env, info)
    assert info["decision"] == "battle" and env.trainer == 0
    assert gen4.read_bag(env.nds, env.battle.addrs, from_battle=True)["balls"], "balls are left"
    assert not env.battle.catch_allowed and not info["action_mask"][BE.BALL_ACTION]


def evolve_kricketot(tmp_path, moves):
    """A Kricketot one EXP short of level 10 with these four moves, played through a wild battle
    that evolves it into a Kricketune, whose level-10 move is False Swipe."""
    import route
    import romdata as R
    import run_env as RE
    start = lone_turtwig(tmp_path, level=9, species=401, moves=moves, exp=R.exp_for_level(401, 10) - 1)
    env = RE.RunEnv(start_state=start, route_actions=[("grind", 10, route.ROUTE202_GRASS, route.SANDGEM_HEAL)])
    obs, info = env.reset(seed=0)
    play_out(env, info)
    (mon,) = gen4.read_party(env.nds)
    assert mon.species == 402 and mon.level == 10
    return [R.move_name(m) for m in mon.moves]


@needs_entrance
def test_an_evolutions_fifth_move_replaces_the_weakest(tmp_path):
    """Tackle, Growl, Leer and Bite: the status moves are worth nothing, so Growl (slot 1) goes,
    where the game's first choice would be Tackle."""
    assert evolve_kricketot(tmp_path, [33, 45, 43, 44]) == ["Tackle", "False Swipe", "Leer", "Bite"]


@needs_entrance
def test_an_evolution_keeps_four_better_moves(tmp_path):
    """Four moves worth more than False Swipe: the new move is given up."""
    assert evolve_kricketot(tmp_path, [163, 2, 280, 405]) == ["Slash", "Karate Chop", "Brick Break", "Bug Buzz"]


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


@pytest.mark.skipif(not (os.path.exists(ROM) and os.path.exists(os.path.join(ROOT, "states/walk/start/199_oreburgh_mine_b2f.state"))),
                    reason="needs the map start states (scripts/make_milestones.py)")
def test_a_battle_inside_a_heal_trip_leaves_no_restart_state(tmp_path):
    """A restart resumes the route action it interrupted from that action's start, and a heal
    trip half done can't be: the mine's would exit to the floor the player is on."""
    import route
    import run_env as RE
    start = hurt_state(tmp_path, os.path.join(ROOT, "states/walk/start/199_oreburgh_mine_b2f.state"))
    restarts = tmp_path / "restarts"
    env = RE.RunEnv(start_state=start, route_actions=[("mend", route.MINE_HEAL)], restart_dir=str(restarts))
    info = take_all(env, env.reset(seed=0)[1])
    assert not env.end and info["decision"] == "battle"               # the mine's wild battle on the trip
    play_out(env, info)
    assert env.end == "no_badge" and env.battles
    assert not list(restarts.glob("*.json"))


@needs_choice
@pytest.mark.parametrize("fails", [3, 4])
def test_a_restart_that_ends_in_a_route_error_is_dropped(tmp_path, fails):
    """Restarts saved inside a heal trip before that was ruled out resume into a route error.
    One that fails in the very route action it resumed (3), or in a later one before the next
    battle (4, as after a mend that found nothing to heal), is dropped, so bad states heal away."""
    import json
    import pynds
    import route
    import run_env as RE
    import scenario
    env = RE.RunEnv(restart_dir=str(tmp_path))
    play_out(env, env.reset(seed=0)[1])
    at3 = [p for p in tmp_path.glob("003_*.json")]                    # Route 201's wild battles
    assert at3
    for p in tmp_path.glob("*.json"):
        if p not in at3[:1]:
            p.unlink()
    broken = list(route.ROUTE)
    broken[fails] = ("exit", 9999)                                     # no way there: the action fails
    meta = json.loads(at3[0].read_text())
    meta["action"] = repr(broken[3])
    at3[0].write_text(json.dumps(meta))
    nds = pynds.PyNDS(ROM)                                             # no wild battle after the resumed one
    nds.load_state_from_file(str(at3[0].with_suffix(".state")))
    nds.memory.write_u32(False, gen4.resolve(nds)["_version"] + scenario.ENCOUNTER_OFFSET, 0)
    nds.save_state_to_file(str(at3[0].with_suffix(".state")))
    env = RE.RunEnv(restart_dir=str(tmp_path), restart_share=1.0, route_actions=broken)
    obs, info = env.reset(seed=1)
    assert info["restart"] == at3[0].stem
    info = play_out(env, info)
    assert info["end"] == "route_error"                               # the battle won, the exit failed
    assert not at3[0].exists() and not at3[0].with_suffix(".state").exists()
