"""RAM audit: plays random battles and counts every RAM read that breaks an invariant.

  python scripts/ram_audit.py [--battles 200] [--workers 4] [--seed S] [--probe N] [--sample-every 10]

Each worker runs a BattleEnv with a random masked policy. Raw RAM is read at every step
boundary (the env's reset/step return) and every SAMPLE_EVERY frames in between. The
mid-turn samples come from wrapping env._tick, so src/ is untouched.

Every party struct is also compared with the BattleMon the game keeps in BattleContext,
a second source for the same values. Mid-turn comparisons are informational: the game copies
BattleMon into the party struct some frames later (BattleMon_CopyToParty). Two differences
are by design and handled in the comparison: the toxic counter (status bits 8-11) lives only
in BattleMon, and a fainted mon's party status is cleared while BattleMon keeps it.

For single frames mid-turn the game holds a party struct decrypted in place: either with the
decomp's partyDecrypted/boxDecrypted flags set in the u16 at +4, or, inside Pokemon_GetValue
and Pokemon_SetValue, with no flags and one or both sections plaintext (in_place_window).
Such structs are counted under "held decrypted" and skipped, and gen4.decode_mon reports them
as not checksum_ok, so the env never reads them. A rejected struct that no such window
explains is a strict violation. Use --sample-every 1 to catch every one.

--probe N adds N forced battles per status/stat move: it writes the move into the enemy's
BattleMon slot 0 so the player really gets hit by Leer, Thunder Wave and so on.
Exits 1 if any strict check was violated.
"""
import argparse, collections, multiprocessing as mp, os, random, struct, sys, time, traceback
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
import numpy as np
import gen4
from battle_env import BattleEnv, read_snapshot

M = os.path.join(ROOT, "states/milestones")
STATES = {"03": os.path.join(M, "03_barry1_battle_turn1.state"),
          "05": os.path.join(M, "05_route201_wild_battle.state")}
EXPECT_TRAINER = {"03": 851, "05": 0}
SAMPLE_EVERY = 10

# BattleContext.battleMons (include/battle/battle_context.h:265) as measured in RAM.
BM_OFF, BM_SIZE = 0x2D40, 0xC0
# BattleMon field offsets, from include/battle/battle_mon.h.
BM_MOVES, BM_BOOSTS, BM_ABILITY, BM_PP, BM_LEVEL = 0xC, 0x18, 0x27, 0x2C, 0x34
BM_HP, BM_MAXHP, BM_EXP, BM_PID, BM_STATUS, BM_VOLATILE, BM_ITEM = 0x4C, 0x50, 0x64, 0x68, 0x6C, 0x70, 0x78
BM_TIMES_DAMAGED, BM_EFFECTS_MASK, BM_EFFECTS_TEMP = 0x7C, 0x80, 0x84
CTX_COMMAND_MAX = 44            # BATTLE_CONTROL_END_WAIT, include/battle/battle_controller_player.h
# curCommandState[0] values seen in the 200-battle run; each command keeps its own sub-states.
KNOWN_CS0 = {0, 1, 3, 4, 5, 14}
STAGE_NAMES = ("hp", "atk", "def", "spe", "spa", "spd", "acc", "eva")

PROBES = {   # name: (move id, effect read on the player)
    "Leer": 43, "Growl": 45, "Screech": 103, "Thunder Wave": 86, "Will-O-Wisp": 261,
    "Toxic": 92, "Poison Powder": 77, "Hypnosis": 95, "Confuse Ray": 109, "Swagger": 207,
    "Fake Out": 252,
}


def status_ok(s: int) -> bool:
    """Gen 4 status word: sleep counter in bits 0-2, then poison, burn, freeze, paralysis,
    toxic, and the toxic counter in bits 8-11. At most one major condition."""
    if s >> 12:
        return False
    major = (s & 7 > 0) + (s >> 4 & 1) + (s >> 5 & 1) + (s >> 6 & 1) + ((s >> 3 & 1) | (s >> 7 & 1))
    return major <= 1 and (s >> 8 & 15 == 0 or s >> 7 & 1 == 1)


