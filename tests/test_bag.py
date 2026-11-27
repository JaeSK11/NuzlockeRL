"""The overworld's Bag actions (bag.py): a Rare Candy on a party Pokémon, and giving an item to hold.
Run: ~/venvs/nuzlockerl/bin/python -m pytest -q tests/test_bag.py"""
import os
import random
import sys
import pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import gen4

ROM = os.environ.get("NUZLOCKERL_ROM", os.path.join(ROOT, "roms/plat-kaizo-nightmare-update-final.nds"))
CENTER = os.path.join(ROOT, "states/milestones/12_oreburgh_pokecenter.state")
pytestmark = pytest.mark.skipif(not (os.path.exists(ROM) and os.path.exists(CENTER)),
                                reason="needs the ROM and milestone 12_oreburgh_pokecenter (scripts/make_milestones.py)")

RARE_CANDY, CHILAN_BERRY, WHITE_HERB = 50, 200, 214
TURTWIG, LUCARIO = 387, 448


def center(party_edits=()):
    """Oreburgh's Pokémon Center with 10 Rare Candies, a Chilan Berry and a White Herb in the bag.
    Each edit (slot, species, level, moves, item) rebuilds that party slot."""
    import pynds
    import romdata as R
    import scenario
    nds = pynds.PyNDS(ROM)
    nds.load_state_from_file(CENTER)
    nds.tick(2)
    party = scenario.read_party_data(nds)
    trainer = scenario.Trainer.from_mon(party[0])
    for slot, species, level, moves, item in party_edits:
        party[slot] = scenario.build_mon(species, level, moves or R.default_moves(species, level), ivs=15,
                                         trainer=trainer, rng=random.Random(0), item=item)
    scenario.write_party(nds, party)
    return nds


def free_to_walk(nds, map_id):
    """In the overworld on this map, with every menu closed, and a step taken from a free tile."""
    import overworld as O
    assert gen4.field_task(nds) == 0 and gen4.read_location(nds).map_id == map_id
    assert any(O.step(nds, d) == "moved" for d in O.DIRS)


def candies(nds):
    return dict(gen4.read_bag(nds, from_battle=False)["medicine"]).get(RARE_CANDY, 0)


def test_a_candy_raises_the_level_by_one_and_leaves_the_player_free():
    import bag
    nds = center()
    map_id, before = gen4.read_location(nds).map_id, gen4.read_party(nds)
    assert candies(nds) == 10
    for n, slot in enumerate((4, 1), start=1):           # the party cursor starts where the last use left it
        assert bag.use_item(nds, RARE_CANDY, slot) == "used"
        mon = gen4.read_party(nds)[slot]
        assert (mon.level, mon.species) == (before[slot].level + 1, before[slot].species)
        assert candies(nds) == 10 - n
    assert [m.level for i, m in enumerate(gen4.read_party(nds)) if i not in (1, 4)] == \
        [m.level for i, m in enumerate(before) if i not in (1, 4)]
    free_to_walk(nds, map_id)


@pytest.mark.parametrize("forget, moves", [
    (lambda: 1, ["Metal Claw", "Bone Rush", "Force Palm", "Feint"]),     # slot 1, Crunch, goes
    (None, ["Metal Claw", "Crunch", "Force Palm", "Feint"]),             # the old moves stay
])
def test_a_candy_that_brings_a_fifth_move_answers_the_forget_prompt(forget, moves):
    """Lucario at 18 knows four moves and learns Bone Rush at 19."""
    import bag
    import romdata as R
    nds = center([(2, LUCARIO, 18, None, 0)])
    map_id = gen4.read_location(nds).map_id
    assert bag.use_item(nds, RARE_CANDY, 2, forget) == "used"
    mon = gen4.read_party(nds)[2]
    assert mon.level == 19 and [R.move_name(m) for m in mon.moves] == moves
    free_to_walk(nds, map_id)


@pytest.mark.parametrize("forget, moves", [
    (lambda: 0, ["Stomp", "Razor Leaf", "Seed Bomb", "Stone Edge"]),     # slot 0, Tackle, goes
    (None, ["Tackle", "Razor Leaf", "Seed Bomb", "Stone Edge"]),
])
def test_a_candy_at_an_evolution_level_evolves_and_answers_its_fifth_move(forget, moves):
    """Turtwig at 15 evolves into Grotle at 16, whose level-16 move is Stomp. Slot 5 is the last
    the party cursor reaches."""
    import bag
    import romdata as R
    nds = center([(5, TURTWIG, 15, [33, 75, 402, 444], 0)])
    map_id = gen4.read_location(nds).map_id
    assert bag.use_item(nds, RARE_CANDY, 5, forget) == "used"
    mon = gen4.read_party(nds)[5]
    assert (mon.species, mon.level) == (388, 16) and [R.move_name(m) for m in mon.moves] == moves
    free_to_walk(nds, map_id)


def test_a_candy_on_a_level_100_pokemon_is_not_spent():
    import bag
    nds = center([(1, LUCARIO, 100, None, 0)])
    assert bag.use_item(nds, RARE_CANDY, 1) == "no_effect"
    assert candies(nds) == 10 and gen4.field_task(nds) == 0


def test_a_missing_item_or_pokemon_leaves_everything_alone():
    import bag
    nds = center()
    assert bag.use_item(nds, 51, 0) == "no_item"
    assert bag.use_item(nds, RARE_CANDY, 6) == "no_pokemon"
    assert bag.give_item(nds, 51, 0) == "no_item"
    assert gen4.field_task(nds) == 0 and candies(nds) == 10


def test_a_second_item_swaps_with_the_first_and_the_first_returns_to_the_bag():
    import bag
    nds = center()
    assert bag.give_item(nds, CHILAN_BERRY, 3) == "given"
    assert gen4.read_party(nds)[3].item == CHILAN_BERRY
    assert gen4.read_bag(nds, from_battle=False)["berries"] == []
    assert bag.give_item(nds, WHITE_HERB, 3) == "given"             # "Would you like to switch the two items?": yes
    assert gen4.read_party(nds)[3].item == WHITE_HERB
    bag_now = gen4.read_bag(nds, from_battle=False)
    assert bag_now["berries"] == [(CHILAN_BERRY, 1)] and WHITE_HERB not in [i for i, _ in bag_now["items"]]
    free_to_walk(nds, gen4.read_location(nds).map_id)


def set_count(nds, item_id, qty):
    """Test setup: the bag's count of item_id, written to its slot."""
    a, off = gen4.resolve(nds)["bag"], 0
    for _, n in gen4.BAG_POCKETS:
        for i in range(n):
            if nds.memory.read_u16(False, a + off + 4 * i) == item_id:
                nds.memory.write_u16(False, a + off + 4 * i + 2, qty)
                return
        off += 4 * n
    raise ValueError(f"no item {item_id} in the bag")


def test_the_last_candy_ends_back_in_the_overworld():
    """With one candy left, the game goes back to the bag after the level-up, not to the party's
    "Use on which Pokémon?", so the flow ends there too. Scripted runs got "stuck" on it."""
    import bag
    nds = center()
    set_count(nds, RARE_CANDY, 1)
    map_id, before = gen4.read_location(nds).map_id, gen4.read_party(nds)[0]
    assert bag.use_item(nds, RARE_CANDY, 0) == "used"
    assert candies(nds) == 0 and gen4.read_party(nds)[0].level == before.level + 1
    free_to_walk(nds, map_id)
