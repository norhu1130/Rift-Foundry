"""Deterministic JSON-compatible value normalization."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any


def _decimal_text(value: Decimal) -> str:
    """Return a stable, non-exponent decimal representation.

    :param value: Finite Decimal to encode without exponent notation.
    :return: Canonical decimal text with trailing zeroes removed.
    """

    if not value.is_finite():
        raise ValueError("non-finite decimal values are not serializable")

    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text == "-0":
        return "0"
    return text


def normalize(value: Any) -> Any:
    """Convert domain values into a canonical JSON-compatible tree.

    Decimal values intentionally become strings. This avoids silently losing
    precision through a binary float or a JSON encoder implementation detail.

    :param value: Domain value to convert into a canonical JSON-compatible tree.
    :return: Canonical JSON-compatible value with Decimals preserved as strings.
    """

    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, dict):
        return {str(key): normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    if isinstance(value, float):
        raise TypeError("binary float values are forbidden; use Decimal")
    return value


def dumps(value: Any) -> str:
    """Serialize a value to canonical UTF-8 JSON text.

    :param value: Domain value to serialize as canonical JSON.
    :return: Canonical compact JSON text with stable key ordering.
    """

    return json.dumps(
        normalize(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
