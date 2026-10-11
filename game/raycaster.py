"""DDA raycaster: walls, a pre-baked floor/ceiling backdrop, and billboards
(zombies, corpses, pickups).

Everything is projected with ONE focal length, derived from the horizontal
field of view, so the buffer has square pixels: scaling it uniformly to the
window keeps walls square and sprites in their drawn proportions.

Fog blends toward each level's fog colour via pre-tinted texture variants
(16 steps). The floor/ceiling backdrop bakes distance shading and fog per
screen row (the true distance of that row), so it costs one blit a frame.
Pure pygame surfaces, no numpy.
"""
import math
import pygame
from .textures import FOG_STEPS, TEX, fog_tint, build_wall_textures
from .zombies import DEATH_TIME

FOV_DEG = 80.0
TAN_HALF = math.tan(math.radians(FOV_DEG) / 2.0)
EYE = 0.5                 # camera height; walls are 1.0 tall
Z_NEAR = 0.02
MIN_SPRITE_DEPTH = 0.3    # nearer billboards are drawn at this size
PICKUP_H = 0.22
CORPSE_H = 0.26
_INF = 1e30

_PICKUP_ART = {}


def focal_length(w):
    """Pixels per wall unit at distance 1 (same horizontally and vertically)."""
    return (w / 2.0) / TAN_HALF


def fog_index(dist, density):
    f = max(0.05, 1.0 - dist * density)
    return min(FOG_STEPS - 1, max(0, int((1.0 - f) * FOG_STEPS)))


def project(player, x, y, w):
    """(depth, screen_x) of a world point, or None if behind the camera."""
    c, s = math.cos(player.angle), math.sin(player.angle)
    dx, dy = x - player.x, y - player.y
    depth = dx * c + dy * s                  # forward
    if depth <= Z_NEAR:
        return None
    lat = -dx * s + dy * c                   # right
    return depth, w / 2.0 + lat / depth * focal_length(w)


def _pickup_art(kind):
    if kind not in _PICKUP_ART:
        s = pygame.Surface((12, 12), pygame.SRCALPHA)
        if kind == "ammo":
            s.fill((60, 60, 40), (0, 2, 12, 9))
            s.fill((225, 185, 45), (1, 3, 10, 7))
            s.fill((120, 90, 20), (3, 5, 6, 3))
        else:  # health: red cross on white
            s.fill((235, 235, 235), (1, 1, 10, 10))
            s.fill((210, 40, 40), (4, 2, 4, 8))
            s.fill((210, 40, 40), (2, 4, 8, 4))
        _PICKUP_ART[kind] = s
    return _PICKUP_ART[kind]


def _shaded(surf, k):
    out = surf.copy()
    out.fill((int(255 * k),) * 3, special_flags=pygame.BLEND_RGB_MULT)
    return out


class Textures:
    """Fog-tinted wall variants (x-facing and darker y-facing sides) plus
    the level's floor/ceiling backdrop."""

    def __init__(self, level=None, w=640, h=400):
        self.base = build_wall_textures()
        self.level = {}
        self.walls = None
        self.background = None
        self.apply_level(level or {}, w, h)

    def apply_level(self, level, w=640, h=400):
        self.level = level
        self.fog_density = level.get("fog", 0.03)
        self.fog_color = tuple(level.get("fog_color", (0, 0, 0)))
        c = self.fog_color
        self.walls = [None if t is None else
                      ([fog_tint(t, i, c) for i in range(FOG_STEPS)],
                       [fog_tint(_shaded(t, 0.72), i, c) for i in range(FOG_STEPS)])
                      for t in self.base]
        self.build_background(w, h)

    def build_background(self, w, h):
        floor = self.level.get("floor", (82, 78, 70))
        ceil = self.level.get("ceiling", (56, 58, 62))
        fogc = self.fog_color
        hor = h // 2
        focal = focal_length(w)
        surf = pygame.Surface((w, h))
        for y in range(h):
            if y < hor:   # ceiling (1.0 - EYE above the eye)
                d, base = focal * (1.0 - EYE) / (hor - y - 0.5), ceil
            else:         # floor (EYE below the eye)
                d, base = focal * EYE / (y - hor + 0.5), floor
            shade = 1.0 / (1.0 + 0.10 * d)
            f = max(0.05, 1.0 - d * self.fog_density)
            col = tuple(min(255, int(b * shade * f + fc * (1.0 - f)))
                        for b, fc in zip(base, fogc))
            surf.fill(col, (0, y, w, 1))
        self.background = surf


