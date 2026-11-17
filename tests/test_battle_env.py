"""Tests for battle_env.py. The events_between tests need no emulator; the rest need the
Kaizo ROM and the local milestone states (not in git).
Run: ~/venvs/nuzlockerl/bin/python -m pytest -q tests  (from ~/nuzlockeRL)"""
import hashlib, json, os, sys
import numpy as np
import pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import battle_env
import gen4
import pynds
import romdata
import scenario
from battle_env import (FAINT_BASE, FAINT_SCALE, BattleEnv, Event, FIGHT_XY, OBS_FIELDS, OBS_SIZE, OBS_SLICES,
                        REWARDS, Snapshot, _Stuck, action_mask, events_between, faint_penalty, is_trapped,
                        move_to_forget, observation, route_for, strengths)

ROM = os.environ.get("NUZLOCKERL_ROM", os.path.join(ROOT, "roms/plat-kaizo-nightmare-update-final.nds"))
M = os.path.join(ROOT, "states/milestones")
BARRY, WILD = (os.path.join(M, s) for s in ("03_barry1_battle_turn1.state", "05_route201_wild_battle.state"))

needs_rom = pytest.mark.skipif(
    not (os.path.exists(ROM) and os.path.isdir(M)),
    reason="needs the Kaizo ROM and local milestone save states (not in git)")

GEN = os.path.join(ROOT, "states/generated")
CHIMCHAR, PIPLUP, PIKACHU, TURTWIG, STARLY, BIDOOF, EEVEE, BONSLY, SHUCKLE = 390, 393, 25, 387, 396, 399, 133, 438, 213
TACKLE, SELFDESTRUCT, GROWL, MEGA_DRAIN, BITE, ROCK_THROW, RAZOR_LEAF, EMBER, SCRATCH = 33, 120, 45, 72, 44, 88, 75, 52, 10
WITHDRAW, ABSORB, WRAP, MEAN_LOOK, DISABLE, TORMENT, ENCORE, CHOICE_BAND = 110, 71, 35, 212, 50, 259, 227, 220
STEALTH_ROCK, BRICK_BREAK, ACCELEROCK = 446, 280, 205      # with Selfdestruct, Roark's Bonsly; 205 is Rollout in vanilla
ROAR, WHIRLWIND = 46, 18
MASTER_BALL, POKE_BALL = 1, 4
TEAM3 = [{"species": CHIMCHAR, "level": 12, "moves": [52, 10, 43, 183]},
         {"species": PIPLUP, "level": 11, "moves": [55, 1, 145, 64]},
         {"species": PIKACHU, "level": 10, "moves": [84, 98, 86, 45]}]
TEAM6 = [{"species": CHIMCHAR, "level": 12, "moves": [52, 10]}, {"species": PIPLUP, "level": 11, "moves": [55, 1]},
         {"species": PIKACHU, "level": 10, "moves": [84, 98]}, {"species": TURTWIG, "level": 10, "moves": [33, 72]},
         {"species": STARLY, "level": 8, "moves": [33, 28]}, {"species": BIDOOF, "level": 7, "moves": [33]}]
# Turtwig's two moves have 1 PP each (Tail Whip, Meditate), so two turns leave it with none. Pikachu is alive.
# Level 16, so Turtwig outlasts three turns of Starly's attacks and Struggle's recoil.
NO_PP = [{"species": TURTWIG, "level": 16, "moves": [39, 96]}, {"species": PIKACHU, "level": 10, "moves": [84, 98]}]
WEAKLEAD = [{"species": PIKACHU, "level": 2, "moves": [84, 45]}, {"species": TURTWIG, "level": 15, "moves": [33, 72, 75, 44]}]
# A weak Starly lead against a Bonsly whose only move is Selfdestruct; Turtwig is the strongest.
WEAK_STARLY = [{"species": STARLY, "level": 8, "moves": [TACKLE]}, {"species": TURTWIG, "level": 14, "moves": [TACKLE]}]
def one_exp_short(species, level, moves):
    """A party of one Pokémon with four moves, one EXP short of `level`. A function, since the EXP
    table comes from the ROM: Turtwig learns Razor Leaf at 15, Chimchar Helping Hand at 12."""
    return lambda: [{"species": species, "level": level - 1, "moves": moves,
                     "exp": romdata.exp_for_level(species, level) - 1}]


