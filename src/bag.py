"""The overworld's Bag: use a Rare Candy on a party Pokémon, or give it an item to hold.

Acts only through button presses, from the overworld with the player free to walk, and reads
RAM to confirm the result: the bag counts, and the party's level, species and held item. The
field menu, the bag and the party screen keep no address of their own that reads live, so the
screens and their cursors are told apart by their pixels, as overworld._yes_no_up does.
"""
from __future__ import annotations

import numpy as np

import gen4
import overworld as O

POCKET_TABS = ("items", "medicine", "balls", "tm_hm", "berries", "mail", "battle_items", "key_items")   # Right's order
MENU_BAG_ROW = 2                # the field menu's rows: Pokédex, Pokémon, Bag
KEY_GAP = 10                    # frames after a press before the next; the cursor moves within a few
SCREEN_FRAMES = 150             # frames for a screen to open or close, with the fade
TEXT_GAP, FLOW_LIMIT = 20, 6000 # frames between A presses through text; frames a flow may run
GIVE_FROM_CANCEL = 2            # Up presses from the first entry of an item's menu, which wraps to CANCEL, to reach GIVE
CLOSE_TRIES = 6                 # B presses to get from any bag screen back to the overworld

MENU_CURSOR = (250, 105, 16)    # the field menu's orange outline, in the column x = 158
TAB_CURSOR = (250, 0, 0)        # the red box round the current pocket's tab
PARTY_CURSOR = (234, 89, 0)     # the orange outline of the selected party slot
PARTY_BOTTOM = (80, 129, 170)   # the party screen's bottom screen, at (5, 5)
MOVE_LIST_TOP = (32, 105, 226)  # the move list's title bar, top screen (5, 5)
PROMPT_BOX = (slice(150, 190), slice(0, 196))   # the party screen's text box, without its CANCEL button and its ▼


def _px(screen, y, x) -> tuple:
    return tuple(int(v) for v in screen[y, x, :3])


def _menu_row(nds) -> int | None:
    """The row of the field menu's cursor (24 pixels per row), None when the menu isn't up."""
    ys = np.nonzero((nds.get_frame()[0][:, 158, :3] == MENU_CURSOR).all(axis=1))[0]
    return int(ys.min() - 8) // 24 if len(ys) >= 20 else None


def _bag_up(nds) -> bool:
    """The bag: a tan bottom screen of pocket buttons."""
    r, g, b = _px(nds.get_frame()[1], 5, 5)
    return r > 220 and g > 190 and b < 140


def _tab(nds) -> int | None:
    """The index in POCKET_TABS of the bag's current pocket: the red box round its tab, 11 pixels per tab."""
    reg = nds.get_frame()[0][89:103, :112, :3]
    xs = np.nonzero((reg == TAB_CURSOR).all(axis=2).any(axis=0))[0]
    return (int(xs.min()) - 5) // 11 if len(xs) else None


def _party_up(nds) -> bool:
    return _px(nds.get_frame()[1], 5, 5) == PARTY_BOTTOM and not _move_list_up(nds)


