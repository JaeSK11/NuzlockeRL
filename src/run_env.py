"""A whole run as one episode: from the starter choice to Roark's badge, a wipe, or a budget of
decisions, under the Nuzlocke rules (NEXT_PHASE step 3).

The agent makes every decision the run brings: the starter first, then each battle's moves and
switches, the ball where the rules allow a catch, and at each Pokémon Center which living
Pokémon to take along and which to leave in the PC, within the rules (pc_options), and which
of them leads. The walk
between them is scripted (route.py). Observations and actions are the battle env's, so one
policy plays both.
"""
from __future__ import annotations
import glob
import json
import os
import uuid

import gymnasium as gym
import numpy as np
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pynds

import battle_env as BE
import gen4
import nuzlocke
import romdata
import route
import scenario

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
START_STATE = os.path.join(ROOT, "states/milestones/01_starter_choice.state")
STARTERS = (387, 390, 393)          # the briefcase's balls, left to right: Turtwig, Chimchar, Piplup
BOSSES = {route.ROARK: "Roark"}     # trainer id -> the capped boss it is (nuzlocke.Rules.level_caps)
BOSS_REWARD = 20.0
# A run whose route ends without the badge is paid as a loss: Roark turned the party down, so it
# never got to fight him. Without it, a lone starter far over his cap ends its run at no cost.
NO_BADGE_REWARD = BE.REWARDS[BE.Event.LOST]
# A catch ends a wild battle without the knockout and win that would pay 6, and its worth shows
# only battles later. A lone starter also risks a wipe while it throws: at 10, trying to catch
# still lost about 2 a battle (PROGRESS §50). At 20 it gained, but the agent threw so rarely that
# it never learned so (§52). At 50 a catch clearly pays; the rules still allow one per route.
CATCH_REWARD = 50.0
MAX_DECISIONS = 3000
RESTARTS_PER_STEP = 20      # restart states kept for each route step; the oldest go first
CATCH_TAG = "_catch"        # ends the name of a restart state whose battle allows a catch


PC_TAKE, PC_LEAVE = 0, 1     # a PC choice's actions: take this Pokémon along, or leave it in the PC


def pc_options(levels: list[int], k: int, taken: list[bool], cap: int | None) -> tuple[bool, bool]:
    """Whether the k-th living Pokémon of a PC choice (the party's first, then the PC's) may be
    taken along, and whether it may be left in the PC, given the choices before it. The rules:
    a party of 1 to 6, and, with cap, no Pokémon over it while any is at or under it (else the
    cap can't be met, and the boss turns the party down). A fainted Pokémon is no choice: it
    stays in the PC."""
    capped = cap is not None and any(level <= cap for level in levels)
    allowed = [not (capped and level > cap) for level in levels]
    return allowed[k] and sum(taken) < scenario.PARTY_SLOTS, sum(taken) > 0 or any(allowed[k + 1:])


def starter_snapshot() -> BE.Snapshot:
    """The three starters as a party, each as a run would get it (level 5, its level-up moves),
    with no enemy: the observation of the starter choice. Action k picks starter k."""
    mons = []
    for species in STARTERS:
        stats = romdata.calc_stats(species, 5, [15] * 6, [0] * 6, 0)
        moves = list(romdata.default_moves(species, 5))
        mons.append(gen4.Mon(pid=0, checksum_ok=True, species=species, moves=moves,
                             pp=[romdata.move(m).pp for m in moves], level=5, hp=stats[0], max_hp=stats[0]))
    return BE.Snapshot(tuple(mons), (), None, None, (6,) * 8, (6,) * 8)


