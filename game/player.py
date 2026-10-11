"""Player: movement (zombies body-block), hitscan shooting, reload, pickups."""
import math
from .world import segment_clear, slide_move

MOVE_SPEED = 3.2
SPRINT_MULT = 1.5
ROT_SPEED = 2.4
TURN_SENS = 0.0026        # radians per mouse pixel at sensitivity 1.0
RADIUS = 0.25
BODY_GAP = 0.5            # closest the player gets to a live zombie
PICKUP_RADIUS = 0.5
MAX_AMMO = 30
START_RESERVE = 45
AMMO_PICKUP = 10
HEALTH_PICKUP = 25
FIRE_INTERVAL = 0.16
RELOAD_TIME = 1.0
SHOT_RANGE = 16.0
STAT_KEYS = ("hp", "ammo", "reserved", "score", "kills", "shots", "hits")


class Player:
    def __init__(self, x, y, angle=0.0):
        self.x, self.y = float(x), float(y)
        self.angle = angle
        self.hp = 100
        self.max_hp = 100
        self.ammo = MAX_AMMO
        self.max_ammo = MAX_AMMO
        self.reserved = START_RESERVE
        self.score = 0
        self.kills = 0
        self.shots = 0
        self.hits = 0
        self.reload_t = 0.0
        self.shoot_cd = 0.0
        # feedback timers (HUD / gun view model)
        self.hurt_flash = 0.0
        self.hurt_dir = 0.0       # attacker bearing relative to facing
        self.hurt_dir_t = 0.0
        self.muzzle = 0.0
        self.kick = 0.0
        self.hit_marker = 0.0
        self.kill_marker = 0.0
        self.walk = 0.0           # distance walked (head/gun bob phase)
        self.bob = 0.0            # 0..1 bob strength, eases with movement

    @property
    def dead(self):
        return self.hp <= 0

    def stats(self):
        """The part of the player that carries between levels."""
        return {k: getattr(self, k) for k in STAT_KEYS}

    def load_stats(self, stats):
        for k in STAT_KEYS:
            if k in stats:
                setattr(self, k, stats[k])

    # ---------- movement ----------
    def turn(self, dt, mouse_dx, keys, sens=1.0):
        self.angle += mouse_dx * TURN_SENS * sens
        if keys.get("turn_l"):
            self.angle -= ROT_SPEED * dt
        if keys.get("turn_r"):
            self.angle += ROT_SPEED * dt
        self.angle %= 2 * math.pi

    def move(self, dt, keys, grid, zombies=()):
        f = (1 if keys.get("fwd") else 0) - (1 if keys.get("back") else 0)
        s = (1 if keys.get("strafe_r") else 0) - (1 if keys.get("strafe_l") else 0)
        moving = bool(f or s)
        self.bob += ((1.0 if moving else 0.0) - self.bob) * min(1.0, dt * 8.0)
        if not moving:
            return
        speed = MOVE_SPEED * (SPRINT_MULT if keys.get("sprint") else 1.0)
        ca, sa = math.cos(self.angle), math.sin(self.angle)
        mx = ca * f - sa * s
        my = sa * f + ca * s
        m = math.hypot(mx, my) or 1.0
        step = speed * dt
        x0, y0 = self.x, self.y
        self._try_move(self.x + mx / m * step, self.y + my / m * step, grid, zombies)
        self.walk += math.hypot(self.x - x0, self.y - y0)

    def _try_move(self, nx, ny, grid, zombies=()):
        if self._bumps(nx, self.y, zombies):
            nx = self.x
        x, _ = slide_move(self.x, self.y, nx, self.y, RADIUS, grid)
        self.x = x
        if self._bumps(self.x, ny, zombies):
            ny = self.y
        _, self.y = slide_move(self.x, self.y, self.x, ny, RADIUS, grid)

    def _bumps(self, x, y, zombies):
        """True if moving to (x, y) pushes into a live zombie. Moving away
        is always allowed, so you can never get stuck inside one."""
        gap2 = BODY_GAP * BODY_GAP
        for z in zombies:
            if not z.alive:
                continue
            nd2 = (z.x - x) ** 2 + (z.y - y) ** 2
            if nd2 < gap2 and nd2 < (z.x - self.x) ** 2 + (z.y - self.y) ** 2:
                return True
        return False

    # ---------- combat ----------
    def take_hit(self, dmg, sx=None, sy=None):
        self.hp -= dmg
        self.hurt_flash = 0.35
        if sx is not None:
            rel = math.atan2(sy - self.y, sx - self.x) - self.angle
            self.hurt_dir = (rel + math.pi) % (2 * math.pi) - math.pi
            self.hurt_dir_t = 0.8

    def start_reload(self):
        if self.reload_t > 0 or self.ammo >= self.max_ammo or self.reserved <= 0:
            return False
        self.reload_t = RELOAD_TIME
        return True

    def try_shoot(self, zombies, grid):
        """Fire one hitscan shot along the view direction.

        A zombie is hit if the shot passes within its body radius; the
        nearest such zombie along the ray takes the bullet, provided no wall
        is in front of it. Returns (result, zombie): result is "kill",
        "hit", "miss", "empty" (dry fire) or None (can't fire yet)."""
        if self.shoot_cd > 0 or self.reload_t > 0:
            return None, None
        if self.ammo <= 0:
            if self.reserved <= 0:
                self.shoot_cd = 0.3
                return "empty", None
            return None, None
        self.ammo -= 1
        self.shots += 1
        self.shoot_cd = FIRE_INTERVAL
        self.muzzle = 0.06
        self.kick = 1.0
        c, s = math.cos(self.angle), math.sin(self.angle)
        best, best_t = None, SHOT_RANGE
        for z in zombies:
            if not z.alive:
                continue
            dx, dy = z.x - self.x, z.y - self.y
            t = dx * c + dy * s                    # distance along the ray
            if t <= 0 or t >= best_t:
                continue
            if abs(-dx * s + dy * c) > z.radius:   # passes beside it
                continue
            if not segment_clear(self.x, self.y, self.x + c * t, self.y + s * t, grid):
                continue
            best, best_t = z, t
        if best is None:
            return "miss", None
        self.hits += 1
        self.hit_marker = 0.15
        if best.hurt(1):
            self.kill_marker = 0.25
            return "kill", best
        return "hit", best

    def update_timers(self, dt):
        self.shoot_cd = max(0.0, self.shoot_cd - dt)
        self.hurt_flash = max(0.0, self.hurt_flash - dt)
        self.hurt_dir_t = max(0.0, self.hurt_dir_t - dt)
        self.muzzle = max(0.0, self.muzzle - dt)
        self.kick = max(0.0, self.kick - dt * 7.0)
        self.hit_marker = max(0.0, self.hit_marker - dt)
        self.kill_marker = max(0.0, self.kill_marker - dt)
        if self.reload_t > 0:
            self.reload_t -= dt
            if self.reload_t <= 0:
                self.reload_t = 0.0
                take = min(self.max_ammo - self.ammo, self.reserved)
                self.ammo += take
                self.reserved -= take

    def pickup_near(self, zombies):
        """Collect a drop lying on a corpse within reach. Ammo goes to the
        reserve (reloading is still needed); health is left on the floor
        while you're at full health. Returns 'ammo'/'health'/None."""
        for z in zombies:
            if not z.pickup:
                continue
            if (z.x - self.x) ** 2 + (z.y - self.y) ** 2 > PICKUP_RADIUS ** 2:
                continue
            kind = z.pickup["kind"]
            if kind == "health":
                if self.hp >= self.max_hp:
                    continue
                self.hp = min(self.max_hp, self.hp + HEALTH_PICKUP)
            else:
                self.reserved += AMMO_PICKUP
            z.pickup = None
            return kind
        return None
