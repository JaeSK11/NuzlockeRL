"""Tests for nuzlocke.py, the rule bookkeeping. Evolution lines come from the ROM, so the tests
that use them are skipped without it."""
import os, sys
import pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from nuzlocke import Rules, Run, line_of

ROM = os.environ.get("NUZLOCKERL_ROM", os.path.join(ROOT, "roms/plat-kaizo-nightmare-update-final.nds"))
needs_rom = pytest.mark.skipif(not os.path.exists(ROM), reason="needs the Kaizo ROM (not in git)")
PICHU, PIKACHU, RAICHU, EEVEE, FLAREON, STARLY, STARAVIA, BIDOOF, SHINX = 172, 25, 26, 133, 136, 396, 397, 399, 403


@needs_rom
def test_an_evolution_line_is_named_by_its_first_species():
    assert line_of(RAICHU) == line_of(PIKACHU) == PICHU
    assert line_of(FLAREON) == EEVEE and line_of(STARAVIA) == STARLY and line_of(BIDOOF) == BIDOOF


@needs_rom
def test_only_the_first_encounter_on_a_route_may_be_caught():
    run = Run()
    assert run.encounter("Route 201", STARLY)
    assert not run.encounter("Route 201", BIDOOF), "the route is used up, caught or not"
    assert run.encounter("Route 202", BIDOOF)


@needs_rom
def test_a_duplicate_doesnt_count_and_leaves_the_route_open():
    run = Run()
    run.encounter("Route 201", STARLY)
    run.caught(STARLY)
    assert not run.encounter("Route 202", STARAVIA), "Staravia is Starly's line"
    assert run.encounter("Route 202", BIDOOF), "the duplicate didn't use up Route 202"


@needs_rom
def test_a_shiny_may_always_be_caught_and_uses_up_nothing():
    run = Run()
    run.encounter("Route 201", STARLY)
    run.caught(STARLY)
    assert run.encounter("Route 201", STARAVIA, shiny=True), "shiny beats both the used route and the duplicate"
    assert run.encounter("Route 203", SHINX), "the shiny didn't use up anything"


@needs_rom
def test_rules_can_be_switched_off():
    run = Run(Rules(first_encounter_only=False, duplicates_clause=False, shiny_clause=False))
    run.caught(STARLY)
    assert run.encounter("Route 201", STARLY) and run.encounter("Route 201", STARAVIA)


def test_the_level_cap_follows_the_bosses_beaten():
    run = Run()
    assert run.level_cap() == 16 and not run.over_cap([15, 16]) and run.over_cap([17])
    run.boss_beaten("Roark")
    assert run.level_cap() == 28
    with pytest.raises(ValueError):
        run.boss_beaten("Barry 2")
    for boss, _ in Rules().level_caps:
        run.boss_beaten(boss)
    assert run.level_cap() is None and not run.over_cap([100])


def test_a_fainted_pokemon_is_gone_for_good():
    run = Run()
    run.fainted(1234)
    assert 1234 in run.dead
