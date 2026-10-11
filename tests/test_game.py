"""Unit tests: levels, world/pathfinding, zombie AI, shooting, rules,
key bindings, save/load, rendering and the engine's screen flow."""
import json
import math
import os
import random
import sys
import tempfile
import unittest
from unittest import mock

# Headless by default: never open a window or steal the cursor when the suite
# runs (setdefault so a real driver can still be forced externally).
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.levels import LEVELS, ZOMBIE_TYPES, parse_level, validate_level
from game.world import (flow_field, flow_step, open_direction, can_occupy,
                        slide_move, FLOW_INF)
from game.player import Player, AMMO_PICKUP, MAX_AMMO, START_RESERVE
from game.zombies import Zombie, IDLE, CHASE, ATTACK_REACH
from game.game import Game, carry_over, GUNSHOT_RADIUS, PITY_AMMO
from game.keys import (KeyBindings, DEFAULTS, MOUSE_LEFT, MOUSE_RIGHT,
                       SENS_MAX, SENS_MIN)
from game.save import SaveManager, SLOTS

DT = 1 / 60


def setUpModule():
    pygame.display.init()
    pygame.display.set_mode((960, 600))


def open_grid(n=21):
    return [[0] * n for _ in range(n)]


class FakePlayer:
    def __init__(self, x=1.5, y=1.5):
        self.x, self.y, self.angle = x, y, 0.0
        self.hp = 100
        self.hits_taken = []

    def take_hit(self, dmg, sx=None, sy=None):
        self.hp -= dmg
        self.hits_taken.append(dmg)


def zombie(x, y, ztype="walker", state=CHASE, seed=1, sprite=None):
    return Zombie(x, y, ztype, sprite, rng=random.Random(seed), state=state)


# ---------------------------------------------------------------- levels
class TestLevels(unittest.TestCase):
    def test_all_levels_valid(self):
        for i in range(len(LEVELS)):
            grid, spawns = validate_level(i)
            px, py = spawns["player"]
            self.assertEqual(grid[int(py)][int(px)], 0, "player in wall")
            for x, y, t in spawns["zombies"]:
                self.assertEqual(grid[int(y)][int(x)], 0, f"level {i}: zombie in wall")

    def test_every_zombie_reachable(self):
        for i in range(len(LEVELS)):
            grid, spawns = parse_level(i)
            px, py = spawns["player"]
            dist = flow_field(grid, int(px), int(py))
            for x, y, _ in spawns["zombies"]:
                self.assertLess(dist[int(y)][int(x)], FLOW_INF, f"level {i}: unreachable")

    def test_sewer_has_its_own_walls(self):
        # regression: 'theme' was never read, so the sewer reused alley brick
        alley, _ = parse_level(0)
        sewer, _ = parse_level(2)
        self.assertIn(1, {c for row in alley for c in row})
        self.assertNotIn(1, {c for row in sewer for c in row})
        self.assertIn(5, {c for row in sewer for c in row})

    def test_door_texture_is_used(self):
        self.assertIn(4, {c for i in range(3) for row in parse_level(i)[0] for c in row})

    def test_level_look_is_not_black(self):
        # regression: the old ambient multiply crushed floors to ~RGB(5,6,4)
        for lvl in LEVELS:
            self.assertGreater(sum(lvl["floor"]), 120)
            self.assertGreater(sum(lvl["ceiling"]), 90)


# ----------------------------------------------------------------- world
class TestWorld(unittest.TestCase):
    def test_flow_field_counts_path_tiles(self):
        grid = [[1, 1, 1, 1, 1],
                [1, 0, 1, 0, 1],
                [1, 0, 0, 0, 1],
                [1, 1, 1, 1, 1]]
        d = flow_field(grid, 1, 1)
        self.assertEqual(d[1][1], 0)
        self.assertEqual(d[1][3], 4)   # round the wall, not through it
        self.assertEqual(d[0][0], FLOW_INF)

    def test_flow_step_never_cuts_corners(self):
        grid = [[1, 1, 1, 1],
                [1, 0, 0, 1],
                [1, 1, 0, 1],
                [1, 1, 1, 1]]
        d = flow_field(grid, 2, 2)
        # from (1,1) the diagonal to (2,2) would clip the wall at (1,2)
        self.assertEqual(flow_step(d, grid, 1.5, 1.5), (2.5, 1.5))

    def test_spawn_facing_is_open(self):
        # regression: spawn facing was random and could stare into a wall
        for i in range(len(LEVELS)):
            grid, spawns = parse_level(i)
            x, y = spawns["player"]
            a = open_direction(grid, x, y)
            self.assertFalse(grid[int(y + math.sin(a) * 1.0)][int(x + math.cos(a) * 1.0)],
                             f"level {i}: facing a wall")

    def test_bodies_cannot_slide_into_walls(self):
        # regression: axis-only checks let a body enter a row whose side wall
        # starts there, overlapping it - after which it was stuck for good.
        grid = [[0, 1, 0],
                [0, 1, 0],
                [0, 0, 0]]
        x, y = 2.2, 2.5          # in the open bottom row, hugging x = 2
        for _ in range(20):
            x, y = slide_move(x, y, x, y - 0.1, 0.25, grid)
        self.assertTrue(can_occupy(x, y, 0.25, grid))
        self.assertGreaterEqual(y, 2.25)   # stopped by the wall corner

    def test_stuck_body_can_work_free(self):
        grid = [[0, 1, 0], [0, 1, 0], [0, 0, 0]]
        x, y = slide_move(2.1, 1.5, 2.3, 1.5, 0.25, grid)  # overlapping column 1
        self.assertAlmostEqual(x, 2.3)


