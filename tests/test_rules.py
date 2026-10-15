import re
import pytest

from app.engine.rules import (ALL_ABILITIES, And, Ability, Open, Or, RuleError, letters_to_mask,
                              mask_to_letters, minimal_sets, parse, tokenize)


def test_tokenizer_kinds_and_positions():
    toks = tokenize("J | (D and G)")
    assert [t.kind for t in toks] == ["ID", "OR", "LPAREN", "ID", "AND", "ID", "RPAREN"]
    assert toks[3].pos == 6


def test_empty_rule_is_open():
    assert isinstance(parse(""), Open)
    assert isinstance(parse("   "), Open)
    assert parse("").evaluate(0)


def test_and_binds_tighter_than_or():
    assert parse("J | D & G") == Or(Ability("J"), And(Ability("D"), Ability("G")))


def test_parentheses_override_precedence():
    assert parse("(J | D) & G") == And(Or(Ability("J"), Ability("D")), Ability("G"))


@pytest.mark.parametrize("rule, held, expected", [
    ("J | (D & G)", "J", True),
    ("J | (D & G)", "D", False),
    ("J | (D & G)", "DG", True),
    ("M AND d", "MD", True),
    ("M AND d", "M", False),
])
def test_evaluate(rule, held, expected):
    assert parse(rule).evaluate(letters_to_mask(held)) is expected


@pytest.mark.parametrize("rule, message", [
    ("J | (D &", "ends too early"),
    ("(J | D", 'Missing ")"'),
    ("J D", 'Unexpected "D"'),
    ("Q", 'Unknown ability "Q"'),
    ("J + D", 'Unexpected "+"'),
    ("& J", "Expected an ability"),
])
def test_errors_explain_what_went_wrong(rule, message):
    with pytest.raises(RuleError, match=re.escape(message)):
        parse(rule)


def test_label_round_trips():
    for rule in ["J", "J|D&G", "(J|D)&G", "M&D&J"]:
        node = parse(rule)
        assert parse(node.label()) == node


def test_minimal_sets():
    sets = minimal_sets(parse("J | (D & G)"))
    assert sorted(mask_to_letters(m) for m in sets) == ["DG", "J"]
    assert minimal_sets(parse("")) == [0]


def test_masks():
    assert letters_to_mask("MDJG") == ALL_ABILITIES
    assert mask_to_letters(0) == "-"
