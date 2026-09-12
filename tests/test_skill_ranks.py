"""Skill ranks follow standard leveling and rank values follow the locked data."""

import json
from decimal import Decimal
from pathlib import Path

from lol_build.cogs import ParticipantContext, create_default_registry
from lol_build.core.timeline import EntityId

ROOT = Path(__file__).resolve().parents[1]


def _context(cog, level: int) -> ParticipantContext:
    """Bind a Cog against itself at one level.

    :param cog: Champion Cog.
    :param level: Champion level.
    :return: Participant context at that level.
    """
    snapshot = cog.snapshot(level=level)
    return ParticipantContext(EntityId.ACTOR, EntityId.TARGET, snapshot, snapshot, 8000, 3000)


def test_standard_leveling_reproduces_the_declared_level13_order() -> None:
    """Jhin declares Q5/W1/E5/R2: Q first, E second, R at 6, 11, and 16."""
    jhin = create_default_registry(ROOT).require_cog("Jhin")

    assert jhin.skill_ranks(13) == {"Q": 5, "E": 5, "W": 1, "R": 2}
    assert jhin.skill_ranks(6) == {"Q": 3, "E": 1, "W": 1, "R": 1}
    assert jhin.skill_ranks(9) == {"Q": 5, "E": 2, "W": 1, "R": 1}
    assert jhin.skill_ranks(16) == {"Q": 5, "E": 5, "W": 3, "R": 3}


def test_rank_value_reads_the_slot_rank_at_the_requested_level() -> None:
    """E at level 9 is rank two, so Jhin E's base damage is BaseDamage[2]."""
    jhin = create_default_registry(ROOT).require_cog("Jhin")

    assert jhin.rank_value("JhinE", "BaseDamage", _context(jhin, 13), Decimal(0)) == Decimal(260)
    assert jhin.rank_value("JhinE", "BaseDamage", _context(jhin, 9), Decimal(0)) == Decimal(80)


def test_rank_value_falls_back_without_the_locked_record() -> None:
    """A Cog built from the summary document alone keeps its level-13 literal."""
    catalog = json.loads((ROOT / "data/raw/16.17.1/en_US/champion.json").read_text())
    registry = create_default_registry(ROOT)
    bare = type(registry.require_cog("Jhin"))(catalog["data"]["Jhin"])

    assert bare.rank_value("JhinE", "BaseDamage", _context(bare, 9), Decimal(260)) == Decimal(260)
