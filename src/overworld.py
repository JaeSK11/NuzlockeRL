"""Walking the overworld, checked in RAM, and each map's walkable graph, found by walking it.

A node is (x, z, height). The Oreburgh Gym's walkway passes over floor tiles with the same
(x, z), and the ROM's collision layer (`fieldmap`) can't see heights, so it can't plan a walk
there. The emulator can: `explore` tries every direction from every tile it reaches, from a
state saved on that tile, and records what each step did.
"""
from __future__ import annotations
import json
import os
import shutil
from collections import deque
from dataclasses import dataclass, field

import gen4
import scenario

DIRS = ("up", "down", "left", "right")
STEP_FRAMES = 32      # a step registers within a few frames of the turn; past this the way is blocked
SETTLE_FRAMES = 40    # a ledge jump takes about 32 frames to land
WARP_FRAMES = 240     # a door's warp runs as a field task for about 100 frames

Node = tuple[int, int, int]


def no_encounters(nds) -> None:
    """Zero the encounter rate of the current map's wild table, so grass doesn't start battles."""
    nds.memory.write_u32(False, gen4.resolve(nds)["_version"] + scenario.ENCOUNTER_OFFSET, 0)


def step(nds, direction: str) -> str:
    """Hold a direction until the player leaves the tile or a field task starts. Returns
    "blocked", "moved", "exit" (the step left the map, by a door, whose warp starts on the mat,
    or a map edge), or "scene" (it started a script or a battle: a trainer, a trigger, a sign,
    a wild Pokémon)."""
    map_id, tile = gen4.read_location(nds).map_id, gen4.read_player_tile(nds)
    nds.button.press_key(direction)
    moved = lambda: gen4.read_player_tile(nds) != tile or gen4.read_location(nds).map_id != map_id
    for _ in range(STEP_FRAMES):
        nds.tick(1)
        if moved() or gen4.field_task(nds):
            break
    nds.button.release_key(direction)
    if not moved() and not gen4.field_task(nds):
        return "blocked"
    nds.tick(SETTLE_FRAMES)
    for _ in range(WARP_FRAMES):
        if not gen4.field_task(nds) or gen4.read_location(nds).map_id != map_id:
            break
        nds.tick(1)
    if gen4.read_location(nds).map_id != map_id:
        return "exit"
    return "scene" if gen4.field_task(nds) or gen4.in_battle(nds) else "moved"


@dataclass
class WalkGraph:
    map_id: int
    start: Node
    edges: dict[Node, dict[str, Node]] = field(default_factory=dict)   # steps within the map
    exits: dict[Node, dict[str, int]] = field(default_factory=dict)    # steps out, to the map entered
    scenes: dict[Node, list[str]] = field(default_factory=dict)        # steps that start a scene

    def path(self, start: Node, goal) -> list[str] | None:
        """The fewest steps from start to goal: a node, or an (x, z) at any height."""
        def reached(n):
            return n == goal if len(goal) == 3 else n[:2] == tuple(goal)
        prev, queue = {start: None}, deque([start])
        while queue:
            n = queue.popleft()
            if reached(n):
                dirs = []
                while prev[n]:
                    n, d = prev[n]
                    dirs.append(d)
                return dirs[::-1]
            for d, to in self.edges.get(n, {}).items():
                if to not in prev:
                    prev[to] = (n, d)
                    queue.append(to)
        return None

    def to_json(self) -> dict:
        key = lambda n: "%d,%d,%d" % n
        return {"map_id": self.map_id, "start": self.start,
                "edges": {key(n): {d: list(t) for d, t in e.items()} for n, e in self.edges.items()},
                "exits": {key(n): e for n, e in self.exits.items()},
                "scenes": {key(n): s for n, s in self.scenes.items()}}

    @classmethod
    def from_json(cls, data: dict) -> "WalkGraph":
        node = lambda k: tuple(int(v) for v in k.split(","))
        return cls(data["map_id"], tuple(data["start"]),
                   {node(k): {d: tuple(t) for d, t in e.items()} for k, e in data["edges"].items()},
                   {node(k): e for k, e in data["exits"].items()},
                   {node(k): s for k, s in data["scenes"].items()})


def explore(nds, start_state: str, work_dir: str) -> WalkGraph:
    """Walk every tile of the start state's map that the player can reach without a scene.
    Keeps one saved state per tile still to be tried in work_dir, which it empties."""
    shutil.rmtree(work_dir, ignore_errors=True)
    os.makedirs(work_dir)
    nds.load_state_from_file(start_state)
    nds.tick(2)
    if gen4.field_task(nds):
        raise RuntimeError(f"{start_state}: a scene is running; explore from a state where the player can walk")
    no_encounters(nds)
    g = WalkGraph(gen4.read_location(nds).map_id, gen4.read_player_tile(nds))
    saved = lambda n: os.path.join(work_dir, "%d_%d_%d.state" % n)
    nds.save_state_to_file(saved(g.start))
    seen, queue = {g.start}, deque([g.start])
    while queue:
        n = queue.popleft()
        for d in DIRS:
            nds.load_state_from_file(saved(n))
            nds.tick(1)
            outcome = step(nds, d)
            if outcome == "exit":
                g.exits.setdefault(n, {})[d] = gen4.read_location(nds).map_id
            elif outcome == "scene":
                g.scenes.setdefault(n, []).append(d)
            elif outcome == "moved":
                to = gen4.read_player_tile(nds)
                g.edges.setdefault(n, {})[d] = to
                if to not in seen:
                    seen.add(to)
                    nds.save_state_to_file(saved(to))
                    queue.append(to)
        os.remove(saved(n))
    shutil.rmtree(work_dir, ignore_errors=True)
    return g


BLOCKED_WAIT, BLOCKED_TRIES = 30, 10   # a person who wanders into the way moves on within a few seconds


def walk_to(nds, graph: WalkGraph, goal) -> str:
    """Walk to goal (a node, or an (x, z) at any height) on the graph's map, re-planning from
    the player's tile after every step, so a person in the way only costs a wait. Returns
    "arrived", "scene" or "exit" when a step starts one, or "stuck" when the way stays blocked
    or the graph has no path."""
    blocked = 0
    while True:
        here = gen4.read_player_tile(nds)
        dirs = graph.path(here, goal)
        if dirs is None:
            return "stuck"
        if not dirs:
            return "arrived"
        outcome = step(nds, dirs[0])
        if outcome in ("scene", "exit"):
            return outcome
        if outcome == "blocked":
            blocked += 1
            if blocked > BLOCKED_TRIES:
                return "stuck"
            nds.tick(BLOCKED_WAIT)
        else:
            blocked = 0
