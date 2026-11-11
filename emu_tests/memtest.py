import sys, time
import pynds
nds = pynds.PyNDS(sys.argv[1])
for i in range(3600):
    if i % 60 == 30: nds.button.press_key("a")
    if i % 60 == 35: nds.button.release_key("a")
    nds.tick()
m = nds.memory
print("methods:", [x for x in dir(m) if x.startswith("read")][:6])
hdr = bytes(m.read_u8(False, 0x027FFE00 + i) for i in range(16))
print("header copy @0x027FFE00:", hdr)
for arm7 in (False, True):
    nz = sum(1 for a in range(0x02000000, 0x02400000, 0x1000) if m.read_u32(arm7, a))
    print(f"arm7={arm7}: nonzero sampled main-RAM words {nz}/1024")
t = time.time(); s = 0
for a in range(0x02000000, 0x02000000 + 4*100000, 4): s ^= m.read_u32(False, a)
print(f"100k u32 reads: {(time.time()-t)*1000:.0f} ms")
