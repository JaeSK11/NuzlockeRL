"""Tests for battle_env.py. The events_between tests need no emulator; the rest need the
Kaizo ROM and the local milestone states (not in git).
Run: ~/venvs/nuzlockerl/bin/python -m pytest -q tests  (from ~/nuzlockeRL)"""
import hashlib, json, os, sys
import numpy as np
import pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import gen4
import pynds
import romdata
import scenario
from battle_env import (BattleEnv, Event, FIGHT_XY, OBS_FIELDS, OBS_SIZE, OBS_SLICES, REWARDS, Snapshot,
                        action_mask, events_between, observation)

ROM = os.environ.get("NUZLOCKERL_ROM", os.path.join(ROOT, "roms/plat-kaizo-nightmare-update-final.nds"))
M = os.path.join(ROOT, "states/milestones")
BARRY, WILD = (os.path.join(M, s) for s in ("03_barry1_battle_turn1.state", "05_route201_wild_battle.state"))

needs_rom = pytest.mark.skipif(
    not (os.path.exists(ROM) and os.path.isdir(M)),
    reason="needs the Kaizo ROM and local milestone save states (not in git)")

GEN = os.path.join(ROOT, "states/generated")
CHIMCHAR, PIPLUP, PIKACHU, TURTWIG, STARLY, BIDOOF, EEVEE = 390, 393, 25, 387, 396, 399, 133
TEAM3 = [{"species": CHIMCHAR, "level": 12, "moves": [52, 10, 43, 183]},
         {"species": PIPLUP, "level": 11, "moves": [55, 1, 145, 64]},
         {"species": PIKACHU, "level": 10, "moves": [84, 98, 86, 45]}]
TEAM6 = [{"species": CHIMCHAR, "level": 12, "moves": [52, 10]}, {"species": PIPLUP, "level": 11, "moves": [55, 1]},
         {"species": PIKACHU, "level": 10, "moves": [84, 98]}, {"species": TURTWIG, "level": 10, "moves": [33, 72]},
         {"species": STARLY, "level": 8, "moves": [33, 28]}, {"species": BIDOOF, "level": 7, "moves": [33]}]
# Turtwig's two moves have 1 PP each (Tail Whip, Meditate), so two turns leave it with none. Pikachu is alive.
NO_PP = [{"species": TURTWIG, "level": 10, "moves": [39, 96]}, {"species": PIKACHU, "level": 10, "moves": [84, 98]}]
WEAKLEAD = [{"species": PIKACHU, "level": 2, "moves": [84, 45]}, {"species": TURTWIG, "level": 15, "moves": [33, 72, 75, 44]}]
SCENARIOS = {   # name: (party, wild enemy (species, level) or None, seed); built on first use, as make_scenario.py does
    "team3": (TEAM3, None, 2), "team_vs_starly12": (TEAM3, (STARLY, 12), 4),
    "team6_vs_starly12": (TEAM6, (STARLY, 12), 5), "no_pp_vs_starly12": (NO_PP, (STARLY, 12), 3),
    "weaklead_vs_eevee": (WEAKLEAD, (EEVEE, 13), 7)}


def scenario_state(name):
    path = os.path.join(GEN, name + ".state")
    if not os.path.exists(path):
        party, enemy, seed = SCENARIOS[name]
        scenario.make_scenario(party, path, seed, ROM, enemy=enemy)
    return path


def snap(player_hp, enemy_hp):
    mon = lambda hp: gen4.Mon(pid=1, checksum_ok=True, species=1, hp=hp, max_hp=20)
    return Snapshot(tuple(map(mon, player_hp)), tuple(map(mon, enemy_hp)), 0, 0, (6,) * 8, (6,) * 8)


def test_events_between():
    assert events_between(snap([10], [10]), snap([8], [4])) == []
    assert events_between(snap([10, 5], [10, 7]), snap([10, 0], [10, 7])) == [Event.PLAYER_FAINTED]
    assert events_between(snap([10], [10, 7]), snap([10], [0, 7])) == [Event.ENEMY_FAINTED]
    assert events_between(snap([10], [3]), snap([10], [0])) == [Event.ENEMY_FAINTED, Event.WON]
    assert events_between(snap([3, 0], [9]), snap([0, 0], [9])) == [Event.PLAYER_FAINTED, Event.LOST]
    assert events_between(snap([3], [3]), snap([0], [0])) == [Event.PLAYER_FAINTED, Event.ENEMY_FAINTED, Event.LOST]
    assert events_between(snap([0, 4], [5]), snap([0, 4], [5])) == []


