import sys, time, os
import numpy as np
from PIL import Image
import pynds

rom, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
t = time.time()
nds = pynds.PyNDS(rom) if hasattr(pynds, "PyNDS") else pynds.pynds(rom)
print("init s:", round(time.time() - t, 2), "type:", type(nds).__name__)

def snap(name):
    top, bot = nds.get_frame()
    print(name, "frame shapes", top.shape, bot.shape, "top mean", round(float(top.mean()), 1))
    Image.fromarray(np.concatenate([top[..., :3], bot[..., :3]], axis=0)).save(f"{out}/{name}.png")

# boot: tick through intro, mash A periodically
t = time.time(); n = 0
for i in range(3600):
    if i % 60 == 30: nds.button.press_key("a")
    if i % 60 == 35: nds.button.release_key("a")
    nds.tick(); n += 1
el = time.time() - t
print(f"boot frames {n} in {el:.2f}s -> {n/el:.0f} fps (boot, tick)")
snap("after_boot")
for k in range(5):
    for i in range(600):
        if i % 40 == 0: nds.button.press_key("a")
        if i % 40 == 5: nds.button.release_key("a")
        nds.tick()
    snap(f"later_{k}")

t = time.time()
for i in range(600): nds.tick()
el = time.time() - t
print(f"tick() with frame copy: {600/el:.0f} fps")

st = f"{out}/test.state"
nds.save_state_to_file(st); print("state bytes", os.path.getsize(st))
t = time.time()
for _ in range(20): nds.load_state_from_file(st)
print(f"load_state avg ms: {(time.time()-t)/20*1000:.1f}")
print("header @0x027FFE00:", hex(nds.memory.read_u32(False, 0x027FFE00)))
