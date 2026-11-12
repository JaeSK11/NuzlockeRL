"""Tests for battle_env.py. The events_between tests need no emulator; the rest need the
Kaizo ROM and the local milestone states (not in git).
Run: ~/venvs/nuzlockerl/bin/python -m pytest -q tests  (from ~/nuzlockeRL)"""
import json, os, sys
import pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import gen4
from battle_env import BattleEnv, Event, REWARDS, Snapshot, events_between

ROM = os.environ.get("NUZLOCKERL_ROM", os.path.join(ROOT, "roms/plat-kaizo-nightmare-update-final.nds"))
M = os.path.join(ROOT, "states/milestones")
BARRY, WILD = (os.path.join(M, s) for s in ("03_barry1_battle_turn1.state", "05_route201_wild_battle.state"))

needs_rom = pytest.mark.skipif(
    not (os.path.exists(ROM) and os.path.isdir(M)),
    reason="needs the Kaizo ROM and local milestone save states (not in git)")


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
    """resultMask values seen while the battle memory is still valid, tapping A through the text."""
    seen = []
    for k in range(3000):
        env.nds.tick()
        if k % 66 == 0:
            env.nds.button.press_key("a"); env.nds.tick(6); env.nds.button.release_key("a")
        if not gen4.in_battle(env.nds, env.addrs):
            return seen
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
    assert set(step) == {"episode", "state", "rng_seed", "turn", "action", "events", "reward",
                         "player_hp", "enemy_hp", "frames"}
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