def test_event_rewards_use_only_faints_and_endings():
    assert REWARDS[Event.TURN_CAP] == REWARDS[Event.LOST] < REWARDS[Event.PLAYER_FAINTED] < 0
    assert REWARDS[Event.STUCK] == REWARDS[Event.ENDED] == 0


@pytest.fixture(scope="module")
def env():
    e = BattleEnv([BARRY, WILD], ROM)
    yield e
    e.close()


def play(env, state, actions, seed=None, keep_rng=False):
    """Returns (info of reset, [(hp before, action, reward, events, terminated, truncated, info)])."""
    _, info0 = env.reset(seed=seed, options={"state": state, "keep_rng": keep_rng})
    rows = []
    for a in actions:
        hp = (env.snap.player[0].hp, env.snap.enemy[0].hp)
        _, r, term, trunc, info = env.step(a)
        rows.append((hp, a, r, info["events"], term, trunc, info))
        if term or trunc:
            break
    return info0, rows


def result_masks_after_end(env):
    """resultMask values seen while the battle memory is still valid, tapping A through the text.
    The battle is over once in_battle() stays False for 3 frames: for a single frame it also
    reads False while the game holds the battle struct decrypted in place."""
    seen, gone = [], 0
    for k in range(3000):
        env.nds.tick()
        if k % 66 == 0:
            env.nds.button.press_key("a"); env.nds.tick(6); env.nds.button.release_key("a")
        if not gen4.in_battle(env.nds, env.addrs):
            gone += 1
            if gone == 3:
                return seen
            continue
        gone = 0
        v = env.nds.memory.read_u8(False, env.addrs["battleResult"])
        if not seen or seen[-1] != v:
            seen.append(v)
    raise AssertionError("battle never ended")


@needs_rom
def test_barry_with_fixed_rng_is_won_in_five_turns(env):
    _, rows = play(env, BARRY, [0] * 10, keep_rng=True)
    assert [r[0] for r in rows] == [(21, 19), (18, 15), (15, 11), (12, 7), (9, 3)]
    assert [r[4] for r in rows] == [False] * 4 + [True]
    assert rows[-1][3] == ["ENEMY_FAINTED", "WON"]
    assert sum(r[2] for r in rows) == 6.0 and rows[-1][6]["outcome"] == "WON"
    assert 1 in result_masks_after_end(env)


@needs_rom
def test_same_seed_repeats_and_different_seeds_differ(env):
    def trajectory(seed):
        info0, rows = play(env, BARRY, [0] * 10, seed=seed)
        return info0["rng_seed"], [(r[0], r[3]) for r in rows]
    assert trajectory(11) == trajectory(11)
    runs = [trajectory(s) for s in range(6)]
    assert len({seed for seed, _ in runs}) == 6
    assert len({tuple(hp for hp, _ in t) for _, t in runs}) >= 2


@needs_rom
def test_turn_cap_is_a_loss():
    e = BattleEnv([BARRY], ROM, turn_cap=2)
    _, rows = play(e, BARRY, [0] * 5, keep_rng=True)
    e.close()
    assert len(rows) == 2 and rows[0][4] is False
    reward, events, term, trunc, info = rows[1][2:]
    assert (reward, events, term, trunc) == (-10.0, ["TURN_CAP"], True, False)
    assert info["outcome"] == "TURN_CAP"


@needs_rom
def test_action_masks(env):
    info, _ = play(env, BARRY, [])
    assert info["action_mask"].tolist() == [True] + [False] * 8 and info["input_mode"] == 0
    with pytest.raises(ValueError):
        env.step(1)
    env.step(0)

    info, _ = play(env, WILD, [])
    assert info["action_mask"].tolist() == [True, True] + [False] * 7 and info["input_mode"] == 1
    for masked in (2, 4):
        with pytest.raises(ValueError):
            env.step(masked)


@needs_rom
def test_move_slot_1_uses_mega_drain(env):
    play(env, WILD, [], keep_rng=True)
    before = env.snap.player[0]
    assert before.moves[:2] == [33, 72]
    env.step(1)
    after = env.snap.player[0]
    assert (after.pp[0], after.pp[1]) == (before.pp[0], before.pp[1] - 1)


