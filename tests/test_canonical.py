from decimal import Decimal

import pytest

from lol_build.core.canonical import dumps


def test_canonical_output_is_byte_stable() -> None:
    first = {
        "z": Decimal("1.2300"),
        "a": [Decimal("0.00"), {"한글": Decimal("-0.0")}],
    }
    second = {
        "a": [Decimal("0"), {"한글": Decimal("0")}],
        "z": Decimal("1.23"),
    }

    assert dumps(first).encode() == dumps(second).encode()
    assert dumps(first) == '{"a":["0",{"한글":"0"}],"z":"1.23"}'


def test_binary_float_is_rejected() -> None:
    with pytest.raises(TypeError, match="binary float"):
        dumps({"damage": 0.1})


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity")])
def test_non_finite_decimal_is_rejected(value: Decimal) -> None:
    with pytest.raises(ValueError, match="non-finite"):
        dumps(value)
