# -*- coding: utf-8 -*-
"""
Block Placer — a Minecraft-like voxel game in single-file Python + Pygame.
Handcrafted Cubic-Odyssey-style map, GTA-style third-person camera, painterly HUD.
No pygame.font — all text rendered with PIL.
"""
import sys
import os
import math
import time
import random
import pygame
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont

# -----------------------------------------------------------------------------
# constants
# -----------------------------------------------------------------------------
WIDTH, HEIGHT = 1280, 720
W2, H2 = WIDTH // 2, HEIGHT // 2
FPS = 60
CHUNK = 32
CHUNK_SHIFT = 5
HY = 48                       # world height (y 0..HY-1)
RADIUS_BY_Q = [10, 14, 18, 22, 27]
QUALITY = 3                   # -> R=22
FOV = 62.0
CAM_DISTANCE = 9.0
CAM_LIFT = 2.4
EYE_H = 1.6
NEAR = 0.4
GRAVITY = 32.0
MOVE_SPEED = 5.2
JUMP_VY = 12.5
CAM_PITCH = 0.18             # downward look pitch (radians); small so center-ray hits ground blocks
FR_S = 2.0                   # frustum margin in pixels

# block colors (r,g,b)
C = {
    "stone":     (148, 142, 134),
    "grass":     (122, 168, 84),
    "leaf":      (84, 152, 72),
    "dirt":      (128, 92, 62),
    "log":       (138, 92, 58),
    "sand":      (232, 210, 158),
    "sandstone": (218, 196, 150),
    "wheat":     (230, 188, 90),
    "glass":     (178, 214, 232),
    "torch":     (255, 196, 90),
    "chest":     (190, 150, 60),
    "bedrock":   (64, 64, 70),
}

BLOCKS = ["grass", "dirt", "log", "leaf", "wheat", "glass", "sand",
          "sandstone", "stone", "torch", "chest"]
PICKABLE = set(BLOCKS)
NON_OPAQUE = {"glass", "torch", "chest"}
OPEAK = BLOCKS[0]

# flag / secret chest coordinates
FLAG_X, FLAG_Z = 25, 30   # glowing beacon at the east hill summit
CHEST_X, CHEST_Z, CHEST_Y = -7, 9, 4   # secret chest hidden in the cottage floor

# -----------------------------------------------------------------------------
# progression data
# -----------------------------------------------------------------------------
TOOL_NAMES = ["Bare Hands", "Wooden Pick", "Stone Pick"]
TOOL_SPEED = [1.0, 1.8, 3.2]
TOOL_MAXTIER = [0, 1, 2]
BLOCK_MINE = {
    "grass":     (0.6, 0),
    "dirt":      (0.8, 0),
    "log":       (1.0, 0),
    "leaf":      (0.5, 0),
    "wheat":     (0.4, 0),
    "glass":     (0.5, 0),
    "sand":      (0.8, 0),
    "sandstone": (1.6, 1),
    "stone":     (2.2, 1),
    "torch":     (0.4, 0),
    "chest":     (0.5, 0),
}
XP_TABLE = {
    "leaf": 2, "wheat": 1, "grass": 2, "sand": 2,
    "dirt": 3, "log": 5, "glass": 3, "sandstone": 6,
    "stone": 8, "torch": 2, "chest": 5,
}
MASTER_ORDER = ["stone", "grass", "dirt", "log", "leaf", "wheat",
                "glass", "sand", "sandstone", "torch", "chest"]
LEVEL_TABLE = {1: 40, 2: 80, 3: 130, 4: 200, 5: 300}
UNLOCK_TABLE = {
    2: {"log", "sand"},
    3: {"glass", "wheat"},
    4: {"sandstone", "leaf"},
    5: {"torch"},
}
UNLOCK_PACK = 6
QUESTS = [
    ("q1", "Chop a Tree",
     "Walk to a tree and mine its trunk (hold RMB).",
     "count", "log", 3, 25),
    ("q2", "Dig the Dirt",
     "Dig up 12 dirt or grass blocks from the plateau.",
     "count", "dirt", 12, 30),
    ("q3", "Climb the Hill",
     "Climb to the top of the east hill where the beacon waits.",
     "flag", None, 0, 60),
    ("q4", "Find the Secret Chest",
     "The cottage has a hidden door — go in and mine the treasure on the floor.",
     "count", "chest", 1, 80),
    ("q5", "Light the Way",
     "Reach Lvl 5, craft torches, and mine a torch to test it.",
     "count", "torch", 1, 60),
]

# -----------------------------------------------------------------------------
# face normals + corners
# -----------------------------------------------------------------------------
FACE_NORMALS = [
    (0, 1, 0),  (0, -1, 0),
    (1, 0, 0),  (-1, 0, 0),
    (0, 0, 1),  (0, 0, -1),
]
# world-offset corners for each face, relative to block origin (x, y, z).
# Block occupies [x,x+1] x [y,y+1] x [z,z+1].
FACE_CORNERS = {
    (0, 1, 0):  [(-.5, 1, -.5), (.5, 1, -.5), (.5, 1, .5), (-.5, 1, .5)],   # +y top
    (0,-1, 0):  [(-.5, 0, -.5), (.5, 0, -.5), (.5, 0, .5), (-.5, 0, .5)],   # -y bottom
    (1, 0, 0):  [(1, -.5, -.5), (1, .5, -.5), (1, .5, .5), (1, -.5, .5)],   # +x right
    (-1,0, 0):  [(0, -.5, -.5), (0, .5, -.5), (0, .5, .5), (0, -.5, .5)],   # -x left
    (0, 0, 1):  [(-.5, -.5, 1), (.5, -.5, 1), (.5, .5, 1), (-.5, .5, 1)],   # +z front
    (0, 0,-1):  [(-.5, -.5, 0), (.5, -.5, 0), (.5, .5, 0), (-.5, .5, 0)],   # -z back
}
# shading multiplier per face (top brightest, bottom darkest)
FACE_SHADE = {
    (0, 1, 0):  1.05,
    (0,-1, 0):  0.55,
    (1, 0, 0):  0.80,
    (-1,0, 0):  0.80,
    (0, 0, 1):  0.92,
    (0, 0,-1):  0.92,
}

# -----------------------------------------------------------------------------
# handcrafted Cubic-Odyssey style map
# -----------------------------------------------------------------------------
def _between(v, a, b):
    return a <= v <= b

