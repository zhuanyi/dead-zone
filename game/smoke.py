"""Headless smoke test (python main.py --smoke): render every level,
simulate 10 seconds of shooting, and check a save/load roundtrip."""
import tempfile
import pygame

from .levels import LEVELS
from .game import Game
from .raycaster import Textures, render_world
from .save import SaveManager


def run(sprites, w=640, h=400):
    buf = pygame.Surface((w, h))
    with tempfile.TemporaryDirectory() as td:
        sm = SaveManager(td)
        for i, lvl in enumerate(LEVELS):
            g = Game(i, sprites, rng=42)
            tex = Textures(lvl, w, h)
            render_world(buf, g.player, g.grid, tex, g.zombies, w, h)
            inp = {}
            for f in range(600):
                inp["shoot"] = f % 20 < 3
                g.update(1 / 60, inp)
                if g.player.dead:
                    break
            render_world(buf, g.player, g.grid, tex, g.zombies, w, h)
            g.player.reload_t = 0.4
            sm.save(0, g)
            d = sm.load(0)
            assert d is not None, "save did not validate"
            g2 = sm.restore(d, sprites)
            p, p2 = g.player, g2.player
            assert (p2.x, p2.y, p2.angle, p2.hp, p2.ammo, p2.score) == \
                   (p.x, p.y, p.angle, p.hp, p.ammo, p.score), "player not restored"
            assert p2.reload_t == 0.4, "reload timer not restored"
            for z, z2 in zip(g.zombies, g2.zombies):
                assert (z2.x, z2.y, z2.hp, z2.alive, z2.state) == \
                       (z.x, z.y, z.hp, z.alive, z.state), "zombie not restored"
            print(f"smoke: level {i + 1} OK ({len(g.zombies)} zombies, "
                  f"{p.kills} killed in 10 s, hp {p.hp})")
    print("smoke: all levels passed")
