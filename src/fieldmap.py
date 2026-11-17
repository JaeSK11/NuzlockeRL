"""The overworld's facts, read from the ROM: map headers, map matrices, tile attributes, map
events (people, warps, triggers), trainers' lines of sight, and a cheapest-walk path finder.

Coordinates are the ones gen4.read_location reports: global tiles on an outdoor matrix (matrix
0 holds Twinleaf Town to Oreburgh City), local tiles inside a building. The formats are retail
Platinum's (pret/pokeplatinum include/struct_defs/events.h, include/constants/field/map.h).

Limits: only the collision bit and the tile behavior are read, not the height data, so a map
with raised floors (the Oreburgh Gym) has edges this can't see. Event lists come from the ROM,
so they include people whose event flag hides them; the caller filters those by the flags in RAM.
"""
from __future__ import annotations
import heapq
import struct
from functools import cache
from typing import NamedTuple

import numpy as np

import romdata as R

COLLISION = 0x8000
GRASS = (0x02, 0x03)
JUMP = {0x38: (1, 0), 0x39: (-1, 0), 0x3A: (0, -1), 0x3B: (0, 1)}       # ledges, by the way they drop
BLOCK = {0x30: {(1, 0)}, 0x31: {(-1, 0)}, 0x32: {(0, -1)}, 0x33: {(0, 1)},
         0x34: {(0, -1), (1, 0)}, 0x35: {(0, -1), (-1, 0)}, 0x36: {(0, 1), (1, 0)}, 0x37: {(0, 1), (-1, 0)}}
DIRS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
TRAINER_SCRIPT_BASE = 2999      # a sight trainer's script is 2999 + its trainer id
SET_VAR = 0x28                  # script command SetVar var, value


class Header(NamedTuple):
    id: int
    matrix: int
    scripts: int
    events: int


class Obj(NamedTuple):
    local_id: int
    gfx: int
    movement: int
    trainer_type: int
    flag: int           # the event flag that hides it; 0 = always shown
    script: int
    dir: int            # 0 up, 1 down, 2 left, 3 right
    sight: int          # a trainer's sight range (data[0])
    x: int
    z: int


class Warp(NamedTuple):
    x: int
    z: int
    dest_header: int
    dest_warp: int


class Coord(NamedTuple):
    """A trigger: walking onto the width x length area at (x, z) runs script while var == value."""
    script: int
    x: int
    z: int
    width: int
    length: int
    value: int
    var: int


class Sign(NamedTuple):
    script: int
    x: int
    z: int


@cache
def header(i: int) -> Header:
    h = R._rom().arm9[R._MAP_HEADER_OFFSET + 24 * i:R._MAP_HEADER_OFFSET + 24 * i + 24]
    _area, _pre, matrix, scripts, _init, _msg, _day, _night, _wild, events = struct.unpack_from("<BBHHHHHHHH", h)
    return Header(i, matrix, scripts, events)


@cache
def matrix(mid: int) -> tuple[int, int, np.ndarray | None, np.ndarray]:
    """(width, height, map header per chunk or None, land data id per chunk), in 32x32-tile chunks."""
    b = R._narc("fielddata/mapmatrix/map_matrix.narc")[mid]
    w, h, has_headers, has_alt, name_len = b[:5]
    o = 5 + name_len
    headers = None
    if has_headers:
        headers = np.frombuffer(b, "<u2", w * h, o).reshape(h, w); o += 2 * w * h
    if has_alt:
        o += w * h
    return w, h, headers, np.frombuffer(b, "<u2", w * h, o).reshape(h, w)


@cache
def attrs(mid: int) -> np.ndarray:
    """Tile attributes of a whole matrix, indexed [z, x]: bit 15 collision, low byte the behavior.
    Chunks without land data read as walls."""
    w, h, _, land = matrix(mid)
    narc = R._narc("fielddata/land_data/land_data.narc")
    grid = np.full((h * 32, w * 32), COLLISION, np.uint16)
    for cz in range(h):
        for cx in range(w):
            if land[cz, cx] != 0xFFFF:
                grid[cz * 32:cz * 32 + 32, cx * 32:cx * 32 + 32] = \
                    np.frombuffer(narc[land[cz, cx]], "<u2", 1024, 0x10).reshape(32, 32)
    return grid


@cache
def events(header_id: int) -> tuple[tuple[Sign, ...], tuple[Obj, ...], tuple[Warp, ...], tuple[Coord, ...]]:
    b = R._narc("fielddata/eventdata/zone_event.narc")[header(header_id).events]
    o = 0

    def count():
        nonlocal o
        o += 4
        return struct.unpack_from("<I", b, o - 4)[0]
    signs = []
    for _ in range(count()):
        s, _t, x, z, _y, _f = struct.unpack_from("<HHiiiH", b, o); o += 20
        signs.append(Sign(s, x, z))
    objs = []
    for _ in range(count()):
        f = struct.unpack_from("<HHHHHHhHHHhhHHi", b, o); o += 32
        objs.append(Obj(f[0], f[1], f[2], f[3], f[4], f[5], f[6], f[7], f[12], f[13]))
    warps = []
    for _ in range(count()):
        warps.append(Warp(*struct.unpack_from("<HHHH", b, o))); o += 12
    coords = []
    for _ in range(count()):
        s, x, z, w, l, _y, v, var = struct.unpack_from("<HHHHHHHH", b, o); o += 16
        coords.append(Coord(s, x, z, w, l, v, var))
    return tuple(signs), tuple(objs), tuple(warps), tuple(coords)


