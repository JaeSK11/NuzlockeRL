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

    def path(self, start: Node, goal, avoid=frozenset()) -> list[str] | None:
        """The fewest steps from start to goal (a node, or an (x, z) at any height), through no
        (x, z) in avoid."""
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
                if to not in prev and to[:2] not in avoid:
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
AROUND_AFTER = 3                       # blocked tries before planning around a person who stands still


WALK_SETTLE = 16      # frames for the last step's walk to finish after its tile has changed


def walk(nds, direction: str, target) -> str:
    """Hold a direction until the player stands on target (x, z), the end of a straight stretch.
    The tile changes as a step begins, so letting go then finishes that step and stops. Stops
    early when a field task starts (a scene, a trainer, a door's warp, a battle), the map changes,
    or the player stops moving. Returns step()'s outcomes; "blocked" when it didn't move at all."""
    map_id, start = gen4.read_location(nds).map_id, gen4.read_player_tile(nds)
    last, still = start, 0
    nds.button.press_key(direction)
    while True:
        nds.tick(1)
        tile = gen4.read_player_tile(nds)
        if gen4.read_location(nds).map_id != map_id or gen4.field_task(nds) or tile[:2] == tuple(target):
            break
        if tile == last:
            still += 1
            if still > STEP_FRAMES:
                break
        else:
            last, still = tile, 0
    nds.button.release_key(direction)
    if gen4.read_player_tile(nds) == start and gen4.read_location(nds).map_id == map_id and not gen4.field_task(nds):
        return "blocked"
    nds.tick(WALK_SETTLE)
    for _ in range(WARP_FRAMES):
        if not gen4.field_task(nds) or gen4.read_location(nds).map_id != map_id:
            break
        nds.tick(1)
    if gen4.read_location(nds).map_id != map_id:
        return "exit"
    return "scene" if gen4.field_task(nds) or gen4.in_battle(nds) else "moved"


def _rom_stretch(nds, goal, avoid=frozenset()):
    """The first straight stretch of the cheapest walk to goal (x, z) on the ROM's collision
    layer, with signs and the people not hidden blocking the way: (direction, end tile), "" when
    there, None when there's no way."""
    loc = gen4.read_location(nds)
    if (loc.x, loc.z) == tuple(goal[:2]):
        return ""
    signs, objs, _, _ = fieldmap.events(loc.map_id)
    blocked = {(s.x, s.z) for s in signs} | {(o.x, o.z) for o in objs if not gen4.read_flag(nds, o.flag)} | set(avoid)
    blocked.discard(tuple(goal[:2]))
    runs = fieldmap.path(fieldmap.header(loc.map_id).matrix, (loc.x, loc.z), tuple(goal[:2]), frozenset(blocked))
    if not runs:
        return None
    d, n = runs[0]
    dx, dz = fieldmap.DIRS[d]
    return d, (loc.x + dx * n, loc.z + dz * n)


def _graph_stretch(graph: WalkGraph, here, goal, avoid=frozenset()):
    """The same on a walkable graph: the first direction of the path and where its run ends."""
    dirs = graph.path(here, goal, avoid)
    if dirs is None:
        return None
    if not dirs:
        return ""
    node = here
    for d in dirs:
        if d != dirs[0]:
            break
        node = graph.edges[node][d]
    return dirs[0], node[:2]


