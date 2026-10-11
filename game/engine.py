"""Game engine: window, main loop, input routing and the screen state machine.

Each screen state has one key handler, one draw function and (for list
screens) one "activate item" function, registered in tables - so adding a
screen never means threading new branches through shared if/elif chains.

Input rules that hold everywhere:
  * Esc always pauses in game and always goes back / cancels in menus.
  * Nothing quits mid-game on a single key press; leaving a run goes
    through the pause menu and a confirmation.
"""
import json
import math
import os
import pygame

from .levels import LEVELS
from .game import Game, carry_over
from .raycaster import Textures, render_world
from .sprites import build_zombie_sprites
from .sound import Sfx
from .keys import KeyBindings, ACTIONS
from .save import SaveManager, SLOTS
from .ui import Ui, fmt_time

W, H = 960, 600
BW, BH = 640, 400   # 3D buffer: square pixels, scaled uniformly 1.5x to the window

(MENU, LEVEL_SELECT, PLAYING, PAUSED, SAVEDLG, KEYBIND,
 WIN, LOSE, CONFIRM, VICTORY) = range(10)

_UP = (pygame.K_UP,)
_DOWN = (pygame.K_DOWN,)
_OK = (pygame.K_RETURN, pygame.K_KP_ENTER)
_DIGITS = {pygame.K_1: 0, pygame.K_2: 1, pygame.K_3: 2,
           pygame.K_KP1: 0, pygame.K_KP2: 1, pygame.K_KP3: 2}


