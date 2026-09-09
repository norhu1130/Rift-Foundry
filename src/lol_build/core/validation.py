"""Comparison policy for calculated combat values and client measurements."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

INTEGER_DAMAGE_ABSOLUTE_TOLERANCE = Decimal(1)
ACCUMULATED_DAMAGE_RELATIVE_TOLERANCE = Decimal("0.01")


@dataclass(frozen=True)
class MeasurementComparison:
    """Record calculation error, tolerance policy, and pass/fail outcome."""

    calculated: Decimal
    measured: Decimal
    absolute_error: Decimal
    relative_error: Decimal | None
    tolerance: Decimal
    tolerance_kind: str
    passed: bool


def _validate(value: Decimal, *, name: str) -> None:
    """Require a finite ``Decimal`` before comparing measured values.

    :param value: Decimal operand whose type and finiteness must be validated.
    :param name: Diagnostic field name included in validation errors.
    :return: None.
    """

    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")


def compare_integer_damage(
    calculated: Decimal,
    measured: Decimal,
) -> MeasurementComparison:
    """Compare one displayed integer-damage observation with ±1 tolerance.

    :param calculated: Value produced by the calculation engine.
    :param measured: Reference value observed in the game client.
    :return: Absolute-error comparison using the ±1 displayed-damage tolerance.
    """

    _validate(calculated, name="calculated")
    _validate(measured, name="measured")
    absolute_error = abs(calculated - measured)
    relative_error = absolute_error / abs(measured) if measured != 0 else None
    return MeasurementComparison(
        calculated,
        measured,
        absolute_error,
        relative_error,
        INTEGER_DAMAGE_ABSOLUTE_TOLERANCE,
        "ABSOLUTE",
        absolute_error <= INTEGER_DAMAGE_ABSOLUTE_TOLERANCE,
    )


def compare_accumulated_damage(
    calculated: Decimal,
    measured: Decimal,
) -> MeasurementComparison:
    """Compare accumulated damage using 1% relative error, exact at zero.

    :param calculated: Value produced by the calculation engine.
    :param measured: Reference value observed in the game client.
    :return: Relative-error comparison using the 1% accumulated-damage tolerance.
    """

    _validate(calculated, name="calculated")
    _validate(measured, name="measured")
    absolute_error = abs(calculated - measured)
    if measured == 0:
        relative_error = None
        passed = absolute_error == 0
    else:
        relative_error = absolute_error / abs(measured)
        passed = relative_error <= ACCUMULATED_DAMAGE_RELATIVE_TOLERANCE
    return MeasurementComparison(
        calculated,
        measured,
        absolute_error,
        relative_error,
        ACCUMULATED_DAMAGE_RELATIVE_TOLERANCE,
        "RELATIVE",
        passed,
    )
