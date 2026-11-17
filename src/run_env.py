"""A whole run as one episode: from the starter choice to Roark's badge, a wipe, or a budget of
decisions, under the Nuzlocke rules (NEXT_PHASE step 3).

The agent makes every decision the run brings: the starter first, then each battle's moves and
switches, and the ball where the rules allow a catch. The walk between them is scripted
(route.py). Observations and actions are the battle env's, so one policy plays both.
"""
from __future__ import annotations
import os

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
MAX_DECISIONS = 3000


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

    Rewards: the battle env's in every battle, plus BOSS_REWARD for each capped boss beaten."""
    metadata = {"render_modes": []}

    def __init__(self, start_state: str = START_STATE, rom: str = BE.DEFAULT_ROM, rules: nuzlocke.Rules | None = None,
                 max_decisions: int = MAX_DECISIONS, log_path: str | None = None):
        self.start_state, self.rules, self.max_decisions = start_state, rules or nuzlocke.Rules(), max_decisions
        self.battle = BE.BattleEnv([], rom=rom, log_path=log_path)
        self.nds = self.battle.nds
        self.action_space = gym.spaces.Discrete(BE.N_ACTIONS)
        self.observation_space = gym.spaces.Box(-1.0, 1.0, (BE.OBS_SIZE,), np.float32)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.battle.np_random = self.np_random              # battle seeds follow the run's seed
        self.nds.load_state_from_file(self.start_state)
        self.nds.tick(2)
        self.run = nuzlocke.Run(self.rules)
        self.runner = route.Runner(self.nds)
        self.script = self.runner.play()
        self.decisions, self.ret, self.battles, self.end = 0, 0.0, [], None
        self.kind = None
        return self._advance(None)

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
            self.kind = "battle"
            self.trainer = self.nds.memory.read_u16(False, gen4.resolve(self.nds)["enemyTrainerID"])
            catch = self._encounter() if not self.trainer else False
            try:
                obs, info = self.battle.reset(options={"attach": True, "catch": catch})
            except RuntimeError:                            # over before any decision
                value = "ENDED"
                continue
            info["decision"] = "battle"
            return obs, info

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
        else:
            obs, reward, term, trunc, info = self.battle.step(action)
            if term or trunc:
                outcome = info["outcome"]
                for m in self.battle.snap.player:
                    if m.hp == 0:
                        self.run.fainted(m.pid)
                if outcome == "CAUGHT":
                    self.run.caught(self.battle.snap.enemy[self.battle.snap.enemy_active or 0].species)
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
        if not self.end and self.decisions >= self.max_decisions:
            obs, info = self._finish("budget")
        self.ret += reward
        terminated = self.end in ("badge", "wipe", "no_badge")
        truncated = self.end in ("budget", "stuck", "route_error")
        if self.end:
            info.update(end=self.end, decisions=self.decisions, battles=self.battles, run_return=self.ret,
                        caught=len(self.run.caught_lines), dead=len(self.run.dead), routes=dict(self.run.routes),
                        location=tuple(gen4.read_location(self.nds)[:3]))
        return obs, reward, terminated, truncated, info
