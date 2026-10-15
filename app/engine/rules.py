"""Gate rules: tokenizer -> recursive-descent parser -> expression tree (AST).

Grammar (AND binds tighter than OR, like * binds tighter than +):

    expr   := term   ( ("|" | "OR")  term   )*
    term   := factor ( ("&" | "AND") factor )*
    factor := ABILITY | "(" expr ")"

An empty rule means the gate is always open.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .powerups import DEFAULT_POWERUPS, PowerUpSet

# The built-in power-ups. Each map can replace them with its own list (see powerups.py);
# these module names stay so older code and tests keep working with the defaults.
ABILITIES = DEFAULT_POWERUPS.abilities
ABILITY_BITS = DEFAULT_POWERUPS.bits
ALL_ABILITIES = DEFAULT_POWERUPS.all_mask
ITEM_NAMES = DEFAULT_POWERUPS.names
FILLER_ITEMS = {k: v for k, v in ITEM_NAMES.items() if k not in ABILITY_BITS}
SHORT_NAMES = {**{p.key: p.label for p in DEFAULT_POWERUPS}, "BOSS": "Boss"}


def item_bit(item: str | None) -> int:
    return DEFAULT_POWERUPS.bit(item)


def mask_to_letters(mask: int) -> str:
    return DEFAULT_POWERUPS.mask_to_letters(mask)


def letters_to_mask(letters) -> int:
    return DEFAULT_POWERUPS.letters_to_mask(letters)


class RuleError(ValueError):
    def __init__(self, message: str, position: int | None = None):
        super().__init__(message)
        self.position = position


# ---------------------------------------------------------------- tokenizer
@dataclass(frozen=True)
class Token:
    kind: str   # "ID", "AND", "OR", "LPAREN", "RPAREN"
    value: str
    pos: int    # 1-based column, for error messages


def tokenize(source: str, powerups: PowerUpSet = DEFAULT_POWERUPS) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    while i < len(source):
        ch = source[i]
        if ch.isspace():
            i += 1
        elif ch in "&|()":
            kind = {"&": "AND", "|": "OR", "(": "LPAREN", ")": "RPAREN"}[ch]
            tokens.append(Token(kind, ch, i + 1))
            i += 1
        elif ch.isalpha():
            j = i
            while j < len(source) and source[j].isalpha():
                j += 1
            word = source[i:j].upper()
            if word in ("AND", "OR"):
                tokens.append(Token(word, word, i + 1))
            elif word in powerups.bits:
                tokens.append(Token("ID", word, i + 1))
            else:
                keys = list(powerups.bits)
                choices = ", ".join(keys[:-1]) + f" or {keys[-1]}" if len(keys) > 1 else (keys[0] if keys else "nothing")
                hint = " That power-up is a collectible, so it can't open doors." if word in powerups else ""
                raise RuleError(
                    f'Unknown ability "{source[i:j]}" at position {i + 1}. Use {choices}.{hint}', i + 1
                )
            i = j
        else:
            raise RuleError(f'Unexpected "{ch}" at position {i + 1}.', i + 1)
    return tokens


# ---------------------------------------------------------------- AST nodes
class Node:
    def evaluate(self, mask: int) -> bool:
        raise NotImplementedError

    def label(self) -> str:
        raise NotImplementedError


@dataclass(frozen=True)
class Open(Node):
    def evaluate(self, mask: int) -> bool:
        return True

    def label(self) -> str:
        return ""


@dataclass(frozen=True)
class Ability(Node):
    name: str
    # The bit is filled in by the parser from the map's power-ups. compare=False keeps
    # Ability("J") == Ability("J") true whatever bit it carries.
    bit: int = field(default=0, compare=False)

    def evaluate(self, mask: int) -> bool:
        return bool(mask & (self.bit or ABILITY_BITS.get(self.name, 0)))

    def label(self) -> str:
        return self.name


@dataclass(frozen=True)
class And(Node):
    left: Node
    right: Node

    def evaluate(self, mask: int) -> bool:
        return self.left.evaluate(mask) and self.right.evaluate(mask)

    def label(self) -> str:
        def wrap(n: Node) -> str:
            return f"({n.label()})" if isinstance(n, Or) else n.label()
        return f"{wrap(self.left)}&{wrap(self.right)}"


@dataclass(frozen=True)
class Or(Node):
    left: Node
    right: Node

    def evaluate(self, mask: int) -> bool:
        return self.left.evaluate(mask) or self.right.evaluate(mask)

    def label(self) -> str:
        return f"{self.left.label()}|{self.right.label()}"


# ---------------------------------------------------------------- parser
class _Parser:
    def __init__(self, tokens: list[Token], bits: dict[str, int]):
        self.tokens = tokens
        self.bits = bits
        self.i = 0

    def peek(self) -> Token | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def expr(self) -> Node:
        node = self.term()
        while (t := self.peek()) and t.kind == "OR":
            self.i += 1
            node = Or(node, self.term())
        return node

    def term(self) -> Node:
        node = self.factor()
        while (t := self.peek()) and t.kind == "AND":
            self.i += 1
            node = And(node, self.factor())
        return node

    def factor(self) -> Node:
        t = self.peek()
        if t is None:
            raise RuleError('Rule ends too early. Expected an ability or "(".')
        if t.kind == "ID":
            self.i += 1
            return Ability(t.value, self.bits[t.value])
        if t.kind == "LPAREN":
            self.i += 1
            node = self.expr()
            closing = self.peek()
            if closing is None or closing.kind != "RPAREN":
                where = f"at position {closing.pos}" if closing else "at the end"
                raise RuleError(f'Missing ")" {where}.', closing.pos if closing else None)
            self.i += 1
            return node
        raise RuleError(f'Expected an ability at position {t.pos}, found "{t.value}".', t.pos)


def parse(source: str | None, powerups: PowerUpSet = DEFAULT_POWERUPS) -> Node:
    tokens = tokenize(source or "", powerups)
    if not tokens:
        return Open()
    parser = _Parser(tokens, powerups.bits)
    node = parser.expr()
    if (extra := parser.peek()) is not None:
        raise RuleError(f'Unexpected "{extra.value}" at position {extra.pos}.', extra.pos)
    return node


def minimal_sets(node: Node) -> list[int]:
    """Smallest ability sets that open the gate, as masks.

    Worked out on the tree itself (like expanding brackets in algebra):
      Ability  -> [{bit}]
      A | B    -> sets(A) + sets(B)
      A & B    -> every set of A combined with every set of B
    then any set that contains a smaller one is dropped. This stays fast however
    many power-ups a map has, unlike trying all 2^A masks.
    """
    def sets(n: Node) -> list[int]:
        if isinstance(n, Open):
            return [0]
        if isinstance(n, Ability):
            return [n.bit or ABILITY_BITS.get(n.name, 0)]
        if isinstance(n, Or):
            return sets(n.left) + sets(n.right)
        return [a | b for a in sets(n.left) for b in sets(n.right)]

    found = sorted(set(sets(node)), key=lambda m: (bin(m).count("1"), m))
    keep: list[int] = []
    for m in found:
        if not any((k & m) == k for k in keep):
            keep.append(m)
    return sorted(keep)


def node_to_dict(node: Node) -> dict:
    """The expression tree as plain JSON, so a game written in any language can evaluate it."""
    if isinstance(node, Open):
        return {"type": "open"}
    if isinstance(node, Ability):
        return {"type": "ability", "name": node.name}
    kind = "and" if isinstance(node, And) else "or"
    return {"type": kind, "left": node_to_dict(node.left), "right": node_to_dict(node.right)}