def path(mid: int, start, goal, blocked=frozenset(), grass_cost: int = 8) -> list[tuple[str, int]] | None:
    """The cheapest walk from start to goal (x, z) on matrix mid, as [(direction, tiles)] runs, or
    None. A grass tile costs grass_cost; ledges are crossed only the way they drop."""
    grid = attrs(mid)
    H, W = grid.shape
    dist, prev, pq = {start: 0}, {}, [(0, start)]
    while pq:
        d, cur = heapq.heappop(pq)
        if cur == goal:
            break
        if d > dist[cur]:
            continue
        x, z = cur
        for name, (dx, dz) in DIRS.items():
            nx, nz = x + dx, z + dz
            if not (0 <= nx < W and 0 <= nz < H) or (nx, nz) in blocked:
                continue
            if (dx, dz) in BLOCK.get(int(grid[z, x]) & 0xFF, ()):
                continue
            a = int(grid[nz, nx])
            step = 1
            if a & 0xFF in JUMP:
                if JUMP[a & 0xFF] != (dx, dz):
                    continue
                nx, nz, step = nx + dx, nz + dz, 2
                a = int(grid[nz, nx])
            elif a & COLLISION and (nx, nz) != goal:
                continue
            if (-dx, -dz) in BLOCK.get(a & 0xFF, ()):
                continue
            nd = d + step * (grass_cost if a & 0xFF in GRASS else 1)
            if nd < dist.get((nx, nz), 1 << 30):
                dist[(nx, nz)], prev[(nx, nz)] = nd, (cur, name, step)
                heapq.heappush(pq, (nd, (nx, nz)))
    if goal != start and goal not in prev:
        return None
    moves, cur = [], goal
    while cur != start:
        cur, name, step = prev[cur]
        moves.append((name, step))
    runs: list[list] = []
    for name, step in reversed(moves):
        if runs and runs[-1][0] == name:
            runs[-1][1] += step
        else:
            runs.append([name, step])
    return [tuple(r) for r in runs]


# Which ways a standing trainer looks, by movement type (decomp generated/movement_types.txt).
# Other types look the way the event's dir says.
LOOKS = {2: "NSWE", 6: "NW", 7: "NE", 8: "SW", 9: "SE", 10: "NSW", 11: "NSE", 12: "NWE", 13: "SWE",
         14: "N", 15: "S", 16: "W", 17: "E", 18: "NSWE", 19: "NSWE"}
FACING = "NSWE"
STEP = {"N": (0, -1), "S": (0, 1), "W": (-1, 0), "E": (1, 0)}


def trainers(header_id: int) -> list[Obj]:
    return [o for o in events(header_id)[1] if o.trainer_type in (1, 2)]


def trainer_id(o: Obj) -> int:
    return o.script - TRAINER_SCRIPT_BASE


def sight(header_id: int, o: Obj) -> set[tuple[int, int]]:
    """The tiles where the trainer spots the player: up to o.sight tiles each way it looks, up to a wall."""
    grid = attrs(header(header_id).matrix)
    tiles = set()
    for d in LOOKS.get(o.movement, FACING[o.dir]):
        dx, dz = STEP[d]
        for i in range(1, o.sight + 1):
            x, z = o.x + dx * i, o.z + dz * i
            if grid[z, x] & COLLISION:
                break
            tiles.add((x, z))
    return tiles


def forced_trainers(header_id: int, start, goal) -> dict[int, bool]:
    """For each sight trainer on the map: True if every walk from start to goal crosses its sight.
    Every person and sign blocks the way, as they stand in the ROM."""
    signs, objs, _, _ = events(header_id)
    base = {(o.x, o.z) for o in objs} | {(s.x, s.z) for s in signs}
    out = {}
    for o in trainers(header_id):
        seen = sight(header_id, o)
        blocked = frozenset((base | seen) - {goal})
        out[trainer_id(o)] = (goal in seen or start in seen
                              or path(header(header_id).matrix, start, goal, blocked, grass_cost=1) is None)
    return out


def set_var_sites(var: int, value: int) -> list[int]:
    """Map headers whose script file holds SetVar(var, value): where in the story a var takes a value."""
    pattern = struct.pack("<HHH", SET_VAR, var, value)
    files = {i for i, data in enumerate(R._narc("fielddata/script/scr_seq.narc")) if pattern in data}
    return [h for h in range(R._MAP_HEADER_COUNT) if header(h).scripts in files]
