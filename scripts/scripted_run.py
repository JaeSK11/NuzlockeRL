"""A rule-based player for the whole run, to see whether Roark's badge is reachable with the
agent's own actions (an existence proof, PROGRESS §57 and §58). It acts only through
RunEnv.step and reads the game state to decide.

usage: scripted_run.py OUT.jsonl [--starters 0 1 2] [--seeds 0 1 2] [--verbose]
One JSON line per run: starter, seed, end, route step, battles, team and PC at the end, Roark's
fight, and the last battles with the decisions of those lost, with a death, or against Roark.

Rules (Player):
- starter: the one asked for.
- moves: a sure knockout (by the Gen 4 damage formula at a low roll) with the most accurate
  move; else the highest expected damage (power, accuracy, STAB, type matchup).
- catch: at a wild battle where the rules allow a catch, weaken the foe with the strongest
  move that won't knock it out until it is at or under CATCH_HP of its HP (or asleep or
  paralyzed), then throw, up to MAX_THROWS, while the active Pokémon has CATCH_SAFE_HP of its HP.
- feeding: on a battle's first turn, before any catch, send in the strongest healthy Pokémon
  (by stats times HP share) unless the weak lead is under the cap and, in a wild battle, beats
  the foe alone, so the weak one is a participant and shares the experience. A lead under half
  its HP goes out.
- Bide: while the foe stores energy, a status move, unless an attack knocks it out.
- run: in a wild battle, once no catch is under way, from a foe that would knock the active
  Pokémon out before it could knock the foe out.
- rescue: an active Pokémon under SWITCH_HP of its HP that can't finish the foe gives way to a
  healthy one with the best matchup. A forced switch picks by health, matchup and level.
- PC: take everyone (the masks apply the level cap); the lead is the weakest Pokémon under the
  cap (to feed it), but on Roark's trip the strongest.
- bag: a Rare Candy for the weakest Pokémon under the cap while it is 4 or more levels under
  the strongest, and at the boss's PC until all reach the cap; a held item for the weakest
  Pokémon holding none.
"""
import argparse
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import battle_env as BE
import gen4
import romdata
import route
import run_env as RE
import scenario

CATCH_HP = 0.5
MAX_THROWS = 6
CATCH_SAFE_HP = 0.55   # an active Pokémon under this share of its HP doesn't weaken or throw
STATUS_CATCH = 0x07 | 0x40          # asleep or paralyzed: catch odds up
VOLATILE_BIDE = 3 << 8              # statusVolatile: storing energy (the layout of battle_env's VOLATILE_ bits)
SWITCH_HP = 0.3


def types_of(mon):
    return romdata.species(mon.species).types


def expected_damage(att, move_id: int, dfn, accuracy: bool = True) -> float:
    """Expected HP damage of one use of move_id by att on dfn, from the Gen 4 formula at a
    mid roll, times accuracy. 0 for a status move."""
    if not move_id:
        return 0.0
    m = romdata.move(move_id)
    if m.cls == 2 or not m.power:
        return 0.0
    phys = m.cls == 0
    a = att.stats.get("atk" if phys else "spa", 0) or 1
    d = dfn.stats.get("def" if phys else "spd", 0) or 1
    base = ((2 * att.level / 5 + 2) * m.power * a / d / 50 + 2)
    base *= 1.5 if m.type in types_of(att) else 1.0
    base *= romdata.type_effectiveness(m.type, types_of(dfn))
    return base * ((m.accuracy or 100) / 100 if accuracy else 1.0) * 0.925


