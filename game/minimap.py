"""Corner minimap: the whole level, north up, with

  * the player as an arrow plus a faint cone showing what you can see
    (the field of view, stopped by walls),
  * every zombie still standing - a filled red dot when it is hunting you,
    a hollow ring while it hasn't noticed you yet (brutes are bigger),
  * pickups lying on the floor - yellow = ammo, white = health.

Map right is world +x and map down is world +y, the same handedness as the
3D view: facing up the map, whatever is on your right on screen is on the
right of the arrow. The walls are drawn once per level into a cached
surface; each frame only the cone, the markers and the arrow are drawn.
"""
import math
import pygame

from .raycaster import FOV_DEG
from .world import ray_length
from .zombies import CHASE

MAX_W, MAX_H = 190, 140      # the map is scaled to fit this box (pixels)
MAX_TILE = 8
PAD = 4
CONE_TILES = 4.0
CONE_RAYS = 13
PANEL = (8, 10, 8, 205)
EDGE = (96, 96, 88)
# muted wall tones so the markers stand out; doors are just wall here (they
# don't open, and a different colour would read as an exit)
WALL = {1: (118, 86, 78), 2: (124, 124, 116), 3: (104, 112, 128),
        4: (118, 86, 78), 5: (90, 110, 84)}
WALL_DEFAULT = (130, 130, 120)
HUNTING = (245, 64, 48)
IDLE = (235, 120, 96)
AMMO = (235, 196, 60)
HEALTH = (240, 240, 240)
PLAYER = (255, 255, 255)
OUTLINE = (0, 0, 0)
CONE = (255, 236, 170, 72)


class Minimap:
    def __init__(self):
        self._grid = None
        self.tile = 0
        self.base = None
        self._cone = None

    def _build(self, grid):
        gh, gw = len(grid), len(grid[0])
        t = max(3, min(MAX_TILE, MAX_W // gw, MAX_H // gh))
        base = pygame.Surface((gw * t + 2 * PAD, gh * t + 2 * PAD), pygame.SRCALPHA)
        base.fill(PANEL)
        for y, row in enumerate(grid):
            for x, cell in enumerate(row):
                if cell:
                    base.fill(WALL.get(cell, WALL_DEFAULT), (PAD + x * t, PAD + y * t, t, t))
        pygame.draw.rect(base, EDGE, base.get_rect(), 1)
        # Holding the grid itself (not its id) means a new level's grid can
        # never be mistaken for the cached one.
        self._grid, self.tile, self.base = grid, t, base
        self._cone = pygame.Surface(base.get_size(), pygame.SRCALPHA)

    def size(self, grid):
        if grid is not self._grid:
            self._build(grid)
        return self.base.get_size()

    def to_map(self, x, y, topleft=(0, 0)):
        """Screen position of world point (x, y) on a map drawn at topleft."""
        return topleft[0] + PAD + x * self.tile, topleft[1] + PAD + y * self.tile

    def draw(self, screen, game, topleft):
        """Draw the map for `game` with its top-left corner at `topleft`.
        Returns the rect it covers."""
        if game.grid is not self._grid:
            self._build(game.grid)
        p, t = game.player, self.tile
        rect = pygame.Rect(topleft, self.base.get_size())
        screen.blit(self.base, rect)
        clip = screen.get_clip()
        screen.set_clip(rect.inflate(-2, -2))      # markers stay inside the frame

        # what you can see: the field of view, each ray stopped by walls
        # (own alpha layer so it tints the floor)
        cx, cy = PAD + p.x * t, PAD + p.y * t
        half = math.radians(FOV_DEG) / 2.0
        cone = [(cx, cy)]
        for i in range(CONE_RAYS):
            a = p.angle - half + i * (2.0 * half / (CONE_RAYS - 1))
            d = ray_length(game.grid, p.x, p.y, a, max_d=CONE_TILES) * t
            cone.append((cx + math.cos(a) * d, cy + math.sin(a) * d))
        self._cone.fill((0, 0, 0, 0))
        pygame.draw.polygon(self._cone, CONE, cone)
        screen.blit(self._cone, rect)

        for z in game.zombies:                      # pickups on corpses
            if z.pickup and not z.alive:
                mx, my = self.to_map(z.x, z.y, topleft)
                screen.fill(AMMO if z.pickup["kind"] == "ammo" else HEALTH,
                            (round(mx) - 2, round(my) - 2, 4, 4))
        for z in game.zombies:                      # zombies still standing
            if not z.alive:
                continue
            pos = tuple(round(v) for v in self.to_map(z.x, z.y, topleft))
            r = 4 if z.ztype == "brute" else 3
            if z.state == CHASE:
                pygame.draw.circle(screen, OUTLINE, pos, r + 1)
                pygame.draw.circle(screen, HUNTING, pos, r)
            else:
                pygame.draw.circle(screen, IDLE, pos, r, 1)

        px, py = self.to_map(p.x, p.y, topleft)    # the player, on top
        c, s = math.cos(p.angle), math.sin(p.angle)
        arrow = [(px + c * 7, py + s * 7),                    # tip
                 (px - c * 4 - s * 4.5, py - s * 4 + c * 4.5),  # back right
                 (px - c * 1.5, py - s * 1.5),                # notch
                 (px - c * 4 + s * 4.5, py - s * 4 - c * 4.5)]  # back left
        pygame.draw.polygon(screen, PLAYER, arrow)
        pygame.draw.polygon(screen, OUTLINE, arrow, 1)
        screen.set_clip(clip)
        return rect
