"""Procedural textures (32x32) - no external image assets needed.

Wall textures: 1=brick, 2=concrete pillar, 3=metal, 4=door, 5=sewer stone.
Floors and ceilings are smooth per-level gradients (see raycaster.Textures).
Zombie sprites are built in sprites.py.
"""
import math
import pygame

TEX = 32
FOG_STEPS = 16


def _noise(x, y, seed=1):
    n = math.sin(x * 127.1 + y * 311.7 + seed * 74.7) * 43758.5453
    return n - math.floor(n)


def _shade(color, f):
    return tuple(max(0, min(255, int(c * f))) for c in color)


def fog_factor(i):
    """Fraction of the original colour kept at fog step i (1.0 = clear)."""
    return max(0.10, 1.0 - i / FOG_STEPS * 0.9)


def fog_tint(surf, i, color=(0, 0, 0)):
    """Copy of surf blended toward the fog colour for fog step i. Alpha is
    untouched, so transparent sprite pixels stay transparent."""
    f = fog_factor(i)
    out = surf.copy()
    if f < 1.0:
        out.fill((int(255 * f),) * 3, special_flags=pygame.BLEND_RGB_MULT)
        add = tuple(int(c * (1.0 - f)) for c in color)
        if any(add):
            out.fill(add, special_flags=pygame.BLEND_RGB_ADD)
    return out


def brick_texture():
    img = pygame.Surface((TEX, TEX), pygame.SRCALPHA)
    base = (128, 46, 38)
    for y in range(TEX):
        row = y // 8
        for x in range(TEX):
            off = 4 if row % 2 else 0
            bx = (x + off) % 16
            if (y % 8 == 0) or (bx == 0):
                img.set_at((x, y), (58, 52, 48, 255))
            else:
                f = 0.85 + 0.3 * _noise(x, y, seed=3)
                img.set_at((x, y), _shade(base, f) + (255,))
    return img


def concrete_texture():
    img = pygame.Surface((TEX, TEX), pygame.SRCALPHA)
    for y in range(TEX):
        for x in range(TEX):
            c = _shade((120, 120, 112), 0.75 + 0.5 * _noise(x, y, seed=9))
            if x < 3 or x >= TEX - 3:          # darker pillar edges
                c = _shade(c, 0.6)
            img.set_at((x, y), c + (255,))
    return img


def metal_texture():
    img = pygame.Surface((TEX, TEX), pygame.SRCALPHA)
    for y in range(TEX):
        for x in range(TEX):
            f = 0.8 + 0.25 * math.sin(x * 0.6) + 0.1 * _noise(x, y, seed=5)
            c = _shade((96, 104, 118), f)
            if y % 8 == 0:                     # panel seams
                c = _shade(c, 0.5)
            if x % 8 == 4 and y % 8 == 3:      # rivets
                c = (190, 196, 205)
            img.set_at((x, y), c + (255,))
    return img


def door_texture():
    img = pygame.Surface((TEX, TEX), pygame.SRCALPHA)
    for y in range(TEX):
        for x in range(TEX):
            c = _shade((104, 78, 52), 0.7 + 0.4 * _noise(x, y, seed=11))
            if 2 <= x <= 5 or 26 <= x <= 29:   # frame
                c = _shade(c, 1.25)
            if x in (1, 30) or y in (1, 30):
                c = (40, 30, 22)
            if 22 <= x <= 24 and 15 <= y <= 17:  # handle
                c = (200, 176, 90)
            img.set_at((x, y), c + (255,))
    return img


def sewer_texture():
    """Big mossy stone blocks with slime running down from the top."""
    img = pygame.Surface((TEX, TEX), pygame.SRCALPHA)
    for y in range(TEX):
        row = y // 10
        for x in range(TEX):
            bx = (x + (8 if row % 2 else 0)) % 16
            if y % 10 == 0 or bx == 0:
                c = (30, 34, 28)
            else:
                c = _shade((70, 78, 66), 0.75 + 0.35 * _noise(x, y, seed=21))
                drip = _noise(x, 0, seed=33)
                if drip > 0.72 and y < 6 + int(drip * 30) % 22:
                    c = _shade((58, 104, 44), 0.8 + 0.3 * _noise(x, y, seed=7))
            img.set_at((x, y), c + (255,))
    return img


def build_wall_textures():
    return [None, brick_texture(), concrete_texture(), metal_texture(),
            door_texture(), sewer_texture()]