@needs_rom
def test_wild_battle_with_fixed_rng_is_lost_in_two_turns(env):
    _, rows = play(env, WILD, [0] * 5, keep_rng=True)
    assert [(r[0], r[3]) for r in rows] == [((23, 17), []), ((11, 12), ["PLAYER_FAINTED", "LOST"])]
    assert rows[-1][4] and rows[-1][2] == -13.0 and rows[-1][6]["outcome"] == "LOST"
    assert env.snap.player[0].hp == 0
    seen = result_masks_after_end(env)
    assert 2 in seen and 1 not in seen


@needs_rom
def test_log_file(tmp_path):
    log = tmp_path / "log.jsonl"
    e = BattleEnv([BARRY], ROM, turn_cap=1, log_path=str(log))
    play(e, BARRY, [0], keep_rng=True)
    e.close()
    step, summary = [json.loads(line) for line in log.read_text().splitlines()]
    assert set(step) == {"episode", "state", "rng_seed", "turn", "action", "forced", "events", "reward",
                         "player_hp", "enemy_hp", "frames"}
    assert step["forced"] is False
    assert step["events"] == ["TURN_CAP"] and step["player_hp"] == [18] and step["enemy_hp"] == [15]
    assert set(summary) >= {"episode", "outcome", "turns", "return", "frames"}
    assert summary["outcome"] == "TURN_CAP" and summary["return"] == -10.0


def battle_frames(info0, rows):
    return info0["frames"] + sum(r[6]["frames"] for r in rows)


@needs_rom
def test_fast_battles_keep_the_rng_path_and_cut_frames(env):
    slow = BattleEnv([BARRY], ROM, fast_battles=False)
    info_s, rows_s = play(slow, BARRY, [0] * 10, keep_rng=True)
    slow.close()
    info_f, rows_f = play(env, BARRY, [0] * 10, keep_rng=True)
    assert [r[0] for r in rows_f] == [r[0] for r in rows_s]
    assert [r[3] for r in rows_f] == [r[3] for r in rows_s]
    assert battle_frames(info_f, rows_f) <= 0.8 * battle_frames(info_s, rows_s)


@needs_rom
@pytest.mark.parametrize("state", [BARRY, WILD])
def test_reset_writes_fast_options_and_keeps_the_other_bits(env, state):
    raw = {}
    for fast in (False, True):
        e = env if fast else BattleEnv([state], ROM, fast_battles=False)
        e.reset(options={"state": state, "keep_rng": True})
        raw[fast] = gen4.read_battle_options(e.nds, e.addrs)
        if not fast:
            e.close()
    written, saved = (gen4.decode_options(raw[f]) for f in (True, False))
    assert (written["text_speed"], written["battle_style"], written["battle_scene"]) == (
        gen4.TEXT_FAST, gen4.STYLE_SET, gen4.SCENE_OFF)
    for k in ("sound_mode", "button_mode", "frame"):
        assert written[k] == saved[k]


@pytest.fixture(scope="module")
def team_env():
    e = BattleEnv([BARRY], ROM)
    yield e
    e.close()


def reset_on(env, name, seed=1):
    return env.reset(seed=seed, options={"state": scenario_state(name)})


def active_pid(env):
    return env.nds.memory.read_u32(False, env.addrs["playerBattleMonPID"])


@needs_rom
def test_switch_makes_the_target_active_and_the_game_keeps_the_menu_order(team_env):
    env = team_env
    _, info = reset_on(env, "team3")
    start = [m.pid for m in env.snap.player]
    assert info["action_mask"].tolist() == [True] * 6 + [False] * 3
    _, reward, term, trunc, info = env.step(4)
    assert (term, trunc, info["switched_in"]) == (False, False, True)
    assert active_pid(env) == start[1]
    assert info["turn"] == 1 and info["forced_switch"] is False
    env.step(4)
    assert active_pid(env) == start[0], "position 1 is now the Pokémon that switched out"
    env.step(5)
    assert active_pid(env) == start[2]


@needs_rom
@pytest.mark.parametrize("action", [4, 5, 6, 7, 8])
def test_every_switch_position_reaches_its_pokemon(team_env, action):
    _, info = reset_on(team_env, "team6_vs_starly12")
    start = [m.pid for m in team_env.snap.player]
    assert info["action_mask"].tolist() == [True] * 2 + [False] * 2 + [True] * 5
    _, _, _, trunc, info = team_env.step(action)
    assert not trunc and info["switched_in"]
    assert active_pid(team_env) == start[action - 3]