class Audit:
    def __init__(self):
        self.res = {}                                  # (check, where) -> [passed, violated, examples]
        self.vals = collections.defaultdict(collections.Counter)
        self.label, self.where = "", "step"
        self.skip = set()

    def check(self, name, ok, detail=""):
        r = self.res.setdefault((name, self.where), [0, 0, []])
        r[0 if ok else 1] += 1
        if not ok and len(r[2]) < 3:
            r[2].append(f"{self.label} {detail() if callable(detail) else detail}")
        return ok

    def merge(self, other):
        for k, (p, v, ex) in other.res.items():
            r = self.res.setdefault(k, [0, 0, []])
            r[0] += p
            r[1] += v
            r[2] += ex[:3 - len(r[2])] if len(r[2]) < 3 else []
        for k, c in other.vals.items():
            self.vals[k].update(c)


def info_row(name, where):
    return name.startswith("8 ") and where == "mid"


def parse_bm(b: bytes) -> dict:
    u16 = lambda o: int.from_bytes(b[o:o + 2], "little")
    u32 = lambda o: int.from_bytes(b[o:o + 4], "little")
    return dict(
        species=u16(0), stats=tuple(u16(2 + 2 * i) for i in range(5)),
        moves=tuple(u16(BM_MOVES + 2 * i) for i in range(4)),
        boosts=tuple(struct.unpack_from("<8b", b, BM_BOOSTS)), ability=b[BM_ABILITY],
        pp=tuple(b[BM_PP:BM_PP + 4]), level=b[BM_LEVEL],
        hp=struct.unpack_from("<i", b, BM_HP)[0], max_hp=u32(BM_MAXHP), exp=u32(BM_EXP),
        pid=u32(BM_PID), status=u32(BM_STATUS), volatile=u32(BM_VOLATILE), item=u16(BM_ITEM),
        times_damaged=b[BM_TIMES_DAMAGED], effects_mask=u32(BM_EFFECTS_MASK),
        effects_temp=u32(BM_EFFECTS_TEMP))


def read_side(nds, base):
    """[(slot, Mon, held)] for each non-empty slot of a 6-struct party array. held says why
    the game has that struct (partly) decrypted in place, and is "" when it doesn't: the
    flags in the u16 at +4, or else the window that in_place_window() finds."""
    raw = gen4.read_bytes(nds, base, gen4.PARTY_MON_SIZE * 6)
    out = []
    for i in range(6):
        chunk = raw[i * gen4.PARTY_MON_SIZE:(i + 1) * gen4.PARTY_MON_SIZE]
        if int.from_bytes(chunk[0:4], "little") or int.from_bytes(chunk[6:8], "little"):
            m, flags = gen4.decode_mon(chunk), int.from_bytes(chunk[4:6], "little")
            held = f"flags={flags}" if flags else "" if m.checksum_ok else in_place_window(chunk)
            out.append((i, m, held))
    return out


def in_place_window(chunk: bytes) -> str:
    """For a struct decode_mon rejects with no flags set: the point inside Pokemon_GetValue or
    Pokemon_SetValue (decomp src/pokemon.c) that explains it, or "" if none does. Those decrypt
    the battle stats, then the blocks, in place, and re-encrypt in the same order. So each
    section must be valid encrypted, plaintext, or part way through (the words up to some
    point already converted). The blocks are valid when their plaintext sums to the checksum."""
    words = lambda b: sum(int.from_bytes(b[j:j + 2], "little") for j in range(0, len(b), 2)) & 0xFFFF
    pid, checksum, enc = gen4._u32(chunk, 0), gen4._u16(chunk, 6), chunk[8:136]
    dec_b = gen4._crypt(enc, checksum)
    blocks = None
    for k in (0, 64, *range(1, 64)):    # words of the blocks already plaintext (decrypting)
        if words(enc[:2 * k] + dec_b[2 * k:]) == checksum:
            blocks = {0: "encrypted", 64: "plaintext"}.get(k, "partly plaintext")
            break
    else:
        for k in range(1, 64):          # words of the blocks already encrypted again
            if words(dec_b[:2 * k] + enc[2 * k:]) == checksum:
                blocks = "partly encrypted again"
                break
    if blocks is None:
        return ""
    raw, dec = chunk[136:236], gen4._crypt(chunk[136:236], pid)
    # k = words of the battle stats already plaintext; status..max_hp are words 0-4. Whole
    # sections first: a garbage level and hp pass by chance about 1 time in 5.
    for k in (0, 5, 1, 2, 3, 4):
        status, level, hp, max_hp = struct.unpack_from("<IBxHH", raw[:2 * k] + dec[2 * k:])
        if (blocks, k) != ("encrypted", 0) and status_ok(status) and 1 <= level <= 100 and 0 < max_hp and hp <= max_hp:
            stats = {0: "encrypted", 5: "plaintext"}.get(k, "partly plaintext")
            return f"blocks {blocks}, battle stats {stats}"
    return ""