class RunEnv(gym.Env):
    """One step is one decision. Episode end: terminated on Roark's badge ("badge"), a lost
    battle ("wipe"), or the route ending without the badge ("no_badge": Roark turned down a party
    over his level cap); truncated on the decision budget ("budget"), a battle the env couldn't
    play ("stuck") or a script that couldn't go on ("route_error").

    Rewards: the battle env's in every battle, plus CATCH_REWARD for each catch, BOSS_REWARD for
    each capped boss beaten, and NO_BADGE_REWARD when the route ends without the badge.

    Restart states, for training only (NEXT_PHASE step 3.10): with restart_dir set, every battle
    a run reaches leaves a state saved as it starts, with the run's bookkeeping beside it. A reset
    then starts from one of them with probability restart_share: it picks a route step at random
    among those with restarts, so later battles get practice while most runs still die early,
    then a state of that step. With catch_restart_share, that share of restarts instead picks
    among the states whose battle allows a catch, which are otherwise rare (PROGRESS §54). A
    run that counts plays from the starter choice.

    Each observation also shows the run's state: whether this battle allows a catch, how far
    along the route the run is, and the next boss's level cap."""
    metadata = {"render_modes": []}

    def __init__(self, start_state: str = START_STATE, rom: str = BE.DEFAULT_ROM, rules: nuzlocke.Rules | None = None,
                 max_decisions: int = MAX_DECISIONS, log_path: str | None = None, route_actions=route.ROUTE,
                 restart_dir: str | None = None, restart_share: float = 0.0, catch_restart_share: float = 0.0):
        self.start_state, self.rules, self.max_decisions = start_state, rules or nuzlocke.Rules(), max_decisions
        self.route_actions, self.restart_dir, self.restart_share = route_actions, restart_dir, restart_share
        self.catch_restart_share = catch_restart_share
        if restart_dir:
            os.makedirs(restart_dir, exist_ok=True)
        self.battle = BE.BattleEnv([], rom=rom, log_path=log_path)
        self.nds = self.battle.nds
        self.action_space = gym.spaces.Discrete(BE.N_ACTIONS)
        self.observation_space = gym.spaces.Box(-1.0, 1.0, (BE.OBS_SIZE,), np.float32)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.battle.np_random = self.np_random              # battle seeds follow the run's seed
        self.run = nuzlocke.Run(self.rules)
        self.runner = route.Runner(self.nds, self.route_actions)
        self.decisions, self.ret, self.battles, self.end = 0, 0.0, [], None
        self.kind, self.restart, self.starter = None, None, None
        resume = self._load_restart() if self.restart_share and self.np_random.random() < self.restart_share else None
        if resume is None:
            self.nds.load_state_from_file(self.start_state)
            self.nds.tick(2)
        self.script = self.runner.play(resume)
        obs, info = self._advance(None)
        info["restart"] = self.restart
        self._show_run(obs, info)
        return obs, info

    def _show_run(self, obs, info):
        if info.get("decision") is None:                    # the run is over
            return
        obs[BE.OBS_SLICES["catch_allowed"]] = info["decision"] == "battle" and self.battle.catch_allowed
        obs[BE.OBS_SLICES["route_progress"]] = self.runner.at / len(self.runner.route)
        obs[BE.OBS_SLICES["run_level_cap"]] = (self.run.level_cap() or 0) / 100

    def _restart_files(self) -> dict[int, list[str]]:
        by_step = {}
        for path in glob.glob(os.path.join(self.restart_dir or "", "*.json")):
            by_step.setdefault(int(os.path.basename(path).split("_")[0]), []).append(path)
        return by_step

    def _load_restart(self):
        """Load a restart state and its bookkeeping. Returns the runner's resume point, or None
        when there is none yet or the one picked was trimmed away by another worker meanwhile."""
        by_step = self._restart_files()
        if not by_step:
            return None
        catchable = sorted(p for paths in by_step.values() for p in paths if p.endswith(CATCH_TAG + ".json"))
        if self.catch_restart_share and catchable and self.np_random.random() < self.catch_restart_share:
            meta_path = catchable[int(self.np_random.integers(len(catchable)))]
        else:
            steps = sorted(by_step)
            meta_path = by_step[steps[int(self.np_random.integers(len(steps)))]]
            meta_path = meta_path[int(self.np_random.integers(len(meta_path)))]
        try:
            with open(meta_path) as f:
                meta = json.load(f)
            if not (meta["at"] < len(self.runner.route) and meta.get("action") == repr(self.runner.route[meta["at"]])):
                self._drop_restart(meta_path)                   # saved on an older route: its step moved
                return None
            self.nds.load_state_from_file(meta_path.removesuffix(".json") + ".state")
        except (OSError, ValueError, FileNotFoundError):
            return None
        self.nds.tick(2)
        r = meta["run"]
        self.run.routes, self.run.caught_lines = dict(r["routes"]), set(r["caught_lines"])
        self.run.dead, self.run.beaten = set(r["dead"]), set(r["beaten"])
        self.runner.trainers_beaten, self.starter = list(meta["trainers_beaten"]), meta["starter"]
        self.restart, self.restart_at = os.path.basename(meta_path).removesuffix(".json"), meta["at"]
        return meta["at"], meta["sub"]

    def _restart_meta(self) -> dict:
        """The run's bookkeeping as the battle starts, before its encounter uses up the route."""
        return {"at": self.runner.at, "sub": self.runner.sub, "action": repr(self.runner.route[self.runner.at]),
                "starter": self.starter,
                "trainers_beaten": list(self.runner.trainers_beaten),
                "run": {"routes": dict(self.run.routes), "caught_lines": sorted(self.run.caught_lines),
                        "dead": sorted(self.run.dead), "beaten": sorted(self.run.beaten)}}

    def _save_restart(self, meta: dict, catch: bool):
        """Save the battle that just started, with the bookkeeping from before it, as a restart
        state. catch: the battle allows a catch and the bag has a ball."""
        name = f"{self.runner.at:03d}_{uuid.uuid4().hex[:12]}" + (CATCH_TAG if catch else "")
        base = os.path.join(self.restart_dir, name)
        self.nds.save_state_to_file(base + ".state.tmp")
        with open(base + ".json.tmp", "w") as f:
            json.dump(meta, f)
        os.replace(base + ".state.tmp", base + ".state")
        os.replace(base + ".json.tmp", base + ".json")                 # last: a reader finds both files
        def age(path):
            try:
                return os.path.getmtime(path)
            except FileNotFoundError:                                   # another worker trimmed it
                return 0.0
        same_step = sorted(self._restart_files().get(self.runner.at, []), key=age)
        for old in same_step[:-RESTARTS_PER_STEP]:
            self._drop_restart(old)

    @staticmethod
    def _drop_restart(meta_path: str):
        for path in (meta_path, meta_path.removesuffix(".json") + ".state"):
            try:
                os.remove(path)
            except FileNotFoundError:                                   # another worker dropped it
                pass

    def _advance(self, value):
        """Play the route to the next decision. Returns (obs, info); sets self.end when the run is over."""
        while True:
            try:
                event = self.script.send(value) if self.kind or value is not None else next(self.script)
            except StopIteration:
                return self._finish("badge" if gen4.read_badges(self.nds) & 1 else "no_badge")
            except route.RunOver as e:
                return self._finish(e.args[0])
            except route.RouteError as e:
                return self._finish("route_error", error=str(e))
            if event == ("starter",):
                self.kind = "starter"
                mask = np.zeros(BE.N_ACTIONS, dtype=bool)
                mask[:len(STARTERS)] = True
                return BE.observation(starter_snapshot(), 0, 1), {"action_mask": mask, "decision": "starter"}
            if event[0] == "pc":
                self.kind = "pc"
                self._pc_start(event[1])
                if (asked := self._pc_next()) is not None:
                    return asked
                value = self._pc_answer()
                continue
            # Not again for the battle a restart resumes, and not inside a heal trip: a restart
            # replays its route action from the start, and a trip half done can't be.
            save = self.restart_dir and not (self.restart and self.kind is None) and not self.runner.in_trip
            meta = self._restart_meta() if save else None
            self.kind = "battle"
            self.trainer = self.nds.memory.read_u16(False, gen4.resolve(self.nds)["enemyTrainerID"])
            catch = self._encounter() if not self.trainer else False
            if save:        # the encounter only reads the game, so the state is still the battle's start
                a = gen4.resolve(self.nds)
                self._save_restart(meta, catch and bool(gen4.read_bag(self.nds, a)["balls"]))
            try:
                obs, info = self.battle.reset(options={"attach": True, "catch": catch})
            except RuntimeError:                            # over before any decision
                value = "ENDED"
                continue
            info["decision"] = "battle"
            return obs, info

    def _pc_start(self, cap):
        """A Pokémon Center's PC choice. A fainted Pokémon counts as dead (Nuzlocke) and is no
        choice; the living ones are asked in turn, the party's first, then up to BE.PC_OFFER in
        the PC, in box order."""
        party = gen4.read_party(self.nds)
        for m in party:
            if m.hp == 0:
                self.run.fainted(m.pid)
        box = [(slot, gen4.decode_mon(scenario.encode_mon(m))) for slot, m in scenario.read_box_data(self.nds).items()
               if m.pid not in self.run.dead][:BE.PC_OFFER]
        living = [k for k, m in enumerate(party) if m.pid not in self.run.dead]
        self.pc = {"party": party, "box": box, "cap": cap,
                   "positions": living + [6 + i for i in range(len(box))],
                   "levels": [party[k].level for k in living] + [m.level for _, m in box], "taken": []}

    def _pc_next(self):
        """The next PC choice that is the agent's, as (obs, info); the rules settle the rest.
        None once all are made."""
        pc = self.pc
        while (k := len(pc["taken"])) < len(pc["positions"]):
            can_take, can_leave = pc_options(pc["levels"], k, pc["taken"], pc["cap"])
            if not (can_take and can_leave):
                pc["taken"].append(can_take)
                continue
            taken = np.zeros(6 + BE.PC_OFFER, dtype=np.float32)
            taken[[p for p, t in zip(pc["positions"], pc["taken"]) if t]] = 1.0
            mask = np.zeros(BE.N_ACTIONS, dtype=bool)
            mask[[PC_TAKE, PC_LEAVE]] = True
            obs = BE.pc_observation(pc["party"], [m for _, m in pc["box"]], pc["positions"][k], taken,
                                    self.run.level_cap())
            return obs, {"action_mask": mask, "decision": "pc"}
        team = self._pc_team()
        if "lead" not in pc and len(team) > 1:          # then which of the new party leads
            mask = np.zeros(BE.N_ACTIONS, dtype=bool)
            mask[:len(team)] = True
            return BE.lead_observation(team, self.run.level_cap()), {"action_mask": mask, "decision": "lead"}
        return None

    def _pc_team(self):
        """The party the PC choices make, in its order: the party's Pokémon taken along, then the PC's."""
        pc = self.pc
        taken = {p for p, t in zip(pc["positions"], pc["taken"]) if t}
        return ([m for k, m in enumerate(pc["party"]) if k in taken]
                + [m for i, (_, m) in enumerate(pc["box"]) if 6 + i in taken])

    def _pc_answer(self):
        """The runner's answer: the party slots to leave in the PC, the box slots to take, and which
        Pokémon of the new party leads."""
        pc = self.pc
        taken = {p for p, t in zip(pc["positions"], pc["taken"]) if t}
        leave = [k for k in range(len(pc["party"])) if k not in taken]
        return leave, [slot for i, (slot, _) in enumerate(pc["box"]) if 6 + i in taken], pc.get("lead", 0)

    def _encounter(self) -> bool:
        """The rules' answer for a wild battle that just started: may the agent throw a ball?"""
        a = gen4.resolve(self.nds)
        foe = gen4.read_party(self.nds, a["enemyBase"])[0]
        trainer_id = scenario.read_party_data(self.nds)[0]["ot_id"]
        return self.run.encounter(gen4.read_location(self.nds).name, foe.species, scenario.is_shiny(foe.pid, trainer_id))

    def _finish(self, end: str, **extra):
        self.end = end
        return np.zeros(BE.OBS_SIZE, dtype=np.float32), {"action_mask": np.zeros(BE.N_ACTIONS, dtype=bool),
                                                          "decision": None, **extra}

    def step(self, action):
        if self.end:
            raise RuntimeError("step() after the run ended; call reset()")
        self.decisions += 1
        reward = 0.0
        if self.kind == "starter":
            self.starter = STARTERS[int(action)]
            obs, info = self._advance(int(action))
        elif self.kind == "pc":
            if len(self.pc["taken"]) < len(self.pc["positions"]):
                self.pc["taken"].append(int(action) == PC_TAKE)
                pick = "pc_take" if int(action) == PC_TAKE else "pc_leave"
            else:                                       # the lead
                self.pc["lead"] = int(action)
                pick = "lead_kept" if int(action) == 0 else "lead_changed"
            asked = self._pc_next()
            obs, info = asked if asked is not None else self._advance(self._pc_answer())
            info["pick"] = pick
        else:
            obs, reward, term, trunc, info = self.battle.step(action)
            if term or trunc:
                outcome = info["outcome"]
                for m in self.battle.snap.player:
                    if m.hp == 0:
                        self.run.fainted(m.pid)
                if outcome == "CAUGHT":
                    self.run.caught(self.battle.snap.enemy[self.battle.snap.enemy_active or 0].species)
                    reward += CATCH_REWARD
                if outcome == "WON" and self.trainer in BOSSES:
                    self.run.boss_beaten(BOSSES[self.trainer])
                    reward += BOSS_REWARD
                self.battles.append({"trainer": self.trainer, "outcome": outcome, "turns": self.battle.turn})
                if outcome == "STUCK":
                    obs, info = self._finish("stuck")
                else:
                    obs, info = self._advance(outcome)
            else:
                info["decision"] = "battle"
        if self.end == "no_badge":
            reward += NO_BADGE_REWARD
        if not self.end and self.decisions >= self.max_decisions:
            obs, info = self._finish("budget")
        # A restart that fails in the action it resumed, or before the run's next battle, can't
        # resume: one saved inside a mend's heal trip fails in the action after the mend.
        if (self.end == "route_error" and self.restart
                and (self.runner.at == self.restart_at or len(self.battles) <= 1)):
            self._drop_restart(os.path.join(self.restart_dir, self.restart + ".json"))
        self.ret += reward
        terminated = self.end in ("badge", "wipe", "no_badge")
        truncated = self.end in ("budget", "stuck", "route_error")
        if self.end:
            info.update(end=self.end, outcome=self.end, decisions=self.decisions, battles=self.battles, run_return=self.ret,
                        route_step=self.runner.at, route_steps=len(self.runner.route), heals=self.runner.heals,
                        caught=len(self.run.caught_lines), dead=len(self.run.dead), routes=dict(self.run.routes),
                        location=tuple(gen4.read_location(self.nds)[:3]))
        self._show_run(obs, info)
        return obs, reward, terminated, truncated, info
