"""Tests for scenario.py. Everything needs the Kaizo ROM; the integration tests also need the
local milestone states (not in git) and take about a minute to generate scenarios.
Run: ~/venvs/nuzlockerl/bin/python -m pytest -q tests/test_scenario.py  (from ~/nuzlockeRL)"""
import os, random, sys
import numpy as np
import pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import gen4
import romdata as R
import scenario as sc

ROM = sc.DEFAULT_ROM
M = os.path.join(ROOT, "states/milestones")
MILESTONES = [os.path.join(M, f) for f in (
    "01_starter_turtwig_box_screen.state", "03_barry1_battle_turn1.state",
    "04_after_barry1_home.state", "05_route201_wild_battle.state")]

needs_rom = pytest.mark.skipif(not os.path.exists(ROM), reason="needs the Kaizo ROM (not in git)")
needs_states = pytest.mark.skipif(
    not (os.path.exists(ROM) and all(os.path.exists(p) for p in MILESTONES + [sc.START_STATE])),
    reason="needs the Kaizo ROM and local milestone states (not in git)")

SOLO = [{"species": 387, "level": 10, "moves": [33, 72, 75, 44]}]
TEAM = [{"species": 390, "level": 12, "moves": [52, 10, 43, 183]},
        {"species": 393, "level": 11, "moves": [55, 1, 145, 64]},
        {"species": 25, "level": 10, "moves": [84, 98, 86, 45]}]


def real_structs():
    """Every distinct 236-byte struct in the milestone states: party, battle copy, enemy."""
    import pynds
    nds, seen = pynds.PyNDS(ROM), {}
    for path in MILESTONES:
        nds.load_state_from_file(path)
        nds.tick(2)
        a = gen4.resolve(nds)
        for name in ("playerBase", "playerBattleBase", "enemyBase"):
            if name != "playerBase" and not gen4.in_battle(nds, a):
                continue
            raw = gen4.read_bytes(nds, a[name], gen4.PARTY_MON_SIZE * 6)
            for i in range(6):
                chunk = raw[i * gen4.PARTY_MON_SIZE:(i + 1) * gen4.PARTY_MON_SIZE]
                if chunk[:4] == bytes(4):
                    break
                seen[chunk] = os.path.basename(path)
    return seen


@pytest.fixture(scope="module")
def structs():
    return real_structs()


@needs_states
def test_encode_inverts_decode_on_real_structs(structs):
    assert len(structs) >= 4
    for raw in structs:
        assert sc.encode_mon(sc.parse_mon(raw)) == raw


@needs_states
def test_computed_values_match_real_structs(structs):
    """The stat formula, base stats, EXP curve, nature, gender and ability slot all come out
    of the hack's tables the way the game itself stored them."""
    for raw in structs:
        m = sc.parse_mon(raw)
        sp = R.species(m["species"])
        assert list(R.calc_stats(m["species"], m["level"], m.ivs, m["evs"], m.pid % 25)) == [m["max_hp"]] + m["stats"]
        assert R.level_for_exp(m["species"], m["exp"]) == m["level"]
        assert (m["form_byte"] >> 1) & 3 == sc.gender_of(m.pid, sp.gender_ratio)
        assert m["ability"] == (sp.abilities[m.pid & 1] or sp.abilities[0])
        assert not sc.is_shiny(m.pid, m["ot_id"])


@needs_rom
def test_build_mon_decodes_through_gen4():
    rng = random.Random(3)
    for species, level in ((387, 10), (25, 50), (150, 100), (292, 20)):
        mon = sc.build_mon(species, level, [33, 45], rng=rng, nature=7, ability_slot=1)
        d = gen4.decode_mon(sc.encode_mon(mon))
        assert d.checksum_ok and not d.is_egg
        assert (d.species, d.level, d.moves, d.hp) == (species, level, [33, 45, 0, 0], d.max_hp)
        assert d.pp == [R.move(33).pp, R.move(45).pp, 0, 0]
        assert mon.pid % 25 == 7 and mon.pid & 1 == 1
        assert d.exp == R.exp_for_level(species, level)
    assert gen4.decode_mon(sc.encode_mon(sc.build_mon(292, 20, [33], rng=rng))).max_hp == 1


