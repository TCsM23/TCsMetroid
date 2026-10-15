"""Load a map exported with "Export for games" and use it from your own game.

Run it from the project folder:
    python examples/load_map.py exported-map.json

Nothing here imports Flask or the planner. A game only needs the JSON file.
"""
import json
import sys


def door_opens(door: dict, held: set[str]) -> bool:
    """`opens_with` lists the smallest ability sets that open the door, like ["J", "DG"].
    An empty string means the door is always open."""
    return any(set(option) <= held for option in door["opens_with"])


def exits(world: dict, room: str, held: set[str]) -> list[str]:
    out = []
    for door in world["doors"]:
        if door["a"] == room and door_opens(door, held):
            out.append(door["b"])
        elif door["b"] == room and not door["one_way"] and door_opens(door, held):
            out.append(door["a"])
    return out


def main(path: str) -> None:
    with open(path, encoding="utf-8") as f:
        world = json.load(f)
    rooms = {r["key"]: r for r in world["rooms"]}
    print(f'{world["name"]}: {len(rooms)} rooms, beatable = {world["analysis"]["beatable"]}')
    print("Collect abilities in this order:", " -> ".join(world["analysis"]["ability_order"]))

    # Replay the planner's fastest route, picking up items on the way.
    held: set[str] = set()
    start_item = rooms[world["start"]]["item"]
    if start_item in world["abilities"]:
        held.add(start_item)
    route = world["analysis"]["fastest_route"]
    for here, nxt in zip(route, route[1:]):
        assert nxt in exits(world, here, held), f"{nxt} should be reachable from {here}"
        item = rooms[nxt]["item"]
        if item in world["abilities"]:
            held.add(item)
        print(f'  {rooms[here]["name"]:>15} -> {rooms[nxt]["name"]:<15} holding {"".join(sorted(held)) or "-"}')
    print(f'Finished in {world["analysis"]["fastest_seconds"]} seconds.')


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "exported-map.json")