@needs_rom
def test_a_dead_or_active_pokemon_cannot_be_switched_to(team_env):
    reset_on(team_env, "team3")
    for action in (6, 7, 8):
        with pytest.raises(ValueError):
            team_env.step(action)


def play_until_forced(env, seed=1, turn_cap=100):
    """Leer (slot 2) every turn, so the lead faints with teammates alive."""
    _, info = env.reset(seed=seed, options={"state": scenario_state("team_vs_starly12")})
    rows = []
    while not env.forced:
        _, r, term, trunc, info = env.step(2)
        rows.append((r, info["events"], term, trunc))
        assert not (term or trunc), rows
    return info, rows


@needs_rom
def test_forced_switch_is_a_decision_that_only_allows_alive_teammates(team_env):
    info, rows = play_until_forced(team_env)
    assert rows[-1] == (-3.0, ["PLAYER_FAINTED"], False, False)
    assert info["forced_switch"] is True and info["turn"] == len(rows)
    assert info["action_mask"].tolist() == [False] * 4 + [True, True] + [False] * 3
    assert team_env.snap.player[0].hp == 0
    obs = observation(team_env.snap, info["turn"], team_env.turn_cap, True)
    assert obs[OBS_SLICES["forced_switch"]][0] == 1.0
    with pytest.raises(ValueError):
        team_env.step(0)
    piplup = team_env.snap.player[1].pid
    _, reward, term, trunc, info = team_env.step(4)
    assert (reward, info["events"], term, trunc) == (0.0, [], False, False), "the faint was already rewarded"
    assert info["switched_in"] and active_pid(team_env) == piplup
    assert info["forced_switch"] is False and info["turn"] == len(rows)


@needs_rom
def test_battle_continues_to_an_end_after_the_forced_switch(team_env):
    play_until_forced(team_env)
    action, term, trunc, info = 4, False, False, {}
    for _ in range(40):
        _, _, term, trunc, info = team_env.step(action)
        if term or trunc:
            break
        action = int(np.flatnonzero(info["action_mask"])[0])
    assert term and not trunc and info["outcome"] in ("WON", "LOST")


@needs_rom
def test_forced_switch_does_not_count_toward_the_turn_cap():
    e = BattleEnv([BARRY], ROM, turn_cap=8)
    info, rows = play_until_forced(e)
    assert len(rows) == 7
    _, _, term, trunc, info = e.step(4)
    assert (term, trunc, info["turn"]) == (False, False, 7)
    _, reward, term, trunc, info = e.step(0)
    e.close()
    assert (term, trunc, info["turn"], info["outcome"]) == (True, False, 8, "TURN_CAP")


@needs_rom
def test_struggle_is_the_only_action_with_no_pp_and_the_game_uses_it(team_env):
    env = team_env
    _, info = reset_on(env, "no_pp_vs_starly12", seed=0)
    enemy_hp = env.snap.enemy[0].hp
    assert info["action_mask"].tolist() == [True, True, False, False, True] + [False] * 4
    env.step(0)
    _, _, _, _, info = env.step(1)
    assert env.snap.player[0].pp == [0, 0, 0, 0]
    assert env.snap.enemy[0].hp == enemy_hp, "Tail Whip and Meditate do no damage"
    assert info["action_mask"].tolist() == [True] + [False] * 8, "a living teammate is masked too"
    obs = observation(env.snap, 2, env.turn_cap)
    assert [obs[OBS_SLICES[f"party0.move{k}.valid"]][0] for k in range(2)] == [0.0, 0.0]
    _, _, term, trunc, info = env.step(0)
    assert not trunc and info["events"] == [], info
    assert env.snap.enemy[0].hp < enemy_hp, "Struggle hit the enemy"
    assert env.snap.player[0].pp == [0, 0, 0, 0]


def check_observation(env, obs):
    assert obs.shape == env.observation_space.shape == (OBS_SIZE,) and obs.dtype == np.float32
    assert np.isfinite(obs).all() and env.observation_space.contains(obs)


