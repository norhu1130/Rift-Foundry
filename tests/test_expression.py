import json
from decimal import Decimal
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from lol_build.core.expression import EvaluationContext, ExpressionError, evaluate

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas/numeric-expression.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)


def _context() -> EvaluationContext:
    return EvaluationContext(
        self_level=13,
        target_level=11,
        stats={
            ("SELF", "BONUS", "HP"): Decimal("400"),
            ("TARGET", "MAX", "HP"): Decimal("2500"),
        },
    )


def test_composed_expression_is_valid_and_evaluates() -> None:
    expression = {
        "type": "ADD",
        "terms": [
            {
                "type": "MULTIPLY",
                "factors": [
                    {"type": "CONSTANT", "value": "0.15"},
                    {"type": "STAT", "entity": "SELF", "basis": "BONUS", "stat": "HP"},
                ],
            },
            {
                "type": "LEVEL_CURVE",
                "level_entity": "SELF",
                "values": [str(value) for value in range(1, 19)],
            },
        ],
    }

    assert list(VALIDATOR.iter_errors(expression)) == []
    assert evaluate(expression, _context()) == Decimal("73.00")


def test_unknown_expression_node_is_rejected_by_schema_and_evaluator() -> None:
    expression = {"type": "DIVIDE", "left": "1", "right": "2"}

    assert list(VALIDATOR.iter_errors(expression))
    with pytest.raises(ExpressionError, match="unsupported expression"):
        evaluate(expression, _context())


def test_missing_stat_fails_instead_of_defaulting_to_zero() -> None:
    expression = {"type": "STAT", "entity": "SELF", "basis": "TOTAL", "stat": "AP"}

    with pytest.raises(ExpressionError, match="not available"):
        evaluate(expression, _context())


def test_binary_number_constant_is_rejected_by_schema() -> None:
    expression = {"type": "CONSTANT", "value": 0.1}

    assert list(VALIDATOR.iter_errors(expression))


@pytest.mark.parametrize("self_level", [0, 19])
def test_level_outside_game_range_is_rejected(self_level: int) -> None:
    with pytest.raises(ExpressionError, match="self_level"):
        EvaluationContext(self_level=self_level, target_level=1, stats={})
