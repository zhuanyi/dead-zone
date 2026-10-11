"""Grid queries shared by the player, the zombies and the renderer:
collision, line of sight, and the BFS flow field zombies follow to reach
the player through corridors instead of pushing into the nearest wall."""
import math
from collections import deque

FLOW_INF = 1 << 30
_N4 = ((1, 0), (-1, 0), (0, 1), (0, -1))
_N8 = _N4 + ((1, 1), (1, -1), (-1, 1), (-1, -1))


def blocked(x, y, grid):
    """True if the point (x, y) is inside a wall or outside the map."""
    if not (0 <= y < len(grid) and 0 <= x < len(grid[0])):
        return True
    return grid[int(y)][int(x)] > 0


def can_occupy(x, y, r, grid):
    """True if a body of half-size r centred at (x, y) touches no wall -
    all four corners are tested, so a body can't slide its edge into a
    wall when it enters a row/column where that wall begins."""
    return not (blocked(x - r, y - r, grid) or blocked(x + r, y - r, grid)
                or blocked(x - r, y + r, grid) or blocked(x + r, y + r, grid))


def slide_move(x, y, nx, ny, r, grid):
    """Axis-separated move with wall sliding. Returns the new (x, y).
    A body already overlapping a wall (e.g. an old save) may move anywhere
    its centre stays out of walls, so it can always work itself free."""
    stuck = not can_occupy(x, y, r, grid)
    ok = (lambda px, py: not blocked(px, py, grid)) if stuck else \
        (lambda px, py: can_occupy(px, py, r, grid))
    if ok(nx, y):
        x = nx
    if ok(x, ny):
        y = ny
    return x, y


def segment_clear(x0, y0, x1, y1, grid, step=0.125):
    """True if no wall lies on the segment (sampled every `step` tiles)."""
    dx, dy = x1 - x0, y1 - y0
    n = int(math.hypot(dx, dy) / step) + 1
    for i in range(1, n):
        t = i / n
        if blocked(x0 + dx * t, y0 + dy * t, grid):
            return False
    return True


def body_clear(x0, y0, x1, y1, grid, r=0.2):
    """segment_clear for a body of radius r: the centre line and both
    flanks must be free, so a zombie never steers into a wall corner."""
    dx, dy = x1 - x0, y1 - y0
    d = math.hypot(dx, dy)
    if d < 1e-9:
        return True
    ox, oy = -dy / d * r, dx / d * r
    return (segment_clear(x0, y0, x1, y1, grid)
            and segment_clear(x0 + ox, y0 + oy, x1 + ox, y1 + oy, grid)
            and segment_clear(x0 - ox, y0 - oy, x1 - ox, y1 - oy, grid))


def flow_field(grid, tx, ty):
    """Path distance (in tiles, 4-connected) from every floor tile to
    tile (tx, ty). Walls and unreachable tiles hold FLOW_INF."""
    h, w = len(grid), len(grid[0])
    dist = [[FLOW_INF] * w for _ in range(h)]
    if not (0 <= tx < w and 0 <= ty < h) or grid[ty][tx]:
        return dist
    dist[ty][tx] = 0
    q = deque([(tx, ty)])
    while q:
        x, y = q.popleft()
        nd = dist[y][x] + 1
        for dx, dy in _N4:
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and not grid[ny][nx] \
                    and dist[ny][nx] > nd:
                dist[ny][nx] = nd
                q.append((nx, ny))
    return dist


def flow_dist(dist, x, y):
    cx, cy = int(x), int(y)
    if 0 <= cy < len(dist) and 0 <= cx < len(dist[0]):
        return dist[cy][cx]
    return FLOW_INF


def flow_step(dist, grid, x, y):
    """Centre of the neighbouring tile (8-way, no corner cutting) that is
    closest to the flow target, or None if no neighbour is closer."""
    cx, cy = int(x), int(y)
    h, w = len(grid), len(grid[0])
    best, bd = None, flow_dist(dist, x, y)
    for dx, dy in _N8:
        nx, ny = cx + dx, cy + dy
        if not (0 <= nx < w and 0 <= ny < h) or grid[ny][nx]:
            continue
        if dx and dy and (grid[cy][nx] or grid[ny][cx]):
            continue  # diagonal would clip a wall corner
        if dist[ny][nx] < bd:
            best, bd = (nx + 0.5, ny + 0.5), dist[ny][nx]
    return best


def ray_length(grid, x, y, ang, max_d=32.0, step=0.1):
    """Distance a ray travels from (x, y) before it hits a wall."""
    c, s = math.cos(ang), math.sin(ang)
    d = 0.0
    while d < max_d:
        d += step
        if blocked(x + c * d, y + s * d, grid):
            break
    return d


def open_direction(grid, x, y, samples=32):
    """Facing with the longest clear view - the player never spawns
    staring at a wall."""
    best = max(range(samples),
               key=lambda i: (ray_length(grid, x, y, i * 2 * math.pi / samples), -i))
    return best * 2 * math.pi / samples
