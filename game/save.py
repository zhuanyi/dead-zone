"""Save / load: 3 JSON slots under <datadir>/saves/ (default
~/.deadzone/saves; override the root with the DEADZONE_HOME env var).

A slot captures the level, the player (including the stats they entered
the level with, so "retry" still works after loading) and every zombie's
state. Version-2 saves from earlier builds still load.
"""
import json
import os
from numbers import Real

from .levels import LEVELS, parse_level
from .game import Game
from .zombies import CHASE, IDLE

SLOTS = 3
VERSION = 3
READABLE = (2, 3)

_PLAYER_REQ = ("x", "y", "angle", "hp", "ammo", "reserved", "score")
_ZOMBIE_REQ = ("x", "y", "hp")


def _num(v):
    return isinstance(v, Real) and not isinstance(v, bool)


class SaveManager:
    def __init__(self, dirpath):
        self.dir = dirpath
        os.makedirs(dirpath, exist_ok=True)

    def _path(self, slot):
        return os.path.join(self.dir, f"slot{slot}.json")

    def exists(self, slot):
        return os.path.exists(self._path(slot))

    def _read(self, slot):
        """Return the validated dict, or None if missing/corrupt/foreign."""
        if not self.exists(slot):
            return None
        try:
            with open(self._path(slot), "r", encoding="utf-8") as f:
                d = json.load(f)
            if not isinstance(d, dict) or d.get("version") not in READABLE:
                return None
            lvl = d["level"]
            if not isinstance(lvl, int) or isinstance(lvl, bool) \
                    or not 0 <= lvl < len(LEVELS):
                return None
            p = d["player"]
            if not all(_num(p[k]) for k in _PLAYER_REQ):
                return None
            zs = d["zombies"]
            _, spawns = parse_level(lvl)
            if not isinstance(zs, list) or len(zs) != len(spawns["zombies"]):
                return None        # map changed since the save was made
            for zd in zs:
                if not all(_num(zd[k]) for k in _ZOMBIE_REQ):
                    return None
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            return None
        return d

    def info(self, slot):
        """Summary dict for the slot list, {"corrupt": True} for an
        unreadable file, or None if the slot is empty."""
        if not self.exists(slot):
            return None
        d = self._read(slot)
        if d is None:
            return {"corrupt": True}
        p = d["player"]
        return {"level_name": LEVELS[d["level"]]["name"],
                "score": int(p["score"]),
                "kills": int(p.get("kills", d.get("kills", 0))),
                "hp": int(p["hp"]), "time": float(d.get("time", 0.0))}

    def delete(self, slot):
        if self.exists(slot):
            os.remove(self._path(slot))

    def save(self, slot, game):
        p = game.player
        data = {
            "version": VERSION,
            "level": game.level_idx,
            "level_name": game.level["name"],
            "time": game.time,
            "entry": game.entry,
            "player": dict(p.stats(), x=p.x, y=p.y, angle=p.angle,
                           reload_t=p.reload_t, shoot_cd=p.shoot_cd),
            "zombies": [{"x": z.x, "y": z.y, "ztype": z.ztype, "hp": z.hp,
                         "alive": z.alive, "state": z.state, "pickup": z.pickup,
                         "attack_cd": z.attack_cd, "windup": z.windup,
                         "dying": z.dying} for z in game.zombies],
        }
        tmp = self._path(slot) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, self._path(slot))     # never leaves a half-written slot
        return data

    def load(self, slot):
        """Return a validated state dict, or None if missing/corrupt."""
        return self._read(slot)

    def restore(self, d, sprites):
        """Build a fresh Game from a load() dict."""
        game = Game(d["level"], sprites, carry=d.get("entry"))
        self.apply(d, game)
        return game

    def apply(self, d, game):
        """Overwrite a Game's state with a load() dict."""
        p, player = d["player"], game.player
        player.load_stats({k: p[k] for k in p if k in player.stats()})
        player.x, player.y, player.angle = p["x"], p["y"], p["angle"]
        if "kills" not in p:                  # version 2 kept kills top-level
            player.kills = d.get("kills", 0)
        player.reload_t = p.get("reload_t", 0.0)
        player.shoot_cd = p.get("shoot_cd", 0.0)
        game.time = d.get("time", 0.0)
        if d.get("entry"):
            game.entry = dict(d["entry"])
        old = d.get("version") == 2
        for z, zd in zip(game.zombies, d["zombies"]):
            z.x, z.y, z.hp = zd["x"], zd["y"], zd["hp"]
            z.alive = bool(zd.get("alive", z.hp > 0))
            # version-2 zombies were always chasing
            z.state = CHASE if old else (CHASE if zd.get("state") == CHASE else IDLE)
            z.pickup = zd.get("pickup")
            z.attack_cd = zd.get("attack_cd", 0.0)
            z.windup = zd.get("windup", 0.0) if z.alive else 0.0
            z.dying = zd.get("dying", 0.0)
        game._flow_tile = None
        game.refresh_flow()