def terrain_top(x, z):
    """Return top y for a column (int) or None outside the map."""
    if not (_between(x, -30, 30) and _between(z, -30, 30)):
        return None
    top = 4
    # West basin: a low depression in the southwest
    if _between(x, -30, -20) and _between(z, -12, 12):
        top = 3
    # East hill: ramps up toward +z, summit at z=30
    if _between(z, 20, 30) and x >= 0:
        top = max(top, 4 + (z - 20))
    return int(top)

@lru_cache(maxsize=None)
def _raw_block(x, z, y):
    """Deterministic block at (x,z,y). Returns name or None. Pure/cacheable."""
    top = terrain_top(x, z)
    if top is None or y > top + 14:
        return None
    if y <= top:
        if y == top:
            if (x, z) == (CHEST_X, CHEST_Z):
                return "chest"
            if _between(x, -1, 1) and _between(z, -30, 30):
                return "dirt"
            if _between(z, -1, 1) and _between(x, -30, 30):
                return "dirt"
            return "grass"
        h = top - y
        if h <= 1:
            return "dirt"
        return "stone"
    # features above the plateau
    h = y - top
    if (x, z) == (FLAG_X, FLAG_Z):
        if h in (1, 2, 3):
            return "torch"
        if h == 4:
            return "chest"
    for tx, tz in [(10, 10), (-15, -18), (18, -8), (-20, 5)]:
        if (x, z) == (tx, tz):
            if 1 <= h <= 3:
                return "log"
            if 4 <= h <= 5:
                return "leaf"
    for rx, rz in [(8, -15), (-5, 20), (22, 2), (-24, -5)]:
        if (x, z) == (rx, rz):
            if 1 <= h <= 2:
                return "sandstone"
    if _between(x, -12, -6) and _between(z, 8, 12) and h <= 4:
        if h in (1, 2):
            if not (x == -9 and z == 12):
                return "sandstone"
        elif h == 3:
            return "dirt"
    # village settlement
    v = _village_blocks(x, z, y)
    if v is not None:
        return v
    # lighthouse beacon
    return _lighthouse_blocks(x, z, y)

def terrain_y_at(x, z):
    t = terrain_top(x, z)
    return int(t) if t is not None else None

# -----------------------------------------------------------------------------
# Village (Cubic-Odyssey style handcrafted settlement) + lighthouse
# -----------------------------------------------------------------------------
# A small settlement on the west plateau with houses, a plaza, a well,
# a market stall, trees, bushes, torches, and a lighthouse on the east hill.

LIGHTHOUSE_X, LIGHTHOUSE_Z = 28, -20   # tall beacon on the southeast grass

VILLAGE_HOUSES = [
    # (x, z, width, depth, wall, roof)
    (10, -10, 8, 6, "sandstone", "log"),    # House A
    (20, -10, 8, 6, "log", "sandstone"),    # House B
    (14, -18, 6, 4, "sandstone", "leaf"),   # House C (small)
]
VILLAGE_PLAZA_X0, VILLAGE_PLAZA_X1 = 9, 27
VILLAGE_PLAZA_Z0, VILLAGE_PLAZA_Z1 = -12, -9
WELL_X, WELL_Z = 18, -10
VILLAGE_TREE_POS = [(8, -14), (28, -12), (24, -18), (12, -16)]
VILLAGE_BUSH_POS = [(7, -11), (29, -14), (21, -19), (13, -17)]
STALL_X, STALL_Z = 25, -18
SIGN_X, SIGN_Z = 16, -20
VILLAGE_TORCH_POS = [(10, -10), (20, -10), (14, -18), (25, -18)]

def _village_blocks(x, z, y):
    top = terrain_top(x, z)
    if top is None:
        return None
    h = y - top

    # Plaza sand
    if _between(x, VILLAGE_PLAZA_X0, VILLAGE_PLAZA_X1) and        _between(z, VILLAGE_PLAZA_Z0, VILLAGE_PLAZA_Z1) and h == 0:
        return "sand"

    # Houses
    for hx, hz, hw, hd, wall, roof in VILLAGE_HOUSES:
        rx = x - hx
        rz = z - hz
        if not (0 <= rx < hw and 0 <= rz < hd):
            continue

        is_wall = (0 == rx or rx == hw-1 or 0 == rz or rz == hd-1)
        is_door = (rz == hd-1 and 3 <= rx <= 4)
        is_win = ((rz in (0, hd-1)) and 1 <= rx <= 2)

        if h == 1:
            if is_door:
                return None
            if is_win:
                return "glass"
            if is_wall:
                return wall
        elif h == 2:
            if is_door:
                return None
            if is_win:
                return "glass"
            if is_wall:
                return wall
        elif h == 3:
            return roof
        elif h == 4:
            if (rx in (0, hw-1) and rz in (0, hd-1)):
                return roof
        # Interior floor
        elif h == 1 and 1 < rx < hw-1 and 1 < rz < hd-1:
            return "sand"

    # Well (glass water + sandstone ring + stone top)
    if (x, z) == (WELL_X, WELL_Z):
        if 1 <= h <= 3:
            return "glass"
    elif 1 <= abs(x - WELL_X) <= 1 and 1 <= abs(z - WELL_Z) <= 1          and not (x == WELL_X and z == WELL_Z):
        if h == 1:
            return "sandstone"
        if h in (2, 3):
            return "stone"

    # Village trees
    for tx, tz in VILLAGE_TREE_POS:
        if (x, z) == (tx, tz):
            if 1 <= h <= 3:
                return "log"
            if 4 <= h <= 6:
                return "leaf"

    # Village bushes
    for tx, tz in VILLAGE_BUSH_POS:
        if (x, z) == (tx, tz) and h == 1:
            return "leaf"

    # Market stall
    if _between(x, STALL_X - 1, STALL_X + 1) and        _between(z, STALL_Z - 1, STALL_Z + 1):
        if h in (1, 2):
            return "sandstone"
        if h == 3:
            return "leaf"

    # Sign post
    if (x, z) == (SIGN_X, SIGN_Z):
        if 1 <= h <= 2:
            return "log"
        if h == 3:
            return "leaf"

    # Torches
    for ttx, ttz in VILLAGE_TORCH_POS:
        if (x, z) == (ttx, ttz):
            if 1 <= h <= 2:
                return "torch"
            if h == 3:
                return "log"

    return None


def _lighthouse_blocks(x, z, y):
    if (x, z) != (LIGHTHOUSE_X, LIGHTHOUSE_Z):
        return None
    top = terrain_top(x, z)
    h = y - top
    if 1 <= h <= 10:
        return "stone"
    if h in (11, 12):
        return "glass"
    if h in (13, 14):
        return "sandstone"
    return None
