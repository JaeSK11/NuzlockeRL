#!/usr/bin/env python3
"""Compare the Kaizo ROM's data with vanilla Platinum (pret/pokeplatinum, repos/pokeplatinum) and print a summary.
Vanilla is read from the decomp's JSON sources. Output also goes to roms/extracted/hack_diff.txt (gitignored).

    ~/venvs/nuzlockerl/bin/python scripts/hack_diff.py [--out PATH]
"""
import argparse, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
import romdata as R

DECOMP = os.path.join(ROOT, "repos/pokeplatinum")


def enum(name):
    return [l.strip() for l in open(os.path.join(DECOMP, "generated", name + ".txt")) if l.strip()]


SPECIES, MOVES, ABILITIES, ITEMS, TYPES = (enum(n) for n in ("species", "moves", "abilities", "items", "pokemon_types"))
EGG_GROUPS, EFFECTS, RANGES = enum("egg_groups"), enum("move_battle_effects"), enum("move_ranges")
FLAG_BITS = {n: i for i, n in enumerate(enum("move_flags"))}
AI_BITS = {n: i - 1 for i, n in enumerate(enum("ai_flags")) if i}
TRAINERS, CLASSES = enum("trainers"), enum("trainer_classes")
GENDER = {"MALE_ONLY": 0, "FEMALE_12_5": 31, "FEMALE_25": 63, "FEMALE_50": 127, "FEMALE_75": 191,
          "FEMALE_87_5": 223, "FEMALE_ONLY": 254, "NO_GENDER": 255}
GROWTH = ["MEDIUM_FAST", "ERRATIC", "FLUCTUATING", "MEDIUM_SLOW", "FAST", "SLOW"]
EVO_BITS = {n: i for i, n in enumerate(enum("evolution_methods"))}
ID = {"species": {n: i for i, n in enumerate(SPECIES)}, "moves": {n: i for i, n in enumerate(MOVES)},
      "items": {n: i for i, n in enumerate(ITEMS)}}


def jload(*parts):
    with open(os.path.join(DECOMP, *parts), encoding="utf8") as f:
        return json.load(f)


def tm_bit(marker):
    return int(marker[2:]) - 1 if marker.startswith("TM") else 92 + int(marker[2:]) - 1


def vanilla_species(i):
    j = jload("res/pokemon", SPECIES[i][8:].lower(), "data.json")
    bs, ev = j["base_stats"], j["ev_yields"]
    keys = ("hp", "attack", "defense", "speed", "special_attack", "special_defense")
    return R.Species(
        id=i, name=R.species_name(i), base_stats=tuple(bs[k] for k in keys),
        types=tuple(TYPES.index(t) for t in j["types"]), abilities=tuple(ABILITIES.index(a) for a in j["abilities"]),
        growth_rate=GROWTH.index(j["exp_rate"][9:]), catch_rate=j["catch_rate"], base_exp=j["base_exp_reward"],
        gender_ratio=GENDER[j["gender_ratio"][13:]], ev_yield=tuple(ev[k] for k in keys),
        held_items=(ITEMS.index(j["held_items"]["common"]), ITEMS.index(j["held_items"]["rare"])),
        egg_groups=tuple(EGG_GROUPS.index(g) for g in j["egg_groups"]), base_friendship=j["base_friendship"],
        hatch_cycles=j["hatch_cycles"],
        tm_mask=sum(1 << tm_bit(m) for m in j["learnset"]["by_tm"]))


def vanilla_learnset(i):
    return tuple((lv, ID["moves"][m]) for lv, m in jload("res/pokemon", SPECIES[i][8:].lower(), "data.json")["learnset"]["by_level"])


def vanilla_evolutions(i):
    out = []
    for e in jload("res/pokemon", SPECIES[i][8:].lower(), "data.json").get("evolutions", []):
        method = EVO_BITS[e[0]]
        if len(e) == 2:
            out.append(R.Evolution(method, 0, ID["species"][e[1]]))
            continue
        p = e[1]
        param = ID["items"][p] if isinstance(p, str) and p.startswith("ITEM_") else \
            ID["moves"][p] if isinstance(p, str) and p.startswith("MOVE_") else \
            ID["species"][p] if isinstance(p, str) else p
        out.append(R.Evolution(method, param, ID["species"][e[2]]))
    return tuple(out)