class Player:
    def __init__(self, env: RE.RunEnv, starter_slot: int):
        self.env, self.starter_slot = env, starter_slot
        self.throws = 0
        self.dead = 0

    def best_attack(self, att, foe, mask, avoid_ko=False):
        """(slot, damage) of the best legal attack; with avoid_ko, the strongest that leaves the
        foe standing (the weakest attack if every one would knock it out)."""
        cands = [(expected_damage(att, att.moves[k], foe), k) for k in range(4) if mask[k]]
        attacks = [c for c in cands if c[0] > 0]
        if not attacks:
            return (cands[0][1], 0.0) if cands else (0, 0.0)
        if avoid_ko:
            safe = [c for c in attacks if c[0] * 1.15 < foe.hp]
            if safe:
                d, k = max(safe)
                return k, d
            d, k = min(attacks)
            return k, d
        sure = [(romdata.move(att.moves[k]).accuracy or 100, -expected_damage(att, att.moves[k], foe, False), k)
                for _, k in attacks if expected_damage(att, att.moves[k], foe, False) * 0.85 >= foe.hp]
        if sure:                                        # a knockout: the most accurate move, then the weakest
            _, _, k = max(sure)
            return k, foe.hp
        d, k = max(attacks)                             # else the hardest hit, by expected damage
        return k, d

    def team(self):
        s = self.env.battle.snap
        return s, [(pos, s.player[idx]) for pos, idx in enumerate(s.slots())]

    def battle_action(self, info):
        env = self.env
        mask = np.array(info["action_mask"], dtype=bool)
        s, party = self.team()
        me = s.player[s.player_active]
        foe = s.enemy[s.enemy_active] if s.enemy_active is not None else s.enemy[0]
        turn = env.battle.turn
        cap = env.run.level_cap() or 100
        if env.battle.forced:
            return self.pick_switch(s, party, foe, mask)
        if turn == 0:                                   # before a catch too: a weak lead doesn't weaken the foe alone
            sw = self.opening_switch(s, party, me, foe, mask, cap)
            if sw is not None:
                return sw
        if s.volatile[1] & VOLATILE_BIDE and self.best_attack(me, foe, mask)[1] < foe.hp:
            k = next((k for k in range(4) if mask[k] and me.moves[k] and romdata.move(me.moves[k]).cls == 2), None)
            if k is not None:                           # Bide pays back double the damage it takes
                return k
        if mask[BE.BALL_ACTION] and self.throws < MAX_THROWS and me.hp >= CATCH_SAFE_HP * me.max_hp:
            if foe.hp <= CATCH_HP * foe.max_hp or foe.status & STATUS_CATCH:
                self.throws += 1
                return BE.BALL_ACTION
            return self.best_attack(me, foe, mask, avoid_ko=True)[0]
        if mask[BE.RUN_ACTION] and self.outmatched(me, foe, mask):
            return BE.RUN_ACTION
        sw = self.rescue_switch(s, party, me, foe, mask)
        if sw is not None:
            return sw
        return self.best_attack(me, foe, mask)[0]

    def opening_switch(self, s, party, me, foe, mask, cap):
        """On the first turn, keep a weak lead in only against a foe it beats safely (it earns the
        experience alone); else send in the strongest healthy Pokémon, which leaves the lead a
        participant. A lead low on HP goes out either way."""
        if s.trapped:
            return None
        others = [(pos, m) for pos, m in party if m.hp > 0 and m.pid != me.pid and mask[3 + pos]]
        if not others:
            return None
        pos, strong = max(others, key=lambda x: self.power(x[1]))
        if self.power(strong) <= self.power(me) * 1.1 and me.hp >= 0.5 * me.max_hp:
            return None
        hurt = me.hp < 0.5 * me.max_hp
        if strong.hp < 0.5 * strong.max_hp and not hurt:
            return None
        if not hurt and (me.level >= cap or (not self.env.trainer and self.safe_alone(me, foe))):
            return None
        return 3 + pos

    def outmatched(self, me, foe, mask) -> bool:
        """The foe knocks the active Pokémon out in fewer turns than it takes to knock the foe out."""
        hit = self.best_attack(me, foe, mask)[1]
        return hit <= 0 or foe.hp / hit > me.hp / max(self.threat(foe, me), 1.0)

    @staticmethod
    def power(m):
        return (m.max_hp + sum(m.stats.values())) * m.hp / max(m.max_hp, 1)

    def safe_alone(self, me, foe) -> bool:
        """The Pokémon knocks the foe out within two attacks and survives three of the foe's."""
        best = max((expected_damage(me, mv, foe) for mv in me.moves), default=0.0)
        return best * 2 >= foe.hp and 3 * self.threat(foe, me) < me.hp

    @staticmethod
    def threat(foe, me) -> float:
        """The foe's hit on me, assuming a 70-power move of one of its types."""
        phys = foe.stats.get("atk", 0) >= foe.stats.get("spa", 0)
        a = (foe.stats.get("atk", 1) if phys else foe.stats.get("spa", 1)) or 1
        d = (me.stats.get("def", 1) if phys else me.stats.get("spd", 1)) or 1
        base = (2 * foe.level / 5 + 2) * 70 * a / d / 50 + 2
        return max((base * 1.5 * romdata.type_effectiveness(t, types_of(me)) for t in types_of(foe)), default=base)

    def rescue_switch(self, s, party, me, foe, mask):
        if s.trapped or me.hp > SWITCH_HP * me.max_hp:
            return None
        if mask[:4].any() and self.best_attack(me, foe, mask)[1] >= foe.hp:
            return None                                 # it can still finish the foe
        others = [(pos, m) for pos, m in party if m.hp > 0.5 * m.max_hp and m.pid != me.pid and mask[3 + pos]]
        if not others:
            return None
        pos, _ = max(others, key=lambda x: (self.matchup(x[1], foe), x[1].level))
        return 3 + pos

    @staticmethod
    def matchup(m, foe):
        best = max((expected_damage(m, mv, foe) for mv in m.moves), default=0.0)
        foe_types = types_of(foe)
        taken = max((romdata.type_effectiveness(t, types_of(m)) for t in foe_types), default=1.0)
        return best / max(foe.hp, 1) / max(taken, 0.25)

    def pick_switch(self, s, party, foe, mask):
        others = [(pos, m) for pos, m in party if mask[3 + pos]]
        pos, _ = max(others, key=lambda x: (x[1].hp > 0.4 * x[1].max_hp, self.matchup(x[1], foe), x[1].level))
        return 3 + pos

    def pc_action(self, info):
        env = self.env
        if info["decision"] == "pc":
            return RE.PC_TAKE
        team = env._pc_team()
        cap = env.pc["cap"]
        levels = [m.level for m in team]
        if cap:                                         # Roark's trip: the strongest leads
            return int(np.argmax([(l, m.hp) for l, m in zip(levels, team)], axis=0)[0])
        under = [i for i, m in enumerate(team) if m.level < (env.run.level_cap() or 100)]
        strongest = max(levels)
        weak = [i for i in under if levels[i] + 3 <= strongest]
        return min(weak, key=lambda i: levels[i]) if weak else 0

    def bag_action(self, info):
        """A Rare Candy for the weakest Pokémon under the cap, if it is 4 or more levels under the
        strongest; at the boss's PC, for the weakest under the cap until all reach it. A held item
        for the weakest Pokémon that holds none."""
        party = gen4.read_party(self.env.nds)
        mask = info["action_mask"]
        alive = [k for k in range(len(party)) if mask[k]]
        if info["decision"] == "hold":
            free = [k for k in alive if not party[k].item]
            return min(free, key=lambda k: party[k].level) if free else BE.BAG_DONE
        cap = self.env.run.level_cap() or 100
        under = [k for k in alive if party[k].level < cap]
        if not under:
            return BE.BAG_DONE
        k = min(under, key=lambda k: party[k].level)
        at_boss = bool(self.env.pc and self.env.pc["cap"])
        return k if at_boss or party[k].level + 4 <= max(m.level for m in party) else BE.BAG_DONE

    def act(self, info):
        d = info["decision"]
        if d == "starter":
            return self.starter_slot
        if d in ("pc", "lead"):
            return self.pc_action(info)
        if d in ("candy", "hold"):
            return self.bag_action(info)
        return self.battle_action(info)