# -----------------------------------------------------------------------------
class World:
    def __init__(self, seed=1337):
        self.seed = seed
        self.static = {}      # (x,y,z) -> name  (precomputed static map)
        self.over = {}        # (x,y,z) -> name  (player overrides / None)
        # precompute static content
        for x in range(-30, 31):
            for z in range(-30, 31):
                for y in range(0, HY + 1):
                    b = _raw_block(x, z, y)
                    if b is not None:
                        self.static[(x, y, z)] = b

    def block(self, x, y, z):
        k = (x, y, z)
        if k in self.over:
            return self.over[k]
        return self.static.get(k)

    def opaque(self, x, y, z):
        b = self.block(x, y, z)
        return b is not None and b not in NON_OPAQUE

    def nopaque(self, x, y, z):
        return not self.opaque(x, y, z)

    def set(self, x, y, z, name):
        self.over[(x, y, z)] = name

    def _build(self, cx, cz):
        pass

    def _ensure(self, cx, cz):
        pass


# -----------------------------------------------------------------------------
# vectors
# -----------------------------------------------------------------------------
def dot(a, b):
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]

def cross(a, b):
    return (a[1]*b[2] - a[2]*b[1],
            a[2]*b[0] - a[0]*b[2],
            a[0]*b[1] - a[1]*b[0])

def normalize(a):
    l = math.sqrt(a[0]*a[0] + a[1]*a[1] + a[2]*a[2]) or 1.0
    return (a[0]/l, a[1]/l, a[2]/l)

# -----------------------------------------------------------------------------
# camera + projection
# -----------------------------------------------------------------------------
_tanfov = math.tan(math.radians(FOV) / 2.0)

def make_camera(player, world):
    """Return (eye, forward) for the active camera. forward is the aim
    direction (horizontal yaw + vertical pitch)."""
    cp = math.cos(player.pitch)
    hx, hz = math.sin(player.yaw), -math.cos(player.yaw)
    fx, fy, fz = hx * cp, -math.sin(player.pitch), hz * cp
    if player.first_person:
        eye = (player.x, player.y + EYE_H, player.z)
    else:
        eye = (player.x - CAM_DISTANCE * hx,
               player.y + EYE_H + CAM_LIFT,
               player.z - CAM_DISTANCE * hz)
    return eye, normalize((fx, fy, fz))

def proj(p, eye, f):
    """Project world point p to (sx, sy, depth) or None if behind/inside."""
    dx = p[0] - eye[0]
    dy = p[1] - eye[1]
    dz = p[2] - eye[2]
    up = (0.0, 1.0, 0.0)
    fu = up[0]*f[0] + up[1]*f[1] + up[2]*f[2]
    u = normalize((up[0] - fu*f[0], up[1] - fu*f[1], up[2] - fu*f[2]))
    r = normalize((f[1]*u[2] - f[2]*u[1],
                   f[2]*u[0] - f[0]*u[2],
                   f[0]*u[1] - f[1]*u[0]))
    vx = dx*r[0] + dy*r[1] + dz*r[2]
    vy = dx*u[0] + dy*u[1] + dz*u[2]
    vz = dx*f[0] + dy*f[1] + dz*f[2]
    if vz <= NEAR:
        return None
    scale = H2 / _tanfov
    sx = W2 + (vx / vz) * scale * (W2 / H2)
    sy = H2 - (vy / vz) * scale
    return (sx, sy, vz)

# -----------------------------------------------------------------------------
# raycast (DDA) for place / mine / grab
# -----------------------------------------------------------------------------
def raycast(player, world, cam, dist=30.0):
    """Shoot a ray from the camera eye along `forward` using a DDA cell march.
    Returns (bx, by, bz, nx, ny, nz) of the first hit block, or None.
    nx, ny, nz is the direction of travel that crossed into the hit cell
    (normal pointing the way the ray came from)."""
    eye, f = cam
    ox, oy, oz = eye
    dx, dy, dz = f[0], f[1], f[2]
    if abs(dx) < 1e-9 and abs(dy) < 1e-9 and abs(dz) < 1e-9:
        return None
    stepx = 1.0 if dx > 0 else -1.0
    stepy = 1.0 if dy > 0 else -1.0
    stepz = 1.0 if dz > 0 else -1.0
    def _tb(o, d):
        # t (distance along ray) to the next integer boundary in direction d
        if d > 0:
            return (math.ceil(o - 1e-9) - o) / d
        if d < 0:
            return (o - math.floor(o + 1e-9)) / (-d)
        return float('inf')
    txx = _tb(ox, dx) if dx != 0 else float('inf')
    tyy = _tb(oy, dy) if dy != 0 else float('inf')
    ttz = _tb(oz, dz) if dz != 0 else float('inf')
    bx = int(math.floor(ox)); by = int(math.floor(oy)); bz = int(math.floor(oz))
    if world.block(bx, by, bz) is not None:
        return (bx, by, bz, 0.0, 0.0, 0.0)
    nx = ny = nz = 0.0
    for _ in range(int(dist) * 2 + 5):
        if txx < tyy and txx < ttz:
            axis, tmin = 'x', txx
        elif tyy < ttz:
            axis, tmin = 'y', tyy
        else:
            axis, tmin = 'z', ttz
        if tmin > dist:
            break
        if axis == 'x':
            bx += stepx
            txx += 1.0 / abs(dx)
            nx, ny, nz = stepx, 0.0, 0.0
        elif axis == 'y':
            by += stepy
            tyy += 1.0 / abs(dy)
            nx, ny, nz = 0.0, stepy, 0.0
        else:
            bz += stepz
            ttz += 1.0 / abs(dz)
            nx, ny, nz = 0.0, 0.0, stepz
        if not (_between(bx, -31, 31) and _between(bz, -31, 31)):
            break
        if by < -1 or by >= HY + 8:
            break
        if world.block(bx, by, bz) is not None:
            return (bx, by, bz, nx, ny, nz)
    return None

def place_block(player, world, cam):
    hit = raycast(player, world, cam)
    if not hit:
        return
    bx, by, bz, nx, ny, nz = hit
    name = BLOCKS[player.selected]
    if player.inventory.get(name, 0) <= 0:
        return
    # only place on a valid face, within bounds, and only on an empty cell
    wx, wy, wz = bx - nx, by - ny, bz - nz
    if wy < 0 or wy >= HY + 6 or not (_between(wx, -31, 31) and _between(wz, -31, 31)):
        return
    if world.block(wx, wy, wz) is not None:
        return
    world.set(wx, wy, wz, name)
    player.inventory[name] = player.inventory.get(name, 0) - 1