def vanilla_move(i):
    j = jload("res/moves", MOVES[i][5:].lower(), "data.json")
    return R.Move(id=i, name=j["name"], type=TYPES.index(j["type"]), cls=("CLASS_PHYSICAL", "CLASS_SPECIAL", "CLASS_STATUS").index(j["class"]),
                  power=j["power"], accuracy=j["accuracy"], pp=j["pp"], priority=j["priority"],
                  effect=EFFECTS.index(j["effect"]["type"]), effect_chance=j["effect"]["chance"],
                  target=0 if j["range"] == RANGES[0] else 1 << (RANGES.index(j["range"]) - 1), flags=sum(1 << FLAG_BITS[f] for f in j["flags"]))


def vanilla_trainer(i):
    j = jload("res/trainers/data", TRAINERS[i][8:].lower() + ".json")
    party = []
    for m in j["party"]:
        moves = tuple(ID["moves"][x] for x in m["moves"]) if m.get("moves") is not None else None
        party.append(R.TrainerMon(species=ID["species"][m["species"]], form=m["form"], level=m["level"],
                                  iv_scale=m["iv_scale"], item=ID["items"][m["item"]] if m.get("item") else 0,
                                  moves=moves, ball_seal=m.get("ball_seal", 0)))
    return R.Trainer(id=i, name=j["name"], class_id=CLASSES.index(j["class"]), class_name="",
                     ai_flags=sum(1 << AI_BITS[f] for f in j["ai_flags"] if f in AI_BITS), double_battle=j["double_battle"],
                     items=tuple(ID["items"][x] for x in j["items"] if x != "ITEM_NONE"), party=tuple(party))


def vanilla_encounters(stem):
    path = os.path.join(DECOMP, "res/field/maps", stem, "encounters.json")
    if not os.path.exists(path):
        return None
    j = jload("res/field/maps", stem, "encounters.json")
    sp = lambda x: ID["species"][x]
    water = lambda k: R.WaterTable(j.get(k + "_rate", 0), tuple(R.WaterSlot(e["level_min"], e["level_max"], sp(e["species"])) for e in j.get(k + "_encounters", [])))
    grass = tuple(R.GrassSlot(e["level"], sp(e["species"])) for e in j.get("land_encounters", []))
    return R.Encounters(id=-1, grass_rate=j.get("land_rate", 0), grass=grass,
                        swarm=tuple(map(sp, j.get("swarms", []))), day=tuple(map(sp, j.get("day", []))),
                        night=tuple(map(sp, j.get("night", []))), radar=tuple(map(sp, j.get("radar", []))),
                        surf=water("surf"), old_rod=water("old_rod"), good_rod=water("good_rod"), super_rod=water("super_rod"))


ENC_ORDER = [l.strip()[len("encounters_"):] for l in open(os.path.join(DECOMP, "res/field/encounters.order")) if l.strip()]
SP = lambda i: R.species_name(i) if i else "-"
MV = lambda i: R.move_name(i) if i else "-"
VMV = lambda i: vanilla_move(i).name if i else "-"        # vanilla's name for a move id; the hack renamed 26 ids
TY = lambda t: "/".join(dict.fromkeys(R.TYPE_NAMES[x] for x in t))
AB = lambda a: "/".join(R.ability_name(x) if x else "-" for x in a)
STAT_LABEL = ("HP", "Atk", "Def", "Spe", "SpA", "SpD")


def species_changes(h, v):
    """List of 'field before -> after' strings, split into core (stats, types, abilities) and other."""
    core, other = [], []
    for k, (a, b) in enumerate(zip(v.base_stats, h.base_stats)):
        if a != b:
            core.append(f"{STAT_LABEL[k]} {a}->{b}")
    if v.types != h.types: core.append(f"type {TY(v.types)} -> {TY(h.types)}")
    if v.abilities != h.abilities: core.append(f"ability {AB(v.abilities)} -> {AB(h.abilities)}")
    for label, a, b in (("catch", v.catch_rate, h.catch_rate), ("base exp", v.base_exp, h.base_exp),
                        ("growth", R.GROWTH_RATES[v.growth_rate], R.GROWTH_RATES[h.growth_rate]),
                        ("gender", v.gender_ratio, h.gender_ratio), ("EV yield", v.ev_yield, h.ev_yield),
                        ("held items", v.held_items, h.held_items), ("egg groups", v.egg_groups, h.egg_groups)):
        if a != b:
            other.append(f"{label} {a}->{b}")
    if v.tm_mask != h.tm_mask:
        gained = [i for i in range(100) if h.tm_mask >> i & 1 and not v.tm_mask >> i & 1]
        lost = [i for i in range(100) if v.tm_mask >> i & 1 and not h.tm_mask >> i & 1]
        other.append(f"TM/HM +{len(gained)} -{len(lost)}")
    return core, other