def sample(env, aud: Audit, where: str):
    nds, a = env.nds, env.addrs
    if not gen4.in_battle(nds, a):
        return
    aud.where = where
    aud.label = f"{aud.state} seed={aud.seed} turn={env.turn} f={env._ep_frames}"
    ck = aud.check
    raw_sides = {"player": read_side(nds, a["playerBattleBase"]), "enemy": read_side(nds, a["enemyBase"])}
    held = [f"{side}[{i}] {f}" for side, slots in raw_sides.items() for i, _, f in slots if f]
    for h in held:
        aud.vals["structs held decrypted by the game (expected, skipped)"][h] += 1
    if not held:
        ck("1 read_snapshot() is not None", read_snapshot(nds, a) is not None)
    sides = {side: [(i, m) for i, m, f in slots if not f] for side, slots in raw_sides.items()}
    for side, slots in sides.items():
        for i, m in slots:
            tag = lambda: f"{side}[{i}] {m}"
            if not ck("1 struct checksum_ok", m.checksum_ok, tag):
                aud.vals["structs failing the checksum"][f"{side}[{i}]"] += 1
                continue
            ck("2 species 1-493", 1 <= m.species <= 493, tag)
            ck("2 level 1-100", 1 <= m.level <= 100, tag)
            ck("2 max_hp > 0", m.max_hp > 0, tag)
            ck("2 hp <= max_hp", m.hp <= m.max_hp, tag)
            ck("2 move ids 0-467", all(0 <= x <= 467 for x in m.moves), tag)
            ck("2 pp == 0 where move == 0", all(p == 0 for x, p in zip(m.moves, m.pp) if x == 0), tag)
            ck("2 pp <= 64", all(p <= 64 for p in m.pp), tag)
            ck("2 status valid Gen 4 bits", status_ok(m.status), tag)

    pids = {"player": nds.memory.read_u32(False, a["playerBattleMonPID"]),
            "enemy": nds.memory.read_u32(False, a["enemyBattleMonPID"])}
    active = {}
    for side, slots in sides.items():
        active[side] = next((m for _, m in slots if m.pid == pids[side]), None)
        if active[side] is None and any(f for _, _, f in raw_sides[side]):
            continue
        ck(f"3 {side}BattleMonPID matches a party slot", active[side] is not None, f"pid={pids[side]:#x}")

    stages = {"player": tuple(gen4.read_bytes(nds, a["statStagesPlayer"], 8)),
              "enemy": tuple(gen4.read_bytes(nds, a["statStagesEnemy"], 8))}
    for side, st in stages.items():
        ck("4 stage bytes 0-12", all(0 <= x <= 12 for x in st), f"{side} {st}")
        for i, x in enumerate(st):
            if x != 6:
                aud.moved[side].add(STAGE_NAMES[i])
    tid = nds.memory.read_u16(False, a["enemyTrainerID"])
    ck("5 enemyTrainerID", tid == EXPECT_TRAINER[aud.state], f"got {tid}")

    wiped = any(slots and all(m.hp == 0 for _, m in slots) for slots in sides.values())
    rm = nds.memory.read_u8(False, a["battleResult"])
    if not wiped:
        ck("7 resultMask == 0 before decided", rm == 0, f"resultMask={rm}")
    else:
        aud.vals["resultMask once a side is wiped"][rm] += 1

    cmd = gen4.read_battle_command(nds, a)
    if not ck("6 battleCtxPtr valid in battle", cmd is not None):
        return
    ctx = nds.memory.read_u32(False, a["battleCtxPtr"])
    aud.vals["command"][cmd[0]] += 1
    aud.vals["curCommandState[0]"][cmd[1]] += 1
    ck("6 command in 0-44 (decomp enum)", 0 <= cmd[0] <= CTX_COMMAND_MAX, f"command={cmd[0]}")
    ck("6 curCommandState[0] in known set", cmd[1] in KNOWN_CS0, f"cs0={cmd[1]}")

    raw = gen4.read_bytes(nds, ctx + BM_OFF, 2 * BM_SIZE)
    bms = {"player": parse_bm(raw[:BM_SIZE]), "enemy": parse_bm(raw[BM_SIZE:])}
    for side, bm in bms.items():
        ck("8 BattleMon curHP <= maxHP, species 1-493",
           0 <= bm["hp"] <= bm["max_hp"] and 1 <= bm["species"] <= 493, f"{side} {bm}")
        ck("8 BattleMon.personality == battle mon PID", bm["pid"] == pids[side], f"{side} {bm['pid']:#x}")
        for k in ("status", "volatile", "effects_mask", "effects_temp", "times_damaged", "boosts"):
            aud.vals[f"{side}.{k}"][bm[k]] += 1
        m = active[side]
        if m is None or not (m.checksum_ok and 1 <= m.level <= 100 and m.hp <= m.max_hp
                             and status_ok(m.status)):
            continue
        aud.vals[f"{side}.party status"][m.status] += 1
        pairs = {"species": (bm["species"], m.species), "level": (bm["level"], m.level),
                 "curHP": (bm["hp"], m.hp), "maxHP": (bm["max_hp"], m.max_hp),
                 "moves": (bm["moves"], tuple(m.moves)), "ppCur": (bm["pp"], tuple(m.pp)),
                 "exp": (bm["exp"], m.exp),
                 "ability": (bm["ability"], m.ability), "heldItem": (bm["item"], m.item),
                 "stats atk/def/spe/spa/spd": (bm["stats"], tuple(m.stats.values())),
                 "statBoosts == statStages": (bm["boosts"], stages[side])}
        if bm["hp"] > 0:
            pairs["status (BattleMon minus toxic counter bits 8-11)"] = (bm["status"] & ~0xF00, m.status)
        else:
            pairs["status of a fainted mon: party copy cleared"] = (0, m.status)
        for name, (x, y) in pairs.items():
            if name in aud.skip and side == "enemy":
                continue
            ok = ck(f"8 {name}", x == y, f"{side} BattleMon={x} party={y}")
            run = aud.runs.get((side, name), 0)
            if aud.where == "mid":
                if not ok:
                    aud.runs[(side, name)] = run + 1
                elif run:
                    aud.vals[f"mismatch run length in samples, {name}"][run] += 1
                    aud.runs[(side, name)] = 0
    if aud.where == "step" and not aud.located:
        aud.located = True
        pid = pids["player"]
        found = [o for o in range(0, 0x4000, 4)
                 if nds.memory.read_u32(False, ctx + o) == pid]
        ck("8 PID search finds battleMons[0].personality at the fixed offset",
           found == [BM_OFF + BM_PID], f"found {[hex(o) for o in found]}")