SCENARIOS = {   # name: (party or a function giving one, wild enemy (species, level) or None, seed[, enemy moves]); built on first use, as make_scenario.py does
    "team3": (TEAM3, None, 2), "team_vs_starly12": (TEAM3, (STARLY, 12), 4),
    "team6_vs_starly12": (TEAM6, (STARLY, 12), 5), "no_pp_vs_starly12": (NO_PP, (STARLY, 12), 3),
    "weaklead_vs_eevee": (WEAKLEAD, (EEVEE, 13), 7),
    "starly_vs_selfdestruct": (WEAK_STARLY, (BONSLY, 15), 8, [SELFDESTRUCT]),
    "turtwig_learns_razor_leaf": (one_exp_short(TURTWIG, 15, [TACKLE, MEGA_DRAIN, BITE, ROCK_THROW]), (BIDOOF, 2), 1, [GROWL]),
    "chimchar_skips_helping_hand": (one_exp_short(CHIMCHAR, 12, [EMBER, SCRATCH, TACKLE, BITE]), (BIDOOF, 2), 1, [GROWL]),
    "bidoof_roars": ([{"species": TURTWIG, "level": 14, "moves": [TACKLE, WITHDRAW]}], (BIDOOF, 25), 3, [ROAR]),
    "turtwig_whirlwinds": ([{"species": TURTWIG, "level": 30, "moves": [WHIRLWIND]}], (BIDOOF, 5), 3, [GROWL]),
    "team6_catch_bidoof": (TEAM6, (BIDOOF, 3), 3, [GROWL]),
    "catch_bidoof": ([{"species": TURTWIG, "level": 14, "moves": [TACKLE, WITHDRAW]}], (BIDOOF, 3), 3, [GROWL]),
    "bonsly_opens": ([{"species": TURTWIG, "level": 14, "moves": [TACKLE, WITHDRAW, BITE, ABSORB]}], (BONSLY, 15), 3,
                     [STEALTH_ROCK, SELFDESTRUCT, BRICK_BREAK, ACCELEROCK])}


# A slow, bulky Shuckle that knows only the move under test, so Turtwig moves first and Tackle
# doesn't knock it out. The player's Choice Band case gives the enemy Growl.
LOCK_CASES = {"wrap": ([WRAP], None), "mean_look": ([MEAN_LOOK], None), "disable": ([DISABLE], None),
              "torment": ([TORMENT], None), "encore": ([ENCORE], None), "choice_band": ([GROWL], CHOICE_BAND)}
for _name, (_moves, _item) in LOCK_CASES.items():
    SCENARIOS["lock_" + _name] = (
        [{"species": TURTWIG, "level": 14, "moves": [TACKLE, WITHDRAW, BITE, ABSORB], **({"item": _item} if _item else {})},
         {"species": STARLY, "level": 12, "moves": [TACKLE, GROWL]}], (SHUCKLE, 25), 3, _moves)


def scenario_state(name):
    path = os.path.join(GEN, name + ".state")
    if not os.path.exists(path):
        party, enemy, seed, *enemy_moves = SCENARIOS[name]
        party = party() if callable(party) else party
        scenario.make_scenario(party, path, seed, ROM, enemy=enemy, enemy_moves=enemy_moves[0] if enemy_moves else None)
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
    assert REWARDS[Event.TURN_CAP] == REWARDS[Event.LOST] < -(FAINT_BASE + FAINT_SCALE) < -FAINT_BASE < 0
    assert REWARDS[Event.STUCK] == REWARDS[Event.ENDED] == REWARDS[Event.FLED] == 0
    assert Event.PLAYER_FAINTED not in REWARDS, "its cost depends on the Pokémon"


