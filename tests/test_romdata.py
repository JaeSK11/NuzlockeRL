"""Cross-checks of romdata.py against facts measured in RAM and on screen.
Run: ~/venvs/nuzlockerl/bin/python -m pytest -q tests/test_romdata.py  (from ~/nuzlockeRL)"""
import os, sys
import pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import romdata as R

ROM = os.environ.get("NUZLOCKERL_ROM", os.path.join(ROOT, "roms/plat-kaizo-nightmare-update-final.nds"))
M = os.path.join(ROOT, "states/milestones")

needs_rom = pytest.mark.skipif(not os.path.exists(ROM), reason="needs the Kaizo ROM (not in git)")
needs_states = pytest.mark.skipif(
    not (os.path.exists(ROM) and os.path.isdir(M)),
    reason="needs the Kaizo ROM and local milestone save states (not in git)")

TURTWIG, CHIMCHAR, DELIBIRD = 387, 390, 225
TACKLE, MEGA_DRAIN, PRESENT, POWDER_SNOW = 33, 72, 217, 181
SHELL_ARMOR = 75
ROUTE_201_MAP_HEADER = 342      # decomp generated/map_headers.txt, 0-based


@needs_rom
def test_turtwig_has_shell_armor():
    s = R.species(TURTWIG)
    assert SHELL_ARMOR in s.abilities
    assert s.ability_names == ("Overgrow", "Shell Armor")
    assert s.types == (12, 12)


@needs_rom
def test_turtwig_learns_mega_drain_by_lv6_and_only_tackle_at_lv5():
    assert dict((m, l) for l, m in R.learnset(TURTWIG))[MEGA_DRAIN] == 6
    assert R.default_moves(TURTWIG, 5) == (TACKLE,)
    assert R.default_moves(TURTWIG, 6) == (TACKLE, MEGA_DRAIN)


@needs_rom
def test_trainer_851_is_barry_with_a_lv5_chimchar():
    t = R.trainer(851)
    assert t.class_name.endswith("Trainer") and not t.double_battle
    assert [(m.species, m.level) for m in t.party] == [(CHIMCHAR, 5)]


@needs_rom
def test_route_201_grass_has_delibird_at_lv4():
    e = R.encounters_for_map(ROUTE_201_MAP_HEADER)
    assert (4, DELIBIRD) in [(g.level, g.species) for g in e.grass]
    assert R.encounters_for_map(0) is None


@needs_rom
def test_delibird_lv4_knows_present_and_powder_snow():
    assert set(R.default_moves(DELIBIRD, 4)) >= {PRESENT, POWDER_SNOW}


@needs_rom
def test_tackle_values_in_the_hack():
    m = R.move(TACKLE)
    assert (m.name, m.type, m.cls, m.power, m.pp) == ("Tackle", 0, 0, 35, 35)
    assert m.accuracy == 100    # retail Gen 4 Tackle is 95: the hack changed it


@needs_rom
def test_names_decode():
    assert R.species_name(TURTWIG) == "Turtwig" and R.species_name(122) == "Mr. Mime"
    assert R.move_name(MEGA_DRAIN) == "Mega Drain" and R.ability_name(SHELL_ARMOR) == "Shell Armor"
    assert R.trainer(1).name == "Tristan"


@needs_rom
def test_tables_are_complete():
    assert len(R.all_species()) == 508 and len(R.all_moves()) == 471 and R.num_trainers() == 928
    assert R.evolutions(TURTWIG)[0].target == 388


def _mon_facts(nds, base):
    """PID, level, nature, IVs, EVs and the five measured stats of the struct at base."""
    import gen4
    raw = gen4.read_bytes(nds, base, gen4.PARTY_MON_SIZE)
    m = gen4.decode_mon(raw)
    decrypted = gen4._crypt(raw[8:136], gen4._u16(raw, 6))
    order = gen4.BLOCK_ORDERS[((m.pid & 0x3E000) >> 13) % 24]
    blk = {letter: decrypted[32 * i:32 * (i + 1)] for i, letter in enumerate(order)}
    evs = tuple(blk["A"][16:22])
    iv_word = gen4._u32(blk["B"], 16)
    ivs = tuple(iv_word >> (5 * k) & 31 for k in range(6))
    measured = (m.max_hp, m.stats["atk"], m.stats["def"], m.stats["spe"], m.stats["spa"], m.stats["spd"])
    return m, ivs, evs, measured


def _load(name):
    import pynds
    n = pynds.PyNDS(ROM)
    n.load_state_from_file(os.path.join(M, name))
    n.tick(2)
    return n


@needs_states
@pytest.mark.parametrize("state,level", [("01_starter_turtwig_box_screen.state", 5), ("04_after_barry1_home.state", 6)])
def test_turtwig_stats_match_ram(state, level):
    import gen4
    n = _load(state)
    m, ivs, evs, measured = _mon_facts(n, gen4.resolve(n)["playerBase"])
    assert (m.species, m.level) == (TURTWIG, level)
    assert R.calc_stats(TURTWIG, level, ivs, evs, m.pid % 25) == measured
    assert R.species(TURTWIG).abilities[m.pid & 1] == m.ability == SHELL_ARMOR


@needs_states
def test_barry_chimchar_matches_ram_pid_and_stats():
    import gen4
    n = _load("03_barry1_battle_turn1.state")
    a = gen4.resolve(n)
    m, ivs, evs, measured = _mon_facts(n, a["enemyBase"])
    t = R.trainer(n.memory.read_u16(False, a["enemyTrainerID"]))
    mon = t.party[0]
    assert t.id == 851 and m.pid == t.mon_pid(0)
    assert ivs == (mon.iv,) * 6
    assert R.calc_stats(mon.species, mon.level, ivs, evs, m.pid % 25) == measured
    assert R.species(mon.species).abilities[m.pid & 1] == m.ability