def hook(env, aud_box):
    orig = env._tick

    def tick(n=1):
        while n > 0:
            k = min(n, SAMPLE_EVERY - env._ep_frames % SAMPLE_EVERY)
            orig(k)
            n -= k
            if env._ep_frames % SAMPLE_EVERY == 0 and aud_box[0] is not None:
                safe_sample(env, aud_box[0], "mid")
    env._tick = tick


def safe_sample(env, aud, where):
    try:
        sample(env, aud, where)
    except Exception as e:
        aud.where = where
        aud.check("sampler raised no exception", False, repr(e))


ENV, BOX, INIT_ERROR = None, [None], None


def init_worker(every):
    # mp.Pool replaces a worker whose initializer raises, forever, so a bad setup would
    # spin instead of failing. Keep the error and raise it from play(), in the main process.
    global ENV, SAMPLE_EVERY, INIT_ERROR
    SAMPLE_EVERY = every
    try:
        ENV = BattleEnv(list(STATES.values()))
        hook(ENV, BOX)
    except Exception:
        INIT_ERROR = traceback.format_exc()


def play(job):
    """job = (index, state key, seed, forced enemy move id or None). Returns (index, Audit, outcome)."""
    if INIT_ERROR:
        raise RuntimeError(f"worker setup failed:\n{INIT_ERROR}")
    idx, st, seed, force = job
    env, aud = ENV, Audit()
    aud.state, aud.seed, aud.located, aud.runs = st, seed, False, {}
    aud.moved = {"player": set(), "enemy": set()}
    if force:
        aud.skip = {"moves", "ppCur"}
    BOX[0] = aud
    rng = random.Random(seed ^ 0x5EED)
    outcome = "ERROR"
    try:
        _, info = env.reset(seed=seed, options={"state": STATES[st]})
        if force:
            ctx = env.nds.memory.read_u32(False, env.addrs["battleCtxPtr"])
            env.nds.memory.write_u16(False, ctx + BM_OFF + BM_SIZE + BM_MOVES, force)
            env.nds.memory.write_u8(False, ctx + BM_OFF + BM_SIZE + BM_PP, 30)
        safe_sample(env, aud, "step")
        while True:
            legal = np.flatnonzero(info["action_mask"])
            if not len(legal):
                outcome = "NO_ACTION"
                break
            _, _, term, trunc, info = env.step(int(rng.choice(list(legal))))
            safe_sample(env, aud, "step")
            if term or trunc:
                outcome = info["outcome"]
                break
    except Exception as e:
        aud.where, aud.label = "step", f"{st} seed={seed}"
        aud.check("episode runs without exception", False, repr(e))
    aud.where, aud.label = "step", f"{st} seed={seed}"
    aud.check("episode ends without STUCK/ERROR", outcome not in ("STUCK", "ERROR"), outcome)
    BOX[0] = None
    aud.vals[f"outcome {st}"][outcome] += 1
    for side, moved in aud.moved.items():
        aud.vals[f"battles with stage off 6, {side} {st}"][bool(moved)] += 1
        for name in moved:
            aud.vals[f"stage moved off 6, {side}, by index (battles)"][name] += 1
    return idx, aud, outcome


