# Changes in this version

## New: minimap

- A **minimap** in the top-left corner, under the zombie count, shows the
  whole level north up. Levels are small, so all of it fits (7 px per tile).
  - **You:** a white arrow, plus a pale cone for your field of view. Each ray of
    the cone stops at the first wall, so it shows what you can actually see.
  - **Zombies:** every one still standing. A **filled red dot** is hunting you;
    a **hollow ring** hasn't noticed you yet. Brutes are bigger. Corpses aren't
    drawn, but drops on them are: **yellow** = ammo, **white** = health.
  - **Orientation:** map right is world +x and map down is world +y, the same
    handedness as the 3D view. Facing up the map, what's on your right on
    screen is right of the arrow, so the map is never mirrored against the view.
  - **Wall colours:** muted per level (brick, steel, mossy stone) so the markers
    stand out. Doors are drawn as plain wall so they don't read as exits.
- **Tab** shows or hides it. It's a normal bindable action ("Toggle minimap",
  including mouse buttons) that acts once per press. Alt+Tab is ignored, so
  switching windows on Windows doesn't flip it. The choice is saved in
  `keys.json`. A short message says how to bring the map back.
- **Cost:** the walls are drawn once per level and cached; each frame only
  redraws the cone, markers and arrow, about 0.2 ms with 19 zombies.
- **Balance:** unchanged. The bot used to tune difficulty already knew where
  every zombie was, so the minimap brings a human closer to what the tuning
  assumed.
- **Tests:** 11 new ones cover the markers per zombie state, the cone direction
  and stopping at walls, the map not being mirrored against the view, fitting
  the corner in every level, the wall layer being cached, and the toggle (key,
  mouse button, Alt+Tab, saved setting). Each was checked by deliberately
  breaking the behaviour it covers.

## Fixes from the design review

Every item from the design review, what changed, and how it was checked.
"Before/after" numbers come from headless simulations of the real game code.

### 1. Zombies can now navigate
- Zombies follow a **BFS flow field** (walking distance to the player,
  recomputed when the player changes tile) instead of steering straight at
  you into walls. With a clear path they steer directly.
- **Aggro model:** zombies idle until they see you (8 tiles), you get close
  (2.5 tiles), or they hear a gunshot (11 tiles of walking distance). A woken
  zombie wakes its neighbours; the last 3 always hunt you.
- **Collision bug fixed (was in the original too):** movement checked one
  axis at a time without the body's corners, so a body entering a row where a
  side wall begins slid its edge into the wall and was stuck there for good.
  Bodies now test all four corners (`world.can_occupy` / `slide_move`).
- Before: parked at spawn, 0 of 19 Sewer zombies ever reached you (5/7 in
  the Alley, 7/14 in the Plant were permanently pinned on walls).
  After: every zombie in every level reaches the player (slowest: a brute
  with a 150-tile path, 131 s).

### 2. Shooting needs aim; ammo matters
- Hitscan now tests each zombie's **body radius** along the crosshair line
  (walker 0.28, runner 0.25, brute 0.38 tiles) and hits the **nearest one on
  the line**. The old ±10° cone hit zombies ~60 px off the sprite and could
  hit a nearer zombie instead of the one under the crosshair.
- Ammo: 30 + 45 reserve to start (was 30 + 120), pickups +10 (was +20) and
  go to the **reserve** (they used to refill the magazine — a free reload).
  Pity rule: when you're nearly out, kills always drop ammo, so a run can't
  soft-lock. A sloppy-aim bot now finishes the Plant with ~28 rounds left.
- Dry fire clicks; "LOW AMMO" / "OUT OF AMMO" prompts.

### 3. Stakes and scoring
- **Campaign:** health, ammo and score carry between levels (with a floor of
  50 HP / 60 rounds). Retry restarts the level with the stats you entered it
  with. Levels unlock in order.
- **Score** = kill points + per-level clear bonus: base, **time under par**
  (`par` is now used; par times re-tuned to 1:30 / 2:00 / 3:20), accuracy,
  remaining health. The best score is the best *run*; bot runs now score
  anywhere from ~570 to ~2,260, so skill shows.
- Health pickups stay on the floor while you're at full health; drops are
  biased to ammo when you're unhurt. Drop rolls moved out of `Player` (they
  used the zombie's private RNG) into `Game`.

### 4. Feedback / game feel
- First-person **gun** with walk bob, recoil kick, **muzzle flash** (the old
  timer was never drawn) and a reload dip animation.
- Zombies: 2-frame **walk** animation, arms-up **attack wind-up** (0.3–0.6 s,
  dodgeable by backing off), **death** collapse and corpses that stay, white
  hit flash, crosshair **hit / kill markers**.
- Player can no longer walk through zombies (**body-blocking**).
- **Audio:** real noise-burst gunshot (the old "noise" was a 4.5 kHz sine),
  zombie alert growls, groans and swipes **positioned in stereo**, kill,
  dry-fire and hit sounds.
- Red edge glow shows **which side** you were hit from.

### 5. Controls
- **Left mouse button shoots** by default (Space is the alternate). Mouse
  buttons can be bound to any action.
- **No instant quit:** the in-game Quit action is gone; leaving a run goes
  through the pause menu and a confirmation.
- **Esc always pauses / goes back** and can't be rebound, so no rebinding can
  strand you (the "rebind Pause, then Esc discards the run" and "bind Quit to
  Esc, Pause becomes unbound" traps are gone). Rebinding a used key **swaps**
  the two actions instead of unbinding one.
- **Mouse sensitivity** setting. Spawn facing is the most open direction
  instead of random. The control hint is generated from the live bindings.

### 6. Visuals and UI
- **Correct proportions:** one focal length for both axes and a uniform 1.5×
  scale of the 640×400 buffer to the 960×600 window (no letterbox). Walls are
  square; sprites keep their art's aspect ratio and stand on the floor.
- **Floors and ceilings** are visible per-level colours (were ~RGB(5,6,4)),
  baked into one backdrop with per-row distance shading and fog — no
  vertical bands or stripes, and 1 blit per frame instead of 1,280.
- Per-level **fog colours**; the Sewer has its own mossy-stone walls; the door
  texture is used in the Alley.
- Menus: titles at the top, text centred by measured width, aligned key
  column, selection highlight, mouse hover/click, confirmation dialogs,
  locked-level display, correct plurals ("1 runner").
- HUD: health and ammo equally prominent, zombies left, score, time vs par,
  reload bar.

### 7. Code
- `Engine` is a table of per-state handlers (input / draw / activate) instead
  of shared if/elif chains; rules live in `game.Game`; grid queries in
  `world.py` (no duplicated `_blocked`); single `main()`; smoke test is a
  module, not a monkey-patch; layout constants live in one place (`ui.py`).
- Saves: v3 drops the RNG state (139 KB → ~3 KB), validates level index,
  zombie count and field types, shows unreadable slots as such, asks before
  overwriting, and still loads v2 saves.
- Rendering: sprites scale only an art-width strip, so a zombie in your face
  costs the same as a distant one (was ~21 ms/frame → ~4.6 ms here).
- Tests: rewritten — 74 tests, including a regression test for each review
  item; the old shooting-test double whose `hurt()` meant the opposite of the
  real one is gone (tests use the real `Zombie`). Key regression tests were
  verified to fail when their fix is reverted.
