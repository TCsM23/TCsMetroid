"""Database models. The engine never touches these directly: a Map is turned into
a WorldGraph with to_graph(), and results are stored back as Seed rows."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .engine.graph import WorldGraph
from .engine.powerups import PowerUpSet
from .extensions import db


def _now():
    return datetime.now(timezone.utc)


class Map(db.Model):
    __tablename__ = "maps"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    start_key = db.Column(db.String(40), nullable=False)
    boss_key = db.Column(db.String(40), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=_now)
    is_template = db.Column(db.Boolean, nullable=False, default=False)
    # The map's own power-up list as JSON. Empty means "use the built-in four + Energy Tank".
    powerups_json = db.Column(db.Text, nullable=False, default="")

    rooms = db.relationship("Room", back_populates="map", cascade="all, delete-orphan", order_by="Room.id")
    gates = db.relationship("Gate", back_populates="map", cascade="all, delete-orphan", order_by="Gate.id")
    seeds = db.relationship("Seed", back_populates="map", cascade="all, delete-orphan", order_by="Seed.number")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "start": self.start_key,
            "boss": self.boss_key,
            "rooms": [r.to_dict() for r in self.rooms],
            "gates": [g.to_dict() for g in self.gates],
            "powerups": self.powerups().to_list(),
        }

    def powerups(self) -> PowerUpSet:
        return PowerUpSet.from_list(json.loads(self.powerups_json) if self.powerups_json else None)

    def _store_powerups(self, data: dict) -> None:
        # from_list validates and fills in defaults, so what is stored is always clean.
        self.powerups_json = json.dumps(PowerUpSet.from_list(data.get("powerups")).to_list())

    def to_graph(self) -> WorldGraph:
        return WorldGraph.from_dict(self.to_dict())

    def room_names(self) -> dict[str, str]:
        return {r.key: r.name for r in self.rooms}

    @classmethod
    def from_dict(cls, data: dict, is_template: bool = False) -> "Map":
        WorldGraph.from_dict(data)  # validate first: raises ValueError / RuleError
        m = cls(name=(data.get("name") or "Untitled map")[:80], description=data.get("description", ""),
                start_key=data["start"], boss_key=data["boss"], is_template=is_template)
        m._store_powerups(data)
        m._add_rooms_and_gates(data)
        db.session.add(m)
        return m

    def replace_from_dict(self, data: dict) -> None:
        """Overwrite this map's rooms and gates with a whole new layout (used by the designer's Save)."""
        WorldGraph.from_dict(data)  # validate before touching anything
        self.name = (data.get("name") or self.name)[:80]
        self.description = data.get("description", self.description)
        self.start_key, self.boss_key = data["start"], data["boss"]
        self._store_powerups(data)
        self.rooms.clear()
        self.gates.clear()
        # Delete the old rows before inserting new ones, or the (map_id, key) unique rule
        # would see a room key twice in the same flush.
        db.session.flush()
        self._add_rooms_and_gates(data)

    def _add_rooms_and_gates(self, data: dict) -> None:
        for r in data["rooms"]:
            self.rooms.append(Room(key=r["key"], name=r.get("name") or r["key"], x=int(r["x"]), y=int(r["y"]),
                                   seconds=int(r.get("seconds", 10)), item=r.get("item") or None))
        for g in data["gates"]:
            self.gates.append(Gate(room_a=g["a"], room_b=g["b"], rule=(g.get("rule") or "").strip(),
                                   one_way=bool(g.get("one_way", False))))


class Room(db.Model):
    __tablename__ = "rooms"
    __table_args__ = (db.UniqueConstraint("map_id", "key"),)

    id = db.Column(db.Integer, primary_key=True)
    map_id = db.Column(db.Integer, db.ForeignKey("maps.id"), nullable=False)
    key = db.Column(db.String(40), nullable=False)
    name = db.Column(db.String(60), nullable=False)
    x = db.Column(db.Integer, nullable=False)
    y = db.Column(db.Integer, nullable=False)
    seconds = db.Column(db.Integer, nullable=False, default=10)
    item = db.Column(db.String(1))

    map = db.relationship("Map", back_populates="rooms")

    def to_dict(self) -> dict:
        return dict(key=self.key, name=self.name, x=self.x, y=self.y, seconds=self.seconds, item=self.item)


class Gate(db.Model):
    __tablename__ = "gates"

    id = db.Column(db.Integer, primary_key=True)
    map_id = db.Column(db.Integer, db.ForeignKey("maps.id"), nullable=False)
    room_a = db.Column(db.String(40), nullable=False)
    room_b = db.Column(db.String(40), nullable=False)
    rule = db.Column(db.String(120), nullable=False, default="")
    one_way = db.Column(db.Boolean, nullable=False, default=False)

    map = db.relationship("Map", back_populates="gates")

    def to_dict(self) -> dict:
        return dict(a=self.room_a, b=self.room_b, rule=self.rule, one_way=self.one_way)


class Seed(db.Model):
    """A generated placement, stored with its route stats for the leaderboard."""
    __tablename__ = "seeds"
    __table_args__ = (db.UniqueConstraint("map_id", "number", "algorithm"),)

    id = db.Column(db.Integer, primary_key=True)
    map_id = db.Column(db.Integer, db.ForeignKey("maps.id"), nullable=False)
    number = db.Column(db.Integer, nullable=False)
    algorithm = db.Column(db.String(20), nullable=False)
    placement_json = db.Column(db.Text, nullable=False)
    route_seconds = db.Column(db.Integer, nullable=False)
    route_moves = db.Column(db.Integer, nullable=False)
    attempts = db.Column(db.Integer, nullable=False)
    code = db.Column(db.String(8), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=_now)

    map = db.relationship("Map", back_populates="seeds")

    @property
    def placement(self) -> dict[str, str]:
        return json.loads(self.placement_json)

    def to_dict(self) -> dict:
        return dict(id=self.id, number=self.number, algorithm=self.algorithm, code=self.code,
                    placement=self.placement, route_seconds=self.route_seconds,
                    route_moves=self.route_moves, attempts=self.attempts)