# --------------------------------------------------------------- zombies
class TestZombieAI(unittest.TestCase):
    def test_idle_until_it_sees_you(self):
        grid = open_grid()
        grid[10][8] = 1   # wall between them
        p = FakePlayer(5.5, 10.5)
        z = zombie(12.5, 10.5, state=IDLE)
        for _ in range(60):
            z.update(DT, p, grid, [z])
        self.assertEqual(z.state, IDLE)
        self.assertEqual((z.x, z.y), (12.5, 10.5))   # no movement while idle
        p.x, p.y = 6.5, 13.5                         # step into view (6.7 tiles)
        for _ in range(30):
            z.update(DT, p, grid, [z])
        self.assertEqual(z.state, CHASE)

    def test_notices_you_up_close_without_sight(self):
        grid = open_grid()
        grid[10][11] = 1
        z = zombie(12.5, 10.5, state=IDLE)
        p = FakePlayer(10.5, 10.5)
        for _ in range(30):
            z.update(DT, p, grid, [z])
        self.assertEqual(z.state, CHASE)

    def test_gunshot_wakes_zombies_within_earshot(self):
        g = Game(2, None, rng=1)
        g.make_noise(GUNSHOT_RADIUS)
        for z in g.zombies:
            near = g.flow[int(z.y)][int(z.x)] <= GUNSHOT_RADIUS
            self.assertEqual(z.state == CHASE, near)

    def test_last_stand(self):
        g = Game(0, None, rng=1)
        for z in g.zombies[3:]:
            z.alive = False
        g.update(DT, {})
        self.assertTrue(all(z.state == CHASE for z in g.alive))

    def test_chasers_reach_you_through_the_maze(self):
        # regression: straight-line steering pinned 19/19 sewer zombies on
        # walls. With the flow field every zombie gets to the player.
        for k in (0, 6, 12):
            g = Game(2, None, rng=1)
            z = g.zombies[k]
            g.zombies = [z]
            z.state = CHASE
            g.player.hp = 10 ** 9
            for _ in range(160 * 60):
                g.update(DT, {})
                if math.hypot(z.x - g.player.x, z.y - g.player.y) < 0.9:
                    break
            self.assertLess(math.hypot(z.x - g.player.x, z.y - g.player.y), 0.9,
                            f"zombie {k} never arrived")

    def test_attack_is_telegraphed(self):
        grid = open_grid(7)
        p = FakePlayer(1.5, 1.5)
        z = zombie(2.0, 1.5)
        self.assertEqual(z.update(DT, p, grid, [z]), "windup")
        self.assertEqual(z.frame(), "attack")
        self.assertEqual(p.hp, 100)                  # nothing yet
        res = None
        for _ in range(int(ZOMBIE_TYPES["walker"]["windup"] / DT) + 2):
            res = z.update(DT, p, grid, [z]) or res
        self.assertEqual(res, "hit")
        self.assertEqual(p.hp, 100 - ZOMBIE_TYPES["walker"]["damage"])

    def test_backing_off_dodges_the_blow(self):
        grid = open_grid(7)
        p = FakePlayer(1.5, 1.5)
        z = zombie(2.0, 1.5)
        z.update(DT, p, grid, [z])                   # wind-up starts
        p.x = 2.0 - ATTACK_REACH - 0.2               # step back out of reach
        res = None
        for _ in range(60):
            res = z.update(DT, p, grid, [z]) or res
            if res:
                break
        self.assertEqual(res, "miss")
        self.assertEqual(p.hp, 100)

    def test_death_leaves_a_corpse(self):
        z = zombie(3.5, 3.5)
        self.assertFalse(z.hurt(1))
        z.hurt(5)
        self.assertFalse(z.alive)
        self.assertGreater(z.dying, 0)

    def test_hurt_semantics(self):
        # the old shooting tests used a double whose hurt() meant the opposite
        z = zombie(3.5, 3.5)
        self.assertFalse(z.hurt(1))   # still alive -> False
        self.assertFalse(z.hurt(1))
        self.assertTrue(z.hurt(1))    # killed -> True
        self.assertFalse(z.hurt(1))   # already dead


# -------------------------------------------------------------- shooting
class TestShooting(unittest.TestCase):
    def setUp(self):
        self.grid = open_grid(30)
        self.p = Player(5.5, 15.5)
        self.p.angle = 0.0

    def test_hit_on_the_body(self):
        z = zombie(13.5, 15.6)
        self.assertEqual(self.p.try_shoot([z], self.grid)[0], "hit")
        self.assertEqual(self.p.ammo, MAX_AMMO - 1)

    def test_miss_beside_the_body(self):
        # regression: a fixed ~10 deg cone hit zombies ~60 px off the sprite
        z = zombie(13.5, 15.5 + 0.45)
        self.assertEqual(self.p.try_shoot([z], self.grid)[0], "miss")
        self.assertEqual(z.hp, ZOMBIE_TYPES["walker"]["hp"])

    def test_crosshair_target_takes_the_bullet(self):
        # regression: the nearest zombie anywhere in the cone was hit instead
        far = zombie(13.5, 15.5, "brute")
        near = zombie(5.5 + 4 * math.cos(math.radians(9)),
                      15.5 + 4 * math.sin(math.radians(9)))
        res, hit = self.p.try_shoot([far, near], self.grid)
        self.assertIs(hit, far)
        self.assertEqual(near.hp, ZOMBIE_TYPES["walker"]["hp"])

    def test_nearest_on_the_line_is_hit(self):
        a, b = zombie(9.5, 15.5), zombie(12.5, 15.5)
        self.assertIs(self.p.try_shoot([b, a], self.grid)[1], a)

    def test_wall_blocks(self):
        self.grid[15][8] = 1
        z = zombie(12.5, 15.5)
        self.assertEqual(self.p.try_shoot([z], self.grid)[0], "miss")

    def test_kill_reported(self):
        z = zombie(9.5, 15.5, "runner")
        self.p.try_shoot([z], self.grid)
        self.p.shoot_cd = 0
        self.assertEqual(self.p.try_shoot([z], self.grid)[0], "kill")
        self.assertEqual(self.p.hits, 2)

    def test_dry_fire(self):
        self.p.ammo = self.p.reserved = 0
        self.assertEqual(self.p.try_shoot([], self.grid)[0], "empty")

    def test_empty_mag_waits_for_reload(self):
        self.p.ammo = 0
        self.assertEqual(self.p.try_shoot([], self.grid), (None, None))


