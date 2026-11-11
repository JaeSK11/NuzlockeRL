import sys, numpy as np
from PIL import Image
import pynds
nds = pynds.PyNDS(sys.argv[1])
nds.load_state_from_file(sys.argv[2] if len(sys.argv) > 2 else "out/test.state")
nds.tick(5)
m = nds._nds
import inspect
print("read sig:", m.read_ram_u32.__doc__)
for addr in (0x02000000, 0x02000800, 0x02100000, 0x027FFE00, 0x027FFC00, 0x023FFE00):
    try: print(hex(addr), hex(nds.memory.read_u32(False, addr)))
    except Exception as e: print(hex(addr), "ERR", e)
try:
    print("arm9 explicit 0x023FFE00:", hex(m.read_ram_u32(False, 0x023FFE00, False)))
except Exception as e: print("explicit ERR", e)
nz = sum(1 for a in range(0x02000000, 0x02400000, 0x1000) if nds.memory.read_u32(False, a))
print("nonzero words sampled in main RAM:", nz, "/ 1024")
# touch YES button (bottom screen ~ (128, 273-192=81))
nds.button.set_touch(128, 81); nds.button.touch()
nds.tick(6); nds.button.release_touch(); nds.tick(120)
top, bot = nds.get_frame()
Image.fromarray(np.concatenate([top[..., :3], bot[..., :3]], 0)).save("out/after_touch.png")
