"""fieldmap.py against what the playthrough to the Oreburgh Gym saw (PROGRESS.md §33).
Run: ~/venvs/nuzlockerl/bin/python -m pytest -q tests/test_fieldmap.py"""
import os, sys
import pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
import fieldmap as F
import romdata as R

ROM = os.environ.get("NUZLOCKERL_ROM", os.path.join(ROOT, "roms/plat-kaizo-nightmare-update-final.nds"))
needs_rom = pytest.mark.skipif(not os.path.exists(ROM), reason="needs the Kaizo ROM (not in git)")

ROUTE_201, ROUTE_202, ROUTE_203, JUBILIFE, OREBURGH_GATE, MINE_B2F, GYM = 342, 343, 344, 3, 258, 199, 47


@needs_rom
def test_route_201_has_the_ledge_and_the_person_the_screen_shows():
    grid = F.attrs(F.header(ROUTE_201).matrix)
    assert all(int(grid[848, x]) & 0xFF == 0x3B for x in range(149, 154))     # ledges that drop south
    assert any((o.x, o.z) == (153, 847) for o in F.events(ROUTE_201)[1])
    assert F.path(0, (153, 849), (153, 846)) is not None                        # around, not up the ledge
    assert ("up", 3) not in F.path(0, (153, 849), (153, 846))


@needs_rom
def test_a_trainers_script_names_the_trainer_met_there():
    met = {(o.x, o.z): R.trainer(F.trainer_id(o)).name for o in F.trainers(ROUTE_202)}
    assert met == {(166, 813): "Tristan", (181, 818): "Natalie", (185, 804): "Logan"}


@needs_rom
def test_the_trainers_a_walk_cannot_avoid():
    assert F.forced_trainers(ROUTE_202, (184, 831), (173, 799)) == {1: True, 3: True, 2: True}
    assert F.forced_trainers(ROUTE_203, (192, 758), (246, 749)) == \
        {356: False, 4: False, 323: False, 355: True, 322: True}
    assert F.forced_trainers(OREBURGH_GATE, (4, 22), (27, 22)) == {329: True, 265: True}
    assert F.forced_trainers(MINE_B2F, (15, 2), (17, 28)) == {195: True, 196: True}


@needs_rom
def test_the_jubilife_multi_battle_arms_only_in_the_oreburgh_gym():
    trigger = [c for c in F.events(JUBILIFE)[3] if (c.x, c.z) == (173, 743)]
    assert [(c.var, c.value) for c in trigger] == [(16503, 3)]
    assert F.set_var_sites(16503, 3) == [GYM]
