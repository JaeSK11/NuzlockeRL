"""Scripted input driver for exploring the game and making save states.

  python drive.py ROM IN_STATE|- OUT_STATE "SCRIPT" [SHOT.png]

SCRIPT is space-separated tokens:
  a b x y l r start select up down left right   tap (hold 6 frames, then 10 idle)
  a*20        repeat a tap 20 times
  hold:up:32  hold a button for 32 frames
  w120        wait 120 frames
  t128,81     tap the touchscreen at (x, y) on the bottom screen
  shot:name   save a screenshot to name.png
  party       print the decoded party (via the gen4 pointer chain)
"""
import sys, os
import numpy as np
from PIL import Image
import pynds
sys.path.insert(0, os.path.dirname(__file__))
import gen4

BUTTONS = {"a", "b", "x", "y", "l", "r", "start", "select", "up", "down", "left", "right"}


def screenshot(nds, path):
    top, bot = nds.get_frame()
    Image.fromarray(np.concatenate([top[..., :3], bot[..., :3]], 0)).save(path)


def tap(nds, key, hold=6, idle=10):
    nds.button.press_key(key); nds.tick(hold)
    nds.button.release_key(key); nds.tick(idle)


def run(nds, script, shotdir="."):
    for tok in script.split():
        if tok in BUTTONS:
            tap(nds, tok)
        elif "*" in tok and tok.split("*")[0] in BUTTONS:
            k, n = tok.split("*")
            for _ in range(int(n)): tap(nds, k)
        elif tok.startswith("hold:"):
            _, k, n = tok.split(":")
            nds.button.press_key(k); nds.tick(int(n)); nds.button.release_key(k); nds.tick(4)
        elif tok.startswith("w"):
            nds.tick(int(tok[1:]))
        elif tok.startswith("t"):
            x, y = map(int, tok[1:].split(","))
            nds.button.set_touch(x, y); nds.button.touch(); nds.tick(6)
            nds.button.release_touch(); nds.tick(10)
        elif tok.startswith("shot:"):
            screenshot(nds, os.path.join(shotdir, tok[5:] + ".png"))
        elif tok == "party":
            for i, m in enumerate(gen4.read_party(nds)):
                print(i, m)
        elif tok == "battle":
            a = gen4.resolve(nds)
            rd = nds.memory.read_u32
            print("battleStatus u8:", hex(nds.memory.read_u8(False, a["battleStatus"])))
            print("enemyTrainerID u16:", nds.memory.read_u16(False, a["enemyTrainerID"]))
            print("playerBattleMonPID:", rd(False, a["playerBattleMonPID"]),
                  "enemyBattleMonPID:", rd(False, a["enemyBattleMonPID"]),
                  "enemyPokemonID u16:", nds.memory.read_u16(False, a["enemyPokemonID"]))
            print("statStages player:", gen4.read_bytes(nds, a["statStagesPlayer"], 8).hex(),
                  "enemy:", gen4.read_bytes(nds, a["statStagesEnemy"], 8).hex())
            for name in ("playerBattleBase", "enemyBase"):
                print(name, hex(a[name]))
                for i, m in enumerate(gen4.read_party(nds, a[name])):
                    print("  ", i, m.species, "lv", m.level, "hp", m.hp, "/", m.max_hp,
                          "moves", m.moves, "ok", m.checksum_ok)
        else:
            raise ValueError(f"bad token {tok!r}")


if __name__ == "__main__":
    rom, st_in, st_out, script = sys.argv[1:5]
    shot = sys.argv[5] if len(sys.argv) > 5 else None
    nds = pynds.PyNDS(rom)
    if st_in != "-":
        nds.load_state_from_file(st_in)
        nds.tick(2)
    run(nds, script, os.path.dirname(shot) if shot else ".")
    if shot:
        screenshot(nds, shot)
    if st_out != "-":
        nds.save_state_to_file(st_out)
