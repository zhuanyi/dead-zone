"""Zombie entity + AI.

A zombie starts IDLE and only joins the hunt (CHASE) when it notices the
player: line of sight within SIGHT_RANGE, the player brushing past within
NOTICE_RANGE, a gunshot it can hear (see game.Game.make_noise), or a
nearby zombie joining in. Chasers follow the level's flow field (BFS path
distance to the player) round corners, and steer straight at the player
when the way is clear.

Attacks are telegraphed: in range, the zombie raises its arms for its
type's wind-up time, and the blow only lands if the player is still within
ATTACK_REACH - so backing off at the right moment dodges it.
"""
import math
import random
from .levels import ZOMBIE_TYPES
from .world import body_clear, segment_clear, flow_step, slide_move

IDLE, CHASE = "idle", "chase"
RADIUS = 0.25
SIGHT_RANGE = 8.0
NOTICE_RANGE = 2.5
DIRECT_RANGE = 6.0      # steer straight at the player if the way is clear
ATTACK_RANGE = 0.65     # start the wind-up
ATTACK_REACH = 0.9      # player must still be this close when the blow lands
ATTACK_CD = 1.0
DEATH_TIME = 0.45
FLASH_TIME = 0.12
SEPARATION = 0.6


def _emit(events, name, z):
    if events is not None:
        events.append((name, z))


class Zombie:
    def __init__(self, x, y, ztype, sprite, rng=None, state=IDLE):
        t = ZOMBIE_TYPES[ztype]
        self.x, self.y = float(x), float(y)
        self.ztype = ztype
        self.hp = t["hp"]
        self.speed = t["speed"]
        self.damage = t["damage"]
        self.score = t["score"]
        self.radius = t["radius"]
        self.windup_time = t["windup"]
        self.sprite = sprite
        self.alive = True
        self.state = state
        self.flash = 0.0
        self.pickup = None
        self.attack_cd = 0.0
        self.windup = 0.0
        self.dying = 0.0
        self.walk = 0.0
        self._rng = rng or random.Random()
        self._look_t = self._rng.uniform(0.0, 0.25)
        self.groan_t = self._rng.uniform(1.5, 5.0)

    # ---------- state ----------
    def alert(self):
        """Join the hunt. Returns True if the zombie was idle."""
        if self.alive and self.state != CHASE:
            self.state = CHASE
            return True
        return False

    def hurt(self, dmg):
        """Apply damage. Returns True if this killed the zombie."""
        if not self.alive:
            return False
        self.hp -= dmg
        self.flash = FLASH_TIME
        self.alert()
        if self.hp <= 0:
            self.alive = False
            self.windup = 0.0
            self.dying = DEATH_TIME
            return True
        return False

    def frame(self):
        if self.windup > 0:
            return "attack"
        return "walk1" if int(self.walk * 3.0) % 2 else "walk0"

    # ---------- per-frame ----------
    def update(self, dt, player, grid, zombies, flow=None, events=None):
        """Advance one tick. Returns "windup", "hit", "miss" or None."""
        self.flash = max(0.0, self.flash - dt)
        if self.dying > 0:
            self.dying = max(0.0, self.dying - dt)
        if not self.alive:
            return None
        self.attack_cd = max(0.0, self.attack_cd - dt)
        dx, dy = player.x - self.x, player.y - self.y
        dist = math.hypot(dx, dy)

        if self.state == IDLE:
            self._look_t -= dt
            if self._look_t <= 0:
                self._look_t = 0.25
                if dist < NOTICE_RANGE or (
                        dist < SIGHT_RANGE
                        and segment_clear(self.x, self.y, player.x, player.y, grid)):
                    self.alert()
                    _emit(events, "alert", self)
            return None

        self.groan_t -= dt
        if self.groan_t <= 0:
            self.groan_t = self._rng.uniform(3.0, 7.0)
            _emit(events, "groan", self)

        if self.windup > 0:
            self.windup -= dt
            if self.windup > 0:
                return None
            self.windup = 0.0
            self.attack_cd = ATTACK_CD
            if dist < ATTACK_REACH:
                player.take_hit(self.damage, self.x, self.y)
                _emit(events, "hurt", None)
                return "hit"
            return "miss"

        if dist < ATTACK_RANGE:
            if self.attack_cd <= 0:
                self.windup = self.windup_time
                _emit(events, "swipe", self)
                return "windup"
            return None

        self._step(dt, player, grid, zombies, flow, dist)
        return None

    def _step(self, dt, player, grid, zombies, flow, dist):
        px, py = player.x, player.y
        if (int(self.x), int(self.y)) == (int(px), int(py)) or (
                dist < DIRECT_RANGE and body_clear(self.x, self.y, px, py, grid)):
            tx, ty = px, py
        else:
            nxt = flow_step(flow, grid, self.x, self.y) if flow else None
            tx, ty = nxt if nxt else (px, py)
        ux, uy = tx - self.x, ty - self.y
        m = math.hypot(ux, uy) or 1.0
        ux, uy = ux / m, uy / m
        # a little shamble so a crowd doesn't move in lockstep
        ang = self._rng.uniform(-0.15, 0.15)
        ca, sa = math.cos(ang), math.sin(ang)
        mx, my = ux * ca - uy * sa, uy * ca + ux * sa
        for o in zombies:                      # separation
            if o is self or not o.alive:
                continue
            ox, oy = self.x - o.x, self.y - o.y
            d2 = ox * ox + oy * oy
            if 0 < d2 < SEPARATION * SEPARATION:
                d = d2 ** 0.5
                mx += ox / d * (SEPARATION - d)
                my += oy / d * (SEPARATION - d)
        m = math.hypot(mx, my) or 1.0
        step = self.speed * dt
        x0, y0 = self.x, self.y
        self._try_move(self.x + mx / m * step, self.y + my / m * step, grid)
        self.walk += math.hypot(self.x - x0, self.y - y0)

    def _try_move(self, nx, ny, grid):
        self.x, self.y = slide_move(self.x, self.y, nx, ny, RADIUS, grid)