@needs_rom
@pytest.mark.parametrize("state", ["team3", "team6_vs_starly12", "no_pp_vs_starly12", BARRY, WILD])
def test_observation_is_finite_and_in_range_through_a_battle(team_env, state):
    env = team_env
    obs, info = env.reset(seed=3, options={"state": state if os.path.isabs(state) else scenario_state(state)})
    check_observation(env, obs)
    rng = np.random.default_rng(0)
    for _ in range(12):
        obs, _, term, trunc, info = env.step(rng.choice(np.flatnonzero(info["action_mask"])))
        check_observation(env, obs)
        if term or trunc:
            break


def test_observation_layout_is_one_contiguous_table():
    assert OBS_SIZE == sum(size for _, size in OBS_FIELDS) and OBS_SIZE > 0
    edges = [(OBS_SLICES[name].start, OBS_SLICES[name].stop) for name, _ in OBS_FIELDS]
    assert edges[0][0] == 0 and edges[-1][1] == OBS_SIZE
    assert all(a[1] == b[0] for a, b in zip(edges, edges[1:]))


def field(obs, name):
    return obs[OBS_SLICES[name]]


@needs_rom
def test_observation_carries_types_and_move_features_from_the_rom(team_env):
    env = team_env
    obs, _ = reset_on(env, "team3")
    types = romdata.TYPE_NAMES
    hot = lambda name: [types[i] for i in np.flatnonzero(field(obs, name))]
    assert (hot("party0.types"), hot("party1.types"), hot("party2.types")) == (["Fire"], ["Water"], ["Electric"])
    assert hot("enemy.types") == ["Normal", "Flying"]
    assert hot("party0.move0.type") == ["Fire"] and field(obs, "party0.move0.class").tolist() == [0, 1, 0]
    assert hot("party0.move1.type") == ["Normal"] and field(obs, "party0.move1.class").tolist() == [1, 0, 0]
    assert field(obs, "party0.move2.class").tolist() == [0, 0, 1] and field(obs, "party0.move2.power")[0] == 0
    ember, scratch = romdata.move(52), romdata.move(10)
    assert field(obs, "party0.move0.power")[0] == pytest.approx(ember.power / 250)
    assert field(obs, "party0.move1.accuracy")[0] == pytest.approx(scratch.accuracy / 100)
    assert field(obs, "party0.level")[0] == pytest.approx(0.12) and field(obs, "party0.hp")[0] == 1.0
    assert [field(obs, f"party{i}.active")[0] for i in range(3)] == [1, 0, 0]
    assert field(obs, "party3.alive")[0] == 0 and not field(obs, "party3.types").any()
    assert not field(obs, "stages_player").any() and not field(obs, "stages_enemy").any()
    assert field(obs, "turn")[0] == 0 and field(obs, "forced_switch")[0] == 0


@needs_rom
def test_observation_follows_the_party_menu_order_after_a_switch(team_env):
    env = team_env
    reset_on(env, "team3")
    obs, *_ = env.step(4)
    types = romdata.TYPE_NAMES
    assert [types[i] for i in np.flatnonzero(field(obs, "party0.types"))] == ["Water"]
    assert [field(obs, f"party{i}.active")[0] for i in range(3)] == [1, 0, 0]
    assert [types[i] for i in np.flatnonzero(field(obs, "party1.types"))] == ["Fire"]
    assert field(obs, "turn")[0] == pytest.approx(1 / env.turn_cap)