def fmt_learnset(ls, name=MV):
    return ", ".join(f"{l}:{name(m)}" for l, m in ls)


def fmt_mon(m, learnset_of, name):
    moves = m.moves if m.moves is not None else R.moves_from_learnset(learnset_of(m.species), m.level)
    return f"{SP(m.species)} Lv{m.level} [{', '.join(name(x) for x in moves)}] iv{m.iv_scale}" + (f" item:{R.item_name(m.item)}" if m.item else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "roms/extracted/hack_diff.txt"))
    args = ap.parse_args()
    lines = []
    out = lines.append

    species_ids = range(1, 494)
    sp_h, sp_v = {i: R.species(i) for i in species_ids}, {i: vanilla_species(i) for i in species_ids}
    ls_h, ls_v = {i: R.learnset(i) for i in species_ids}, {i: vanilla_learnset(i) for i in species_ids}
    ev_h, ev_v = {i: R.evolutions(i) for i in species_ids}, {i: vanilla_evolutions(i) for i in species_ids}
    changes = {i: species_changes(sp_h[i], sp_v[i]) for i in species_ids}
    changed_stats = [i for i in species_ids if sp_h[i].base_stats != sp_v[i].base_stats]
    changed_types = [i for i in species_ids if sp_h[i].types != sp_v[i].types]
    changed_abil = [i for i in species_ids if sp_h[i].abilities != sp_v[i].abilities]
    changed_any = [i for i in species_ids if any(changes[i])]

    mv_ids = range(1, 468)
    mv_h, mv_v = {i: R.move(i) for i in mv_ids}, {i: vanilla_move(i) for i in mv_ids}
    mfields = ("power", "accuracy", "pp", "type", "cls", "priority", "effect", "effect_chance", "target", "flags")
    mchanged = {f: [i for i in mv_ids if getattr(mv_h[i], f) != getattr(mv_v[i], f)] for f in mfields}

    tr_ids = range(1, 928)
    tr_h, tr_v = {i: R.trainer(i) for i in tr_ids}, {i: vanilla_trainer(i) for i in tr_ids}

    def trainer_key(t, learnset_of):
        return (t.class_id, t.ai_flags, t.double_battle, t.items,
                tuple((m.species, m.form, m.level, m.iv_scale, m.item or 0,
                       m.moves if m.moves is not None else R.moves_from_learnset(learnset_of(m.species), m.level)) for m in t.party))
    tr_changed = [i for i in tr_ids if trainer_key(tr_h[i], R.learnset) != trainer_key(tr_v[i], lambda s: ls_v[s] if s in ls_v else ())]

    enc_pairs = {}
    for eid, stem in enumerate(ENC_ORDER):
        v = vanilla_encounters(stem)
        if v is not None:
            enc_pairs[stem] = (R.encounters(eid), v)
    enc_changed = [s for s, (h, v) in enc_pairs.items() if (h.grass_rate, h.grass) != (v.grass_rate, v.grass) or h.surf != v.surf
                   or h.old_rod != v.old_rod or h.good_rod != v.good_rod or h.super_rod != v.super_rod]

    out("KAIZO vs VANILLA PLATINUM. Vanilla = pret/pokeplatinum res/ JSON; Kaizo = ROM " + os.path.basename(R.ROM_PATH))
    out("")
    out("== SUMMARY ==")
    out(f"species (1-493) with changed base stats: {len(changed_stats)}, types: {len(changed_types)}, abilities: {len(changed_abil)}, any field: {len(changed_any)}")
    out("species with changed " + ", ".join(
        f"{label} {sum(any(c.startswith(label) for c in changes[i][1]) for i in species_ids)}"
        for label in ("catch", "base exp", "growth", "gender", "EV yield", "held items", "egg groups", "TM/HM")))
    out(f"species with a changed level-up learnset: {sum(ls_h[i] != ls_v[i] for i in species_ids)}, evolutions: {sum(ev_h[i] != ev_v[i] for i in species_ids)}")
    out("moves (1-467) changed, by field: " + ", ".join(f"{f} {len(mchanged[f])}" for f in mfields))
    out(f"trainers (1-927) with a changed party, class, AI or items: {len(tr_changed)}")
    out(f"encounter tables compared: {len(enc_pairs)}, with different grass or water slots: {len(enc_changed)}")

    out("")
    out("== STARTERS (all fields that changed; base stats are HP/Atk/Def/Spe/SpA/SpD) ==")
    starters = (387, 388, 389, 390, 391, 392, 393, 394, 395)
    for i in starters:
        h, core_other = sp_h[i], changes[i]
        out(f"{SP(i)} ({i}): {'/'.join(map(str, h.base_stats))}  {TY(h.types)}  {AB(h.abilities)}  catch {h.catch_rate}")
        out("    changed: " + ("; ".join(core_other[0] + core_other[1]) or "nothing"))
        if ev_h[i] != ev_v[i]:
            out("    evolutions: " + str([(R.EVO_METHODS[e.method], e.param, SP(e.target)) for e in ev_v[i]]) + " -> " + str([(R.EVO_METHODS[e.method], e.param, SP(e.target)) for e in ev_h[i]]))
        else:
            out("    evolutions: unchanged " + str([(R.EVO_METHODS[e.method], e.param, SP(e.target)) for e in ev_h[i]]))
        out(f"    learnset vanilla: {fmt_learnset(ls_v[i], VMV)}")
        out(f"    learnset kaizo:   {fmt_learnset(ls_h[i])}")

    early_maps = [s for s in ENC_ORDER if re.fullmatch(r"route_20[1-4].*|oreburgh_gate.*|oreburgh_mine.*|ravaged_path|wayward_cave.*|floaroma_meadow|lake_verity.*|twinleaf_town|sendoff_spring", s)]

    def water_slots(t):
        return [s for tab in (t.surf, t.old_rod, t.good_rod, t.super_rod) for s in tab.slots]

    early = {}
    for s in early_maps:
        if s in enc_pairs:
            for t in enc_pairs[s]:
                for sl in list(t.grass) + water_slots(t):
                    early[sl.species] = None
                for lst in (t.swarm, t.day, t.night, t.radar):
                    early.update({x: None for x in lst})
    early_ids = sorted(i for i in early if 0 < i < 494 and i not in starters)
    out("")
    out(f"== EARLY-ROUTE POKEMON ({len(early_ids)} species in the vanilla or Kaizo tables of Routes 201-204, Oreburgh Gate/Mine, Ravaged Path, Wayward Cave, Floaroma Meadow, Lake Verity) ==")
    for i in early_ids:
        h = sp_h[i]
        c = changes[i]
        out(f"{SP(i)} ({i}): {'/'.join(map(str, h.base_stats))}  {TY(h.types)}  {AB(h.abilities)}  catch {h.catch_rate}  "
            + ("changed: " + "; ".join(c[0] + c[1]) if any(c) else "(unchanged)"))
        if ls_h[i] != ls_v[i]:
            out(f"    learnset vanilla: {fmt_learnset(ls_v[i], VMV)}")
            out(f"    learnset kaizo:   {fmt_learnset(ls_h[i])}")

    out("")
    out("== SPECIES WITH CHANGED STATS, TYPES OR ABILITIES (compact, first 60) ==")
    for i in [x for x in species_ids if any(changes[x][0])][:60]:
        out(f"{SP(i)} ({i}): " + "; ".join(changes[i][0]))

    out("")
    out("== MOVES WITH CHANGED POWER, ACCURACY, PP OR TYPE ==")
    for i in sorted(set(mchanged["power"]) | set(mchanged["accuracy"]) | set(mchanged["pp"]) | set(mchanged["type"])):
        a, b = mv_v[i], mv_h[i]
        d = []
        if a.power != b.power: d.append(f"power {a.power}->{b.power}")
        if a.accuracy != b.accuracy: d.append(f"acc {a.accuracy}->{b.accuracy}")
        if a.pp != b.pp: d.append(f"PP {a.pp}->{b.pp}")
        if a.type != b.type: d.append(f"type {R.TYPE_NAMES[a.type]}->{R.TYPE_NAMES[b.type]}")
        out(f"{b.name} ({i}{', vanilla ' + a.name if a.name != b.name else ''}): " + ", ".join(d))
    for f in ("cls", "priority", "effect", "effect_chance", "target", "flags"):
        ids = mchanged[f]
        out(f"changed {f}: " + (", ".join(f"{mv_h[i].name}" for i in ids) if ids else "none"))

    out("")
    out("== ENCOUNTER TABLES (Kaizo | vanilla), slot odds GRASS_SLOT_PERCENT ==")
    for s in early_maps:
        if s not in enc_pairs:
            continue
        h, v = enc_pairs[s]
        out(f"-- {s}: grass rate {h.grass_rate} | {v.grass_rate}")
        for k in range(12):
            hs = h.grass[k] if h.grass[k].species else None
            vs = v.grass[k] if k < len(v.grass) and v.grass[k].species else None
            if hs or vs:
                out(f"   {R.GRASS_SLOT_PERCENT[k]:>2}%  {(f'{SP(hs.species)} Lv{hs.level}' if hs else '-'):<22}| {f'{SP(vs.species)} Lv{vs.level}' if vs else '-'}")
        for label in ("swarm", "day", "night", "radar"):
            a, b = getattr(h, label), getattr(v, label)
            if any(a) or any(b):
                out(f"   {label}: {[SP(x) for x in a]} | {[SP(x) for x in b]}")
        for label in ("surf", "old_rod", "good_rod", "super_rod"):
            a, b = getattr(h, label), getattr(v, label)
            if a.rate or b.rate:
                fm = lambda t: [f"{SP(x.species)} Lv{x.min_level}-{x.max_level}" for x in t.slots if x.species]
                out(f"   {label} rate {a.rate} | {b.rate}: {fm(a)} | {fm(b)}")

    def ids_of(names):
        return [TRAINERS.index(n) for n in names]
    early_names = ["TRAINER_LEADER_ROARK", "TRAINER_RIVAL_ROUTE_201_PIPLUP", "TRAINER_RIVAL_ROUTE_201_TURTWIG", "TRAINER_RIVAL_ROUTE_201_CHIMCHAR",
                   "TRAINER_RIVAL_ROUTE_203_PIPLUP", "TRAINER_RIVAL_ROUTE_203_TURTWIG", "TRAINER_RIVAL_ROUTE_203_CHIMCHAR",
                   "TRAINER_GALACTIC_GRUNT_JUBILIFE_CITY_1", "TRAINER_GALACTIC_GRUNT_JUBILIFE_CITY_2",
                   "TRAINER_GALACTIC_GRUNT_FLOAROMA_MEADOW_1", "TRAINER_GALACTIC_GRUNT_FLOAROMA_MEADOW_2",
                   "TRAINER_GALACTIC_GRUNT_VALLEY_WINDWORKS_1", "TRAINER_GALACTIC_GRUNT_VALLEY_WINDWORKS_2",
                   "TRAINER_GALACTIC_GRUNT_VALLEY_WINDWORKS_3", "TRAINER_COMMANDER_MARS_VALLEY_WINDWORKS"]
    out("")
    out("== ROARK, EARLY RIVAL AND GALACTIC TEAMS (Kaizo vs vanilla; moves in [] are explicit or level-up defaults) ==")
    for i in ids_of(early_names):
        h, v = tr_h[i], tr_v[i]
        out(f"-- {TRAINERS[i]} (id {i}) {h.name}/{h.class_name}; AI kaizo {list(h.ai_flag_names())} vanilla {list(R.Trainer(i, '', 0, '', v.ai_flags, False, (), ()).ai_flag_names())}; "
            f"double {h.double_battle}; items kaizo {[R.item_name(x) for x in h.items]} vanilla {[R.item_name(x) for x in v.items]}")
        for k in range(max(len(h.party), len(v.party))):
            hk = fmt_mon(h.party[k], R.learnset, MV) if k < len(h.party) else "-"
            same = k < len(h.party) and k < len(v.party) and fmt_mon(h.party[k], R.learnset, str) == fmt_mon(v.party[k], lambda s: ls_v[s], str)
            vk = fmt_mon(v.party[k], lambda s: ls_v[s], VMV) if k < len(v.party) else "-"
            out(f"   kaizo:   {hk}")
            out(f"   vanilla: {vk}" + ("   (same)" if same else ""))

    text = "\n".join(lines) + "\n"
    print(text)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf8") as f:
        f.write(text)


if __name__ == "__main__":
    main()