def cast_rays(player, grid, w):
    """Per screen column: (perp_dist, wall_id, tex_x in [0,1), side)."""
    c, s = math.cos(player.angle), math.sin(player.angle)
    plane_x, plane_y = -s * TAN_HALF, c * TAN_HALF
    gh, gw = len(grid), len(grid[0])
    px, py = player.x, player.y
    cols = []
    for x in range(w):
        cam = 2.0 * (x + 0.5) / w - 1.0
        rx, ry = c + plane_x * cam, s + plane_y * cam
        map_x, map_y = int(px), int(py)
        delta_x = _INF if rx == 0 else abs(1.0 / rx)
        delta_y = _INF if ry == 0 else abs(1.0 / ry)
        if rx < 0:
            step_x, side_x = -1, (px - map_x) * delta_x
        else:
            step_x, side_x = 1, (map_x + 1.0 - px) * delta_x
        if ry < 0:
            step_y, side_y = -1, (py - map_y) * delta_y
        else:
            step_y, side_y = 1, (map_y + 1.0 - py) * delta_y
        side, wall_id = 0, 0
        for _ in range(256):
            if side_x < side_y:
                side_x += delta_x
                map_x += step_x
                side = 0
            else:
                side_y += delta_y
                map_y += step_y
                side = 1
            if not (0 <= map_y < gh and 0 <= map_x < gw):
                break
            cell = grid[map_y][map_x]
            if cell > 0:
                wall_id = cell
                break
        if wall_id == 0:
            # No wall (ray left the map): infinite distance, so the map edge
            # never occludes sprites.
            cols.append((_INF, 0, 0.0, side))
            continue
        # (rx, ry) is not normalised, so this is already the perpendicular
        # (fisheye-free) distance.
        perp = (side_x - delta_x) if side == 0 else (side_y - delta_y)
        hit = py + perp * ry if side == 0 else px + perp * rx
        cols.append((max(perp, Z_NEAR), wall_id, hit - math.floor(hit), side))
    return cols


def render_world(buf, player, grid, tex, zombies, w, h):
    """Draw backdrop, walls, then corpses/zombies/pickups into buf.
    Returns the per-column wall data."""
    if tex.background is None or tex.background.get_size() != (w, h):
        tex.build_background(w, h)
    cols = cast_rays(player, grid, w)
    buf.blit(tex.background, (0, 0))
    focal = focal_length(w)
    hor = h // 2
    for x in range(w):
        dist, wall_id, wall_x, side = cols[x]
        if wall_id == 0:
            continue
        line_h = min(int(focal / dist), h * 4)
        if line_h < 1:
            continue
        v = tex.walls[wall_id][side][fog_index(dist, tex.fog_density)]
        tex_x = int(wall_x * TEX) % TEX
        strip = pygame.transform.scale(v.subsurface(tex_x, 0, 1, TEX), (1, line_h))
        buf.blit(strip, (x, hor - (line_h >> 1)))
    _draw_billboards(buf, player, zombies, w, h, cols, tex)
    return cols


def blit_billboard(buf, art, sx, depth, world_h, w, h, cols, squash=1.0):
    """Draw `art` standing on the floor at (screen x, depth), world_h wall
    units tall, keeping the art's aspect ratio and clipping per column
    against nearer walls. Only a narrow (art-width) strip is scaled, so a
    sprite in your face costs no more than one far away."""
    full = focal_length(w) / max(depth, MIN_SPRITE_DEPTH)
    aw, ah = art.get_size()
    height = int(full * world_h * squash)
    width = int(full * world_h * aw / ah)
    if height < 1 or width < 1:
        return
    feet = h // 2 + int(full * EYE)
    top = feet - height
    x0 = int(sx - width / 2.0)
    xs, xe = max(0, x0), min(w, x0 + width)
    if xs >= xe or top >= h or feet <= 0:
        return
    strip = pygame.transform.scale(art, (aw, height))
    for x in range(xs, xe):
        if depth >= cols[x][0]:              # a wall is nearer
            continue
        buf.blit(strip, (x, top), ((x - x0) * aw // width, 0, 1, height))


def _draw_billboards(buf, player, zombies, w, h, cols, tex):
    entries = []
    for z in zombies:
        pr = project(player, z.x, z.y, w)
        if pr is not None:
            entries.append((pr[0], pr[1], z))
    entries.sort(key=lambda e: -e[0])        # far to near
    for depth, sx, z in entries:
        spr = z.sprite
        if spr is not None:
            f_i = fog_index(depth, tex.fog_density)
            if z.alive:
                art = spr.surface(z.frame(), f_i, flash=z.flash > 0)
                blit_billboard(buf, art, sx, depth, spr.scale, w, h, cols)
            elif z.dying > 0:                # collapse: sink toward the floor
                k = z.dying / DEATH_TIME
                art = spr.surface("walk0", f_i, flash=k > 0.7)
                blit_billboard(buf, art, sx, depth, spr.scale, w, h, cols,
                               squash=0.15 + 0.85 * k)
            else:
                art = spr.surface("corpse", f_i)
                blit_billboard(buf, art, sx, depth, CORPSE_H * spr.scale, w, h, cols)
        if z.pickup and not z.alive:
            blit_billboard(buf, _pickup_art(z.pickup["kind"]), sx, depth - 0.02,
                           PICKUP_H, w, h, cols)
