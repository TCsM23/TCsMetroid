"""Built-in starting layouts. Each one teaches a classic Metroidvania pattern.

Every template must be beatable (tests/test_features.py checks this), so a new
map made from one always starts in a working state.
"""
from .demo_map import DEMO_MAP

BLANK = {
    "name": "Blank map",
    "description": "Just a start room and a boss room joined by an open door.",
    "start": "start",
    "boss": "boss",
    "rooms": [
        {"key": "start", "name": "Start", "x": 1, "y": 1, "seconds": 5, "item": None},
        {"key": "boss", "name": "Boss", "x": 2, "y": 1, "seconds": 30, "item": None},
    ],
    "gates": [{"a": "start", "b": "boss", "rule": "", "one_way": False}],
}

HUB = {
    "name": "Hub and spokes",
    "description": "One central room with a door to each wing. Each wing hides the ability that opens the next door.",
    "start": "hub",
    "boss": "boss",
    "rooms": [
        {"key": "hub", "name": "Central Hub", "x": 2, "y": 2, "seconds": 8, "item": None},
        {"key": "west", "name": "West Wing", "x": 1, "y": 2, "seconds": 12, "item": "M"},
        {"key": "north", "name": "North Wing", "x": 2, "y": 1, "seconds": 12, "item": "D"},
        {"key": "east", "name": "East Wing", "x": 3, "y": 2, "seconds": 12, "item": "J"},
        {"key": "south", "name": "South Wing", "x": 2, "y": 3, "seconds": 12, "item": "G"},
        {"key": "boss", "name": "Throne Room", "x": 4, "y": 2, "seconds": 30, "item": None},
    ],
    "gates": [
        {"a": "hub", "b": "west", "rule": "", "one_way": False},
        {"a": "hub", "b": "north", "rule": "M", "one_way": False},
        {"a": "hub", "b": "east", "rule": "D", "one_way": False},
        {"a": "hub", "b": "south", "rule": "J", "one_way": False},
        {"a": "east", "b": "boss", "rule": "G", "one_way": False},
    ],
}

LOCK_AND_KEY = {
    "name": "Lock and key corridor",
    "description": "A mostly straight path where each ability sits in a side room just before the door it opens.",
    "start": "gate",
    "boss": "boss",
    "rooms": [
        {"key": "gate", "name": "Outer Gate", "x": 1, "y": 2, "seconds": 5, "item": None},
        {"key": "hall", "name": "Long Hall", "x": 2, "y": 2, "seconds": 10, "item": None},
        {"key": "cache", "name": "Supply Cache", "x": 2, "y": 1, "seconds": 8, "item": "M"},
        {"key": "gallery", "name": "Gallery", "x": 3, "y": 2, "seconds": 10, "item": None},
        {"key": "vault", "name": "Vault", "x": 3, "y": 3, "seconds": 8, "item": "D"},
        {"key": "tower", "name": "Tower Base", "x": 4, "y": 2, "seconds": 12, "item": None},
        {"key": "roof", "name": "Rooftop", "x": 4, "y": 1, "seconds": 15, "item": "J"},
        {"key": "boss", "name": "Sky Arena", "x": 5, "y": 2, "seconds": 30, "item": None},
    ],
    "gates": [
        {"a": "gate", "b": "hall", "rule": "", "one_way": False},
        {"a": "hall", "b": "cache", "rule": "", "one_way": False},
        {"a": "hall", "b": "gallery", "rule": "M", "one_way": False},
        {"a": "gallery", "b": "vault", "rule": "", "one_way": False},
        {"a": "gallery", "b": "tower", "rule": "D", "one_way": False},
        {"a": "tower", "b": "roof", "rule": "", "one_way": False},
        {"a": "tower", "b": "boss", "rule": "J", "one_way": False},
    ],
}

ONE_WAY_TRAP = {
    "name": "One-way drop trap",
    "description": "Beatable, but dropping into the pit before finding the Dash Boots strands the player. The Analysis page flags it.",
    "start": "ledge",
    "boss": "boss",
    "rooms": [
        {"key": "ledge", "name": "High Ledge", "x": 1, "y": 1, "seconds": 5, "item": None},
        {"key": "store", "name": "Storeroom", "x": 1, "y": 2, "seconds": 10, "item": "D"},
        {"key": "hall", "name": "Upper Hall", "x": 2, "y": 1, "seconds": 8, "item": None},
        {"key": "pit", "name": "Sinkhole", "x": 2, "y": 2, "seconds": 15, "item": "J"},
        {"key": "shaft", "name": "Escape Shaft", "x": 3, "y": 2, "seconds": 12, "item": None},
        {"key": "boss", "name": "Deep Lair", "x": 4, "y": 2, "seconds": 30, "item": None},
    ],
    "gates": [
        {"a": "ledge", "b": "store", "rule": "", "one_way": False},
        {"a": "ledge", "b": "hall", "rule": "", "one_way": False},
        {"a": "hall", "b": "pit", "rule": "", "one_way": True},
        {"a": "pit", "b": "shaft", "rule": "D", "one_way": False},
        {"a": "shaft", "b": "boss", "rule": "J", "one_way": False},
    ],
}

BUILT_IN = {
    "blank": BLANK,
    "demo": DEMO_MAP,
    "hub": HUB,
    "lock": LOCK_AND_KEY,
    "trap": ONE_WAY_TRAP,
}
