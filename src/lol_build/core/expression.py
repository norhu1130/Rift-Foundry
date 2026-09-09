"""Evaluation for the deliberately restricted numeric expression tree."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from typing import Any

DECIMAL_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)
StatKey = tuple[str, str, str]


class ExpressionError(ValueError):
    """Raised for an invalid expression or missing evaluation input."""


@dataclass(frozen=True)
class EvaluationContext:
    """Provide champion levels and exact Decimal stats to expression nodes."""

    self_level: int
    target_level: int
    stats: Mapping[StatKey, Decimal]

    def __post_init__(self) -> None:
        """Validate dataclass invariants after initialization.

        :return: None.
        """

        for name, level in (("self_level", self.self_level), ("target_level", self.target_level)):
            if not 1 <= level <= 18:
                raise ExpressionError(f"{name} must be between 1 and 18, got {level}")
        if any(not isinstance(value, Decimal) for value in self.stats.values()):
            raise ExpressionError("all stat values must be Decimal instances")


def evaluate(expression: Mapping[str, Any], context: EvaluationContext) -> Decimal:
    """Evaluate a schema-validated expression without executing arbitrary code.

    :param expression: Validated expression tree to evaluate.
    :param context: Levels and stat values referenced by the expression.
    :return: Deterministically evaluated Decimal value.
    """

    with localcontext(DECIMAL_CONTEXT):
        return _evaluate(expression, context)


def _evaluate(expression: Mapping[str, Any], context: EvaluationContext) -> Decimal:
    """Recursively interpret one node of the restricted expression tree.

    :param expression: Restricted numeric expression tree.
    :param context: Exact levels and stat values referenced by nested expression nodes.
    :return: Exact value of the expression under ``context``.
    """

    expression_type = expression.get("type")

    if expression_type == "CONSTANT":
        try:
            value = Decimal(expression["value"])
        except Exception as error:
            raise ExpressionError(f"invalid constant: {expression.get('value')!r}") from error
        if not value.is_finite():
            raise ExpressionError("constant must be finite")
        return value

    if expression_type == "STAT":
        key = (expression["entity"], expression["basis"], expression["stat"])
        try:
            return context.stats[key]
        except KeyError as error:
            raise ExpressionError(f"stat is not available in evaluation context: {key}") from error

    if expression_type == "ADD":
        terms = expression["terms"]
        if len(terms) < 2:
            raise ExpressionError("ADD requires at least two terms")
        return sum((_evaluate(term, context) for term in terms), start=Decimal(0))

    if expression_type == "MULTIPLY":
        factors = expression["factors"]
        if len(factors) < 2:
            raise ExpressionError("MULTIPLY requires at least two factors")
        result = Decimal(1)
        for factor in factors:
            result *= _evaluate(factor, context)
        return result

    if expression_type == "LEVEL_CURVE":
        values = expression["values"]
        if len(values) != 18:
            raise ExpressionError("LEVEL_CURVE requires exactly 18 values")
        level = context.self_level if expression["level_entity"] == "SELF" else context.target_level
        return Decimal(values[level - 1])

    raise ExpressionError(f"unsupported expression type: {expression_type!r}")
