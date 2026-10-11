"""One level in play: player + zombies + grid, the per-frame simulation,
and the rules - noise, drops, scoring and carry-over between levels.

Sound-worthy moments are appended to `Game.events` as (name, zombie|None)
for the engine to play (positioned when a zombie is attached).
"""
import random
from .levels import LEVELS, TYPE_NAMES, parse_level
from .player import Player
from .zombies import Zombie
from .world import flow_field, flow_dist, open_direction

GUNSHOT_RADIUS = 11     # path tiles a gunshot carries
PACK_RADIUS = 3.0       # an alerted zombie wakes idle ones this close
LAST_STAND = 3          # this few left: they all come for you
DROP_CHANCE = 0.45      # brutes always drop
AMMO_SHARE = 0.6        # share of drops that are ammo (when hurt)
PITY_AMMO = 15          # below this much total ammo, kills always drop ammo
MIN_HP_CARRY = 50       # between levels you patch up to at least this...
MIN_AMMO_CARRY = 60     # ...and scavenge up to this much total ammo


def carry_over(stats):
    """Stats for the next level: everything carries, with a floor on
    health and ammo so a run can't become unwinnable."""
    s = dict(stats)
    s["hp"] = max(s["hp"], MIN_HP_CARRY)
    total = s["ammo"] + s["reserved"]
    if total < MIN_AMMO_CARRY:
        s["reserved"] += MIN_AMMO_CARRY - total
    return s


class Game:
    def __init__(self, level_idx, sprites, rng=None, carry=None):
        self.level_idx = level_idx
        self.level = LEVELS[level_idx]
        self.grid, spawns = parse_level(level_idx)
        seed = rng if isinstance(rng, int) else random.randrange(1 << 30)
        self.rng = random.Random(seed)
        px, py = spawns["player"]
        self.player = Player(px, py, angle=open_direction(self.grid, px, py))
        if carry:
            self.player.load_stats(carry)
        self.entry = self.player.stats()     # retry checkpoint
        self.zombies = [
            Zombie(x, y, TYPE_NAMES[t], sprites[t] if sprites else None,
                   rng=random.Random(seed + 100 + i * 7))
            for i, (x, y, t) in enumerate(spawns["zombies"])]
        self.time = 0.0
        self.events = []
        self.flow = None
        self._flow_tile = None
        self.refresh_flow()

    @property
    def alive(self):
        return [z for z in self.zombies if z.alive]

    # ---------- AI support ----------
    def refresh_flow(self):
        tile = (int(self.player.x), int(self.player.y))
        if tile != self._flow_tile:
            self.flow = flow_field(self.grid, *tile)
            self._flow_tile = tile

    def _alert(self, z):
        if z.alert():
            self.events.append(("alert", z))
            return True
        return False

    def make_noise(self, radius):
        """Wake idle zombies within `radius` tiles of walking distance."""
        for z in self.zombies:
            if z.alive and flow_dist(self.flow, z.x, z.y) <= radius:
                self._alert(z)

    def _pack_alert(self, source):
        queue = [source]
        while queue:
            s = queue.pop()
            for z in self.zombies:
                if z.alive and (z.x - s.x) ** 2 + (z.y - s.y) ** 2 <= PACK_RADIUS ** 2 \
                        and self._alert(z):
                    queue.append(z)

    # ---------- per frame ----------
    def update(self, dt, inp):
        """inp: movement booleans (fwd, back, strafe_l, strafe_r, turn_l,
        turn_r, sprint) plus shoot, reload, mouse_dx, sens."""
        p = self.player
        self.time += dt
        p.turn(dt, inp.get("mouse_dx", 0), inp, inp.get("sens", 1.0))
        p.move(dt, inp, self.grid, self.zombies)
        p.update_timers(dt)
        self.refresh_flow()

        if inp.get("shoot"):
            res, z = p.try_shoot(self.zombies, self.grid)
            if res == "empty":
                self.events.append(("empty", None))
            elif res is not None:
                self.events.append(("shoot", None))
                self.make_noise(GUNSHOT_RADIUS)
                if res == "kill":
                    self.on_kill(z)
                elif res == "hit":
                    self.events.append(("hit", z))
                if p.ammo == 0 and p.start_reload():
                    self.events.append(("reload", None))
        if inp.get("reload") and p.start_reload():
            self.events.append(("reload", None))
        if p.pickup_near(self.zombies):
            self.events.append(("pickup", None))

        first = len(self.events)
        for z in self.zombies:
            z.update(dt, p, self.grid, self.zombies, self.flow, self.events)
        for name, z in self.events[first:]:
            if name == "alert":
                self._pack_alert(z)
        alive = self.alive
        if len(alive) <= LAST_STAND:
            for z in alive:
                self._alert(z)

    # ---------- rules ----------
    def on_kill(self, z):
        p = self.player
        p.score += z.score
        p.kills += 1
        self.events.append(("kill", z))
        self.drop(z)

    def drop(self, z):
        p = self.player
        if p.ammo + p.reserved < PITY_AMMO:
            z.pickup = {"kind": "ammo"}
            return
        if z.ztype == "brute" or self.rng.random() < DROP_CHANCE:
            hurt = p.hp < p.max_hp
            z.pickup = {"kind": "health" if hurt and self.rng.random() >= AMMO_SHARE
                        else "ammo"}

    def clear_bonus(self):
        """Bonus for clearing the level: base + time under par + accuracy
        (this level's shots) + half the health you finish with."""
        p, e = self.player, self.entry
        shots, hits = p.shots - e["shots"], p.hits - e["hits"]
        acc = hits / shots if shots else 1.0
        return {
            "clear": 100 * (self.level_idx + 1),
            "time": max(0, int(round((self.level["par"] - self.time) * 2))),
            "accuracy": int(round(100 * acc)),
            "health": max(0, int(p.hp)) // 2,
        }

    def finish(self):
        bonus = self.clear_bonus()
        self.player.score += sum(bonus.values())
        return bonus