def _party_cursor(nds) -> int | None:
    """The party slot under the cursor: two columns, slots 0, 2, 4 left and 1, 3, 5 right; None on CANCEL."""
    m = (nds.get_frame()[0][:192, :, :3] == PARTY_CURSOR).all(axis=2)
    ys, xs = np.nonzero(m)
    if len(ys) < 100:
        return None
    return 2 * (int(ys.min()) // 48) + (1 if xs.min() >= 128 else 0)


def _move_list_up(nds) -> bool:
    return _px(nds.get_frame()[0], 5, 5) == MOVE_LIST_TOP


def _prompt(nds) -> np.ndarray:
    return nds.get_frame()[0][PROMPT_BOX][:, :, :3].copy()


def _key(nds, key: str) -> None:
    O.press(nds, key)
    nds.tick(KEY_GAP)


def _until(nds, cond, frames: int = SCREEN_FRAMES) -> bool:
    for _ in range(frames // 2):
        if cond():
            return True
        nds.tick(2)
    return cond()


def _close(nds) -> bool:
    """B back out of whatever is up, until the player is free. Never run during an evolution: B cancels it."""
    for _ in range(CLOSE_TRIES):
        if not gen4.field_task(nds):
            return True
        _key(nds, "b")
        nds.tick(SCREEN_FRAMES // 2)
    return not gen4.field_task(nds)


def _find(nds, item_id: int) -> tuple[str, int] | None:
    """(pocket, position in it) of the item in the bag's RAM, None when the bag has none."""
    for pocket, slots in gen4.read_bag(nds, from_battle=False).items():
        for i, (item, qty) in enumerate(slots):
            if item == item_id:
                return pocket, i
    return None


def _count(nds, item_id: int) -> int:
    return sum(q for slots in gen4.read_bag(nds, from_battle=False).values() for i, q in slots if i == item_id)


def _open_item(nds, pocket: str, pos: int) -> str:
    """The field menu's Bag, the item's pocket, the item selected with its menu open. "" or the failure."""
    _key(nds, "x")
    if not _until(nds, lambda: _menu_row(nds) is not None, 60):
        return "no_menu"
    for _ in range(8):
        if _menu_row(nds) == MENU_BAG_ROW:
            break
        _key(nds, "down")
    _key(nds, "a")
    if not _until(nds, lambda: _bag_up(nds)):
        return "no_bag"
    nds.tick(30)
    want = POCKET_TABS.index(pocket)
    for _ in range(len(POCKET_TABS)):
        if _tab(nds) == want:
            break
        _key(nds, "right")
        nds.tick(20)
    if _tab(nds) != want:
        return "no_pocket"
    size = len(gen4.read_bag(nds, from_battle=False)[pocket])
    for _ in range(size):
        _key(nds, "up")                 # the list doesn't wrap, so this lands on its first item
    for _ in range(pos):
        _key(nds, "down")
    _key(nds, "a")
    nds.tick(20)
    return ""


def _party_to(nds, slot: int) -> bool:
    """Move the party cursor to slot by a path over slots that exist: a party fills in order, so
    a slot's column up from it and the left column beside it are always there."""
    row, col = divmod(slot, 2)
    for _ in range(12):
        here = _party_cursor(nds)
        if here == slot:
            return True
        if here is None:
            key = "up"
        else:
            hr, hc = divmod(here, 2)
            if hc == col:
                key = "down" if hr < row else "up"
            elif col == 0:
                key = "left"
            else:
                key = "up" if hr > row else "right"
        _key(nds, key)
    return _party_cursor(nds) == slot


def _forget_step(nds, forget, state: dict) -> None:
    """One press for a fifth move's prompts: the YES/NO box "Should a move be deleted?" takes A on
    YES, or Down then A on NO, which asks "Stop trying to teach it?" and takes A; the move list takes
    Down to the slot, then A. forget() gives the slot, or None to keep the old moves."""
    if _move_list_up(nds):
        nds.tick(30)
        for _ in range(state.pop("slot", 0)):
            _key(nds, "down")
        _key(nds, "a")
        return
    if state.pop("gave_up", False):
        _key(nds, "a")
        return
    slot = forget() if forget else None
    if slot is None:
        _key(nds, "down")
        state["gave_up"] = True
    else:
        state["slot"] = slot
    _key(nds, "a")


def _play(nds, done, answer) -> bool:
    """Press A through the text, stat boxes and an evolution until done() is true, and call
    answer(state) once for each YES/NO box or move list. A box stays up while it closes and a
    second question can follow it at once, so a box counts as answered while its text is the
    same. Never B, which cancels an evolution."""
    state, answered = {}, None
    for frame in range(0, FLOW_LIMIT, 5):
        if done():
            return True
        if frame % TEXT_GAP == 0:
            question = _prompt(nds)
            if _move_list_up(nds) or O._yes_no_up(nds) and (answered is None or not (question == answered).all()):
                answer(state)
                answered = question
            elif not O._yes_no_up(nds):
                answered = None
                O.press(nds, "a")
        nds.tick(5)
    return False


def use_item(nds, item_id: int, party_slot: int, forget=None) -> str:
    """From the overworld, use a Rare Candy from the bag on the party Pokémon at party_slot, and answer the
    level-up, a fifth move (forget() gives the slot to forget, or None to keep the old moves) and an evolution.
    Returns "used" when the bag's count fell by one and the level rose by one or the Pokémon evolved;
    else why not: "busy" (not free to walk), "no_item", "no_pokemon", "no_menu", "no_bag", "no_pocket",
    "no_party", "no_effect" (the count didn't change), "stuck", "not_closed", or "unconfirmed" (RAM
    disagrees). Ends back in the overworld, with the menus closed."""
    if gen4.field_task(nds):
        return "busy"
    found = _find(nds, item_id)
    if found is None:
        return "no_item"
    party = gen4.read_party(nds)
    if party_slot >= len(party):
        return "no_pokemon"
    before, count = party[party_slot], _count(nds, item_id)
    result = _open_item(nds, *found)
    if not result:
        _key(nds, "a")                  # USE, the first entry of a candy's menu
        if not _until(nds, lambda: _party_up(nds) and _party_cursor(nds) is not None):
            result = "no_party"
        elif not _party_to(nds, party_slot):
            result = "no_party"
    if result:
        _close(nds)
        return result
    nds.tick(30)
    prompt = _prompt(nds)
    _key(nds, "a")
    nds.tick(40)
    last = count == 1                   # with none left, the game goes back to the bag, not to the party's prompt
    asked = lambda: _party_up(nds) and (_prompt(nds) == prompt).all() or last and _bag_up(nds)
    if not _play(nds, asked, lambda state: _forget_step(nds, forget, state)):
        _close(nds)
        return "stuck"
    after = gen4.read_party(nds)[party_slot]
    spent = count - _count(nds, item_id)
    if not _close(nds):
        return "not_closed"
    if spent == 0:
        return "no_effect"
    grown = after.species != before.species or after.level == before.level + 1
    return "used" if spent == 1 and grown else "unconfirmed"


def give_item(nds, item_id: int, party_slot: int) -> str:
    """From the overworld, give an item from the bag to the party Pokémon at party_slot, swapping with
    what it holds. Returns "given" when the Pokémon holds item_id and the bag's count changed; else why not:
    "busy", "no_item", "no_pokemon", "no_menu", "no_bag", "no_pocket", "no_party", "stuck", "not_closed",
    or "unconfirmed" (RAM disagrees). Ends back in the overworld, with the menus closed."""
    if gen4.field_task(nds):
        return "busy"
    found = _find(nds, item_id)
    if found is None:
        return "no_item"
    if party_slot >= len(gen4.read_party(nds)):
        return "no_pokemon"
    before = {i: _count(nds, i) for i in {item_id, gen4.read_party(nds)[party_slot].item}}
    result = _open_item(nds, *found)
    if not result:
        for _ in range(GIVE_FROM_CANCEL + 1):
            _key(nds, "up")             # to CANCEL, then up to GIVE, the entry before TRASH
        _key(nds, "a")
        if not _until(nds, lambda: _party_up(nds) and _party_cursor(nds) is not None) or not _party_to(nds, party_slot):
            result = "no_party"
    if result:
        _close(nds)
        return result
    nds.tick(30)
    _key(nds, "a")
    if not _play(nds, lambda: _bag_up(nds), lambda state: _key(nds, "a")):
        _close(nds)
        return "stuck"
    held = gen4.read_party(nds)[party_slot].item
    changed = any(_count(nds, i) != n for i, n in before.items())
    if not _close(nds):
        return "not_closed"
    return "given" if held == item_id and changed else "unconfirmed"