def walk_to(nds, graph: WalkGraph | None, goal) -> str:
    """Walk to goal (a node, or an (x, z) at any height), a straight stretch at a time, planning
    again from the player's tile after each. A blocked step waits for the person in the way;
    after AROUND_AFTER blocked tries the walk plans around that tile, and forgets such tiles
    again if that leaves no way. With a graph the plan uses it; without one it uses the ROM's
    collision layer (`fieldmap`), which sees no heights, and goes on across the edge into the
    next map of the same matrix, as the outdoor maps are. Returns "arrived", "scene" or "exit"
    when a step starts one, or "stuck" when the way stays blocked or there's no path."""
    avoid, waits = set(), 0
    while True:
        here = gen4.read_player_tile(nds)
        plan = _rom_stretch(nds, goal, avoid) if graph is None else _graph_stretch(graph, here, goal, avoid)
        if plan is None:
            if not avoid:
                return "stuck"
            avoid.clear()
        elif plan == "":
            return "arrived"
        else:
            direction, end = plan
            map_id = gen4.read_location(nds).map_id
            outcome = walk(nds, direction, end)
            if outcome == "exit" and graph is None and \
                    fieldmap.header(gen4.read_location(nds).map_id).matrix == fieldmap.header(map_id).matrix:
                outcome = "moved"
            if outcome in ("scene", "exit"):
                return outcome
            if outcome != "blocked":
                waits = 0
                continue
            if waits % AROUND_AFTER == AROUND_AFTER - 1:
                dx, dz = fieldmap.DIRS[direction]
                avoid.add((here[0] + dx, here[1] + dz))
        waits += 1
        if waits > BLOCKED_TRIES:
            return "stuck"
        nds.tick(BLOCKED_WAIT)


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


def talk_from(nds, graph: WalkGraph | None, tile, direction: str) -> str:
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


def talk_to(nds, graph: WalkGraph | None, x: int, z: int) -> str:
    """Talk to the person at (x, z) from the nearest free tile beside them, on the graph or,
    without one, on the ROM's collision layer."""
    here = gen4.read_player_tile(nds)
    beside = []
    for d, (dx, dz) in fieldmap.DIRS.items():
        tile = (x - dx, z - dz)
        if graph is not None:
            for n in graph.nodes():
                if n[:2] == tile and (r := graph.path(here, n)) is not None:
                    beside.append((len(r), n, d))
        else:
            loc = gen4.read_location(nds)
            matrix = fieldmap.header(loc.map_id).matrix
            people = {(o.x, o.z) for o in fieldmap.events(loc.map_id)[1] if not gen4.read_flag(nds, o.flag)}
            if not fieldmap.attrs(matrix)[tile[1], tile[0]] & fieldmap.COLLISION and tile not in people \
                    and (r := fieldmap.path(matrix, (loc.x, loc.z), tile)) is not None:
                beside.append((sum(n for _, n in r), tile, d))
    if not beside:
        return "stuck"
    _, tile, d = min(beside)
    return talk_from(nds, graph, tile, d)


def take_exit(nds, graph: WalkGraph | None, dest_map: int) -> str:
    """Walk to the nearest way into dest_map, take it, and wait out the warp. With a graph, the
    way is a step the graph recorded; without one, a warp event of the map, entered by walking
    onto it, or from an exit mat, by walking on toward the wall. Returns "arrived" on dest_map,
    or the outcome that stopped the walk."""
    here = gen4.read_player_tile(nds)
    if graph is not None:
        ways = [(len(r), n, d) for n, e in graph.exits.items() for d, m in e.items()
                if m == dest_map and (r := graph.path(here, n)) is not None]
        if not ways:
            return "stuck"
        _, tile, d = min(ways)
        walked = walk_to(nds, graph, tile)
        if walked != "arrived" or step(nds, d) != "exit":
            return walked if walked != "arrived" else "stuck"
    else:
        loc = gen4.read_location(nds)
        matrix = fieldmap.header(loc.map_id).matrix
        warps = [w for w in fieldmap.events(loc.map_id)[2] if w.dest_header == dest_map]
        ways = [(sum(n for _, n in r), w) for w in warps
                if (r := fieldmap.path(matrix, (loc.x, loc.z), (w.x, w.z))) is not None]
        if not ways:
            return "stuck"
        _, w = min(ways)
        walked = walk_to(nds, None, (w.x, w.z))
        if walked == "arrived":
            grid = fieldmap.attrs(matrix)
            walls = [d for d, (dx, dz) in fieldmap.DIRS.items()
                     if not (0 <= w.x + dx < grid.shape[1] and 0 <= w.z + dz < grid.shape[0])
                     or grid[w.z + dz, w.x + dx] & fieldmap.COLLISION]
            walked = next((o for d in walls if (o := step(nds, d)) == "exit"), "stuck")
        if walked != "exit":
            return walked
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
