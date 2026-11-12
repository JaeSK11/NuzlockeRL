"""Regression checks for gen4.py against the milestone save states.
Run: ~/venvs/nuzlockerl/bin/python -m pytest -q tests  (from ~/nuzlockeRL)"""
import os, sys
import pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pynds, gen4

ROM = os.environ.get("NUZLOCKERL_ROM", os.path.join(ROOT, "roms/plat-kaizo-nightmare-update-final.nds"))
M = os.path.join(ROOT, "states/milestones")

pytestmark = pytest.mark.skipif(
    not (os.path.exists(ROM) and os.path.isdir(M)),
    reason="needs the Kaizo ROM and local milestone save states (not in git)")


def load(name):
    n = pynds.PyNDS(ROM)
    n.load_state_from_file(os.path.join(M, name))
    n.tick(2)
    return n


def test_no_party_before_starter():
    n = load("00_twinleaf_bedroom_no_party.state")
    assert gen4.read_party(n) == [] and not gen4.in_battle(n)


def test_starter_party_matches_full_scan():
    n = load("01_starter_turtwig_box_screen.state")
    party = gen4.read_party(n)
    assert [(m.species, m.level, m.hp, m.max_hp, m.checksum_ok) for m in party] == [(387, 5, 21, 21, True)]
    assert [addr for addr, _ in gen4.scan_for_mons(n)] == [gen4.resolve(n)["playerBase"]]


def test_barry_battle_state():
    n = load("03_barry1_battle_turn1.state")
    a = gen4.resolve(n)
    assert gen4.in_battle(n, a)
    assert n.memory.read_u16(False, a["enemyTrainerID"]) == 851
    enemy = gen4.read_party(n, a["enemyBase"])
    assert (enemy[0].species, enemy[0].level, enemy[0].hp, enemy[0].max_hp) == (390, 5, 19, 19)
    assert gen4.read_bytes(n, a["statStagesPlayer"], 8) == bytes([6] * 8)


def test_after_battle_party_updated():
    n = load("04_after_barry1_home.state")
    assert not gen4.in_battle(n)
    m = gen4.read_party(n)[0]
    assert (m.species, m.level, m.max_hp, m.moves[:2]) == (387, 6, 23, [33, 72])


def test_struct_held_decrypted_is_not_valid():
    n = load("03_barry1_battle_turn1.state")
    a = gen4.resolve(n)
    raw = bytearray(gen4.read_bytes(n, a["playerBase"], gen4.PARTY_MON_SIZE))
    assert gen4.decode_mon(bytes(raw)).checksum_ok
    held = bytearray(raw)
    held[4:6] = (3).to_bytes(2, "little")
    assert not gen4.decode_mon(bytes(held)).checksum_ok
    # Pokemon_GetValue's window: battle stats already plaintext, blocks still encrypted
    half = bytearray(raw)
    half[136:236] = gen4._crypt(bytes(raw[136:236]), gen4._u32(raw, 0))
    m = gen4.decode_mon(bytes(half))
    assert not m.checksum_ok
    assert gen4.decode_mon(bytes(half), with_battle_stats=False).checksum_ok