# ------------------------------------------------------- player & rules
class TestPlayerRules(unittest.TestCase):
    def test_cannot_walk_through_zombies(self):
        # regression: there was no body-blocking at all
        grid = open_grid()
        p = Player(5.5, 10.5)
        p.angle = 0.0
        z = zombie(6.5, 10.5)
        for _ in range(120):
            p.move(DT, {"fwd": True}, grid, [z])
        self.assertLess(p.x, z.x)
        self.assertGreaterEqual(z.x - p.x, 0.49)
        for _ in range(30):                       # backing away always works
            p.move(DT, {"back": True}, grid, [z])
        self.assertLess(p.x, 5.6)

    def test_health_not_wasted_at_full_hp(self):
        p = Player(1.5, 1.5)
        z = zombie(1.5, 1.5)
        z.alive, z.pickup = False, {"kind": "health"}
        self.assertIsNone(p.pickup_near([z]))
        self.assertIsNotNone(z.pickup)
        p.hp = 60
        self.assertEqual(p.pickup_near([z]), "health")
        self.assertEqual(p.hp, 85)

    def test_ammo_goes_to_reserve(self):
        # regression: an ammo pickup used to refill the mag (a free reload)
        p = Player(1.5, 1.5)
        p.ammo = 3
        z = zombie(1.5, 1.5)
        z.alive, z.pickup = False, {"kind": "ammo"}
        p.pickup_near([z])
        self.assertEqual(p.ammo, 3)
        self.assertEqual(p.reserved, START_RESERVE + AMMO_PICKUP)

    def test_pity_drop_when_nearly_out(self):
        g = Game(0, None, rng=1)
        g.player.ammo, g.player.reserved = 2, PITY_AMMO - 5
        z = g.zombies[0]
        z.alive = False
        g.drop(z)
        self.assertEqual(z.pickup, {"kind": "ammo"})

    def test_no_health_drops_at_full_health(self):
        g = Game(0, None, rng=1)
        kinds = set()
        for _ in range(200):
            z = zombie(1.5, 1.5, "brute")
            g.drop(z)
            kinds.add(z.pickup["kind"])
        self.assertEqual(kinds, {"ammo"})

    def test_drops_do_not_use_zombie_rng(self):
        g = Game(0, None, rng=1)
        z = g.zombies[0]
        state = z._rng.getstate()
        g.drop(z)
        self.assertEqual(z._rng.getstate(), state)

    def test_clear_bonus_uses_par_and_accuracy(self):
        # regression: score was fixed per level and par was never read
        g = Game(0, None, rng=1)
        g.time = LEVELS[0]["par"] - 30
        g.player.shots, g.player.hits, g.player.hp = 10, 8, 60
        b = g.clear_bonus()
        self.assertEqual(b, {"clear": 100, "time": 60, "accuracy": 80, "health": 30})
        g.time = LEVELS[0]["par"] + 30
        self.assertEqual(g.clear_bonus()["time"], 0)

    def test_carry_over_keeps_stats_with_a_floor(self):
        s = Player(0, 0).stats()
        s.update(hp=20, ammo=5, reserved=10, score=500)
        c = carry_over(s)
        self.assertEqual((c["hp"], c["ammo"] + c["reserved"], c["score"]), (50, 60, 500))
        s.update(hp=90, ammo=30, reserved=80)
        self.assertEqual(carry_over(s)["hp"], 90)
        self.assertEqual(carry_over(s)["reserved"], 80)

    def test_game_starts_from_carry(self):
        carry = dict(Player(0, 0).stats(), hp=64, score=321)
        g = Game(1, None, rng=1, carry=carry)
        self.assertEqual((g.player.hp, g.player.score), (64, 321))
        self.assertEqual(g.entry["hp"], 64)