class Engine:
    def __init__(self, datadir):
        self.datadir = datadir
        os.makedirs(datadir, exist_ok=True)
        pygame.display.init()
        pygame.font.init()
        self.screen = pygame.display.set_mode((W, H))
        pygame.display.set_caption("Dead Zone")
        self.clock = pygame.time.Clock()
        self.keys = KeyBindings(os.path.join(datadir, "keys.json"))
        self.saves = SaveManager(os.path.join(datadir, "saves"))
        self.sfx = Sfx()
        self.tex = Textures(None, BW, BH)
        self.sprites = build_zombie_sprites()
        self.ui = Ui(self.screen, W, H, self.keys)
        self.buf = pygame.Surface((BW, BH))
        self.best, self.unlocked = 0, 1
        self._load_progress()
        self.state = MENU
        self.sel = 0
        self.game = None
        self.bonus = None
        self.dlg_mode, self.dlg_back = "load", MENU
        self.bind_back, self.capturing = MENU, None
        self.confirm = None          # (prompt, detail, on_yes, back_state)
        self.msg, self.msg_t = None, 0.0
        self.running = True
        self.mouse_dx = 0
        self.fire_lock = False       # ignore a fire button still held from a menu click
        self.handlers = {
            MENU: (self._key_menu, self._draw_menu),
            LEVEL_SELECT: (self._key_levels, self._draw_levels),
            PLAYING: (self._key_playing, self._draw_playing),
            PAUSED: (self._key_paused, self._draw_paused),
            SAVEDLG: (self._key_dialog, self._draw_dialog),
            KEYBIND: (self._key_binds, self._draw_binds),
            WIN: (self._key_win, self._draw_win),
            LOSE: (self._key_lose, self._draw_lose),
            CONFIRM: (self._key_confirm, self._draw_confirm),
            VICTORY: (self._key_victory, self._draw_victory),
        }
        self.activators = {
            MENU: lambda i, pos: self._run_item(self._main_items(), i),
            PAUSED: lambda i, pos: self._run_item(self._pause_items(), i),
            LEVEL_SELECT: lambda i, pos: self._pick_level(i),
            SAVEDLG: lambda i, pos: self._pick_slot(i),
            KEYBIND: self._pick_bind_row,
        }

    # ---------- persistence ----------
    def _progress_path(self):
        return os.path.join(self.datadir, "best.json")

    def _load_progress(self):
        try:
            with open(self._progress_path(), "r", encoding="utf-8") as f:
                d = json.load(f)
            self.best = max(0, int(d.get("score", 0)))
            self.unlocked = min(len(LEVELS), max(1, int(d.get("unlocked", 1))))
        except (OSError, ValueError, TypeError, AttributeError):
            self.best, self.unlocked = 0, 1

    def _save_progress(self):
        try:
            with open(self._progress_path(), "w", encoding="utf-8") as f:
                json.dump({"score": self.best, "unlocked": self.unlocked}, f)
        except OSError:
            pass

    def record_best(self):
        if self.game and self.game.player.score > self.best:
            self.best = self.game.player.score
        self._save_progress()

    def _set_msg(self, text, t=2.5):
        self.msg, self.msg_t = text, t

    # ---------- navigation ----------
    def goto(self, state):
        self.state = state
        self.sel = 0
        self.ui.item_rects = []

    def ask(self, prompt, detail, on_yes):
        self.confirm = (prompt, detail, on_yes, self.state)
        self.state = CONFIRM

    def open_dialog(self, mode):
        self.dlg_mode, self.dlg_back = mode, self.state
        self.goto(SAVEDLG)

    def open_binds(self):
        self.bind_back, self.capturing = self.state, None
        self.goto(KEYBIND)

    def pause(self):
        self.goto(PAUSED)

    def resume(self):
        self.state = PLAYING
        self._mouse_enter()

    def quit_to_menu(self):
        self.record_best()
        self.game = None
        self.goto(MENU)

    def quit_app(self):
        self.record_best()
        self.running = False

    # ---------- game control ----------
    def _apply_level_look(self):
        lvl = self.game.level
        self.tex.apply_level(lvl, BW, BH)
        for s in self.sprites:
            s.apply_fog(lvl.get("fog_color", (0, 0, 0)))

    def start_level(self, idx, carry=None):
        self.game = Game(idx, self.sprites, carry=carry)
        self._apply_level_look()
        self.state = PLAYING
        self._set_msg(f"{LEVELS[idx]['name']}   -   par {fmt_time(LEVELS[idx]['par'])}", 3.0)
        self._mouse_enter()

    def new_campaign(self):
        self.start_level(0)

    def load_slot(self, slot):
        d = self.saves.load(slot)
        if d is None:
            self._set_msg(f"Slot {slot + 1} is empty" if not self.saves.exists(slot)
                          else f"Slot {slot + 1} can't be read")
            return False
        self.game = self.saves.restore(d, self.sprites)
        self._apply_level_look()
        self.state = PLAYING
        self.msg = None
        self._mouse_enter()
        return True

    def _do_save(self, slot):
        self.saves.save(slot, self.game)
        self.state = self.dlg_back
        self._set_msg(f"Saved to slot {slot + 1}")

    def _win(self):
        g = self.game
        self.bonus = g.finish()
        self.unlocked = max(self.unlocked, min(len(LEVELS), g.level_idx + 2))
        self.record_best()
        self.goto(WIN)
        self.sfx.play("win")

    def _advance(self):
        g = self.game
        if g.level_idx + 1 < len(LEVELS):
            self.start_level(g.level_idx + 1, carry_over(g.player.stats()))
        else:
            self.record_best()
            self.goto(VICTORY)

    # ---------- main loop ----------
    def run(self):
        while self.running:
            dt = min(self.clock.tick(60) / 1000.0, 0.05)
            for ev in pygame.event.get():
                self._on_event(ev)
            self._sync_mouse()            # before update: no input latency
            if self.state == PLAYING:
                self.update(dt)
            if self.msg_t > 0:
                self.msg_t -= dt
                if self.msg_t <= 0:
                    self.msg = None
            self.render()
            pygame.display.flip()

    def _sync_mouse(self):
        if self.state == PLAYING:
            if not pygame.event.get_grab():
                pygame.mouse.set_visible(False)
                pygame.event.set_grab(True)
            # Classic mouse look: take the accumulated relative motion, then
            # re-centre so the cursor never runs out at the window edge.
            if pygame.mouse.get_focused():
                self.mouse_dx = pygame.mouse.get_rel()[0]
                pygame.mouse.set_pos((W // 2, H // 2))
                pygame.mouse.get_rel()     # swallow the re-centre echo
            else:
                self.mouse_dx = 0          # Alt+Tab: don't turn from a stale delta
        else:
            if pygame.event.get_grab():
                pygame.event.set_grab(False)
            pygame.mouse.set_visible(True)

    def _mouse_enter(self):
        """Centre the cursor and zero motion when play (re)starts."""
        self.mouse_dx = 0
        self.fire_lock = True
        pygame.mouse.set_pos((W // 2, H // 2))
        pygame.mouse.get_rel()

    def _on_event(self, ev):
        if ev.type == pygame.QUIT:
            self.quit_app()                # window close button: always allowed
        elif ev.type == pygame.WINDOWFOCUSLOST and self.state == PLAYING:
            self.pause()                   # never keep playing blind
        elif ev.type == pygame.ACTIVEEVENT and ev.gain == 0 \
                and ev.state & pygame.APPINPUTFOCUS and self.state == PLAYING:
            self.pause()
        elif ev.type == pygame.KEYDOWN:
            self._on_key(ev.key)
        elif ev.type == pygame.MOUSEBUTTONDOWN:
            self._on_click(ev.button, ev.pos)
        elif ev.type == pygame.MOUSEMOTION and self.state in self.activators \
                and not self.capturing:
            i = self.ui.hit_item(ev.pos)
            if i is not None:
                self.sel = i

    def _on_key(self, key):
        self.handlers[self.state][0](key)

    def _on_click(self, button, pos):
        if self.state == KEYBIND and self.capturing:
            if button in (1, 2, 3):
                self.keys.assign(self.capturing, -button)
                self.capturing = None
            return
        if self.state == PLAYING:
            if -button == self.keys.bindings["pause"]:
                self.pause()
            elif -button == self.keys.bindings["map"]:
                self.toggle_minimap()
            return
        if button != 1 or self.state not in self.activators:
            return
        i = self.ui.hit_item(pos)
        if i is not None:
            self.sel = i
            self.activators[self.state](i, pos)

    # ---------- generic list menus ----------
    def _run_item(self, items, i):
        label, hotkey, fn = items[i]
        fn()

    def _menu_key(self, items, key):
        if key in _UP:
            self.sel = (self.sel - 1) % len(items)
        elif key in _DOWN:
            self.sel = (self.sel + 1) % len(items)
        elif key in _OK:
            self._run_item(items, self.sel)
        else:
            for i, (_, hotkey, _) in enumerate(items):
                if hotkey == key:
                    self.sel = i
                    self._run_item(items, i)
                    return

    def _main_items(self):
        return [("New game  [N]", pygame.K_n, self.new_campaign),
                ("Level select  [C]", pygame.K_c, lambda: self.goto(LEVEL_SELECT)),
                ("Load game  [L]", pygame.K_l, lambda: self.open_dialog("load")),
                ("Settings & key bindings  [K]", pygame.K_k, self.open_binds),
                ("Quit  [Q]", pygame.K_q, self.quit_app)]

    def _pause_items(self):
        lose = "Progress since your last save will be lost."
        return [("Resume  [Esc]", None, self.resume),
                ("Save game  [S]", pygame.K_s, lambda: self.open_dialog("save")),
                ("Load game  [L]", pygame.K_l, lambda: self.open_dialog("load")),
                ("Settings & key bindings  [K]", pygame.K_k, self.open_binds),
                ("Quit to main menu  [M]", pygame.K_m,
                 lambda: self.ask("Quit to the main menu?", lose, self.quit_to_menu)),
                ("Quit to desktop  [Q]", pygame.K_q,
                 lambda: self.ask("Quit to the desktop?", lose, self.quit_app))]

    # ---------- per-state input ----------
    def _key_menu(self, key):
        if key == pygame.K_ESCAPE:
            self.ask("Quit to the desktop?", "", self.quit_app)
        else:
            self._menu_key(self._main_items(), key)

    def _key_levels(self, key):
        if key == pygame.K_ESCAPE:
            self.goto(MENU)
        elif key in _UP:
            self.sel = (self.sel - 1) % len(LEVELS)
        elif key in _DOWN:
            self.sel = (self.sel + 1) % len(LEVELS)
        elif key in _OK:
            self._pick_level(self.sel)
        elif key in _DIGITS:
            self._pick_level(_DIGITS[key])

    def _pick_level(self, i):
        self.sel = i
        if i >= self.unlocked:
            self._set_msg(f"Locked - clear level {i} first")
        else:
            self.start_level(i)

    def _key_playing(self, key):
        if key == pygame.K_ESCAPE or key == self.keys.bindings["pause"]:
            self.pause()
        elif key == self.keys.bindings["map"] \
                and not pygame.key.get_mods() & pygame.KMOD_ALT:  # Alt+Tab switches windows
            self.toggle_minimap()

    def toggle_minimap(self):
        if self.keys.toggle_minimap():
            self._set_msg("Minimap on", 1.5)
        else:
            self._set_msg(f"Minimap off - press {self.keys.label('map')} to show it", 2.0)

    def _key_paused(self, key):
        items = self._pause_items()
        if key == pygame.K_ESCAPE:
            self.resume()
        elif key in _UP or key in _DOWN or key in _OK \
                or any(h == key for _, h, _ in items):
            self._menu_key(items, key)
        elif key == self.keys.bindings["pause"]:
            self.resume()

    def _key_dialog(self, key):
        if key == pygame.K_ESCAPE:
            self.state = self.dlg_back
        elif key in _UP:
            self.sel = (self.sel - 1) % SLOTS
        elif key in _DOWN:
            self.sel = (self.sel + 1) % SLOTS
        elif key in _OK:
            self._pick_slot(self.sel)
        elif key in _DIGITS:
            self._pick_slot(_DIGITS[key])
        elif key in (pygame.K_DELETE, pygame.K_BACKSPACE) and self.saves.exists(self.sel):
            slot = self.sel
            self.ask(f"Delete slot {slot + 1}?", "This can't be undone.",
                     lambda: (self.saves.delete(slot), self._set_msg(f"Slot {slot + 1} deleted")))

    def _pick_slot(self, slot):
        self.sel = slot
        if self.dlg_mode == "save":
            if self.saves.exists(slot):
                self.ask(f"Overwrite slot {slot + 1}?", "The old save will be replaced.",
                         lambda: self._do_save(slot))
            else:
                self._do_save(slot)
        else:
            self.load_slot(slot)

    def _key_binds(self, key):
        rows = len(ACTIONS) + 1
        sens_row = len(ACTIONS)
        if self.capturing:
            if key == pygame.K_ESCAPE:
                self.capturing = None
            elif self.keys.assign(self.capturing, key):
                self.capturing = None
            return
        if key == pygame.K_ESCAPE:
            self.state = self.bind_back
        elif key in _UP:
            self.sel = (self.sel - 1) % rows
        elif key in _DOWN:
            self.sel = (self.sel + 1) % rows
        elif key in _OK and self.sel < sens_row:
            self.capturing = ACTIONS[self.sel][0]
        elif key in (pygame.K_LEFT, pygame.K_MINUS, pygame.K_KP_MINUS):
            self.sel = sens_row
            self.keys.adjust_sens(-0.1)
        elif key in (pygame.K_RIGHT, pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
            self.sel = sens_row
            self.keys.adjust_sens(0.1)
        elif key == pygame.K_r:
            self.keys.reset()
            self._set_msg("Bindings reset to defaults")

    def _pick_bind_row(self, i, pos):
        if i < len(ACTIONS):
            self.capturing = ACTIONS[i][0]
        else:
            r = self.ui.item_rects[i]
            # the "<  1.0x  >" value is drawn from r.left + 360; its middle
            # splits the "<" half from the ">" half
            self.keys.adjust_sens(-0.1 if pos[0] < r.left + 415 else 0.1)

    def _key_win(self, key):
        if key in _OK or key in (pygame.K_n, pygame.K_SPACE):
            self._advance()
        elif key == pygame.K_ESCAPE:
            self.quit_to_menu()

    def _key_lose(self, key):
        if key in _OK or key == pygame.K_r:
            g = self.game
            self.start_level(g.level_idx, g.entry)
        elif key == pygame.K_ESCAPE:
            self.quit_to_menu()

    def _key_victory(self, key):
        if key in _OK or key == pygame.K_ESCAPE:
            self.quit_to_menu()

    def _key_confirm(self, key):
        prompt, detail, on_yes, back = self.confirm
        if key in _OK or key == pygame.K_y:
            self.confirm = None
            self.state = back
            on_yes()
        elif key in (pygame.K_n, pygame.K_ESCAPE):
            self.confirm = None
            self.state = back

    # ---------- update ----------
    def update(self, dt):
        g = self.game
        inp = self.keys.poll_state(pygame.key.get_pressed(), pygame.mouse.get_pressed(3))
        fire = inp["shoot"] or inp["shoot_alt"]
        if self.fire_lock:
            if fire:
                fire = False
            else:
                self.fire_lock = False
        inp["shoot"] = fire
        inp["mouse_dx"], self.mouse_dx = self.mouse_dx, 0
        inp["sens"] = self.keys.sens
        g.update(dt, inp)
        self._play_events()
        if g.player.dead:
            self.record_best()
            self.goto(LOSE)
            self.sfx.play("lose")
        elif not g.alive:
            self._win()

    def _play_events(self):
        g = self.game
        for name, z in g.events:
            if z is None:
                self.sfx.play(name)
            else:
                self.sfx.play(name, *self._spatial(z.x, z.y))
        g.events.clear()

    def _spatial(self, x, y):
        """(volume, pan) for a sound at world (x, y), heard by the player."""
        p = self.game.player
        dx, dy = x - p.x, y - p.y
        d = math.hypot(dx, dy)
        rel = math.atan2(dy, dx) - p.angle
        return 1.0 / (1.0 + 0.3 * d), math.sin(rel) * min(1.0, d)

    # ---------- render ----------
    def render(self):
        self.handlers[self.state][1]()
        if self.msg:
            self.ui.toast(self.msg)

    def _draw_world(self, hud=True):
        g = self.game
        render_world(self.buf, g.player, g.grid, self.tex, g.zombies, BW, BH)
        pygame.transform.scale(self.buf, (W, H), self.screen)
        self.ui.viewmodel(g.player, live=hud)
        if hud:
            self.ui.hud(g)

    def _hint_line(self):
        k = self.keys.label
        return (f"{k('fwd')}/{k('strafe_l')}/{k('back')}/{k('strafe_r')} move   |   "
                f"mouse or {k('turn_l')}/{k('turn_r')} turn   |   {k('shoot')} or "
                f"{k('shoot_alt')} shoot   |   {k('reload')} reload   |   {k('map')} map   |   Esc pause")

    def _draw_menu(self):
        items = self._main_items()
        self.ui.main_menu(self.best, [i[0] for i in items], self.sel, self._hint_line())

    def _draw_levels(self):
        self.ui.level_select(LEVELS, self.unlocked, self.sel)

    def _draw_playing(self):
        self._draw_world()

    def _draw_paused(self):
        self._draw_world(hud=False)
        self.ui.pause([i[0] for i in self._pause_items()], self.sel)

    def _draw_dialog(self):
        if self.game is not None:
            self._draw_world(hud=False)
            self.ui.dim(200)
        else:
            self.ui.bg()
        self.ui.save_load(self.dlg_mode, [self.saves.info(s) for s in range(SLOTS)],
                          self.sel)

    def _draw_binds(self):
        self.ui.key_bind(self.sel, self.capturing)

    def _draw_win(self):
        self.ui.win(self.game, self.bonus, self.game.level_idx + 1 >= len(LEVELS))

    def _draw_lose(self):
        self.ui.lose(self.game.player, self.game.level["name"])

    def _draw_victory(self):
        self.ui.victory(self.game.player.score if self.game else 0, self.best)

    def _draw_confirm(self):
        back = self.confirm[3]
        if self.game is not None and back in (PAUSED, SAVEDLG, PLAYING):
            self._draw_world(hud=False)
        else:
            self.ui.bg()
        self.ui.confirm(self.confirm[0], self.confirm[1])