def party_report(env):
    mons = gen4.read_party(env.nds)
    box = [gen4.decode_mon(scenario.encode_mon(m)) for m in scenario.read_box_data(env.nds).values()]
    f = lambda m: {"species": romdata.species_name(m.species), "level": m.level, "hp": m.hp, "max_hp": m.max_hp,
                   "dead": m.pid in env.run.dead or m.hp == 0}
    return [f(m) for m in mons], [f(m) for m in box]


def play_run(env, starter_slot, seed, verbose=False):
    t0 = time.time()
    p = Player(env, starter_slot)
    obs, info = env.reset(seed=seed)
    roark = {"fought": False, "enemy_down": 0, "enemies": 6}
    trace, moves = [], []
    while info.get("decision") is not None:
        act = p.act(info)
        d = info["decision"]
        nb = len(env.battles)
        snap_before = env.battle.snap if d == "battle" else None
        if d == "battle":
            if env.battle.turn == 0 and not env.battle.forced:
                p.throws, moves = 0, []
            sn = env.battle.snap
            me = sn.player[sn.player_active]
            fo = sn.enemy[sn.enemy_active if sn.enemy_active is not None else 0]
            what = (f"move {romdata.move_name(me.moves[act])}" if act < 4 else "ball" if act == BE.BALL_ACTION
                    else "run" if act == BE.RUN_ACTION else f"switch {act - 3}")
            moves.append(f"{romdata.species_name(me.species)} {me.level} {me.hp}/{me.max_hp} vs "
                         f"{romdata.species_name(fo.species)} {fo.level} {fo.hp}/{fo.max_hp}: {what}")
        obs, r, term, trunc, info = env.step(act)
        if len(env.battles) > nb:
            b = env.battles[-1]
            enemy = (snap_before or env.battle.snap).enemy   # the next battle may already be up
            rec = {"at": env.runner.at, "trainer": b["trainer"], "outcome": b["outcome"], "turns": b["turns"],
                   "foe": [romdata.species_name(m.species) for m in enemy][:6],
                   "foe_levels": [m.level for m in enemy][:6]}
            died = len(env.run.dead) > p.dead
            p.dead = len(env.run.dead)
            if b["outcome"] == "LOST" or b["trainer"] == route.ROARK or died:
                rec["decisions"] = moves[-40:]
            trace.append(rec)
            if verbose:
                mine = [(romdata.species_name(m.species), m.level, m.hp) for m in gen4.read_party(env.nds)]
                print(f"  step {rec['at']} trainer {b['trainer']} {b['outcome']} t{b['turns']} foe {rec['foe'][0]} {rec['foe_levels'][0]} mine {mine}", flush=True)
            if b["trainer"] == route.ROARK:
                roark = {"fought": True, "enemy_down": sum(m.hp == 0 for m in enemy), "enemies": len(enemy)}
        if term or trunc:
            break
    party, box = party_report(env)
    return {"starter": romdata.species_name(RE.STARTERS[starter_slot]), "seed": seed, "end": env.end,
            "route_step": env.runner.at, "route_steps": len(env.runner.route),
            "battles": len(env.battles), "won": sum(b["outcome"] == "WON" for b in env.battles),
            "caught": len(env.run.caught_lines), "dead": len(env.run.dead),
            "party": party, "box": box, "roark": roark, "decisions": env.decisions,
            "trace": trace[-12:], "seconds": round(time.time() - t0)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--starters", type=int, nargs="+", default=[0, 1, 2])
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--seeds", type=int, nargs="+", default=[0])
    args = ap.parse_args()
    env = RE.RunEnv()
    with open(args.out, "a") as f:
        for seed in args.seeds:
            for st in args.starters:
                rec = play_run(env, st, seed, args.verbose)
                f.write(json.dumps(rec) + "\n")
                f.flush()
                team = ", ".join(f"{m['species']} {m['level']}" + ("x" if m["dead"] else "") for m in rec["party"])
                print(f"{rec['starter']} seed {seed}: {rec['end']} step {rec['route_step']}/{rec['route_steps']} "
                      f"won {rec['won']}/{rec['battles']} caught {rec['caught']} roark {rec['roark']} "
                      f"team [{team}] {rec['seconds']}s", flush=True)


if __name__ == "__main__":
    main()