# ------------------------------------------------------------------ keys
class TestKeys(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.td.name, "keys.json")

    def tearDown(self):
        self.td.cleanup()

    def test_mouse_shoots_by_default(self):
        kb = KeyBindings(self.path)
        self.assertEqual(kb.bindings["shoot"], MOUSE_LEFT)
        held = mock.MagicMock()
        held.__getitem__.return_value = False
        self.assertTrue(kb.poll_state(held, (True, False, False))["shoot"])
        self.assertFalse(kb.poll_state(held, (False, False, False))["shoot"])
        self.assertEqual(kb.label("shoot"), "MOUSE LEFT")

    def test_persist_roundtrip(self):
        kb = KeyBindings(self.path)
        kb.assign("fwd", pygame.K_i)
        kb.assign("reload", MOUSE_RIGHT)
        kb.adjust_sens(0.5)
        kb2 = KeyBindings(self.path)
        self.assertEqual(kb2.bindings["fwd"], pygame.K_i)
        self.assertEqual(kb2.bindings["reload"], MOUSE_RIGHT)
        self.assertAlmostEqual(kb2.sens, 1.5)

    def test_escape_cannot_be_bound(self):
        kb = KeyBindings(self.path)
        self.assertFalse(kb.assign("quit", pygame.K_q))       # no such action now
        self.assertFalse(kb.assign("fwd", pygame.K_ESCAPE))
        self.assertEqual(kb.bindings["pause"], DEFAULTS["pause"])

    def test_assign_swaps_instead_of_unbinding(self):
        kb = KeyBindings(self.path)
        kb.assign("reload", pygame.K_SPACE)           # SPACE was shoot_alt
        self.assertEqual(kb.bindings["reload"], pygame.K_SPACE)
        self.assertEqual(kb.bindings["shoot_alt"], pygame.K_r)
        self.assertNotIn(0, kb.bindings.values())

    def test_swapped_file_loads(self):
        with open(self.path, "w") as f:
            json.dump({"fwd": pygame.K_s, "back": pygame.K_w}, f)
        kb = KeyBindings(self.path)
        self.assertEqual((kb.bindings["fwd"], kb.bindings["back"]), (pygame.K_s, pygame.K_w))

    def test_old_file_with_escape_pause_and_quit(self):
        with open(self.path, "w") as f:
            json.dump({"pause": pygame.K_ESCAPE, "quit": pygame.K_q, "fwd": "x"}, f)
        kb = KeyBindings(self.path)
        self.assertEqual(kb.bindings, DEFAULTS)

    def test_sensitivity_clamped(self):
        kb = KeyBindings(self.path)
        for _ in range(50):
            kb.adjust_sens(0.1)
        self.assertEqual(kb.sens, SENS_MAX)
        for _ in range(50):
            kb.adjust_sens(-0.1)
        self.assertEqual(kb.sens, SENS_MIN)

    def test_reset(self):
        kb = KeyBindings(self.path)
        kb.assign("shoot", pygame.K_k)
        kb.reset()
        self.assertEqual(kb.bindings, DEFAULTS)