def table(aud: Audit, title: str) -> int:
    rows = sorted({k[0] for k in aud.res})
    print(f"\n{title}\n{'check':<68}{'step ok':>9}{'step bad':>9}{'mid ok':>9}{'mid bad':>9}")
    bad_strict = 0
    for name in rows:
        cells, mark = [], ""
        for where in ("step", "mid"):
            p, v, _ = aud.res.get((name, where), [0, 0, []])
            cells += [p, v]
            if v:
                if info_row(name, where):
                    mark = mark or " (info)"
                else:
                    bad_strict += v
                    mark = " <== VIOLATED"
        print(f"{name:<68}{cells[0]:>9}{cells[1]:>9}{cells[2]:>9}{cells[3]:>9}{mark}")
    for (name, where), (p, v, ex) in sorted(aud.res.items()):
        for e in ex:
            print(f"  e.g. [{where}] {name}: {e}")
    return bad_strict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--battles", type=int, default=200)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--sample-every", type=int, default=SAMPLE_EVERY, help="frames between mid-turn samples")
    ap.add_argument("--probe", type=int, default=0, help="forced battles per probe move")
    args = ap.parse_args()
    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(2 ** 31)
    jobs = [(i, ("03", "05")[i % 2], seed * 100003 + i, None) for i in range(args.battles)]
    pjobs = [(10 ** 6 + j * 1000 + k, "03", seed * 100003 + 10 ** 6 + j * 1000 + k, mv)
             for j, mv in enumerate(PROBES.values()) for k in range(args.probe)]
    print(f"{args.battles} battles (+{len(pjobs)} probe), {args.workers} workers, seed {seed}")
    t0 = time.time()
    results = {}
    with mp.Pool(args.workers, init_worker, (args.sample_every,)) as pool:
        for n, (idx, aud, outcome) in enumerate(pool.imap_unordered(play, jobs + pjobs), 1):
            results[idx] = aud
            if n % 10 == 0:
                print(f"  {n}/{len(jobs) + len(pjobs)} battles, {time.time() - t0:.0f}s", flush=True)
    main_aud, probe_aud = Audit(), collections.defaultdict(Audit)
    for idx in sorted(results):
        if idx < 10 ** 6:
            main_aud.merge(results[idx])
        else:
            name = list(PROBES)[(idx - 10 ** 6) // 1000]
            probe_aud[name].merge(results[idx])
    bad = table(main_aud, "Random-policy battles")
    for k, c in sorted(main_aud.vals.items()):
        print(f"{k}: " + ", ".join(f"{x}:{n}" for x, n in sorted(c.items())))
    for name, aud in probe_aud.items():
        print(f"\nProbe: enemy forced to use {name}")
        for (chk, where), (p, v, ex) in sorted(aud.res.items()):
            if v:
                bad += 0 if info_row(chk, where) else v
                print(f"  {chk} [{where}] {p} ok, {v} bad" + (" (info)" if info_row(chk, where) else ""), ex[:1])
        for k, c in sorted(aud.vals.items()):
            if k.startswith(("player.status", "player.volatile", "player.boosts", "player.effects", "outcome")):
                print(f"  {k}: " + ", ".join(f"{x}:{n}" for x, n in sorted(c.items())))
    print(f"\n{bad} strict violations, {time.time() - t0:.0f}s")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
