# TCsMetroid

Metroidvania route planner, randomizer and game. A Flask web app that models a Metroidvania map as a graph. Rooms are nodes; gates are
edges guarded by ability rules such as `J | (D & G)`. The app can:

- **Check** whether a map can be finished (fixed-point BFS, grouped into spheres)
- **Route** the fastest path to the boss with BFS, DFS, Dijkstra and A\* side by side
- **Randomize** item locations into seeds that are guaranteed to stay beatable
- **Analyze** ability order, required items, soft-lock traps, regions and one-way splits
- **Rank** thousands of seeds with hand-written sorting and binary search
- **Design** maps visually: drag rooms, draw doors, and see the map re-checked after every change
- **Start from templates** (hub and spokes, lock and key, one-way trap) or save your own
- **Experiment in a sandbox** without touching saved maps
- **Invent power-ups**: every map has its own list of abilities and collectibles, with letters, names and colours
- **Zoom and pan** the designer and sandbox canvas (buttons, Ctrl + scroll, pinch)
- **Play** any map as a top-down action game: doors, enemies, a guardian boss, an energy HUD, a minimap and soft-lock warnings
- **Export for games**: JSON with parsed rule trees and pre-computed analysis (see `examples/load_map.py`)
- **Animated backgrounds** (graph constellation, perspective grid, hyperspace warp), page transitions and scroll reveals, all switched off by the OS "reduce motion" setting
- **Light and dark mode** from the TCsMetroid moodboard (charcoal, Metroid red, light blue, lime), remembered per browser
- **Responsive** layout with a menu button on tablets and phones
- **Edit** maps in a table editor, and import/export them as JSON
- **Serve** everything through a JSON API

Every data structure the algorithms rely on (queue, stack, min-heap, union-find, the rule
parser) is written from scratch in `app/engine/`, so the algorithms can be read and tested
on their own. networkx is used only in the tests, to cross-check the results.

## Run it

Requires Python 3.10 or newer.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Open http://127.0.0.1:5000. On first run the app creates `instance/planner.db` and loads the
13-room demo map, "Derelict Outpost".

Run the tests:

```bash
pytest
```

Reset the database to just the demo map:

```bash
flask --app run reset-db
```

## Project layout

```
app/
  engine/              pure Python, no Flask or database imports
    rules.py           tokenizer, recursive-descent parser, expression tree (AST)
    structures.py      Queue, Stack, MinHeap, UnionFind
    graph.py           WorldGraph: adjacency list of rooms and gates
    checker.py         beatability check (fixed-point BFS, spheres, blocked gates)
    search.py          BFS, DFS, Dijkstra, A* over (room, abilities) states
    randomizer.py      Fisher-Yates, shuffle & reroll, assumed fill, seed codes
    analysis.py        Kahn's topological sort, criticality, union-find regions,
                       Tarjan's SCC, danger zones (forward + reverse search)
    sorting.py         merge sort, 3-way quicksort, binary search (lower bound)
  models.py            SQLAlchemy: Map, Room, Gate, Seed
  services.py          generate and store seeds
  routes.py            HTML pages
  api.py               JSON API
  views.py             turns engine results into SVG-ready data for templates
  templates/           Jinja templates
  static/style.css
  demo_map.py          the sample map
  map_templates.py     built-in starting layouts
  static/designer.js   drag-and-drop designer (browser side)
  static/game.js       the playable game (browser side)
  static/motion.js     animated backgrounds, page motion, mobile menu
  engine/powerups.py   per-map power-up lists
tests/                 171 pytest tests
examples/load_map.py   using an exported map without the planner
run.py
```

## Algorithms and data structures