def grab_block(player, world, cam):
    hit = raycast(player, world, cam)
    if not hit:
        return
    bx, by, bz, nx, ny, nz = hit
    name = world.block(bx, by, bz)
    if name is None or name not in PICKABLE:
        return
    world.set(bx, by, bz, None)
    player.inventory[name] = player.inventory.get(name, 0) + 1
    _complete_quests(player, world)

def gain_xp(player, amount):
    """Award XP, promote levels, unlock blocks, bump tool tier.
    Returns list of (level, block) events."""
    player.xp += amount
    events = []
    while player.level in LEVEL_TABLE and player.xp >= LEVEL_TABLE[player.level]:
        player.xp -= LEVEL_TABLE[player.level]
        player.level += 1
        events.append((player.level, None))
        for b in UNLOCK_TABLE.get(player.level, ()):
            if b not in player.unlocked:
                player.unlocked.add(b)
                player.inventory[b] = player.inventory.get(b, 0) + UNLOCK_PACK
                events.append((player.level, b))
        if player.level >= 2 and player.tool < 1:
            player.tool = 1
        if player.level >= 4 and player.tool < 2:
            player.tool = 2
    return events

def _complete_quests(player, world):
    """Mark any quest whose goal is now met (count met, or flag reached)."""
    for q in QUESTS:
        qid, qtitle, qdesc, kind, goal_block, goal_count, reward = q
        qstate = player.quests[qid]
        if qstate["done"]:
            continue
        if kind == "flag":
            if math.hypot(player.x - FLAG_X, player.z - FLAG_Z) <= 6.0:
                qstate["done"] = True
                player.flag_done = True
                player._level_up = (player.level, "flag")
        elif kind == "count":
            need = int(goal_count if goal_count else 1)
            if player.mined.get(goal_block, 0) >= need:
                qstate["done"] = True
                player._level_up = (player.level, goal_block)
        if all(player.quests[q2[0]]["done"] for q2 in QUESTS):
            player.flag_done = True
            for lv, b in gain_xp(player, 300):
                player._level_up = (lv, b)

def quest_status(player):
    """Return list of (done, title, progress_text) for the HUD quest panel."""
    out = []
    for q in QUESTS:
        qid, qtitle, qdesc, kind, goal_block, goal_count, reward = q
        done = player.quests[qid]["done"]
        if kind == "flag":
            d = math.hypot(player.x - FLAG_X, player.z - FLAG_Z)
            txt = "DONE!" if done else f"Beacon {int(d)} blocks away"
        else:
            got = player.mined.get(goal_block, 0)
            need = int(goal_count if goal_count else 1)
            txt = "DONE!" if done else f"{got}/{need} {goal_block}"
        out.append((done, qtitle, txt))
    return out

def mining_progress(player):
    """Return (0..1) progress of the current mining action, or -1 if idle."""
    if player.mining_target is None:
        return -1.0
    tx, ty, tz = player.mining_target
    name = player.world.block(tx, ty, tz)
    if name is None or name not in BLOCK_MINE:
        return -1.0
    base_sec, tier = BLOCK_MINE[name]
    if TOOL_MAXTIER[player.tool] < tier:
        return -1.0
    return min(1.0, player.mine_t / (base_sec / TOOL_SPEED[player.tool]))

def update_mining(player, world, dt, cam, mouse_down):
    """Drive mining each frame. While mouse_down, mine the block under the
    crosshair (hold to break); otherwise reset the timer."""
    if mouse_down:
        hit = raycast(player, world, cam)
        if not hit:
            player.mining_target = None
            player.mine_t = 0.0
        else:
            bx, by, bz, nx, ny, nz = hit
            name = world.block(bx, by, bz)
            if name is None or name not in BLOCK_MINE:
                player.mining_target = None
                player.mine_t = 0.0
            elif player.mining_target != (bx, by, bz):
                player.mining_target = (bx, by, bz)
                player.mine_t = 0.0
            else:
                base_sec, tier = BLOCK_MINE[name]
                if TOOL_MAXTIER[player.tool] < tier:
                    return None
                player.mine_t += dt
                break_sec = base_sec / TOOL_SPEED[player.tool]
                if player.mine_t >= break_sec:
                    world.set(bx, by, bz, None)
                    player.mining_target = None
                    player._level_up = None
                    for lv, b in gain_xp(player, XP_TABLE.get(name, 1)):
                        player._level_up = (lv, b)
                    player.inventory[name] = player.inventory.get(name, 0) + 1
                    player.mined[name] = player.mined.get(name, 0) + 1
                    _complete_quests(player, world)
                    return name
    else:
        player.mining_target = None
        player.mine_t = 0.0
    return None


# -----------------------------------------------------------------------------
# Player
# -----------------------------------------------------------------------------
class Player:
    def __init__(self, world):
        self.world = world
        self.x, self.y, self.z = 0.0, 5.5, 0.0
        self.vx, self.vy, self.vz = 0.0, 0.0, 0.0
        self.first_person = False
        self.yaw = 0.0
        self.pitch = CAM_PITCH
        self.selected = 0
        # progression state
        self.xp = 0
        self.level = 1
        self.tool = 0
        self.unlocked = set(BLOCKS)
        self.inventory = {b: 3 for b in BLOCKS}
        self.mining_target = None
        self.mine_t = 0.0
        self._level_up = None
        self.flag_done = False
        self.quests = {q[0]: {"done": False} for q in QUESTS}
        self.mined = {b: 0 for b in MASTER_ORDER}


def respawn(player):
    player.x, player.y, player.z = 0.0, 5.5, 0.0
    player.vx, player.vy, player.vz = 0.0, 0.0, 0.0


# -----------------------------------------------------------------------------
# text (PIL)
# -----------------------------------------------------------------------------
_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/home/punkiam/.local/share/fonts/DejaVuSans.ttf",
]

def _get_font(size):
    for p in _FONT_PATHS:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

_text_cache = {}

def text_surface(text, size, color, background=None):
    key = (text, size, str(color), str(background))
    if key in _text_cache:
        return _text_cache[key]
    font = _get_font(size)
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bbox = d.textbbox((0, 0), text, font=font)
    w = max(bbox[2] - bbox[0], 1)
    h = max(bbox[3] - bbox[1], 1)
    if background is None:
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    else:
        img = Image.new("RGBA", (w, h), background)
    dd = ImageDraw.Draw(img)
    dd.text((-bbox[0], -bbox[1]), text, font=font, fill=color)
    surf = pygame.image.frombytes(img.tobytes(), img.size, "RGBA")
    _text_cache[key] = surf
    return surf


