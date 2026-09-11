"""Guard champion Cog base values against off-by-one-rank DataValue reads.

CommunityDragon ``DataValues`` arrays are indexed by rank: index 0 is a
placeholder and indices 1-5 match Data Dragon's rank 1-5 values (Sivir E's
rank-one cooldown 24 is ``cooldownTime[1]``). A Cog that declares its skill
order in a ``*_LEVEL13_Q5_W1_E5_R2_POLICY_*`` blocker must therefore use the
value at that rank. This scan flags a base term — ``Decimal(<int>) + <ratio>
* <stat>`` — that matches a varying array of its own champion only at a
different rank and never at the declared one.
"""

from __future__ import annotations

import ast
import json
import re
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAMPIONS = ROOT / "src/lol_build/cogs/champions"
BINS = ROOT / "data/raw/16.17.1/communitydragon/champions"
POLICY = re.compile(r"_LEVEL13_([QWER]\d(?:_[QWER]\d){3})_POLICY")
SLOT = re.compile(r"/Spells/[A-Za-z_]*?([QWER])(?:_[A-Za-z]+)?Ability/")

#: Base terms whose off-rank match was checked by hand and is a coincidence.
KNOWN_COINCIDENCES = {
    # Bel'Veth's per-stack passive damage is a level formula, not Q or R.
    ("belveth", 10),
    # Diana's shield is W5 ``ShieldBase[5]`` in the ``DianaOrbs`` record,
    # which this slot pattern does not map to W.
    ("diana", 105),
    # Hecarim's Rampage is Q5 ``BaseDamage[5]`` in ``HecarimRapidSlash``,
    # which this slot pattern does not map to Q.
    ("hecarim", 180),
    # Kalista's Rend constants coincide with a W tooltip-only recharge array.
    ("kalista", 60),
    ("kalista", 40),
    # Katarina's dagger damage is a passive level formula, not Q.
    ("katarina", 150),
}


def _slot_arrays(champion: str) -> dict[str, list[list[Decimal]]]:
    """Collect each ability slot's varying DataValue arrays.

    :param champion: Lower-case champion module stem.
    :return: Arrays keyed by slot letter.
    """
    document = json.loads((BINS / f"{champion}.bin.json").read_text(encoding="utf-8"))
    arrays: dict[str, list[list[Decimal]]] = {}
    for key, value in document.items():
        match = SLOT.search(key)
        if not match or not isinstance(value, dict) or "mSpell" not in value:
            continue
        for data_value in value["mSpell"].get("DataValues") or []:
            values = data_value.get("values") if isinstance(data_value, dict) else None
            if values and len(set(values)) > 1:
                arrays.setdefault(match.group(1), []).append(
                    [Decimal(str(round(number, 6))).normalize() for number in values]
                )
    return arrays


def _off_rank_base_terms(module: Path) -> list[tuple[str, int, int]]:
    """Find base terms that only match their champion's data at a wrong rank.

    :param module: Champion Cog module path.
    :return: ``(stem, line, value)`` for every suspicious base term.
    """
    text = module.read_text(encoding="utf-8")
    policy = POLICY.search(text)
    source = BINS / f"{module.stem}.bin.json"
    if not policy or not source.exists():
        return []
    ranks = {slot[0]: int(slot[1]) for slot in re.findall(r"[QWER]\d", policy.group(1))}
    arrays = _slot_arrays(module.stem)
    found = []
    for node in ast.walk(ast.parse(text)):
        if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add)):
            continue
        left = node.left
        if not (
            isinstance(left, ast.Call)
            and getattr(left.func, "id", None) == "Decimal"
            and left.args
            and isinstance(left.args[0], ast.Constant)
            and isinstance(left.args[0].value, int)
            and isinstance(node.right, ast.BinOp)
            and isinstance(node.right.op, ast.Mult)
        ):
            continue
        value = Decimal(left.args[0].value)
        if value < 10:
            continue
        at_rank = off_rank = False
        for slot, slot_arrays in arrays.items():
            rank = ranks.get(slot)
            if rank is None:
                continue
            for values in slot_arrays:
                at_rank |= values[rank] == value
                off_rank |= any(
                    number == value and index != rank for index, number in enumerate(values)
                )
        if off_rank and not at_rank:
            found.append((module.stem, node.lineno, int(value)))
    return found


def test_policy_ranked_base_terms_use_the_declared_rank() -> None:
    """Fail when a Cog base value is read from the wrong rank of its own data."""
    flagged = [
        entry
        for module in sorted(CHAMPIONS.glob("*/*.py"))
        if module.name != "__init__.py"
        for entry in _off_rank_base_terms(module)
        if (entry[0], entry[2]) not in KNOWN_COINCIDENCES
    ]

    assert flagged == []


def test_known_coincidences_still_exist() -> None:
    """Keep the allowlist honest: drop an entry once its Cog no longer matches."""
    present = {
        (entry[0], entry[2])
        for module in sorted(CHAMPIONS.glob("*/*.py"))
        if module.name != "__init__.py"
        for entry in _off_rank_base_terms(module)
    }

    assert present >= KNOWN_COINCIDENCES