@needs_rom
def test_observation_of_status_hp_and_pp_for_a_made_up_snapshot():
    mon = lambda **kw: gen4.Mon(pid=kw.pop("pid"), checksum_ok=True, **kw)
    ember_pp = romdata.move(52).pp
    hurt = mon(pid=1, species=CHIMCHAR, level=50, hp=10, max_hp=40, status=0x10, moves=[52, 0, 0, 0],
               pp=[ember_pp // 2, 0, 0, 0])
    foe = mon(pid=2, species=STARLY, level=20, hp=5, max_hp=20, status=0x03, moves=[0] * 4, pp=[0] * 4)
    fainted_foe = mon(pid=3, species=STARLY, level=20, hp=0, max_hp=20, moves=[0] * 4, pp=[0] * 4)
    snap = Snapshot((hurt,), (foe, fainted_foe), 0, 0, (7,) * 8, (3,) * 8)
    obs = observation(snap, 5, 10)
    assert field(obs, "party0.hp")[0] == 0.25 and field(obs, "party0.level")[0] == 0.5
    assert field(obs, "party0.status").tolist() == [0, 0, 1, 0, 0]
    assert field(obs, "enemy.status").tolist() == [1, 0, 0, 0, 0]
    assert field(obs, "party0.move0.pp")[0] == pytest.approx((ember_pp // 2) / ember_pp)
    assert field(obs, "party0.move0.valid")[0] == 1 and field(obs, "party0.move1.valid")[0] == 0
    assert field(obs, "enemy_fainted").tolist() == [0, 1, 0, 0, 0, 0]
    assert field(obs, "enemy_remaining")[0] == pytest.approx(1 / 6)
    assert field(obs, "stages_player").tolist() == [pytest.approx(1 / 6)] * 8
    assert field(obs, "stages_enemy").tolist() == [pytest.approx(-0.5)] * 8
    assert field(obs, "turn")[0] == 0.5


def test_action_mask_rules_without_an_emulator():
    def mask(hps, pps=(3,) * 3, order=(), forced=False):
        party = tuple(gen4.Mon(pid=i + 1, checksum_ok=True, species=1, hp=hp, max_hp=20, moves=[33, 0, 0, 0],
                               pp=[pp, 0, 0, 0]) for i, (hp, pp) in enumerate(zip(hps, pps)))
        enemy = (gen4.Mon(pid=9, checksum_ok=True, species=1, hp=5, max_hp=20, moves=[33, 0, 0, 0], pp=[3, 0, 0, 0]),)
        return action_mask(Snapshot(party, enemy, 0, 0, (6,) * 8, (6,) * 8, order), forced).astype(int).tolist()
    assert mask([5, 0, 7]) == [1, 0, 0, 0, 0, 1, 0, 0, 0], "the fainted teammate at position 1 is masked"
    assert mask([5, 0, 7], order=(0, 2, 1, 3, 4, 5)) == [1, 0, 0, 0, 1, 0, 0, 0, 0], "switch targets follow the menu order"
    assert mask([0, 4, 7], forced=True) == [0, 0, 0, 0, 1, 1, 0, 0, 0]
    assert mask([5, 4, 7], pps=(0, 3, 3)) == [1, 0, 0, 0, 0, 0, 0, 0, 0], "Struggle is the only action"


@needs_rom
def test_a_one_frame_battle_dropout_after_a_switch_is_not_the_battles_end(team_env):
    """in_battle() reads False for a single frame as the prompt after this switch rises."""
    team_env.reset(options={"state": scenario_state("team6_vs_starly12"), "keep_rng": True})
    gen4.write_battle_seed(team_env.nds, team_env.addrs, 2195011642)
    for action in (6, 6, 8, 0, 5, 8, 7):
        _, _, term, trunc, info = team_env.step(action)
        assert not (term or trunc) and info["events"] == []


def ram_after_a_fight_tap(nds):
    """curCommandState[0] and a hash of main RAM after the same input from a loaded state."""
    a = gen4.resolve(nds)
    gen4.write_battle_seed(nds, a, 0x12345678)
    nds.tick(20)
    nds.button.set_touch(*FIGHT_XY); nds.button.touch(); nds.tick(6); nds.button.release_touch()
    nds.tick(200)
    return gen4.read_battle_command(nds, a)[1], hashlib.sha1(gen4.read_bytes(nds, gen4.MAIN_RAM, 0x400000)).hexdigest()


@needs_rom
def test_a_state_loads_the_same_whatever_ran_before():
    """NooDS used to pick the CPU run function from the halt states before a load. The ARM7
    is halted as this battle ends, so after the next load it stayed stopped: no touch input,
    and every tap was ignored (patches/noods-load-state-run-function.patch)."""
    state = scenario_state("weaklead_vs_eevee")
    fresh = pynds.PyNDS(ROM)
    fresh.load_state_from_file(state)
    want = ram_after_a_fight_tap(fresh)
    assert want[0] == gen4.CS_MOVE_MENU, "the FIGHT tap opens the move menu"
    e = BattleEnv([state], ROM)
    _, info = e.reset(seed=0)
    for _ in range(50):
        _, _, term, trunc, info = e.step(int(np.flatnonzero(info["action_mask"])[0]))
        if term or trunc:
            break
    assert info["outcome"] in ("WON", "LOST")
    e.nds.load_state_from_file(state)
    assert ram_after_a_fight_tap(e.nds) == want
    e.close()