# ------------------------------------------------------------------ save
class TestSave(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.sm = SaveManager(self.td.name)

    def tearDown(self):
        self.td.cleanup()

    def _game(self):
        g = Game(1, None, rng=3, carry=dict(Player(0, 0).stats(), hp=70))
        p = g.player
        p.x, p.y, p.angle = 3.3, 4.4, 1.2
        p.hp, p.ammo, p.reserved, p.kills, p.score, p.shots, p.hits = 55, 11, 40, 2, 30, 9, 5
        g.zombies[0].alive = False
        g.zombies[0].pickup = {"kind": "ammo"}
        g.zombies[1].state = CHASE
        g.zombies[1].windup = 0.2
        g.time = 12.5
        return g

    def test_roundtrip(self):
        g = self._game()
        self.sm.save(1, g)
        info = self.sm.info(1)
        self.assertEqual((info["kills"], info["score"], info["hp"]), (2, 30, 55))
        g2 = self.sm.restore(self.sm.load(1), None)
        for k in ("x", "y", "angle", "hp", "ammo", "reserved", "kills", "score", "shots", "hits"):
            self.assertEqual(getattr(g2.player, k), getattr(g.player, k), k)
        self.assertEqual(g2.entry["hp"], 70)     # retry checkpoint survives a load
        self.assertEqual(g2.time, 12.5)
        self.assertFalse(g2.zombies[0].alive)
        self.assertEqual(g2.zombies[0].pickup, {"kind": "ammo"})
        self.assertEqual((g2.zombies[1].state, g2.zombies[1].windup), (CHASE, 0.2))
        self.assertEqual(g2.zombies[2].state, IDLE)

    def test_save_is_small(self):
        # regression: 98% of a 139 KB save was Mersenne-Twister state
        self.sm.save(0, Game(2, None, rng=1))
        self.assertLess(os.path.getsize(os.path.join(self.td.name, "slot0.json")), 8000)

    def test_version_2_save_still_loads(self):
        g = Game(0, None, rng=1)
        v2 = {"version": 2, "level": 0, "level_name": "x", "kills": 4, "time": 3.0,
              "player": {"x": 2.5, "y": 1.5, "angle": 0.5, "hp": 80, "ammo": 7,
                         "reserved": 50, "score": 40},
              "zombies": [{"x": z.x, "y": z.y, "hp": z.hp, "alive": True, "rng": [3, [0], None]}
                          for z in g.zombies]}
        with open(os.path.join(self.td.name, "slot2.json"), "w") as f:
            json.dump(v2, f)
        g2 = self.sm.restore(self.sm.load(2), None)
        self.assertEqual((g2.player.kills, g2.player.hp), (4, 80))
        self.assertTrue(all(z.state == CHASE for z in g2.zombies))

    def test_rejects_bad_saves(self):
        good = self.sm.save(0, Game(0, None, rng=1))
        bad = [dict(good, level=7), dict(good, level="0"),
               dict(good, zombies=good["zombies"][:-1]), dict(good, version=1),
               dict(good, player=dict(good["player"], hp="lots"))]
        for i, d in enumerate(bad):
            with open(os.path.join(self.td.name, "slot0.json"), "w") as f:
                json.dump(d, f)
            self.assertIsNone(self.sm.load(0), f"bad save {i} accepted")
            self.assertEqual(self.sm.info(0), {"corrupt": True})
        self.assertIsNone(self.sm.info(1))
        self.assertEqual(SLOTS, 3)


# ---------------------------------------------------------------- render
class TestRender(unittest.TestCase):
    W, H = 160, 100

    def setUp(self):
        from game.raycaster import Textures
        self.tex = Textures({"fog": 0.0, "floor": (80, 80, 80), "ceiling": (40, 40, 40)},
                            self.W, self.H)

    def _bbox(self, p, grid, zombies):
        from game.raycaster import render_world
        base, withz = pygame.Surface((self.W, self.H)), pygame.Surface((self.W, self.H))
        render_world(base, p, grid, self.tex, [], self.W, self.H)
        render_world(withz, p, grid, self.tex, zombies, self.W, self.H)
        pts = [(x, y) for x in range(self.W) for y in range(self.H)
               if withz.get_at((x, y)) != base.get_at((x, y))]
        if not pts:
            return None
        xs, ys = zip(*pts)
        return min(xs), min(ys), max(xs), max(ys)

    def test_square_wall_face_is_square(self):
        # regression: walls drew 1.2x too wide on screen. Measure the drawn
        # face of a single block in both directions.
        from game.raycaster import render_world
        p = Player(5.5, 5.5)
        p.angle = 0.0
        empty, block = open_grid(11), open_grid(11)
        block[5][8] = 1                           # one block, 2.5 tiles ahead
        a, b = pygame.Surface((self.W, self.H)), pygame.Surface((self.W, self.H))
        render_world(a, p, empty, self.tex, [], self.W, self.H)
        render_world(b, p, block, self.tex, [], self.W, self.H)
        cx, cy = self.W // 2, self.H // 2
        width = sum(a.get_at((x, cy)) != b.get_at((x, cy)) for x in range(self.W))
        height = sum(a.get_at((cx, y)) != b.get_at((cx, y)) for y in range(self.H))
        self.assertGreater(height, 10)
        self.assertLessEqual(abs(width - height), 2)

    def test_sprite_keeps_art_proportions(self):
        # regression: 12x16 art was drawn square, then stretched 1.5x again
        from game.sprites import build_zombie_sprites
        spr = build_zombie_sprites()[0]
        p = Player(3.5, 5.5)
        p.angle = 0.0
        z = Zombie(5.5, 5.5, "walker", spr, rng=random.Random(1))
        x0, y0, x1, y1 = self._bbox(p, open_grid(11), [z])
        art = spr.art["walk0"]
        drawn_ratio = (x1 - x0 + 1) / (y1 - y0 + 1)
        self.assertAlmostEqual(drawn_ratio, art.get_width() / art.get_height(), delta=0.12)

    def test_zombie_ahead_is_centred_and_on_the_floor(self):
        from game.sprites import build_zombie_sprites
        from game.raycaster import focal_length, EYE
        p = Player(3.5, 5.5)
        p.angle = 0.0
        z = Zombie(6.5, 5.5, "walker", build_zombie_sprites()[0], rng=random.Random(1))
        x0, y0, x1, y1 = self._bbox(p, open_grid(11), [z])
        self.assertLessEqual(abs((x0 + x1) / 2 - self.W / 2), 1.5)
        floor_line = self.H // 2 + focal_length(self.W) / 3.0 * EYE
        self.assertLessEqual(abs(y1 - floor_line), 2)

    def test_wall_hides_zombie(self):
        from game.sprites import build_zombie_sprites
        grid = open_grid(11)
        grid[5][5] = 1
        p = Player(3.5, 5.5)
        p.angle = 0.0
        z = Zombie(7.5, 5.5, "walker", build_zombie_sprites()[0], rng=random.Random(1))
        self.assertIsNone(self._bbox(p, grid, [z]))

    def test_close_zombie_renders(self):
        from game.raycaster import render_world
        from game.sprites import build_zombie_sprites
        p = Player(3.5, 3.5)
        z = Zombie(3.53, 3.5, "brute", build_zombie_sprites()[2], rng=random.Random(1))
        z.flash = 0.1
        render_world(pygame.Surface((640, 400)), p, open_grid(11), self.tex, [z], 640, 400)

    def test_floor_has_no_vertical_banding(self):
        # regression: floor fog was keyed to each column's wall distance
        from game.raycaster import render_world
        grid = open_grid(21)
        for y in range(21):
            grid[y][14] = 1
        grid[10][14] = 0               # a gap: far wall in the middle columns
        p = Player(10.5, 10.5)
        p.angle = 0.0
        buf = pygame.Surface((self.W, self.H))
        render_world(buf, p, grid, self.tex, [], self.W, self.H)
        row = self.H - 2
        self.assertEqual(len({tuple(buf.get_at((x, row))) for x in range(self.W)}), 1)

    def test_open_edge_does_not_occlude(self):
        from game.raycaster import cast_rays, _INF
        p = Player(3.5, 3.5)
        for c in cast_rays(p, open_grid(8), 4):
            self.assertEqual((c[0], c[1]), (_INF, 0))

    def test_corpse_and_pickup_drawn(self):
        from game.sprites import build_zombie_sprites
        p = Player(3.5, 5.5)
        p.angle = 0.0
        z = Zombie(5.5, 5.5, "walker", build_zombie_sprites()[0], rng=random.Random(1))
        z.alive, z.pickup = False, {"kind": "ammo"}
        self.assertIsNotNone(self._bbox(p, open_grid(11), [z]))


# ---------------------------------------------------------------- engine
class TestEngine(unittest.TestCase):
    def setUp(self):
        from game import engine
        self.E = engine
        self.td = tempfile.TemporaryDirectory()
        self.e = engine.Engine(self.td.name)
        self.e.running = True

    def tearDown(self):
        self.td.cleanup()

    def test_menu_to_playing_and_back(self):
        E, e = self.E, self.e
        e._on_key(pygame.K_n)
        self.assertEqual(e.state, E.PLAYING)
        self.assertEqual(e.game.level_idx, 0)
        e._on_key(pygame.K_ESCAPE)
        self.assertEqual(e.state, E.PAUSED)
        e._on_key(pygame.K_ESCAPE)
        self.assertEqual(e.state, E.PLAYING)

    def test_q_does_not_quit_mid_game(self):
        # regression: Q (next to W/A) quit to the desktop instantly
        e = self.e
        e.new_campaign()
        for k in (pygame.K_q, pygame.K_m, pygame.K_x):
            e._on_key(k)
        self.assertTrue(e.running)
        self.assertEqual(e.state, self.E.PLAYING)

    def test_quitting_from_pause_asks_first(self):
        E, e = self.E, self.e
        e.new_campaign()
        e._on_key(pygame.K_ESCAPE)
        e._on_key(pygame.K_q)
        self.assertEqual(e.state, E.CONFIRM)
        self.assertTrue(e.running)
        e._on_key(pygame.K_n)                  # "no"
        self.assertEqual(e.state, E.PAUSED)
        e._on_key(pygame.K_m)
        e._on_key(pygame.K_y)
        self.assertEqual(e.state, E.MENU)
        self.assertIsNone(e.game)

    def test_escape_always_pauses_and_resumes(self):
        # regression: with Pause rebound, Esc in the pause menu dropped the run
        E, e = self.E, self.e
        e.keys.assign("pause", pygame.K_o)
        e.new_campaign()
        e._on_key(pygame.K_ESCAPE)
        self.assertEqual(e.state, E.PAUSED)
        e._on_key(pygame.K_ESCAPE)
        self.assertEqual(e.state, E.PLAYING)
        self.assertIsNotNone(e.game)
        e._on_key(pygame.K_o)
        self.assertEqual(e.state, E.PAUSED)

    def test_mouse_button_can_pause(self):
        e = self.e
        e.keys.assign("pause", MOUSE_RIGHT)
        e.new_campaign()
        e._on_click(3, (10, 10))
        self.assertEqual(e.state, self.E.PAUSED)

    def test_rebinding_screen(self):
        E, e = self.E, self.e
        e._on_key(pygame.K_k)
        self.assertEqual(e.state, E.KEYBIND)
        e._on_key(pygame.K_RETURN)             # row 0: move forward
        self.assertEqual(e.capturing, "fwd")
        e._on_key(pygame.K_ESCAPE)             # cancels capture, stays put
        self.assertIsNone(e.capturing)
        self.assertEqual(e.state, E.KEYBIND)
        e.render()
        i = [a for a, _ in self.E.ACTIONS].index("reload")
        e._on_click(1, e.ui.item_rects[i].center)
        self.assertEqual(e.capturing, "reload")
        e._on_click(3, (5, 5))                 # bind a mouse button
        self.assertEqual(e.keys.bindings["reload"], MOUSE_RIGHT)
        e._on_key(pygame.K_ESCAPE)
        self.assertEqual(e.state, E.MENU)

    def test_titles_never_overlap_rows(self):
        # regression: titles were drawn at screen centre, over the content
        E, e = self.E, self.e
        title_bottom = 48 + e.ui.f_l.get_height()
        for state, setup in ((E.KEYBIND, e.open_binds),
                             (E.LEVEL_SELECT, lambda: e.goto(E.LEVEL_SELECT)),
                             (E.SAVEDLG, lambda: e.open_dialog("load"))):
            e.goto(E.MENU)
            setup()
            e.render()
            self.assertTrue(e.ui.item_rects)
            for r in e.ui.item_rects:
                self.assertGreater(r.top, title_bottom, f"state {state}")
                self.assertLessEqual(r.bottom, 600 - 50)

    def test_level_select_is_locked_until_earned(self):
        E, e = self.E, self.e
        e.goto(E.LEVEL_SELECT)
        e._on_key(pygame.K_3)
        self.assertEqual(e.state, E.LEVEL_SELECT)
        e.unlocked = 3
        e._on_key(pygame.K_3)
        self.assertEqual(e.state, E.PLAYING)
        self.assertEqual(e.game.level_idx, 2)

    def test_win_carries_stats_and_unlocks(self):
        E, e = self.E, self.e
        e.new_campaign()
        g = e.game
        g.player.hp, g.player.reserved, g.player.score = 77, 33, 200
        for z in g.zombies:
            z.alive = False
        e.update(DT)
        self.assertEqual(e.state, E.WIN)
        self.assertEqual(e.unlocked, 2)
        score = e.game.player.score
        self.assertGreater(score, 200)          # clear bonus added
        with open(os.path.join(self.td.name, "best.json")) as f:
            self.assertEqual(json.load(f)["score"], score)
        e._on_key(pygame.K_RETURN)
        self.assertEqual(e.game.level_idx, 1)
        self.assertEqual((e.game.player.hp, e.game.player.score), (77, score))

    def test_retry_uses_level_entry_stats(self):
        E, e = self.E, self.e
        e.start_level(1, dict(Player(0, 0).stats(), hp=66, score=150))
        e.game.player.hp = 0
        e.update(DT)
        self.assertEqual(e.state, E.LOSE)
        e._on_key(pygame.K_r)
        self.assertEqual((e.game.level_idx, e.game.player.hp, e.game.player.score), (1, 66, 150))

    def test_last_level_win_leads_to_victory(self):
        E, e = self.E, self.e
        e.start_level(2)
        for z in e.game.zombies:
            z.alive = False
        e.update(DT)
        e._on_key(pygame.K_RETURN)
        self.assertEqual(e.state, E.VICTORY)
        e.render()
        e._on_key(pygame.K_RETURN)
        self.assertEqual(e.state, E.MENU)

    def test_save_overwrite_asks_and_load_restores(self):
        E, e = self.E, self.e
        e.new_campaign()
        e._on_key(pygame.K_ESCAPE)
        e._on_key(pygame.K_s)
        e._on_key(pygame.K_1)
        self.assertEqual(e.state, E.PAUSED)
        self.assertTrue(e.saves.exists(0))
        e._on_key(pygame.K_s)
        e._on_key(pygame.K_1)
        self.assertEqual(e.state, E.CONFIRM)    # occupied slot
        e._on_key(pygame.K_y)
        self.assertEqual(e.state, E.PAUSED)
        e._on_key(pygame.K_m)
        e._on_key(pygame.K_y)
        e._on_key(pygame.K_l)
        e._on_key(pygame.K_2)                    # empty slot: stays, no crash
        self.assertEqual(e.state, E.SAVEDLG)
        e._on_key(pygame.K_1)
        self.assertEqual(e.state, E.PLAYING)

    def test_focus_lost_pauses(self):
        E, e = self.E, self.e
        e.new_campaign()
        e._on_event(pygame.event.Event(pygame.WINDOWFOCUSLOST))
        self.assertEqual(e.state, E.PAUSED)
        e.state = E.PLAYING
        e._on_event(pygame.event.Event(pygame.ACTIVEEVENT, gain=0,
                                       state=pygame.APPINPUTFOCUS))
        self.assertEqual(e.state, E.PAUSED)

    def test_fire_held_from_a_menu_click_is_ignored(self):
        e = self.e
        e.new_campaign()
        held = mock.MagicMock()
        held.__getitem__.return_value = False
        with mock.patch.object(pygame.key, "get_pressed", return_value=held), \
                mock.patch.object(pygame.mouse, "get_pressed", return_value=(True, False, False)):
            e.update(DT)
            self.assertEqual(e.game.player.shots, 0)
        with mock.patch.object(pygame.key, "get_pressed", return_value=held), \
                mock.patch.object(pygame.mouse, "get_pressed", return_value=(False, False, False)):
            e.update(DT)
        with mock.patch.object(pygame.key, "get_pressed", return_value=held), \
                mock.patch.object(pygame.mouse, "get_pressed", return_value=(True, False, False)):
            e.update(DT)
        self.assertEqual(e.game.player.shots, 1)

    def test_sync_mouse_before_update(self):
        e = self.e
        e.new_campaign()
        order = []
        e._sync_mouse = lambda: order.append("sync")
        e.update = lambda dt: order.append("update")
        e.render = lambda: None
        with mock.patch.object(pygame.event, "get",
                               side_effect=[[], [pygame.event.Event(pygame.QUIT)]]), \
                mock.patch.object(pygame.display, "flip"):
            e.run()
        self.assertEqual(order[:2], ["sync", "update"])

    def test_sync_mouse_zeroes_delta_when_unfocused(self):
        e = self.e
        e.new_campaign()
        e.mouse_dx = 123
        with mock.patch.object(pygame.mouse, "get_focused", return_value=False), \
                mock.patch.object(pygame.mouse, "set_pos") as sp:
            e._sync_mouse()
        self.assertEqual(e.mouse_dx, 0)
        sp.assert_not_called()

    def test_every_screen_renders(self):
        E, e = self.E, self.e
        e.new_campaign()
        g = e.game
        g.player.muzzle, g.player.hurt_dir_t, g.player.reload_t = 0.05, 0.5, 0.5
        for st in (E.PLAYING, E.PAUSED, E.LOSE, E.MENU, E.LEVEL_SELECT, E.KEYBIND):
            e.state = st
            e.render()
        e.open_dialog("save")
        e.render()
        e.ask("Sure?", "detail", lambda: None)
        e.render()
        e.bonus = g.clear_bonus()
        e.state = E.WIN
        e.render()

    def test_events_become_positional_sounds(self):
        e = self.e
        e.new_campaign()
        p = e.game.player
        z = zombie(p.x + math.cos(p.angle + math.pi / 2) * 3, p.y + math.sin(p.angle + math.pi / 2) * 3)
        e.game.events = [("groan", z), ("shoot", None)]
        with mock.patch.object(e.sfx, "play") as play:
            e._play_events()
        name, vol, pan = play.call_args_list[0][0]
        self.assertEqual(name, "groan")
        self.assertGreater(pan, 0.9)            # 90 deg to the right
        self.assertLess(vol, 1.0)
        self.assertEqual(play.call_args_list[1][0], ("shoot",))
        self.assertEqual(e.game.events, [])


# --------------------------------------------------------------- minimap
class TestMinimap(unittest.TestCase):
    def setUp(self):
        from game.minimap import Minimap
        self.mm = Minimap()

    def _px(self, surf, x, y):
        mx, my = self.mm.to_map(x, y)
        return tuple(surf.get_at((round(mx), round(my))))[:3]

    def test_marks_zombies_by_state(self):
        from game.minimap import HUNTING, IDLE, AMMO
        g = Game(2, None, rng=1)                 # the sewer: 19 zombies
        hunting, idle, dead = g.zombies[0], g.zombies[8], g.zombies[12]
        hunting.state = CHASE
        dead.alive, dead.pickup = False, {"kind": "ammo"}
        surf = pygame.Surface((300, 200))
        self.mm.draw(surf, g, (0, 0))

        def around(z):
            cx, cy = (round(v) for v in self.mm.to_map(z.x, z.y))
            return [tuple(surf.get_at((cx + dx, cy + dy)))[:3]
                    for dx in range(-5, 6) for dy in range(-5, 6)]
        self.assertEqual(self._px(surf, hunting.x, hunting.y), HUNTING)   # filled
        self.assertNotEqual(self._px(surf, idle.x, idle.y), IDLE)         # hollow...
        self.assertGreater(around(idle).count(IDLE), 6)                   # ...ring
        self.assertEqual(self._px(surf, dead.x, dead.y), AMMO)            # drop shown
        self.assertNotIn(HUNTING, around(dead))                           # corpse not
        self.assertNotIn(IDLE, around(dead))

    def test_view_cone_points_where_you_look(self):
        from types import SimpleNamespace
        g = SimpleNamespace(grid=open_grid(11), player=Player(5.5, 5.5), zombies=[])
        surf = pygame.Surface((200, 200))
        for angle, ahead, behind in ((0.0, (7.5, 5.5), (3.5, 5.5)),
                                     (math.pi / 2, (5.5, 7.5), (5.5, 3.5))):
            g.player.angle = angle
            surf.fill((0, 0, 0))
            self.mm.draw(surf, g, (0, 0))
            self.assertGreater(sum(self._px(surf, *ahead)), sum(self._px(surf, *behind)))

    def test_view_cone_stops_at_walls(self):
        from types import SimpleNamespace
        grid = open_grid(11)
        for y in range(11):
            grid[y][7] = 1                       # a wall 1.5 tiles ahead
        g = SimpleNamespace(grid=grid, player=Player(5.5, 5.5), zombies=[])
        surf = pygame.Surface((200, 200))
        self.mm.draw(surf, g, (0, 0))
        beyond, untouched = self._px(surf, 8.5, 5.5), self._px(surf, 8.5, 9.5)
        self.assertEqual(beyond, untouched)      # no light through the wall
        self.assertGreater(sum(self._px(surf, 6.5, 5.5)), sum(beyond))

    def test_map_is_not_mirrored(self):
        # whatever is on your right on screen is on the right of the arrow
        from game.raycaster import project
        self.mm.size(open_grid(11))
        p = Player(5.5, 5.5)
        for angle in (0.0, 0.7, math.pi / 2, math.pi, -math.pi / 2):
            p.angle = angle
            c, s = math.cos(angle), math.sin(angle)
            x, y = p.x + 2 * c - s, p.y + 2 * s + c      # 2 ahead, 1 to the right
            self.assertGreater(project(p, x, y, 640)[1], 320)
            px, py = self.mm.to_map(p.x, p.y)
            zx, zy = self.mm.to_map(x, y)
            self.assertGreater(c * (zy - py) - s * (zx - px), 0)

    def test_every_level_fits_the_corner(self):
        from game.ui import MINIMAP_POS
        for i in range(len(LEVELS)):
            w, h = self.mm.size(parse_level(i)[0])
            self.assertLessEqual(MINIMAP_POS[0] + w, 280)   # clear of the centre
            self.assertLessEqual(MINIMAP_POS[1] + h, 280)   # above the crosshair

    def test_walls_drawn_once_per_level(self):
        surf = pygame.Surface((300, 200))
        g = Game(0, None, rng=1)
        self.mm.draw(surf, g, (0, 0))
        base = self.mm.base
        g.player.angle += 1.0
        self.mm.draw(surf, g, (0, 0))
        self.assertIs(self.mm.base, base)
        self.mm.draw(surf, Game(2, None, rng=1), (0, 0))
        self.assertIsNot(self.mm.base, base)
        self.assertNotEqual(self.mm.base.get_size(), base.get_size())


class TestMinimapControls(unittest.TestCase):
    def setUp(self):
        from game import engine
        self.E = engine
        self.td = tempfile.TemporaryDirectory()
        self.e = engine.Engine(self.td.name)
        self.e.running = True

    def tearDown(self):
        self.td.cleanup()

    def test_settings(self):
        kb = KeyBindings(os.path.join(self.td.name, "k.json"))
        self.assertTrue(kb.minimap)
        self.assertEqual(kb.bindings["map"], pygame.K_TAB)
        held = mock.MagicMock()
        held.__getitem__.return_value = True
        self.assertNotIn("map", kb.poll_state(held, (True, True, True)))  # press, not hold
        kb.toggle_minimap()
        self.assertFalse(KeyBindings(kb.path).minimap)
        kb.reset()
        self.assertTrue(KeyBindings(kb.path).minimap)
        with open(kb.path, "w") as f:
            json.dump({"_minimap": "nope"}, f)
        self.assertTrue(KeyBindings(kb.path).minimap)

    def test_tab_toggles_and_is_remembered(self):
        from game.ui import MINIMAP_POS
        e = self.e
        e.new_campaign()
        rect = pygame.Rect(MINIMAP_POS, e.ui.minimap.size(e.game.grid))

        def corner():
            e.msg = None
            e.render()
            return pygame.image.tobytes(e.screen.subsurface(rect), "RGB")
        with_map = corner()
        e._on_key(pygame.K_TAB)
        self.assertFalse(e.keys.minimap)
        self.assertIn("TAB", e.msg)              # says how to get it back
        self.assertNotEqual(corner(), with_map)
        self.assertFalse(KeyBindings(os.path.join(self.td.name, "keys.json")).minimap)
        e._on_key(pygame.K_TAB)
        self.assertTrue(e.keys.minimap)
        self.assertEqual(corner(), with_map)

    def test_map_sits_below_the_zombie_count(self):
        from game.ui import MINIMAP_POS
        self.assertLessEqual(38 + self.e.ui.f_m.get_height(), MINIMAP_POS[1])

    def test_alt_tab_does_not_toggle(self):
        e = self.e
        e.new_campaign()
        with mock.patch.object(pygame.key, "get_mods", return_value=pygame.KMOD_LALT):
            e._on_key(pygame.K_TAB)
        self.assertTrue(e.keys.minimap)

    def test_bindable_to_a_mouse_button(self):
        from game.keys import MOUSE_MIDDLE
        e = self.e
        e.keys.assign("map", MOUSE_MIDDLE)
        e.new_campaign()
        e._on_click(2, (10, 10))
        self.assertFalse(e.keys.minimap)
        e._on_key(pygame.K_TAB)                  # Tab is no longer the map key
        self.assertFalse(e.keys.minimap)
        self.assertEqual(e.state, self.E.PLAYING)


if __name__ == "__main__":
    unittest.main(verbosity=2)