# -----------------------------------------------------------------------------
# sky / clouds / shadow  (clouds use cloud.png, Minecraft-style)
# -----------------------------------------------------------------------------
_CLOUD_SURF = None
_sky_surf = None
_clouds = None

def _init_sky():
    global _sky_surf, _clouds
    # sky gradient + sun (drawn once on a static canvas)
    _sky_surf = pygame.Surface((WIDTH, HEIGHT))
    top = (86, 148, 222)
    mid = (178, 214, 232)
    bot = (232, 240, 244)
    for y in range(HEIGHT):
        t = y / float(HEIGHT)
        if t < 0.7:
            r = int(top[0] + (mid[0]-top[0]) * (t/0.7))
            g = int(top[1] + (mid[1]-top[1]) * (t/0.7))
            b = int(top[2] + (mid[2]-top[2]) * (t/0.7))
        else:
            u = (t-0.7)/0.3
            r = int(mid[0] + (bot[0]-mid[0]) * u)
            g = int(mid[1] + (bot[1]-mid[1]) * u)
            b = int(mid[2] + (bot[2]-mid[2]) * u)
        pygame.draw.rect(_sky_surf, (r, g, b), (0, y, WIDTH, 1))
    pygame.draw.circle(_sky_surf, (255, 244, 210), (WIDTH - 230, 90), 52)
    pygame.draw.circle(_sky_surf, (255, 244, 210), (WIDTH - 230, 90), 30)
    # cloud.png — Minecraft-style painted clouds (puff of white)
    cpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cloud.png")
    raw = None
    try:
        raw = Image.open(cpath).convert("RGBA")
    except Exception:
        raw = None
    _clouds = []
    for _ in range(7):
        cx = random.randint(40, WIDTH - 40)
        cy = random.randint(20, 90)
        if raw is None:
            _clouds.append((cx, cy, None))
            continue
        sc = random.randint(90, 200)
        ih = max(1, int(raw.size[1] * sc / float(raw.size[0])))
        img = raw.resize((sc, ih), Image.LANCZOS)
        surf = pygame.image.frombytes(img.tobytes(), img.size, "RGBA")
        _clouds.append((cx, cy, surf))

def draw_sky_decor(surf, cam):
    global _sky_surf, _clouds
    if _sky_surf is None:
        _init_sky()
    surf.blit(_sky_surf, (0, 0))
    eye, f = cam
    # simple parallax from yaw: yaw = atan2(fx, -fz)
    yaw = math.atan2(f[0], -f[2])
    for cx, cy, sprite in _clouds:
        if sprite is None:
            continue
        px = int(cx + yaw * 120.0)
        surf.blit(sprite, (px, int(cy - sprite.get_height() * 0.55)))

# -----------------------------------------------------------------------------
# shadow (soft ground shadow under the player)
# -----------------------------------------------------------------------------
def draw_shadow(surf, player, cam):
    if player.first_person:
        return
    # project the player's feet onto ground; draw a dark ellipse
    feet = (player.x, max(player.y - 0.2, 0.5), player.z)
    p = proj(feet, *cam)
    if p is None:
        return
    sx, sy, _d = p
    rad = max(8, int(18 / max(_d, 0.4)))
    pygame.draw.ellipse(surf, (40, 44, 30, 0), (int(sx)-rad, int(sy), rad*2, rad))
    # alpha not supported on Surface; use a soft gray
    pygame.draw.ellipse(surf, (60, 70, 40), (int(sx)-rad+1, int(sy)+2, max(4, rad*2-2), max(4, rad)))