def test_a_faint_costs_more_the_stronger_the_pokemon():
    def mon(hp, total):
        return gen4.Mon(pid=1, checksum_ok=True, species=1, hp=hp, max_hp=total // 2,
                        stats={"atk": total - total // 2, "def": 0, "spe": 0, "spa": 0, "spd": 0})
    def party(*hps):
        return Snapshot(tuple(mon(hp, t) for hp, t in zip(hps, (400, 100, 200))), (), 0, None, (6,) * 8, (6,) * 8)
    assert strengths(party(5, 5, 5).player) == [1.0, 0.25, 0.5]
    ace, fodder = faint_penalty(party(5, 5, 5), party(0, 5, 5)), faint_penalty(party(5, 5, 5), party(5, 0, 5))
    assert ace == -(FAINT_BASE + FAINT_SCALE) and fodder == -(FAINT_BASE + FAINT_SCALE / 4)
    assert REWARDS[Event.WON] + REWARDS[Event.ENEMY_FAINTED] + fodder > 0 > REWARDS[Event.WON] + REWARDS[Event.ENEMY_FAINTED] + ace
    assert faint_penalty(party(0, 5, 5), party(0, 0, 5)) == fodder, "only new faints count"


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
    # Turtwig levels up at the end, and the text waits for a button; the env answers it, so the
    # game's own result arrives before the episode ends.
    assert rows[-1][6]["result_mask"] == 1
    assert 1 in result_masks_after_end(env)


@needs_rom
def test_a_fifth_move_replaces_the_weakest():
    path = scenario_state("turtwig_learns_razor_leaf")
    e = BattleEnv([path], ROM)
    _, rows = play(e, path, [0] * 5, seed=1)
    info = rows[-1][6]
    moves = gen4.read_party(e.nds, e.addrs["playerBattleBase"])[0].moves
    e.close()
    assert info["outcome"] == "WON" and info["result_mask"] == 1
    assert [(d["move"], d["forgot"]) for d in info["learned"]] == [("Razor Leaf", "Tackle")]
    assert list(moves) == [RAZOR_LEAF, MEGA_DRAIN, BITE, ROCK_THROW]


@needs_rom
def test_a_weaker_fifth_move_is_given_up():
    path = scenario_state("chimchar_skips_helping_hand")
    e = BattleEnv([path], ROM)
    _, rows = play(e, path, [0] * 5, seed=1)
    info = rows[-1][6]
    moves = gen4.read_party(e.nds, e.addrs["playerBattleBase"])[0].moves
    e.close()
    assert info["outcome"] == "WON" and info["result_mask"] == 1
    assert [(d["move"], d["forgot"]) for d in info["learned"]] == [("Helping Hand", None)]
    assert list(moves) == [EMBER, SCRATCH, TACKLE, BITE]


def lock_prompt(name, tmp_path):
    """A state saved at the first prompt where the case's lock or trap holds. Tackle is used
    until then: in a generated battle the enemy does nothing on turn 1 (PROGRESS.md §27)."""
    e = BattleEnv([scenario_state("lock_" + name)], ROM)
    try:
        for seed in range(10):
            e.reset(seed=seed)
            for _ in range(4):
                e.step(0)
                s = e.snap
                if s.trapped or any(s.locks) or s.encored:
                    path = str(tmp_path / (name + ".state"))
                    e.nds.save_state_to_file(path)
                    return path, s
        raise AssertionError(f"{name}: the condition never held")
    finally:
        e.close()


def game_accepts(path, action):
    """Whether the game takes the action through its menus, whatever the mask says."""
    e = BattleEnv([path], ROM)
    e.reset(options={"state": path, "keep_rng": True})
    try:
        for screen in route_for(action, False, False):
            e._walk(screen)
        e._run_to_prompt()
        return True
    except _Stuck:
        return False
    finally:
        e.close()


@needs_rom
@pytest.mark.parametrize("name", ["wrap", "mean_look", "disable", "torment", "choice_band"])
def test_mask_matches_what_the_game_accepts(name, tmp_path, monkeypatch):
    path, s = lock_prompt(name, tmp_path)
    mask = action_mask(s)
    monkeypatch.setattr(battle_env, "STEP_FRAME_GUARD", 2500)    # a refused action is called STUCK sooner
    actions = [a for a in range(4) if s.player[s.player_active].moves[a]] + [3 + k for k in range(1, len(s.slots()))]
    assert {a: game_accepts(path, a) for a in actions} == {a: bool(mask[a]) for a in actions}


@needs_rom
def test_encore_allows_only_the_encored_move_and_uses_it_from_fight(tmp_path):
    path, s = lock_prompt("encore", tmp_path)
    assert s.encored and action_mask(s).tolist() == [True, False, False, False, True] + [False] * 5
    e = BattleEnv([path], ROM)
    e.reset(options={"state": path, "keep_rng": True})
    pp = e.snap.player[e.snap.player_active].pp[0]
    _, _, _, stuck, info = e.step(0)
    after = e.snap.player[e.snap.player_active].pp[0]
    e.close()
    assert not stuck and info["move"] == "Tackle" and after == pp - 1


def test_trap_rules_the_game_cant_show_here():
    """Shadow Tag, Arena Trap, Magnet Pull and Shed Shell, which no Pokémon before Roark brings."""
    def effects(types=(0, 0), ability=0, item=0, volatile=0):
        return gen4.BattleEffects(moves=(TACKLE, 0, 0, 0), types=types, ability=ability, item=item, volatile=volatile,
                                  effects_mask=0, taunt_turns=0, magnet_rise_turns=0, disabled_move=0,
                                  encored_move=0, choice_move=0, last_move=0)
    assert is_trapped(effects(), battle_env.ARENA_TRAP)
    assert not is_trapped(effects(types=(battle_env.TYPE_FLYING, 0)), battle_env.ARENA_TRAP)
    assert not is_trapped(effects(), battle_env.MAGNET_PULL)
    assert is_trapped(effects(types=(battle_env.TYPE_STEEL, 0)), battle_env.MAGNET_PULL)
    assert is_trapped(effects(), battle_env.SHADOW_TAG)
    assert not is_trapped(effects(ability=battle_env.SHADOW_TAG), battle_env.SHADOW_TAG)
    assert not is_trapped(effects(item=battle_env.SHED_SHELL, volatile=battle_env.VOLATILE_MEAN_LOOK), None)
    assert is_trapped(effects(volatile=battle_env.VOLATILE_MEAN_LOOK), None)


@needs_rom
@pytest.mark.parametrize("name, action", [("bidoof_roars", 1), ("turtwig_whirlwinds", 0)])
def test_roar_or_whirlwind_ends_a_wild_battle_as_fled(name, action):
    """Either side's Roar or Whirlwind ends a wild battle, and the game records a flee (5)."""
    path = scenario_state(name)
    e = BattleEnv([path], ROM)
    _, rows = play(e, path, [action] * 3, seed=1)
    e.close()
    reward, events, term, trunc, info = rows[-1][2:]
    assert (len(rows), events, reward, term, trunc) == (1, ["FLED"], 0.0, True, False)
    assert info["outcome"] == "FLED" and info["result_mask"] == gen4.RESULT_FLED


def set_first_ball(env, item, count):
    """Put `count` of `item` first in the Poké Balls pocket of the bag and of the battle's copy."""
    off = 4 * sum(n for _, n in gen4.BAG_POCKETS[:6])
    for bag in ("bag", "bagBattle"):
        env.nds.memory.write_u16(False, env.addrs[bag] + off, item)
        env.nds.memory.write_u16(False, env.addrs[bag] + off + 2, count)


@needs_rom
def test_a_ball_is_offered_only_when_the_caller_allows_a_catch():
    path = scenario_state("catch_bidoof")
    e = BattleEnv([path], ROM)
    _, info = e.reset(seed=1)
    assert not info["action_mask"][battle_env.BALL_ACTION]
    e.reset(seed=1, options={"catch": True})
    set_first_ball(e, POKE_BALL, 5)
    assert e._can_throw()
    for bag in ("bag", "bagBattle"):
        for k in range(15):
            e.nds.memory.write_u32(False, e.addrs[bag] + 4 * sum(n for _, n in gen4.BAG_POCKETS[:6]) + 4 * k, 0)
    assert not e._can_throw(), "no ball left in the bag"
    e.close()


@needs_rom
def test_a_master_ball_catches_and_ends_the_battle_as_caught():
    path = scenario_state("catch_bidoof")
    e = BattleEnv([path], ROM)
    e.reset(seed=1, options={"catch": True})
    set_first_ball(e, MASTER_BALL, 1)
    _, reward, term, trunc, info = e.step(battle_env.BALL_ACTION)
    e._tick(120)
    party = [m.species for m in gen4.read_party(e.nds, e.addrs["playerBase"])]
    e.close()
    assert (info["outcome"], info["result_mask"], reward, term, trunc) == ("CAUGHT", gen4.RESULT_CAUGHT, 0.0, True, False)
    assert info["pick"] == "ball" and party == [TURTWIG, BIDOOF]


@needs_rom
def test_a_catch_with_a_full_party_goes_to_the_pc():
    """With six in the party the game says the catch was sent to the PC, which waits for a
    button, and stores it in the first box. The first real deposit read back by read_box."""
    path = scenario_state("team6_catch_bidoof")
    e = BattleEnv([path], ROM)
    e.reset(seed=1, options={"catch": True})
    set_first_ball(e, MASTER_BALL, 1)
    _, _, term, trunc, info = e.step(battle_env.BALL_ACTION)
    e._tick(120)
    party, box = gen4.read_party(e.nds, e.addrs["playerBase"]), gen4.read_box(e.nds, 0, e.addrs)
    e.close()
    assert info["outcome"] == "CAUGHT" and len(party) == 6
    # A boxed Pokémon keeps no level field; its level comes from its EXP
    assert box[0] is not None and box[0].checksum_ok and box[0].species == BIDOOF
    assert romdata.level_for_exp(BIDOOF, box[0].exp) == 3 and box[0].moves[0] == GROWL


@needs_rom
def test_the_enemys_first_move_follows_the_battle_seed():
    """Generated states are saved before the enemy picks its turn-1 move, so the seed the env
    writes at reset decides it. Saved at the prompt, every seed gave the same move (PROGRESS.md §28)."""
    path = scenario_state("bonsly_opens")
    e = BattleEnv([path], ROM)
    firsts = set()
    for seed in range(12):
        e.reset(seed=seed)
        e.step(1)                                           # Withdraw
        firsts.add(gen4.read_battle_effects(e.nds, e.addrs, 1).last_move)
    e.close()
    assert len(firsts) >= 3 and firsts <= {STEALTH_ROCK, SELFDESTRUCT, BRICK_BREAK, ACCELEROCK}


@needs_rom
def test_move_to_forget_keeps_old_moves_for_a_weaker_one():
    grass = romdata.species(TURTWIG).types
    four = [TACKLE, MEGA_DRAIN, BITE, ROCK_THROW]
    assert move_to_forget(four, grass, RAZOR_LEAF) == 0
    assert move_to_forget(four, grass, GROWL) is None
    assert move_to_forget([GROWL, MEGA_DRAIN, BITE, ROCK_THROW], grass, TACKLE) == 0


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
    assert info["action_mask"].tolist() == [True] + [False] * 9 and info["input_mode"] == 0
    with pytest.raises(ValueError):
        env.step(1)
    env.step(0)

    info, _ = play(env, WILD, [])
    assert info["action_mask"].tolist() == [True, True] + [False] * 8 and info["input_mode"] == 1
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
    assert rows[-1][4] and rows[-1][2] == REWARDS[Event.LOST] - FAINT_BASE - FAINT_SCALE  # the only Pokémon is the ace
    assert rows[-1][6]["outcome"] == "LOST"
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
    assert set(step) == {"episode", "state", "rng_seed", "turn", "action", "forced", "pick", "move", "pp_before",
                         "events", "reward", "player_hp", "enemy_hp", "frames"}
    assert step["forced"] is False
    assert step["events"] == ["TURN_CAP"] and step["player_hp"] == [18] and step["enemy_hp"] == [15]
    assert set(summary) >= {"episode", "outcome", "turns", "return", "frames"}
    assert summary["outcome"] == "TURN_CAP" and summary["return"] == -10.0


def battle_frames(info0, rows):
    """Frames to the last decision. The last step also waits for the game to record the
    result (BattleEnv._await_result), which the battle options don't shorten."""
    return info0["frames"] + sum(r[6]["frames"] for r in rows[:-1])


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
    assert info["action_mask"].tolist() == [True] * 6 + [False] * 4
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
    assert info["action_mask"].tolist() == [True] * 2 + [False] * 2 + [True] * 5 + [False]
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
    lead = -(FAINT_BASE + FAINT_SCALE * strengths(team_env.snap.player)[0])
    assert rows[-1] == (lead, ["PLAYER_FAINTED"], False, False)
    assert info["forced_switch"] is True and info["turn"] == len(rows)
    assert info["action_mask"].tolist() == [False] * 4 + [True, True] + [False] * 4
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
def test_forced_switch_does_not_count_toward_the_turn_cap(team_env):
    """The cap is set one turn past the forced switch: the switch must not reach it."""
    turns = len(play_until_forced(team_env)[1])
    e = BattleEnv([BARRY], ROM, turn_cap=turns + 1)
    info, rows = play_until_forced(e)
    assert len(rows) == turns
    _, _, term, trunc, info = e.step(4)
    assert (term, trunc, info["turn"]) == (False, False, turns)
    _, reward, term, trunc, info = e.step(0)
    e.close()
    assert (term, trunc, info["turn"], info["outcome"]) == (True, False, turns + 1, "TURN_CAP")


@needs_rom
def test_struggle_is_the_only_action_with_no_pp_and_the_game_uses_it(team_env):
    env = team_env
    _, info = reset_on(env, "no_pp_vs_starly12", seed=0)
    enemy_hp = env.snap.enemy[0].hp
    assert info["action_mask"].tolist() == [True, True, False, False, True] + [False] * 5
    env.step(0)
    _, _, _, _, info = env.step(1)
    assert env.snap.player[0].pp == [0, 0, 0, 0]
    assert env.snap.enemy[0].hp == enemy_hp, "Tail Whip and Meditate do no damage"
    assert info["action_mask"].tolist() == [True] + [False] * 9, "a living teammate is masked too"
    obs = observation(env.snap, 2, env.turn_cap)
    assert [obs[OBS_SLICES[f"party0.move{k}.valid"]][0] for k in range(2)] == [0.0, 0.0]
    _, _, term, trunc, info = env.step(0)
    assert not trunc and "PLAYER_FAINTED" not in info["events"], info
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


def test_observation_carries_type_matchups_against_the_enemy():
    """Turtwig (Grass) with Tackle and Razor Leaf against Gastly (Ghost/Poison): Tackle can't
    touch a Ghost, Razor Leaf is resisted by Poison but gets the same-type bonus, and Poison
    hits Grass twice as hard."""
    GASTLY, TACKLE, RAZOR_LEAF = 92, 33, 75
    stats = {"atk": 20, "def": 20, "spe": 20, "spa": 20, "spd": 20}
    turtwig = gen4.Mon(pid=1, checksum_ok=True, species=TURTWIG, level=15, hp=40, max_hp=40,
                       moves=[TACKLE, RAZOR_LEAF, 0, 0], pp=[35, 25, 0, 0], stats=stats)
    gastly = gen4.Mon(pid=2, checksum_ok=True, species=GASTLY, level=15, hp=30, max_hp=30)
    obs = observation(Snapshot((turtwig,), (gastly,), 0, 0, (6,) * 8, (6,) * 8), 1, 10)
    assert [field(obs, f"party0.move0.{n}")[0] for n in ("effect", "immune", "stab")] == [-1, 1, 0]
    assert [field(obs, f"party0.move1.{n}")[0] for n in ("effect", "immune", "stab")] == [-0.5, 0, 1]
    assert field(obs, "party0.hit_by_enemy_types").tolist() == [0.0, 0.5]   # Ghost 1x, Poison 2x
    assert field(obs, "party0.strength")[0] == 1.0


def test_action_mask_rules_without_an_emulator():
    def mask(hps, pps=(3,) * 3, order=(), forced=False, can_throw=False):
        party = tuple(gen4.Mon(pid=i + 1, checksum_ok=True, species=1, hp=hp, max_hp=20, moves=[33, 0, 0, 0],
                               pp=[pp, 0, 0, 0]) for i, (hp, pp) in enumerate(zip(hps, pps)))
        enemy = (gen4.Mon(pid=9, checksum_ok=True, species=1, hp=5, max_hp=20, moves=[33, 0, 0, 0], pp=[3, 0, 0, 0]),)
        return action_mask(Snapshot(party, enemy, 0, 0, (6,) * 8, (6,) * 8, order), forced, can_throw).astype(int).tolist()
    assert mask([5, 0, 7]) == [1, 0, 0, 0, 0, 1, 0, 0, 0, 0], "the fainted teammate at position 1 is masked"
    assert mask([5, 0, 7], order=(0, 2, 1, 3, 4, 5)) == [1, 0, 0, 0, 1, 0, 0, 0, 0, 0], "switch targets follow the menu order"
    assert mask([0, 4, 7], forced=True) == [0, 0, 0, 0, 1, 1, 0, 0, 0, 0]
    assert mask([5, 4, 7], pps=(0, 3, 3)) == [1, 0, 0, 0, 0, 0, 0, 0, 0, 0], "Struggle is the only action"
    assert mask([5, 4, 7], can_throw=True)[9] == 1 and mask([5, 4, 7], pps=(0, 3, 3), can_throw=True)[9] == 1
    assert mask([0, 4, 7], forced=True, can_throw=True)[9] == 0, "no ball at a forced switch"


@needs_rom
def test_a_one_frame_battle_dropout_after_a_switch_is_not_the_battles_end(team_env):
    """in_battle() reads False for a single frame as the prompt after this switch rises."""
    team_env.reset(options={"state": scenario_state("team6_vs_starly12"), "keep_rng": True})
    gen4.write_battle_seed(team_env.nds, team_env.addrs, 2195011642)
    for action in (6, 6, 8, 0, 5, 8, 7):
        _, _, term, trunc, info = team_env.step(action)
        assert not (term or trunc) and info["events"] == []


def ram_after_a_fight_tap(nds):
    """curCommandState[0] and a hash of main RAM after the same input from a loaded state. The
    state is saved before the first prompt, so wait for it, then SETTLE frames, as the env does."""
    a = gen4.resolve(nds)
    gen4.write_battle_seed(nds, a, 0x12345678)
    while not gen4.waiting_for_command(nds, a):
        nds.tick()
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


@needs_rom
def test_a_selfdestruct_that_ends_the_battle_still_costs_the_faint_it_causes(team_env):
    """Selfdestruct zeroes its user's HP before the blast lands. The episode must end on the
    game's own result, after the blast, not as a clean win at the first 0 HP."""
    reset_on(team_env, "starly_vs_selfdestruct")
    starly = strengths(team_env.snap.player)[0]
    for _ in range(5):      # Tackle does 1 HP a turn, so only the Selfdestruct, when it comes, ends the battle
        _, reward, terminated, truncated, info = team_env.step(0)
        if terminated or truncated:
            break
    assert terminated and info["outcome"] == "WON" and info["result_mask"] == 1
    assert info["events"] == ["PLAYER_FAINTED", "ENEMY_FAINTED", "WON"]
    assert info["fainted_strengths"] == [starly] and starly < 1
    assert reward == pytest.approx(REWARDS[Event.WON] + REWARDS[Event.ENEMY_FAINTED] - FAINT_BASE - FAINT_SCALE * starly)
    assert (info["pick"], info["move"]) == ("resisted", "Tackle"), "Normal into Rock"


@needs_rom
def test_info_names_each_decision(team_env):
    reset_on(team_env, "team_vs_starly12")
    mon = team_env.snap.player[team_env.snap.player_active]
    _, _, _, _, info = team_env.step(0)
    assert (info["move"], info["pp_before"]) == (romdata.move(mon.moves[0]).name, mon.pp[0])
    assert info["pick"] in ("super", "neutral", "resisted", "immune", "status")
    if not (info["outcome"] if "outcome" in info else None):
        _, _, _, _, info = team_env.step(int(np.flatnonzero(info["action_mask"][4:])[0]) + 4)
        assert (info["pick"], info["move"], info["pp_before"]) == ("switch", None, None)


@needs_rom
def test_the_wait_for_the_result_rides_out_snapshots_that_read_invalid(team_env, monkeypatch):
    """The game decrypts a party struct in place while it writes it, so a snapshot can read
    invalid for a frame, as when it adds the exp after a win. The wait must go on to the result."""
    import battle_env
    real, calls = battle_env.read_snapshot, [0]
    def flaky(nds, addrs):
        calls[0] += 1
        return None if calls[0] % 3 == 0 else real(nds, addrs)
    reset_on(team_env, "starly_vs_selfdestruct")
    monkeypatch.setattr(battle_env, "read_snapshot", flaky)
    for _ in range(5):
        _, _, terminated, truncated, info = team_env.step(0)
        if terminated or truncated:
            break
    assert info["outcome"] == "WON" and info["result_mask"] == 1 and "PLAYER_FAINTED" in info["events"]
