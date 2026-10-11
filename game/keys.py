"""Key and mouse bindings, mouse sensitivity and minimap visibility,
persisted to keys.json.

An action maps to a pygame key constant (> 0) or a mouse button
(MOUSE_LEFT / MOUSE_MIDDLE / MOUSE_RIGHT, stored as -1 / -2 / -3).

Esc is reserved: it always pauses in game and always goes back in menus,
so it can't be bound and no rebinding can lock you out of the pause menu.
Binding a key that another action uses swaps the two bindings, so every
action always keeps a key.
"""
import json
import os
import pygame

MOUSE_LEFT, MOUSE_MIDDLE, MOUSE_RIGHT = -1, -2, -3
MOUSE_NAMES = {MOUSE_LEFT: "MOUSE LEFT", MOUSE_MIDDLE: "MOUSE MIDDLE",
               MOUSE_RIGHT: "MOUSE RIGHT"}
RESERVED = {pygame.K_ESCAPE}

ACTIONS = [
    ("fwd", "Move forward"), ("back", "Move backward"),
    ("strafe_l", "Strafe left"), ("strafe_r", "Strafe right"),
    ("turn_l", "Turn left"), ("turn_r", "Turn right"),
    ("sprint", "Sprint"), ("shoot", "Shoot"), ("shoot_alt", "Shoot (alternate)"),
    ("reload", "Reload"), ("map", "Toggle minimap"),
    ("pause", "Pause (Esc always works)"),
]

DEFAULTS = {
    "fwd": pygame.K_w,
    "back": pygame.K_s,
    "strafe_l": pygame.K_a,
    "strafe_r": pygame.K_d,
    "turn_l": pygame.K_LEFT,
    "turn_r": pygame.K_RIGHT,
    "sprint": pygame.K_LSHIFT,
    "shoot": MOUSE_LEFT,
    "shoot_alt": pygame.K_SPACE,
    "reload": pygame.K_r,
    "map": pygame.K_TAB,
    "pause": pygame.K_p,
}
PRESS_ACTIONS = ("pause", "map")     # act once per key press, not while held
HELD_ACTIONS = tuple(a for a, _ in ACTIONS if a not in PRESS_ACTIONS)

SENS_DEFAULT, SENS_MIN, SENS_MAX = 1.0, 0.2, 3.0


def _build_key_names():
    names = {}
    for attr in dir(pygame):
        if attr.startswith("K_"):
            val = getattr(pygame, attr)
            if isinstance(val, int) and val > 0:
                try:
                    names[val] = pygame.key.name(val).upper()
                except Exception:
                    pass
    return names


KEY_NAMES = _build_key_names()


def valid_code(code):
    if not isinstance(code, int) or isinstance(code, bool):
        return False
    return code in MOUSE_NAMES or (code > 0 and code not in RESERVED)


class KeyBindings:
    def __init__(self, path):
        self.path = path
        self.bindings = dict(DEFAULTS)
        self.sens = SENS_DEFAULT
        self.minimap = True
        self.load()

    def load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return  # corrupt file -> defaults
        if not isinstance(data, dict):
            return
        for action in DEFAULTS:
            code = data.get(action)
            if valid_code(code):
                # same swap rule as assign(): stays conflict-free even if
                # the file was hand-edited into duplicates
                old = self.bindings[action]
                for a, k in self.bindings.items():
                    if a != action and k == code:
                        self.bindings[a] = old
                self.bindings[action] = code
        sens = data.get("_mouse_sens")
        if isinstance(sens, (int, float)) and not isinstance(sens, bool):
            self.sens = min(SENS_MAX, max(SENS_MIN, float(sens)))
        if isinstance(data.get("_minimap"), bool):
            self.minimap = data["_minimap"]

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(dict(self.bindings, _mouse_sens=self.sens,
                               _minimap=self.minimap), f, indent=2)
        except OSError:
            pass

    def reset(self):
        self.bindings = dict(DEFAULTS)
        self.sens = SENS_DEFAULT
        self.minimap = True
        self.save()

    def assign(self, action, code):
        """Bind `code` to `action`; an action already using it takes this
        action's old binding (swap). Returns False for reserved/invalid."""
        if action not in DEFAULTS or not valid_code(code):
            return False
        old = self.bindings[action]
        for a, k in self.bindings.items():
            if a != action and k == code:
                self.bindings[a] = old
        self.bindings[action] = code
        self.save()
        return True

    def toggle_minimap(self):
        self.minimap = not self.minimap
        self.save()
        return self.minimap

    def adjust_sens(self, delta):
        self.sens = round(min(SENS_MAX, max(SENS_MIN, self.sens + delta)), 2)
        self.save()

    def label(self, action):
        code = self.bindings.get(action, 0)
        if code in MOUSE_NAMES:
            return MOUSE_NAMES[code]
        if code <= 0:
            return "-"
        return KEY_NAMES.get(code) or pygame.key.name(code).upper() or "?"

    def is_down(self, action, held, mouse=None):
        """`held` is pygame.key.get_pressed() (index it by key constant -
        never use `in`); `mouse` is pygame.mouse.get_pressed()."""
        code = self.bindings.get(action, 0)
        if code > 0:
            return bool(held[code])
        if code < 0 and mouse is not None:
            i = -code - 1
            return i < len(mouse) and bool(mouse[i])
        return False

    def poll_state(self, held, mouse=None):
        """Booleans for every held action (movement, turning, fire, reload)."""
        return {a: self.is_down(a, held, mouse) for a in HELD_ACTIONS}