@needs_rom
def test_build_mon_rejects_bad_input():
    for args in ((0, 5, [33]), (494, 5, [33]), (387, 0, [33]), (387, 101, [33]), (387, 5, []), (387, 5, [1] * 5)):
        with pytest.raises(ValueError):
            sc.build_mon(*args)


@needs_states
def test_write_party_reads_back_and_sets_count():
    import pynds
    nds = pynds.PyNDS(ROM)
    nds.load_state_from_file(sc.START_STATE)
    nds.tick(2)
    rng = random.Random(0)
    mons = sc.mons_from_spec(TEAM, sc.Trainer.from_mon(sc.read_party_data(nds)[0]), rng)
    sc.write_party(nds, mons)
    base = gen4.resolve(nds)["playerBase"]
    assert nds.memory.read_u32(False, base - 4) == 3
    party = gen4.read_party(nds)
    assert [(m.species, m.level, m.moves, m.checksum_ok) for m in party] == [
        (390, 12, [52, 10, 43, 183], True), (393, 11, [55, 1, 145, 64], True), (25, 10, [84, 98, 86, 45], True)]
    sc.write_party(nds, mons[:1])
    assert len(gen4.read_party(nds)) == 1 and nds.memory.read_u32(False, base - 4) == 1


@pytest.fixture(scope="module")
def scenarios(tmp_path_factory):
    d = tmp_path_factory.mktemp("scenarios")
    out = {}
    for name, party, seed in (("solo", SOLO, 1), ("team", TEAM, 2)):
        path = str(d / f"{name}.state")
        out[name] = (path, sc.make_scenario(party, path, seed, enemy=(396, 5)))
    return out


@needs_states
def test_scenario_battle_copy_and_forced_enemy(scenarios):
    import pynds
    nds = pynds.PyNDS(ROM)
    for name, spec in (("solo", SOLO), ("team", TEAM)):
        path, record = scenarios[name]
        assert record["enemy"]["species"] == 396 and record["enemy"]["level"] == 5
        nds.load_state_from_file(path)
        nds.tick(2)
        a = gen4.resolve(nds)
        assert gen4.in_battle(nds, a) and gen4.waiting_for_command(nds, a)
        battle = gen4.read_party(nds, a["playerBattleBase"])
        assert [(m.species, m.level, m.moves) for m in battle] == [(s["species"], s["level"], s["moves"]) for s in spec]
        assert all(m.checksum_ok and m.hp == m.max_hp > 0 for m in battle)
        assert battle[0].pp == [R.move(mv).pp for mv in spec[0]["moves"]]


def play_greedy(env, path, seed):
    env.reset(seed=seed, options={"state": path})
    from battle_env import action_mask
    for _ in range(100):
        _, _, term, trunc, info = env.step(int(np.flatnonzero(action_mask(env.snap))[0]))
        if term or trunc:
            return info["outcome"]


@pytest.fixture(scope="module")
def env():
    from battle_env import BattleEnv
    e = BattleEnv([], ROM)
    yield e
    e.close()


@needs_states
def test_scenarios_play_to_the_end(env, scenarios):
    for name in ("solo", "team"):
        assert play_greedy(env, scenarios[name][0], 0) == "WON"


@needs_states
def test_action_mask_and_move_slot_taps(env, scenarios):
    """Each slot's tap lowers exactly that slot's PP by 1, so BattleEnv's slot 2 and 3 guesses are right."""
    path = scenarios["solo"][0]
    for slot in range(4):
        env.reset(seed=slot, options={"state": path})
        assert env.snap.player[0].moves == SOLO[0]["moves"]
        assert env.snap.player[0].pp == [R.move(mv).pp for mv in SOLO[0]["moves"]]
        from battle_env import action_mask
        assert action_mask(env.snap)[:4].all()
        before = list(env.snap.player[0].pp)
        env.step(slot)
        after = env.snap.player[0].pp
        assert [b - a for b, a in zip(before, after)] == [int(i == slot) for i in range(4)]
