"""Checks for the Nuzlocke-rule RAM fields in gen4.py against the milestone save states.
Run: ~/venvs/nuzlockerl/bin/python -m pytest -q tests/test_nuzlocke_ram.py  (from ~/nuzlockeRL)"""
import os, sys
import pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pynds, gen4, drive

ROM = os.environ.get("NUZLOCKERL_ROM", os.path.join(ROOT, "roms/plat-kaizo-nightmare-update-final.nds"))
M = os.path.join(ROOT, "states/milestones")
S00, S01, S02, S03, S04, S05 = (
    "00_twinleaf_bedroom_no_party.state", "01_starter_turtwig_box_screen.state",
    "02_route201_before_barry.state", "03_barry1_battle_turn1.state",
    "04_after_barry1_home.state", "05_route201_wild_battle.state")
WALK_SCRIPT = os.path.join(ROOT, "scripts/milestones/05_route201_wild_battle.txt")

pytestmark = pytest.mark.skipif(
    not (os.path.exists(ROM) and os.path.isdir(M)),
    reason="needs the Kaizo ROM and local milestone save states (not in git)")

TURTWIG, CHIMCHAR, PIPLUP, DELIBIRD = 387, 390, 393, 225
ROUTE_201, TWINLEAF_TOWN, TWINLEAF_HOME_1F, TWINLEAF_BEDROOM = 342, 411, 414, 415


def load(name):
    n = pynds.PyNDS(ROM)
    n.load_state_from_file(os.path.join(M, name))
    n.tick(2)
    return n


def test_location_in_every_milestone():
    got = {}
    for name in (S00, S01, S02, S03, S04, S05):
        loc = gen4.read_location(load(name))
        got[name] = (loc.map_id, loc.x, loc.z, loc.name)
    assert got == {
        S00: (TWINLEAF_BEDROOM, 4, 6, "Twinleaf Town"),
        S01: (ROUTE_201, 113, 854, "Route 201"),
        S02: (ROUTE_201, 113, 854, "Route 201"),
        S03: (ROUTE_201, 113, 854, "Route 201"),
        S04: (TWINLEAF_HOME_1F, 6, 8, "Twinleaf Town"),
        S05: (ROUTE_201, 117, 853, "Route 201"),
    }


def test_walking_changes_map_position_and_facing():
    n = load(S04)
    a = gen4.resolve(n)
    tokens = [t for line in open(WALK_SCRIPT) if not line.startswith("#") for t in line.split()]
    maps, last = [], None
    for tok in tokens[:196]:
        drive.run(n, tok)
        loc = gen4.read_location(n, a)
        if loc.map_id != last:
            maps.append((loc.map_id, loc.name))
            last = loc.map_id
    assert maps == [(TWINLEAF_HOME_1F, "Twinleaf Town"), (TWINLEAF_TOWN, "Twinleaf Town"),
                    (ROUTE_201, "Route 201")]
    assert tuple(gen4.read_location(n, a))[1:] == (113, 853, 0)
    for move, expect in (("down", (113, 854, 1)), ("left", (112, 854, 2)), ("up", (112, 853, 0))):
        drive.run(n, f"hold:{move}:5 hold:{move}:16 w20")
        assert tuple(gen4.read_location(n, a))[1:] == expect


def test_badges_are_zero_and_follow_the_byte():
    for name in (S00, S01, S02, S03, S04, S05):
        assert gen4.read_badges(load(name)) == 0
    n = load(S02)
    n.memory.write_u8(False, gen4.resolve(n)["badges"], 0b101)
    assert gen4.read_badges(n) == 0b101


def test_pokedex_starter_flags():
    assert gen4.read_pokedex(load(S00)) == (set(), set())
    for name in (S01, S02, S03):
        caught, seen = gen4.read_pokedex(load(name), from_battle=False)
        assert (caught, seen) == ({TURTWIG}, {TURTWIG})
    assert CHIMCHAR not in gen4.read_pokedex(load(S01))[1]
    assert PIPLUP not in gen4.read_pokedex(load(S01))[1]


