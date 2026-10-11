"""Screens and overlays: menus, settings, save/load, dialogs, the HUD and
the first-person gun.

Every label is anchored by its measured size (no hand-tuned x offsets) and
every title sits above its content. Clickable rows are recorded in
`item_rects` by whichever screen drew them last, so mouse hit-testing uses
exactly the geometry that is on screen.
"""
import math
import pygame
from .keys import ACTIONS
from .minimap import Minimap
from .player import RELOAD_TIME

FG = (225, 225, 215)
DIM = (140, 140, 130)
RED = (196, 48, 36)
GOLD = (255, 214, 110)
GREEN = (110, 210, 110)
BG = (14, 15, 14)
SEL_FILL = (70, 28, 24)
SEL_EDGE = (160, 64, 52)

TITLE_Y = 48
MENU_STEP = 48
BIND_TOP = 120
BIND_STEP = 31
MINIMAP_POS = (16, 66)      # under the "N zombies left" line


def fmt_time(t):
    t = max(0, int(t))
    return f"{t // 60}:{t % 60:02d}"


def plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


class Ui:
    def __init__(self, screen, w, h, keys):
        self.screen = screen
        self.w, self.h = w, h
        self.keys = keys
        self.f_s = pygame.font.SysFont(None, 22)
        self.f_m = pygame.font.SysFont(None, 30)
        self.f_l = pygame.font.SysFont(None, 44)
        self.f_xl = pygame.font.SysFont(None, 84)
        self.item_rects = []
        self._cache = {}
        self.minimap = Minimap()

    # ---------- primitives ----------
    def text(self, s, font, color=FG, shadow=False, **anchor):
        surf = font.render(s, True, color)
        rect = surf.get_rect(**anchor)
        if shadow:
            self.screen.blit(font.render(s, True, (0, 0, 0)), rect.move(2, 2))
        self.screen.blit(surf, rect)
        return rect

    def bg(self, color=BG):
        self.screen.fill(color)

    def dim(self, alpha=170):
        key = ("dim", alpha)
        if key not in self._cache:
            s = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
            s.fill((0, 0, 0, alpha))
            self._cache[key] = s
        self.screen.blit(self._cache[key], (0, 0))

    def title(self, s, color=RED):
        return self.text(s, self.f_l, color, shadow=True, midtop=(self.w // 2, TITLE_Y))

    def hint(self, s, line=0):
        return self.text(s, self.f_s, DIM, midbottom=(self.w // 2, self.h - 16 - 24 * line))

    def panel(self, rect, selected=False):
        pygame.draw.rect(self.screen, SEL_FILL if selected else (24, 24, 23), rect,
                         border_radius=10)
        pygame.draw.rect(self.screen, SEL_EDGE if selected else (60, 60, 56), rect, 2,
                         border_radius=10)

    def toast(self, msg):
        surf = self.f_m.render(msg, True, GOLD)
        r = surf.get_rect(midtop=(self.w // 2, 84)).inflate(28, 14)
        pygame.draw.rect(self.screen, (10, 10, 10), r, border_radius=8)
        pygame.draw.rect(self.screen, (120, 96, 40), r, 2, border_radius=8)
        self.screen.blit(surf, surf.get_rect(center=r.center))

    def hit_item(self, pos):
        for i, r in enumerate(self.item_rects):
            if r.collidepoint(pos):
                return i
        return None

    def menu_list(self, labels, sel, top, enabled=None, step=MENU_STEP):
        rects = []
        for i, label in enumerate(labels):
            on = enabled is None or enabled[i]
            tw, th = self.f_m.size(label)
            r = pygame.Rect(0, 0, max(tw + 48, 360), th + 16)
            r.center = (self.w // 2, top + i * step)
            if i == sel:
                self.panel(r, selected=True)
            self.text(label, self.f_m, GOLD if i == sel else (FG if on else (90, 90, 86)),
                      center=r.center)
            rects.append(r)
        self.item_rects = rects
        return rects

    # ---------- screens ----------
    def main_menu(self, best, labels, sel, hint):
        self.bg()
        self.text("DEAD ZONE", self.f_xl, RED, shadow=True, midtop=(self.w // 2, 56))
        self.text("a retro zombie shooter", self.f_s, DIM, midtop=(self.w // 2, 128))
        self.menu_list(labels, sel, top=220)
        self.text(f"Best run score: {best}", self.f_m, GOLD,
                  midbottom=(self.w // 2, self.h - 52))
        self.hint(hint)

    def level_select(self, levels, unlocked, sel):
        self.bg()
        self.title("CHOOSE YOUR DEATH")
        rects = []
        for i, lvl in enumerate(levels):
            r = pygame.Rect(0, 0, 640, 112)
            r.midtop = (self.w // 2, 118 + i * 128)
            locked = i >= unlocked
            self.panel(r, selected=(i == sel))
            self.text(f"[{i + 1}]  {lvl['name']}", self.f_m,
                      (95, 95, 90) if locked else (GOLD if i == sel else FG),
                      midtop=(r.centerx, r.top + 12))
            self.text(lvl["desc"], self.f_s, DIM, midtop=(r.centerx, r.top + 46))
            if locked:
                self.text(f"LOCKED - clear level {i} to unlock", self.f_s, RED,
                          midtop=(r.centerx, r.top + 74))
            else:
                z = lvl["zombies"]
                self.text(f"{plural(z['walker'], 'walker')}  /  {plural(z['runner'], 'runner')}"
                          f"  /  {plural(z['brute'], 'brute')}   -   par {fmt_time(lvl['par'])}",
                          self.f_s, (130, 170, 130), midtop=(r.centerx, r.top + 74))
            rects.append(r)
        self.item_rects = rects
        self.hint("Up/Down + Enter, 1-3 or click   |   Esc = back")

    def save_load(self, mode, infos, sel):
        self.title("SAVE GAME" if mode == "save" else "LOAD GAME")
        rects = []
        for i, info in enumerate(infos):
            r = pygame.Rect(0, 0, 640, 80)
            r.midtop = (self.w // 2, 130 + i * 96)
            self.panel(r, selected=(i == sel))
            col = GOLD if i == sel else FG
            if info is None:
                self.text(f"Slot {i + 1}:  (empty)", self.f_m, DIM, center=r.center)
            elif info.get("corrupt"):
                self.text(f"Slot {i + 1}:  (unreadable save)", self.f_m, RED, center=r.center)
            else:
                self.text(f"Slot {i + 1}:  {info['level_name']}", self.f_m, col,
                          midtop=(r.centerx, r.top + 12))
                self.text(f"Score {info['score']}   |   {plural(info['kills'], 'kill')}   |   "
                          f"HP {info['hp']}   |   {fmt_time(info['time'])}",
                          self.f_s, DIM, midtop=(r.centerx, r.top + 48))
            rects.append(r)
        self.item_rects = rects
        if mode == "save":
            self.hint("Enter, 1-3 or click = save here (asks before overwriting)", 1)
        else:
            self.hint("Enter, 1-3 or click = load", 1)
        self.hint("Del = delete slot   |   Esc = back")

    def bind_row_rect(self, i):
        return pygame.Rect(self.w // 2 - 320, BIND_TOP + i * BIND_STEP, 640, BIND_STEP - 3)

    def key_bind(self, sel, capturing):
        self.bg()
        self.title("SETTINGS & KEY BINDINGS")
        rects = []
        rows = [(a, label) for a, label in ACTIONS] + [(None, "Mouse sensitivity")]
        for i, (action, label) in enumerate(rows):
            r = self.bind_row_rect(i)
            if i == sel:
                self.panel(r, selected=True)
            col = GOLD if i == sel else FG
            self.text(label, self.f_m, col, midleft=(r.left + 24, r.centery))
            live = action is not None and capturing == action
            if action is None:
                val = f"<   {self.keys.sens:.1f}x   >"
            elif live:
                val = "press a key or mouse button..."
            else:
                val = f"[ {self.keys.label(action)} ]"
            self.text(val, self.f_m, (120, 220, 120) if live else col,
                      midleft=(r.left + 360, r.centery))
            rects.append(r)
        self.item_rects = rects
        if capturing:
            self.hint("Press the new key or mouse button   |   Esc = cancel")
        else:
            self.hint("Left/Right or click < > = sensitivity   |   R = reset to defaults", 1)
            self.hint("Up/Down + Enter or click a row to rebind   |   Esc = back")

    def pause(self, labels, sel):
        self.dim()
        self.text("PAUSED", self.f_xl, FG, shadow=True, midtop=(self.w // 2, 70))
        self.menu_list(labels, sel, top=230)
        self.hint("Esc = resume")

    def confirm(self, prompt, detail):
        self.dim(120)
        r = pygame.Rect(0, 0, 620, 190)
        r.center = (self.w // 2, self.h // 2)
        self.panel(r)
        self.text(prompt, self.f_m, FG, midtop=(r.centerx, r.top + 32))
        if detail:
            self.text(detail, self.f_s, DIM, midtop=(r.centerx, r.top + 78))
        self.text("Y / Enter = yes        N / Esc = no", self.f_m, GOLD,
                  midtop=(r.centerx, r.top + 126))

    def win(self, game, bonus, last_level):
        self.bg((10, 18, 10))
        self.text("AREA CLEARED", self.f_xl, GREEN, shadow=True, midtop=(self.w // 2, 56))
        self.text(game.level["name"], self.f_m, DIM, midtop=(self.w // 2, 140))
        rows = [
            ("Clear bonus", bonus["clear"]),
            (f"Time {fmt_time(game.time)}  (par {fmt_time(game.level['par'])})", bonus["time"]),
            (f"Accuracy {bonus['accuracy']}%", bonus["accuracy"]),
            (f"Health left {max(0, int(game.player.hp))}", bonus["health"]),
        ]
        y = 200
        for label, pts in rows:
            self.text(label, self.f_m, FG, midleft=(self.w // 2 - 250, y))
            self.text(f"+{pts}", self.f_m, GOLD, midright=(self.w // 2 + 250, y))
            y += 42
        pygame.draw.line(self.screen, (80, 80, 76), (self.w // 2 - 250, y - 14),
                         (self.w // 2 + 250, y - 14), 2)
        self.text("Run score", self.f_l, FG, midleft=(self.w // 2 - 250, y + 14))
        self.text(str(game.player.score), self.f_l, GOLD, midright=(self.w // 2 + 250, y + 14))
        self.hint("Enter = finish the campaign" if last_level
                  else "Enter = next level (health and ammo carry over)   |   Esc = end run")

    def victory(self, score, best):
        self.bg((10, 18, 10))
        self.text("THE DEAD ZONE IS CLEAR", self.f_l, GREEN, shadow=True,
                  midtop=(self.w // 2, 150))
        self.text(f"Final run score: {score}", self.f_l, FG, midtop=(self.w // 2, 240))
        self.text("New best!" if score >= best and score > 0 else f"Best: {best}",
                  self.f_m, GOLD, midtop=(self.w // 2, 310))
        self.hint("Enter = main menu")

    def lose(self, player, level_name):
        self.bg((22, 8, 8))
        self.text("YOU DIED", self.f_xl, RED, shadow=True, midtop=(self.w // 2, 130))
        self.text(level_name, self.f_m, DIM, midtop=(self.w // 2, 230))
        self.text(f"Run score {player.score}   |   {plural(player.kills, 'kill')}",
                  self.f_m, FG, midtop=(self.w // 2, 280))
        self.hint("R / Enter = retry this level with the health and ammo you entered it with", 1)
        self.hint("Esc = end run")

    # ---------- in game ----------
    def _gradient_strip(self, height, alpha):
        key = ("strip", height, alpha)
        if key not in self._cache:
            s = pygame.Surface((self.w, height), pygame.SRCALPHA)
            for y in range(height):
                s.fill((0, 0, 0, int(alpha * y / height)), (0, y, self.w, 1))
            self._cache[key] = s
        return self._cache[key]

    def _edge(self, side):
        """Red glow along one screen edge (hurt direction)."""
        key = ("edge", side)
        if key not in self._cache:
            depth = 110
            if side in ("left", "right"):
                s = pygame.Surface((depth, self.h), pygame.SRCALPHA)
                for i in range(depth):
                    a = int(200 * (1 - i / depth) ** 2)
                    x = i if side == "left" else depth - 1 - i
                    s.fill((220, 20, 10, a), (x, 0, 1, self.h))
            else:
                s = pygame.Surface((self.w, depth), pygame.SRCALPHA)
                for i in range(depth):
                    a = int(200 * (1 - i / depth) ** 2)
                    y = i if side == "top" else depth - 1 - i
                    s.fill((220, 20, 10, a), (0, y, self.w, 1))
            self._cache[key] = s
        return self._cache[key]

    def _vignette(self):
        if "vig" not in self._cache:
            s = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
            for i in range(80):
                pygame.draw.rect(s, (170, 0, 0, int(170 * (1 - i / 80) ** 2)),
                                 (i, i, self.w - 2 * i, self.h - 2 * i), 1)
            self._cache["vig"] = s
        return self._cache["vig"]

    def hud(self, game):
        p, w, h = game.player, self.w, self.h
        if p.hurt_flash > 0:
            v = self._vignette()
            v.set_alpha(int(255 * min(1.0, p.hurt_flash * 3)))
            self.screen.blit(v, (0, 0))
        if p.hurt_dir_t > 0:
            a = p.hurt_dir
            side = ("top" if abs(a) < math.pi / 4 else
                    "bottom" if abs(a) > 3 * math.pi / 4 else
                    "right" if a > 0 else "left")
            e = self._edge(side)
            e.set_alpha(int(255 * min(1.0, p.hurt_dir_t / 0.5)))
            pos = {"left": (0, 0), "top": (0, 0), "right": (w - e.get_width(), 0),
                   "bottom": (0, h - e.get_height())}[side]
            self.screen.blit(e, pos)

        self.screen.blit(self._gradient_strip(96, 190), (0, h - 96))
        # health (bottom left)
        frac = max(0.0, p.hp / p.max_hp)
        col = GREEN if frac > 0.5 else (GOLD if frac > 0.25 else (235, 70, 55))
        self.text("HEALTH", self.f_s, DIM, bottomleft=(24, h - 64))
        hp_r = self.text(str(max(0, int(p.hp))), self.f_l, col, shadow=True,
                         bottomleft=(24, h - 20))
        bar = pygame.Rect(hp_r.right + 16, h - 42, 170, 14)
        pygame.draw.rect(self.screen, (40, 40, 38), bar)
        pygame.draw.rect(self.screen, col, (bar.x, bar.y, int(bar.w * frac), bar.h))
        # ammo (bottom right)
        self.text("AMMO", self.f_s, DIM, bottomright=(w - 24, h - 64))
        res_r = self.text(f"/ {p.reserved}", self.f_m, DIM, bottomright=(w - 24, h - 24))
        self.text("--" if p.reload_t > 0 else str(p.ammo), self.f_l,
                  (235, 70, 55) if p.ammo == 0 else GOLD, shadow=True,
                  bottomright=(res_r.left - 10, h - 20))
        # level / zombies (top left), score / time (top right)
        left = len(game.alive)
        self.text(game.level["name"], self.f_s, DIM, shadow=True, topleft=(20, 14))
        self.text(f"{plural(left, 'zombie')} left", self.f_m, FG, shadow=True, topleft=(20, 38))
        if self.keys.minimap:
            self.minimap.draw(self.screen, game, MINIMAP_POS)
        self.text(f"SCORE {p.score}", self.f_m, FG, shadow=True, topright=(w - 20, 14))
        par = game.level["par"]
        self.text(f"TIME {fmt_time(game.time)}  /  PAR {fmt_time(par)}", self.f_s,
                  (235, 120, 100) if game.time > par else DIM, shadow=True,
                  topright=(w - 20, 44))
        # crosshair + hit marker
        cx, cy = w // 2, h // 2
        for x0, y0, x1, y1 in ((cx - 12, cy, cx - 4, cy), (cx + 4, cy, cx + 12, cy),
                               (cx, cy - 12, cx, cy - 4), (cx, cy + 4, cx, cy + 12)):
            pygame.draw.line(self.screen, (0, 0, 0), (x0 + 1, y0 + 1), (x1 + 1, y1 + 1), 3)
            pygame.draw.line(self.screen, FG, (x0, y0), (x1, y1), 2)
        if p.hit_marker > 0 or p.kill_marker > 0:
            mc = (255, 70, 50) if p.kill_marker > 0 else (255, 255, 255)
            for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                pygame.draw.line(self.screen, mc, (cx + 7 * sx, cy + 7 * sy),
                                 (cx + 14 * sx, cy + 14 * sy), 2)
        # reload bar / prompts under the crosshair
        if p.reload_t > 0:
            prog = 1.0 - p.reload_t / RELOAD_TIME
            r = pygame.Rect(0, 0, 140, 8)
            r.midtop = (cx, cy + 34)
            pygame.draw.rect(self.screen, (30, 30, 30), r)
            pygame.draw.rect(self.screen, GOLD, (r.x, r.y, int(r.w * prog), r.h))
            self.text("RELOADING", self.f_s, GOLD, shadow=True, midtop=(cx, cy + 46))
        elif p.ammo == 0 and p.reserved == 0:
            self.text("OUT OF AMMO - kills drop ammo, find one", self.f_m, (235, 80, 60),
                      shadow=True, midtop=(cx, cy + 40))
        elif p.ammo <= 5 and p.reserved > 0:
            self.text(f"LOW AMMO - reload [{self.keys.label('reload')}]", self.f_s, GOLD,
                      shadow=True, midtop=(cx, cy + 40))

    def _gun(self):
        """First-person SMG + hands (procedural, cached). Returns
        (surface, muzzle point in surface coordinates)."""
        if "gun" not in self._cache:
            s = pygame.Surface((64, 56), pygame.SRCALPHA)
            skin, skin_d = (186, 146, 116), (146, 108, 84)
            pygame.draw.polygon(s, skin_d, [(6, 56), (26, 56), (28, 44), (14, 40)])
            pygame.draw.polygon(s, skin, [(8, 56), (24, 56), (26, 46), (15, 43)])
            pygame.draw.polygon(s, (50, 53, 58), [(21, 56), (45, 56), (41, 21), (25, 21)])
            pygame.draw.polygon(s, (78, 82, 90), [(25, 21), (41, 21), (38, 9), (28, 9)])
            pygame.draw.line(s, (112, 117, 126), (27, 21), (29, 10))
            pygame.draw.rect(s, (36, 40, 46), (29, 4, 8, 7))
            pygame.draw.rect(s, (8, 8, 8), (31, 5, 4, 4))
            pygame.draw.rect(s, (96, 100, 108), (32, 1, 2, 4))
            pygame.draw.polygon(s, skin_d, [(38, 56), (64, 56), (64, 38), (50, 32), (37, 42)])
            pygame.draw.polygon(s, skin, [(41, 56), (64, 56), (64, 41), (51, 35), (40, 44)])
            k = 4
            self._cache["gun"] = (pygame.transform.scale(s, (64 * k, 56 * k)), (33 * k, 3 * k))
        return self._cache["gun"]

    def viewmodel(self, player, live=True):
        gun, (mx, my) = self._gun()
        ph = player.walk * 2.2
        ox = math.sin(ph) * 12 * player.bob
        oy = abs(math.cos(ph)) * 10 * player.bob + player.kick * 18
        if player.reload_t > 0:
            oy += math.sin(math.pi * (1.0 - player.reload_t / RELOAD_TIME)) * 180
        x = int(self.w // 2 - gun.get_width() // 2 + 96 + ox)
        y = int(self.h - gun.get_height() + 36 + oy)
        self.screen.blit(gun, (x, y))
        if live and player.muzzle > 0:
            cx, cy = x + mx, y + my
            pts = []
            for i in range(12):
                r = 46 if i % 2 == 0 else 16
                a = i * math.pi / 6 + 0.3
                pts.append((cx + math.cos(a) * r, cy + math.sin(a) * r * 0.8))
            pygame.draw.polygon(self.screen, (255, 200, 90), pts)
            pygame.draw.circle(self.screen, (255, 250, 210), (cx, cy), 14)
