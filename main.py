#!/usr/bin/env python3
"""Dead Zone - a retro first-person zombie shooter.

Run:  python main.py            (normal game)
      python main.py --smoke     (headless smoke test, no window)

Data (saves, key binds, best score) lives in ~/.deadzone by default.
Override with the DEADZONE_HOME environment variable.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    if "--smoke" in sys.argv:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    import pygame
    from game.engine import Engine, W, H
    if "--smoke" in sys.argv:
        from game import smoke
        from game.sprites import build_zombie_sprites
        pygame.display.init()
        pygame.display.set_mode((W, H))
        smoke.run(build_zombie_sprites())
        return 0
    datadir = os.environ.get("DEADZONE_HOME",
                             os.path.join(os.path.expanduser("~"), ".deadzone"))
    Engine(datadir).run()
    pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