| Concept | Where | Used for |
|---|---|---|
| Graph (adjacency list) | `engine/graph.py` | The map itself |
| Bitmask | `engine/rules.py` | A set of abilities stored as one integer |
| Queue | `engine/structures.py` | BFS, Kahn's algorithm, danger-zone search |
| Stack | `engine/structures.py` | DFS, Tarjan's SCC |
| Min-heap | `engine/structures.py` | Dijkstra, A\*, relaxed heuristic |
| Hash map | `engine/search.py` | Visited states mapped to their parent |
| Linked list | `engine/search.py` | Parent pointers walked back from the boss to rebuild the route |
| Tree | `engine/rules.py` | Parsed gate rules |
| Union-find | `engine/structures.py` | Connected regions |
| BFS | `engine/checker.py`, `search.py` | Beatability, fewest-moves route |
| DFS | `engine/search.py` | Comparison baseline |
| Dijkstra | `engine/search.py` | Fastest route in seconds |
| A\* | `engine/search.py` | Fastest route with fewer states expanded |
| Recursive-descent parsing | `engine/rules.py` | Gate rules |
| Fixed-point iteration | `engine/checker.py` | Spheres of progression |
| Kahn's topological sort | `engine/analysis.py` | Ability order, cycle (soft-lock) detection |
| Tarjan's SCC | `engine/analysis.py` | Parts of the map split by one-way drops |
| Reverse reachability | `engine/analysis.py` | States the player can reach but never finish from |
| Fisher-Yates shuffle | `engine/randomizer.py` | Unbiased shuffling |
| Assumed fill | `engine/randomizer.py` | Randomizer that is beatable by construction |
| Merge sort | `engine/sorting.py` | Stable leaderboard sort |
| 3-way quicksort | `engine/sorting.py` | Fast sort with many equal keys |
| Binary search | `engine/sorting.py` | First seed at or above a target |

### Why search over states, not rooms

Which gates you can open depends on what you have picked up, so the same room can matter
several times. Every search works on `(room, abilities held)` pairs. With 4 abilities, that
is at most 16 states per room, so the search space is O(R · 2^A).

### Why A\* stays optimal

A\*'s estimate is the fastest time to the boss **if every gate were open**. Removing
constraints can only make a trip shorter, so the estimate never overestimates (it is
admissible), and A\* returns the same time as Dijkstra while expanding fewer states. On the
demo map: Dijkstra expands 37 states, A\* expands 25, and both find 221 seconds.

## JSON API

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/maps` | | map list |
| POST | `/api/maps` | map JSON | `{id, name}` (201) |
| GET | `/api/maps/<id>` | | map JSON |
| POST | `/api/maps/<id>/check` | `{"placement": {...}}` optional | beatable, spheres, blocked gates |
| GET/POST | `/api/maps/<id>/route?algorithm=astar` | `{"placement": {...}}` optional | route steps and stats |
| POST | `/api/maps/<id>/randomize` | `{"seed": 42, "algorithm": "assumed"}` | stored seed |

Example:

```bash
curl -X POST http://127.0.0.1:5000/api/maps/1/randomize \
     -H "Content-Type: application/json" -d '{"seed": 42, "algorithm": "assumed"}'
```

## Map JSON format

```json
{
  "name": "Derelict Outpost",
  "start": "landing",
  "boss": "boss",
  "rooms": [{"key": "cave", "name": "Mossy Cave", "x": 2, "y": 3, "seconds": 12, "item": "M"}],
  "gates": [{"a": "hall", "b": "shaft", "rule": "M", "one_way": false}]
}
```

Items: `M` Morph Ball, `D` Dash Boots, `J` Double Jump, `G` Grapple Beam, `E` Energy Tank (filler).
Rules use `M D J G`, `&` or `AND`, `|` or `OR`, and parentheses. An empty rule is an open door.

## Known limits

- A map can have up to 16 power-ups, 10 of them abilities (the search space grows as rooms × 2^abilities).
- Rooms are drawn on a grid with straight-line gates, so gates between non-neighboring cells can cross.
- Seed batches are generated inside the request. Very large batches (thousands) take a few seconds.
