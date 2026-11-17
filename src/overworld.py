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

import fieldmap
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

    def nodes(self) -> set[Node]:
        return set(self.edges) | {n for e in self.edges.values() for n in e.values()} | {self.start}

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


TEXT_GAP, TEXT_QUIET, TEXT_LIMIT = 20, 40, 30000   # frames between presses; free this long = done; give up after


def press(nds, key: str, frames: int = 4) -> None:
    nds.button.press_key(key)
    nds.tick(frames)
    nds.button.release_key(key)


def advance_text(nds, yes: bool = False, limit: int = TEXT_LIMIT) -> str:
    """Press B every TEXT_GAP frames while a field task runs, until none has run for TEXT_QUIET
    frames. B never starts a new talk, but answers no to a yes/no, and a question the story
    needs answered yes then asks again forever (Rowan's Pokédex): yes=True presses A instead.
    Also carries a battle's closing text and a whiteout through to the overworld.
    Returns "done", "battle" when a battle starts, or "stuck" after limit frames."""
    key, quiet, was_battle = ("a" if yes else "b"), 0, gen4.in_battle(nds)
    for frame in range(limit):
        if gen4.in_battle(nds):
            if not was_battle:
                return "battle"
        else:
            was_battle = False
        if gen4.field_task(nds) or gen4.in_battle(nds):
            quiet = 0
            if frame % TEXT_GAP == 0:
                press(nds, key)
        else:
            quiet += 1
            if quiet >= TEXT_QUIET:
                return "done"
        nds.tick(1)
    return "stuck"


def talk_from(nds, graph: WalkGraph, tile, direction: str) -> str:
    """Walk to tile, face direction, press A. Returns "talking" when a script starts, "nothing"
    when none does, or walk_to's outcome when the walk doesn't arrive."""
    walked = walk_to(nds, graph, tile)
    if walked != "arrived":
        return walked
    press(nds, direction, 3)            # a short press turns the player without stepping
    nds.tick(12)
    press(nds, "a")
    nds.tick(30)
    return "talking" if gen4.field_task(nds) else "nothing"


def talk_to(nds, graph: WalkGraph, x: int, z: int) -> str:
    """Talk to the person at (x, z) from the nearest tile beside them."""
    here = gen4.read_player_tile(nds)
    beside = []
    for d, (dx, dz) in (("up", (0, -1)), ("down", (0, 1)), ("left", (-1, 0)), ("right", (1, 0))):
        for n in graph.nodes():
            if (n[0] + dx, n[1] + dz) == (x, z):
                route = graph.path(here, n)
                if route is not None:
                    beside.append((len(route), n, d))
    if not beside:
        return "stuck"
    _, tile, d = min(beside)
    return talk_from(nds, graph, tile, d)


def take_exit(nds, graph: WalkGraph, dest_map: int) -> str:
    """Walk to the nearest step that leads to dest_map, take it, and wait out the warp.
    Returns "arrived" on dest_map, or the outcome that stopped the walk."""
    here = gen4.read_player_tile(nds)
    ways = [(len(r), n, d) for n, e in graph.exits.items() for d, m in e.items()
            if m == dest_map and (r := graph.path(here, n)) is not None]
    if not ways:
        return "stuck"
    _, tile, d = min(ways)
    walked = walk_to(nds, graph, tile)
    if walked != "arrived":
        return walked
    if step(nds, d) != "exit":
        return "stuck"
    for _ in range(WARP_FRAMES):
        if not gen4.field_task(nds):
            break
        nds.tick(1)
    return "arrived" if gen4.read_location(nds).map_id == dest_map else "stuck"


def spotted_by(nds) -> list[int]:
    """The trainers on this map whose sight covers the player's tile, among those not hidden.
    A scene that starts on such a tile is a trainer walking up to battle."""
    loc = gen4.read_location(nds)
    return [fieldmap.trainer_id(o) for o in fieldmap.trainers(loc.map_id)
            if not gen4.read_flag(nds, o.flag) and (loc.x, loc.z) in fieldmap.sight(loc.map_id, o)]
