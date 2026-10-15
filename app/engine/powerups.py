"""Power-ups: the items a map can hold. Every map has its own list, so a designer
can invent "Wall Jump" or "Ice Beam" instead of using the four built-in abilities.

Two kinds:
- progression power-ups get one bit each and can appear in gate rules ("W & I")
- collectibles (progression=False) open nothing; in the game they add max energy

The engine only ever sees bits, so checker, search, randomizer and analysis
work the same for 2 power-ups or 12. With A progression power-ups the search
space is rooms x 2^A states, which is why the count is capped.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

MAX_PROGRESSION = 10    # 2^10 = 1024 states per room: still instant
MAX_POWERUPS = 16
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass(frozen=True)
class PowerUp:
    key: str                 # one capital letter, used in gate rules and room items
    name: str
    color: str = "#7dd3fc"
    progression: bool = True
    short: str = ""          # short label for tight spaces ("Grapple")
    description: str = ""

    @property
    def label(self) -> str:
        return self.short or self.name.split()[-1]


class PowerUpSet:
    """An ordered, validated list of power-ups plus the bit given to each ability."""

    def __init__(self, items: list[PowerUp]):
        if not items:
            raise ValueError("A map needs at least one power-up.")
        if len(items) > MAX_POWERUPS:
            raise ValueError(f"A map can have at most {MAX_POWERUPS} power-ups.")
        self.items: list[PowerUp] = []
        self.by_key: dict[str, PowerUp] = {}
        for p in items:
            if not (len(p.key) == 1 and "A" <= p.key <= "Z"):
                raise ValueError(f'Power-up key "{p.key}" must be a single capital letter A-Z.')
            if p.key in self.by_key:
                raise ValueError(f'Two power-ups use the key "{p.key}".')
            if not p.name.strip():
                raise ValueError(f'Power-up "{p.key}" needs a name.')
            if not _COLOR.match(p.color):
                raise ValueError(f'Power-up "{p.key}" colour must look like #33aaff.')
            self.items.append(p)
            self.by_key[p.key] = p
        abilities = [p for p in self.items if p.progression]
        if len(abilities) > MAX_PROGRESSION:
            raise ValueError(f"A map can have at most {MAX_PROGRESSION} abilities (power-ups that open doors).")
        self.bits: dict[str, int] = {p.key: 1 << i for i, p in enumerate(abilities)}
        self.all_mask: int = (1 << len(abilities)) - 1

    # ---- lookups
    def __iter__(self):
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __contains__(self, key) -> bool:
        return key in self.by_key

    @property
    def names(self) -> dict[str, str]:
        return {p.key: p.name for p in self.items}

    @property
    def abilities(self) -> dict[str, str]:
        return {p.key: p.name for p in self.items if p.progression}

    def bit(self, item: str | None) -> int:
        return self.bits.get(item, 0) if item else 0

    def name(self, key: str) -> str:
        return self.by_key[key].name if key in self.by_key else key

    def short(self, key: str) -> str:
        return self.by_key[key].label if key in self.by_key else key.title()

    def color(self, key: str) -> str:
        return self.by_key[key].color if key in self.by_key else "#8392bb"

    def mask_to_letters(self, mask: int) -> str:
        return "".join(k for k, b in self.bits.items() if mask & b) or "-"

    def letters_to_mask(self, letters) -> int:
        mask = 0
        for ch in letters:
            if ch not in self.bits:
                raise ValueError(f"Unknown ability {ch!r}")
            mask |= self.bits[ch]
        return mask

    # ---- conversion
    def to_list(self) -> list[dict]:
        return [asdict(p) for p in self.items]

    @classmethod
    def from_list(cls, data: list[dict] | None) -> "PowerUpSet":
        if not data:
            return DEFAULT_POWERUPS
        items = []
        for raw in data:
            items.append(PowerUp(
                key=str(raw.get("key", "")).strip().upper(),
                name=str(raw.get("name", "")).strip()[:40],
                color=str(raw.get("color") or "#7dd3fc").strip(),
                progression=bool(raw.get("progression", True)),
                short=str(raw.get("short") or "").strip()[:14],
                description=str(raw.get("description") or "").strip()[:160],
            ))
        return cls(items)


DEFAULT_POWERUPS = PowerUpSet([
    PowerUp("M", "Morph Ball", "#f5c04a", True, "Morph", "Curl into a ball to roll through tight tunnels."),
    PowerUp("D", "Dash Boots", "#4fd8ea", True, "Dash", "Burst forward to cross wide gaps."),
    PowerUp("J", "Double Jump", "#b08cff", True, "Jump", "Jump again in mid-air to reach high ledges."),
    PowerUp("G", "Grapple Beam", "#6fe08a", True, "Grapple", "Latch onto grapple points and swing across."),
    PowerUp("E", "Energy Tank", "#ff7aa0", False, "Energy", "Raises maximum energy. Opens no doors."),
])
