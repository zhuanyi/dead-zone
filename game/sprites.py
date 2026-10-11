"""Procedural zombie sprites: pixel-art billboards with animation frames.

Each type has two walk frames, an arms-raised attack frame (the wind-up
telegraph) and a corpse. Frames are pre-tinted for every fog step of the
current level (apply_fog) plus one white "hit flash" variant.

Chars: . transparent, G skin, D dark skin/cloth, E eye, H hand, L leg,
B brute hide, R torn red shirt, X blood.
"""
import pygame
from .textures import FOG_STEPS, fog_tint
from .levels import ZOMBIE_TYPES

PALETTE = {
    "G": (96, 128, 66), "D": (58, 84, 44), "E": (235, 40, 30),
    "H": (118, 148, 84), "L": (66, 74, 60), "B": (84, 100, 70),
    "R": (132, 44, 38), "X": (112, 12, 10),
}

# ---- walker (12 x 16) --------------------------------------------------
_W_UPPER = [
    "....GGGG....",
    "...GGGGGG...",
    "...GEGGEG...",
    "...GGGGGG...",
    "....GDDG....",
    "..DDGGGGDD..",
    ".HDDGGGGDDH.",
    ".H.DGGXGD.H.",
    "HH.DGGGGD.HH",
    "...DGGGGD...",
    "....DDDD....",
]
_W_ATTACK = [
    "H..........H",
    "HH..GGGG..HH",
    ".H.GGGGGG.H.",
    ".HDGEGGEGDH.",
    "..DGGGGGGD..",
    "...DGDDGD...",
    "...DGGGGD...",
    "...DGGXGD...",
    "...DGGGGD...",
    "...DGGGGD...",
    "....DDDD....",
]
_W_LEGS_A = [
    "....L..L....",
    "....L...L...",
    "....L...L...",
    "....L....L..",
    "...LL....LL.",
]
_W_LEGS_B = [
    "....L..L....",
    "...L...L....",
    "...L...L....",
    "..L....L....",
    ".LL....LL...",
]

# ---- runner (12 x 16): thin, red shirt, long stride --------------------
_R_UPPER = [
    "............",
    ".....GGG....",
    "....GEGEG...",
    "....GGGGG...",
    ".....GDG....",
    "...HRRRRH...",
    "..H.RRRR.H..",
    "..H.RXRR.H..",
    ".H..RRRR..H.",
    "....RRRR....",
    "....DDDD....",
]
_R_ATTACK = [
    ".H........H.",
    ".H...GGG..H.",
    "..H.GEGEG.H.",
    "..H.GGGGGH..",
    "...HHGDGH...",
    "....RRRR....",
    "....RRRR....",
    "....RXRR....",
    "....RRRR....",
    "....RRRR....",
    "....DDDD....",
]
_R_LEGS_A = [
    "....L..L....",
    "...L....L...",
    "..L.....L...",
    ".L.......L..",
    "LL.......LL.",
]
_R_LEGS_B = [
    "....L..L....",
    "....L..L....",
    "....L.L.....",
    "...L..L.....",
    "..LL..LL....",
]

# ---- brute (14 x 16): huge shoulders ----------------------------------
_B_UPPER = [
    "....BBBBBB....",
    "...BBBBBBBB...",
    "...BEBBBBEB...",
    "...BBBBBBBB...",
    "....BDDDDB....",
    ".BBBBBBBBBBBB.",
    "BBBBBBBBBBBBBB",
    "BB.BBBBBBBB.BB",
    "BB.BBBXBBBB.BB",
    "HH.BBBBBBBB.HH",
    "HH..BBBBBB..HH",
    "....LLLLLL....",
]
_B_ATTACK = [
    "HH..BBBBBB..HH",
    "BB.BBBBBBBB.BB",
    "BB.BEBBBBEB.BB",
    "BBBBBBBBBBBBBB",
    ".BB.BDDDDB.BB.",
    "...BBBBBBBB...",
    "...BBBBBBBB...",
    "...BBBBBBBB...",
    "...BBBXBBBB...",
    "...BBBBBBBB...",
    "....BBBBBB....",
    "....LLLLLL....",
]
_B_LEGS_A = [
    "....LL..LL....",
    "....LL...LL...",
    "...LLL...LL...",
    "...LLL...LLL..",
]
_B_LEGS_B = [
    "....LL..LL....",
    "...LL...LL....",
    "...LL...LLL...",
    "..LLL...LLL...",
]


def _corpse(c, w):
    rows = [
        "......XX....",
        "..XX" + c * 4 + "X...",
        ".D" + c * 3 + "E" + c * 3 + "DX.",
        "LLDD" + c * 4 + "DDLL",
        "XLLDDDDDDLLX",
    ]
    pad = (w - 12) // 2
    return ["." * pad + r + "." * (w - 12 - pad) for r in rows]


def _frames(upper, attack, legs_a, legs_b, body_char, w):
    return {"walk0": upper + legs_a, "walk1": upper + legs_b,
            "attack": attack + legs_a, "corpse": _corpse(body_char, w)}


ART = {
    "walker": _frames(_W_UPPER, _W_ATTACK, _W_LEGS_A, _W_LEGS_B, "G", 12),
    "runner": _frames(_R_UPPER, _R_ATTACK, _R_LEGS_A, _R_LEGS_B, "R", 12),
    "brute": _frames(_B_UPPER, _B_ATTACK, _B_LEGS_A, _B_LEGS_B, "B", 14),
}


def _art(rows):
    w = len(rows[0])
    assert all(len(r) == w for r in rows), "ragged sprite rows"
    s = pygame.Surface((w, len(rows)), pygame.SRCALPHA)
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch != ".":
                s.set_at((x, y), PALETTE[ch] + (255,))
    return s


def _flash(surf):
    out = surf.copy()
    out.fill((150, 150, 150), special_flags=pygame.BLEND_RGB_ADD)
    return out


class ZombieSprite:
    """Animation frames for one zombie type. `scale` is the drawn height
    in wall units; width follows the art's own aspect ratio."""

    FRAMES = ("walk0", "walk1", "attack", "corpse")

    def __init__(self, frames, scale):
        self.art = {k: _art(v) for k, v in frames.items()}
        self.flash_art = {k: _flash(s) for k, s in self.art.items()}
        self.scale = scale
        self._fog_color = None
        self.fogged = {}
        self.apply_fog((0, 0, 0))

    def apply_fog(self, color):
        """Rebuild the fog-tinted frames for a level's fog colour."""
        color = tuple(color)
        if color == self._fog_color:
            return
        self._fog_color = color
        self.fogged = {k: [fog_tint(s, i, color) for i in range(FOG_STEPS)]
                       for k, s in self.art.items()}

    def surface(self, frame, fog_i=0, flash=False):
        if flash:
            return self.flash_art[frame]
        return self.fogged[frame][max(0, min(FOG_STEPS - 1, fog_i))]


def build_zombie_sprites():
    return [ZombieSprite(ART[t], ZOMBIE_TYPES[t]["height"])
            for t in ("walker", "runner", "brute")]
