"""Level definitions: 3 hand-made maps, each with its own look and roster.

Map legend (strings, each char = one cell):
  #  wall (brick; mossy stone in the sewer theme)   %  concrete pillar
  =  metal wall      *  door (decorative)
  .  floor           S  player spawn       1/2/3  zombie spawns (walker/runner/brute)

The maps are fixed (not generated at runtime). The unit tests verify them:
rectangular, every zombie spawn reachable from S, marker counts match the
declared roster.
"""
from collections import Counter

LEVELS = [
    {
        "name": "Level 1 - The Alley",
        "desc": "Narrow backstreets. A few walkers. Clear them all.",
        "theme": "alley",
        "map": [
            "#####*#############*######",
            "#S............##..#......#",
            "#.#.......#######.#..#.#.#",
            "#.#......##.###...#..#.#.#",
            "#.#.....##....#.1.#...1#.#",
            "#.#...#.#..####.......##.#",
            "#.##..#......##.1.....##.#",
            "#.##..#......#..####..##.#",
            "#.....#..........##...#..#",
            "*....###*###..........#..#",
            "#.......##.2.#...##..##..#",
            "#1..##..#....#.......#####",
            "#..1##..#....#....##.#...*",
            "#...##..#...###........1.#",
            "########*###########*#####",
        ],
        "fog": 0.035,
        "fog_color": (14, 16, 22),
        "floor": (82, 78, 70),
        "ceiling": (34, 38, 54),
        "zombies": {"walker": 6, "runner": 1, "brute": 0},
        "par": 90,
    },
    {
        "name": "Level 2 - Abandoned Plant",
        "desc": "Open factory floor, pillar columns, faster crowds.",
        "theme": "plant",
        "map": [
            "==========================",
            "=S...........=...........=",
            "=............=.......%...=",
            "=.....2......=2....3%..%.=",
            "=........1.........%..%..=",
            "=............=.....%.....=",
            "=11.........1=....2......=",
            "======.============.======",
            "=............=...........=",
            "=.2.....%....=...........=",
            "=....2%............%.....=",
            "=........%...=.......2...=",
            "=......1.%...=...%.1.....=",
            "=.........1..=...........=",
            "==========================",
        ],
        "fog": 0.03,
        "fog_color": (20, 20, 24),
        "floor": (96, 92, 84),
        "ceiling": (58, 60, 66),
        "zombies": {"walker": 7, "runner": 6, "brute": 1},
        "par": 120,
    },
    {
        "name": "Level 3 - The Sewer",
        "desc": "A dark maze. Everything that crawls here wants your blood.",
        "theme": "sewer",
        "map": [
            "##########################",
            "#S..#..3....#1......2..3##",
            "###.#.#######1#########.##",
            "#...#.#..1.2..#.#.......##",
            "#.###.#.#######2#.#####.##",
            "#.#...#.#.......#...#.#.##",
            "#.#.###.###.#####.#.#.#.##",
            "#.#.....2...#...#.#.#...##",
            "#.#.#########.#.#.#.###.##",
            "#.#...#.#.....#2#3#..1#.##",
            "#.###.#.#.#####.#####.#.##",
            "#.1.#.#.#1#...#.....#.#.##",
            "###.#.#.#.#.#.#####.#.####",
            "#...#...#.#.#.#2....#1..##",
            "#.#######1#.###.#######.##",
            "#.#.2.....#.....#...#...##",
            "#.#.#######.#####.#.#.#.##",
            "#...#.............#...#2##",
            "##########################",
        ],
        "fog": 0.055,
        "fog_color": (8, 18, 10),
        "floor": (54, 70, 50),
        "ceiling": (46, 48, 42),
        "zombies": {"walker": 8, "runner": 8, "brute": 3},
        "par": 200,
    },
]

# height: drawn height in wall units; radius: hit/collision radius (tiles);
# windup: seconds a zombie telegraphs before its blow lands.
ZOMBIE_TYPES = {
    "walker": {"hp": 3, "speed": 1.6, "damage": 12, "score": 10,
               "height": 0.85, "radius": 0.28, "windup": 0.45},
    "runner": {"hp": 2, "speed": 3.2, "damage": 8, "score": 15,
               "height": 0.78, "radius": 0.25, "windup": 0.30},
    "brute": {"hp": 8, "speed": 1.1, "damage": 25, "score": 40,
              "height": 1.05, "radius": 0.38, "windup": 0.60},
}
TYPE_NAMES = ("walker", "runner", "brute")

WALL_CHARS = {"#": 1, "%": 2, "=": 3, "*": 4}
# per-theme texture overrides: the sewer's '#' walls use mossy stone (5)
THEME_WALLS = {"sewer": {"#": 5}}


def parse_level(idx):
    """Return (grid, spawns) for level idx. grid: rows of ints (0 = floor)."""
    lvl = LEVELS[idx]
    walls = dict(WALL_CHARS, **THEME_WALLS.get(lvl.get("theme"), {}))
    grid = []
    spawns = {"player": None, "zombies": []}
    for y, row in enumerate(lvl["map"]):
        line = []
        for x, ch in enumerate(row):
            if ch in walls:
                line.append(walls[ch])
                continue
            line.append(0)
            if ch == "S":
                spawns["player"] = (x + 0.5, y + 0.5)
            elif ch in "123":
                spawns["zombies"].append((x + 0.5, y + 0.5, int(ch) - 1))
        grid.append(line)
    return grid, spawns


def validate_level(idx):
    """Sanity: rectangular grid, has a spawn, roster matches the markers."""
    lvl = LEVELS[idx]
    grid, spawns = parse_level(idx)
    assert spawns["player"] is not None, f"level {idx}: no player spawn"
    assert len({len(r) for r in grid}) == 1, f"level {idx}: ragged map rows"
    marked = Counter(i for _, _, i in spawns["zombies"])
    expected = [lvl["zombies"][t] for t in TYPE_NAMES]
    got = [marked[i] for i in range(3)]
    assert got == expected, f"level {idx}: markers {got} != declared {expected}"
    return grid, spawns