def test_battle_pokedex_copy_leads_the_save_copy():
    n = load(S03)
    assert gen4.read_pokedex(n, from_battle=False)[1] == {TURTWIG}
    assert gen4.read_pokedex(n) == ({TURTWIG}, {TURTWIG, CHIMCHAR})
    n = load(S05)
    assert gen4.read_pokedex(n, from_battle=False) == ({TURTWIG}, {TURTWIG, CHIMCHAR})
    assert gen4.read_pokedex(n) == ({TURTWIG}, {TURTWIG, CHIMCHAR, DELIBIRD})


def test_after_barry_battle_save_copy_has_chimchar():
    assert gen4.read_pokedex(load(S04)) == ({TURTWIG}, {TURTWIG, CHIMCHAR})


EMPTY_BAG = {name: [] for name, _ in gen4.BAG_POCKETS}


def test_bag_empty_until_after_the_cutscenes():
    for name in (S00, S01, S02, S03, S04):
        assert gen4.read_bag(load(name)) == EMPTY_BAG


def test_bag_in_wild_battle_matches_the_bag_screen():
    n = load(S05)
    a = gen4.resolve(n)
    expected = dict(EMPTY_BAG, items=[(94, 1)], medicine=[(50, 10)], berries=[(200, 1)],
                    balls=[(4, 20), (3, 5), (14, 5)], key_items=[(433, 1), (459, 1)])
    assert gen4.read_bag(n, a, from_battle=False) == expected
    assert gen4.read_bag(n, a, from_battle=True) == expected


def test_boxes_are_empty_and_read_as_30_slots():
    for name in (S00, S05):
        n = load(name)
        assert all(gen4.read_box(n, b) == [None] * 30 for b in range(18))
    with pytest.raises(IndexError):
        gen4.read_box(load(S00), 18)


def test_box_reader_decodes_a_mon_written_into_a_slot():
    n = load(S01)
    a = gen4.resolve(n)
    raw = gen4.read_bytes(n, a["playerBase"], gen4.BOX_MON_SIZE)
    slot = 4 + (2 * 30 + 7) * gen4.BOX_MON_SIZE
    for i in range(0, gen4.BOX_MON_SIZE, 4):
        n.memory.write_u32(False, a["pcBoxes"] + slot + i, int.from_bytes(raw[i:i + 4], "little"))
    box = gen4.read_box(n, 2, a)
    assert [i for i, m in enumerate(box) if m] == [7]
    assert (box[7].species, box[7].checksum_ok, box[7].moves[0]) == (TURTWIG, True, 33)
    assert gen4.read_box(n, 0, a) == [None] * 30


def test_catching_updates_party_bag_and_pokedex():
    """Throws a Great Ball at the wild Delibird. The seed is one that catches on the first throw."""
    n = load(S05)
    a = gen4.resolve(n)
    for _ in range(400):
        if gen4.waiting_for_command(n, a):
            break
        n.tick(1)
    n.tick(30)
    gen4.write_battle_seed(n, a, 560161641)
    drive.run(n, "t60,165 w60 t192,58 w60 t190,23 w60 t128,175 w60")
    assert gen4.read_bag(n, a)["balls"] == [(4, 20), (3, 4), (14, 5)]
    assert gen4.read_bag(n, a, from_battle=False)["balls"] == [(4, 20), (3, 5), (14, 5)]
    result = None
    for _ in range(200):
        if not gen4.in_battle(n, a):
            break
        result = n.memory.read_u8(False, a["battleResult"])
        drive.run(n, "a w10")
    assert result == 4
    assert [m.species for m in gen4.read_party(n)] == [TURTWIG, DELIBIRD]
    assert gen4.read_pokedex(n) == ({TURTWIG, DELIBIRD}, {TURTWIG, CHIMCHAR, DELIBIRD})
    assert gen4.read_bag(n, a)["balls"] == [(4, 20), (3, 4), (14, 5)]