# -----------------------------------------------------------------------------
# draw player sprite (GTA-style, projection-sized)
# -----------------------------------------------------------------------------
def draw_player(surf, player, cam):
    if player.first_person:
        return
    eye, f = cam
    feet = (player.x, player.y, player.z)
    head = (player.x, player.y + 1.6, player.z)
    pf = proj(feet, eye, f)
    ph = proj(head, eye, f)
    if pf is None or ph is None:
        return
    fx, fy, _ = pf
    hx, hy, _ = ph
    hpx = max(abs(hy - fy), 18)
    wpx = max(8, int(hpx * 0.48))
    x0 = int(fx - wpx/2.0); y0 = int(fy - hpx)
    # legs
    c_leg = (60, 66, 80)
    pygame.draw.rect(surf, c_leg, (x0 + wpx//2 - 7, y0 + int(hpx*0.45), 14, int(hpx*0.55)))
    pygame.draw.rect(surf, c_leg, (x0 + wpx//2 - wpx//2, y0 + int(hpx*0.45), int(wpx/2 - 6), int(hpx*0.55)))
    pygame.draw.rect(surf, (40, 44, 54), (x0, y0 + int(hpx*0.8), wpx, int(hpx*0.2)))
    pygame.draw.rect(surf, (40, 44, 54), (x0 + wpx//2, y0 + int(hpx*0.8), wpx//2, int(hpx*0.2)))
    # torso
    pygame.draw.rect(surf, (120, 150, 190), (x0 + int(wpx*0.2), y0, int(wpx*0.6), int(hpx*0.45)))
    pygame.draw.rect(surf, (84, 152, 72), (x0, y0 + int(hpx*0.52), wpx, int(hpx*0.16)))
    # head + hair + hat
    cx = x0 + wpx//2
    hy2 = y0 + int(hpx*0.4)
    pygame.draw.ellipse(surf, (232, 202, 162), (cx - wpx//2 + int(wpx*0.1), hy2, wpx*0.8, hpx*0.45))
    pygame.draw.ellipse(surf, (40, 34, 30), (cx - wpx//2 + int(wpx*0.1), hy2 - 2, wpx*0.8, hpx*0.2))
    pygame.draw.ellipse(surf, (110, 84, 48), (cx - wpx//2 + int(wpx*0.08), hy2 - hpx*0.06, wpx*0.84, hpx*0.12))
    # eyes (two dots)
    ey = hy2 + int(hpx*0.2)
    pygame.draw.circle(surf, (30, 20, 15), (cx - wpx//4, ey), max(1, wpx//10))
    pygame.draw.circle(surf, (30, 20, 15), (cx + wpx//4, ey), max(1, wpx//10))


# -----------------------------------------------------------------------------
# quads: build + draw with painter's algorithm
# -----------------------------------------------------------------------------
def _shade(color, k):
    r = min(255, max(0, int(color[0] * k)))
    g = min(255, max(0, int(color[1] * k)))
    b = min(255, max(0, int(color[2] * k)))
    return (r, g, b)

def build_quads(world, cam):
    """Build visible quads. Returns list of (z, sx0, sy0, sx1, sy1, sx2, sy2, sx3, sy3, color)."""
    eye, f = cam
    quads = []
    R = RADIUS_BY_Q[QUALITY]
    ex, ey, ez = eye
    x0 = int(ex - R); x1 = int(ex + R)
    z0 = int(ez - R); z1 = int(ez + R)
    for x in range(x0, x1 + 1):
        for z in range(z0, z1 + 1):
            # quick: is there any block in this column?
            top = terrain_top(x, z)
            if top is None:
                continue
            for y in range(0, top + 15):
                name = world.block(x, y, z)
                if name is None:
                    continue
                col = C.get(name, (120, 120, 120))
                for ni, fn in enumerate(FACE_NORMALS):
                    # back-face culling
                    if dot(fn, f) >= 0.0:
                        continue
                    corners = FACE_CORNERS[fn]
                    pts = []
                    depths = []
                    on_screen = True
                    for (dx, dy, dz) in corners:
                        wx = x + dx
                        wy = y + dy
                        wz = z + dz
                        p = proj((wx, wy, wz), eye, f)
                        if p is None:
                            on_screen = False
                            break
                        on_screen = True
                        pts.append((p[0], p[1]))
                        depths.append(p[2])
                    if not on_screen:
                        continue
                    # frustum: keep quad only if at least one corner is on screen
                    if not any((-FR_S < px <= WIDTH + FR_S and -FR_S <= py <= HEIGHT + FR_S)
                               for px, py in pts):
                        continue
                    depth = sum(depths) / len(depths)
                    # per-face shading
                    sh = FACE_SHADE.get(fn, 1.0)
                    # brightness boost by distance (atmospheric)
                    dc = 1.0 / (1.0 + depth * 0.004)
                    col2 = _shade(col, sh * dc)
                    quads.append((depth, pts[0][0], pts[0][1],
                                  pts[1][0], pts[1][1],
                                  pts[2][0], pts[2][1],
                                  pts[3][0], pts[3][1], col2))
    return quads

def draw_quads(surf, quads):
    # painter's: farthest first — quads carry their depth in q[0]; larger
    # depth means farther, so draw descending (far → near).
    quads.sort(key=lambda q: q[0], reverse=True)
    for q in quads:
        z, x0, y0, x1, y1, x2, y2, x3, y3, col = q
        pygame.draw.polygon(surf, col, [(x0, y0), (x1, y1), (x2, y2), (x3, y3)])
        # subtle edge
        e = tuple(max(0, min(255, int(c*0.75))) for c in col)
        pygame.draw.polygon(surf, e, [(x0, y0), (x1, y1), (x2, y2), (x3, y3)], 1)

# -----------------------------------------------------------------------------
# main draw
# -----------------------------------------------------------------------------
def draw(surf, world, player, cam):
    surf.fill((30, 40, 55))
    draw_sky_decor(surf, cam)
    quads = build_quads(world, cam)
    draw_quads(surf, quads)
    draw_shadow(surf, player, cam)
    draw_player(surf, player, cam)
    draw_hud(surf, player, player.first_person, False, False, QUALITY, RADIUS_BY_Q[QUALITY])
    # center crosshair (what you can place / mine / grab)
    pygame.draw.line(surf, (245, 245, 245), (W2 - 8, H2), (W2 + 8, H2), 1)
    pygame.draw.line(surf, (245, 245, 245), (W2, H2 - 8), (W2, H2 + 8), 1)

# -----------------------------------------------------------------------------
# HUD
# -----------------------------------------------------------------------------
def draw_hud(surf, player, fp, outline, show_debug, quality, R):
    # ---- top-left panel ----
    panel = pygame.Surface((330, 250), pygame.SRCALPHA)
    pygame.draw.rect(panel, (20, 24, 30, 200), (0, 0, 330, 250), border_radius=10)
    surf.blit(panel, (10, 10))
    surf.blit(text_surface("Block Placer", 52, (122, 168, 84), None), (14, 12))
    surf.blit(text_surface(f"LVL {player.level}  ·  {TOOL_NAMES[player.tool]}", 26,
                           (240, 230, 160), None), (22, 62))
    next_lv = LEVEL_TABLE.get(player.level, 999999)
    frac = min(1.0, player.xp / next_lv) if next_lv else 0.0
    bw, bh, bx, by = 260, 14, 22, 92
    pygame.draw.rect(surf, (50, 54, 62), (bx, by, bw, bh), border_radius=7)
    pygame.draw.rect(surf, (240, 214, 84), (bx, by, int(bw * frac), bh), border_radius=7)
    surf.blit(text_surface(f"{int(player.xp)}/{int(next_lv)} xp", 16,
                           (230, 230, 230), None), (bx + bw + 4, by - 4))
    held = BLOCKS[player.selected]
    cnt = player.inventory.get(held, 0)
    surf.blit(text_surface(f"Holding {held} x{cnt}", 22, (240, 240, 240), None), (22, 114))
    surf.blit(text_surface(f"pos ({int(player.x)}, {int(player.y)}, {int(player.z)})", 16,
                           (200, 200, 200), None), (22, 140))
    surf.blit(text_surface(f"mode {('third-person' if not fp else 'first-person')}"
                           f"  radius {R}", 15, (180, 180, 180), None), (22, 162))
    surf.blit(text_surface("M outlines  V radius  F cam  R respawn  0 debug", 15,
                           (170, 170, 170), None), (22, 180))
    mp = mining_progress(player)
    if mp >= 0.0:
        surf.blit(text_surface("mining...", 16, (255, 214, 120), None), (22, 200))
        pygame.draw.rect(surf, (50, 54, 62), (bx, 214, bw, 10), border_radius=5)
        pygame.draw.rect(surf, (255, 214, 120), (bx, 214, int(bw * mp), 10), border_radius=5)
    else:
        surf.blit(text_surface("LMB mine  RMB grab  (hold to break)", 15,
                               (170, 170, 170), None), (22, 204))
    if player._level_up is not None:
        lv, b = player._level_up
        t = text_surface(f"LEVEL UP! +{b or 'flag'}", 30, (255, 224, 90), (20, 24, 30, 220))
        surf.blit(t, (10 + (WIDTH - t.get_width()) // 2, 290))
    if player.flag_done:
        t = text_surface("VICTORY — all quests complete!", 30,
                         (255, 224, 90), (20, 24, 30, 220))
        surf.blit(t, (10 + (WIDTH - t.get_width()) // 2, 260))

    # ---- right panel: quests ----
    quest_rows = quest_status(player)
    panel2 = pygame.Surface((280, 30 + len(quest_rows) * 46), pygame.SRCALPHA)
    pygame.draw.rect(panel2, (18, 22, 28, 200), (0, 0, 280, 30 + len(quest_rows) * 46), border_radius=10)
    surf.blit(panel2, (WIDTH - 300, 10))
    surf.blit(text_surface("OBJECTIVES", 26, (122, 168, 84), None), (WIDTH - 300 + 14, 14))
    for i, (done, title, txt) in enumerate(quest_rows):
        y0 = 34 + i * 46
        t = text_surface(title, 17, (255, 255, 255), None)
        surf.blit(t, (WIDTH - 300 + 14, y0))
        col2 = (84, 152, 72) if done else (160, 160, 160)
        surf.blit(text_surface(txt, 15, col2, None), (WIDTH - 300 + 14, y0 + 20))
        cx = WIDTH - 300 + 254
        pygame.draw.circle(surf, (120, 120, 120), (cx, y0 + 8), 8)
        if done:
            pygame.draw.line(surf, (122, 168, 84), (cx - 5, y0 + 8), (cx + 5, y0 + 8), 2)
            pygame.draw.line(surf, (122, 168, 84), (cx + 5, y0 + 8), (cx + 12, y0 + 1), 2)

    # ---- bottom hotbar ----
    barw = (WIDTH - 24) // len(BLOCKS)
    barh = 50
    bar_y = HEIGHT - barh - 8
    for i, b in enumerate(BLOCKS):
        x = 12 + i * barw
        locked = b not in player.unlocked
        col_bg = (14, 16, 20, 210) if not locked else (22, 26, 34, 220)
        pygame.draw.rect(surf, col_bg, (x, bar_y, barw - 2, barh), border_radius=4)
        if i == player.selected and not locked:
            pygame.draw.rect(surf, (122, 168, 84), (x, bar_y, barw - 2, barh), 2, border_radius=4)
        if locked:
            lock_t = text_surface("?", 26, (160, 160, 160), None)
            surf.blit(lock_t, (x + barw // 2 - lock_t.get_width() // 2,
                               bar_y + barh // 2 - lock_t.get_height() // 2))
            continue
        ic_col = C.get(b, (120, 120, 120))
        ic = pygame.Surface((24, 24), pygame.SRCALPHA)
        pygame.draw.rect(ic, (ic_col[0], ic_col[1], ic_col[2], 255), (2, 2, 20, 20))
        x2 = x + (barw - 24) // 2
        y2 = bar_y + (barh - 24) // 2
        surf.blit(ic, (x2, y2))
        cnt = player.inventory.get(b, 0)
        surf.blit(text_surface(str(cnt), 18, (240, 240, 240), None),
                  (x + barw - 18, bar_y + barh - 18))


# -----------------------------------------------------------------------------
# display sizing + fullscreen (F11)
# -----------------------------------------------------------------------------
def _init_display():
    """Set window size to the native desktop resolution when it is at least
    1280x720 (so the window is not tiny on a big monitor), else 1280x720."""
    global WIDTH, HEIGHT, W2, H2
    try:
        ds = pygame.display.get_desktop_mode()
    except Exception:
        ds = None
    if ds is not None and len(ds) >= 2 and ds[0] >= 1280 and ds[1] >= 720:
        WIDTH, HEIGHT = ds[0], ds[1]
    else:
        WIDTH, HEIGHT = 1280, 720
    W2, H2 = WIDTH // 2, HEIGHT // 2

def _place_at_crosshair(player, world, cam):
    """Drop the selected block a few blocks in front of the eye (E 'place')."""
    eye, f = cam
    wx = int(eye[0] + f[0] * 3.0)
    wy = int(eye[1] + f[1] * 3.0)
    wz = int(eye[2] + f[2] * 3.0)
    name = BLOCKS[player.selected]
    if player.inventory.get(name, 0) <= 0:
        return
    if wy < 0 or wy >= HY + 6:
        return
    if not (_between(wx, -31, 31) and _between(wz, -31, 31)):
        return
    world.set(wx, wy, wz, name)
    player.inventory[name] = player.inventory.get(name, 0) - 1

# -----------------------------------------------------------------------------
# game loop
# -----------------------------------------------------------------------------
def main():
    pygame.init()
    pygame.display.set_caption("Block Placer")
    _init_display()
    # Open fullscreen by default so the screen is big and ready to play right
    # away. If the display can't go fullscreen, fall back to a large
    # resizable window so you can still play.
    try:
        screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.FULLSCREEN)
        fullscreen = True
    except Exception:
        try:
            screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
            fullscreen = False
        except Exception:
            screen = pygame.display.set_mode((WIDTH, HEIGHT))
            fullscreen = False
    clock = pygame.time.Clock()
    world = World(seed=1337)
    player = Player(world)
    start = time.time()
    hint_until = start + 8.0
    global player_global_x
    while True:
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if e.type == pygame.MOUSEWHEEL:
                # mouse wheel = look up / down (vertical aiming)
                player.pitch = max(-1.3, min(1.3, player.pitch - e.delta * 0.05))
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    pygame.quit()
                    sys.exit()
                if e.key == pygame.K_f:
                    player.first_person = not player.first_person
                if e.key == pygame.K_F11:
                    # Toggle between fullscreen and a large resizable window.
                    # (This build has pygame.FULLSCREEN and pygame.RESIZABLE
                    #  but not BORDERLESS/NORESIZE, so we only use those.)
                    if not fullscreen:
                        try:
                            screen = pygame.display.set_mode((WIDTH, HEIGHT),
                                                             pygame.FULLSCREEN)
                            fullscreen = True
                        except Exception:
                            try:
                                screen = pygame.display.set_mode((WIDTH, HEIGHT),
                                                                 pygame.RESIZABLE)
                                fullscreen = False
                            except Exception:
                                pass
                    else:
                        try:
                            screen = pygame.display.set_mode((WIDTH, HEIGHT),
                                                             pygame.RESIZABLE)
                            fullscreen = False
                        except Exception:
                            pass
                if e.key == pygame.K_r:
                    respawn(player)
                if e.key == pygame.K_e:
                    # E = grab the block you are looking at, or drop the
                    # selected block in front of you when nothing is in sight.
                    cam_e = make_camera(player, world)
                    hit = raycast(player, world, cam_e)
                    if hit is not None:
                        bx, by, bz, nx, ny, nz = hit
                        name = world.block(bx, by, bz)
                        if name is not None and name in PICKABLE:
                            world.set(bx, by, bz, None)
                            player.inventory[name] = player.inventory.get(name, 0) + 1
                            if name in BLOCKS:
                                player.selected = BLOCKS.index(name)
                            _complete_quests(player, world)
                        else:
                            place_block(player, world, cam_e)
                    else:
                        _place_at_crosshair(player, world, cam_e)
                if e.key == pygame.K_m:
                    player.selected = (player.selected + 1) % len(BLOCKS)
                if e.key == pygame.K_SPACE and player.vy < 2.0:
                    player.vy = JUMP_VY
                elif e.key in (pygame.K_0, pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4,
                               pygame.K_5, pygame.K_6, pygame.K_7, pygame.K_8, pygame.K_9):
                    idx = e.key - pygame.K_1
                    if 0 <= idx < len(BLOCKS):
                        player.selected = idx
        dt = clock.tick(FPS)
        if dt > 0.0:
            dt = min(dt, 0.05)
        # movement (WASD relative to camera yaw; arrow keys turn camera)
        keys = pygame.key.get_pressed()
        ffx = math.sin(player.yaw); ffz = -math.cos(player.yaw)
        vx = 0.0
        vz = 0.0
        if keys[pygame.K_w]:   # forward
            vx += 1.0
        if keys[pygame.K_s]:   # backward
            vx -= 1.0
        if keys[pygame.K_a]:   # left
            vz += 1.0
        if keys[pygame.K_d]:   # right
            vz -= 1.0
        wx = vx * ffx + vz * ffz
        wz = vx * ffz - vz * ffx
        player.x += wx * MOVE_SPEED * dt
        player.z += wz * MOVE_SPEED * dt
        # camera turn (arrow keys)
        if keys[pygame.K_LEFT] or keys[pygame.K_UP]:
            player.yaw += 0.9 * dt
        if keys[pygame.K_RIGHT] or keys[pygame.K_DOWN]:
            player.yaw -= 0.9 * dt
        # physics
        player.vy -= GRAVITY * dt
        old_y = player.y
        player.y += player.vy * dt
        ground_top = terrain_y_at(player.x, player.z)
        stand_h = 1.2
        if ground_top is None:
            if player.y < 0.0:
                player.y = 0.0
                player.vy = 0.0
        else:
            if player.y <= ground_top + 1.0 and player.vy <= 0.0:
                player.y = ground_top + stand_h
                if old_y < ground_top + stand_h + 0.3:
                    player.vy = 0.0
        if player.y < 0.0:
            player.y = 0.0
            player.vy = 0.0
        mouse_down = pygame.mouse.get_pressed()[2]
        cam = make_camera(player, world)
        update_mining(player, world, dt, cam, mouse_down)
        # level-up banner: show ~1.4s
        if player._level_up is not None:
            if not hasattr(player, "_lu_time"):
                player._lu_time = time.time()
            if time.time() - player._lu_time > 1.4:
                player._level_up = None
        # LMB place
        if pygame.mouse.get_pressed()[0]:
            place_block(player, world, cam)
        # RMB grab (single press handled in events? use held -> grab)
        if not mouse_down:
            pass
        draw(screen, world, player, cam)
        # help hint
        if not player.first_person and time.time() < hint_until:
            msg = ("WASD move · Space jump · E pick/place · HOLD RMB mine · "
                   "1-9 block · F cam · F11 window/fullscreen · ESC quit")
            t = text_surface(msg, 22, (255, 255, 255), None)
            surf = pygame.Surface((t.get_width(), t.get_height()), pygame.SRCALPHA)
            pygame.draw.rect(surf, (20, 24, 30, 180), (0, 0, t.get_width(), t.get_height()), border_radius=6)
            surf.blit(t, (6, 6))
            screen.blit(surf, (W2 - t.get_width()//2 - 6, HEIGHT - 70))
        pygame.display.flip()
    pygame.quit()


def _selftest():
    pygame.init()
    surf = pygame.Surface((WIDTH, HEIGHT))
    world = World(seed=1337)
    player = Player(world)
    player.x, player.y, player.z = 0.0, 5.5, 0.0
    player.yaw = 0.0
    player.first_person = False
    cam = make_camera(player, world)
    # exercise quad building
    quads = build_quads(world, cam)
    print(f"selftest: built {len(quads)} quads")
    # exercise the full draw pipeline (sky + clouds + quads + player + HUD)
    draw(surf, world, player, cam)
    pil = Image.frombytes("RGBA", surf.get_size(), surf.get_buffer()).convert("RGB")
    pil.save("/tmp/selftest_frame.png")
    print("selftest: frame saved to /tmp/selftest_frame.png", pil.size)
    # verify village/lighthouse are present in the world
    vb = world.block(10, 5, -10)      # house A interior/floor
    lh = world.block(28, 14, -20)     # lighthouse upper stone
    print("selftest: houseA(10,5,-10)=", vb, "lighthouse(28,14,-20)=", lh)
    print("selftest: ALL PASSED")
    pygame.quit()


def _frames(N, out):
    """Render N frames to an off-screen canvas (headless, no window)."""
    pygame.init()
    surf = pygame.Surface((WIDTH, HEIGHT))
    world = World(seed=1337)
    player = Player(world)
    player.yaw = 0.0
    for i in range(N):
        cam = make_camera(player, world)
        draw(surf, world, player, cam)
        pil = Image.frombytes("RGBA", surf.get_size(), surf.get_buffer())
        pil = pil.convert("RGB")
        pil.save(out)
        print(f"saved {out} ({pil.size})")
    pygame.quit()


if __name__ == "__main__":
    args = sys.argv[1:]
    if any("selftest" in a or "self-test" in a for a in args):
        _selftest()
    else:
        if any("frames" in a for a in args):
            i = args.index("--frames")
            N = int(args[i + 1])
            # output: either next token, or value after --out / -o
            j = i + 2
            if j < len(args) and args[j].startswith("--"):
                j += 1
            out = args[j] if j < len(args) else "frame.png"
            _frames(N, out)
        else:
            main()
