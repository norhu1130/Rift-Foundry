"""Same-passive and shared-cooldown item duplicates must never be scored."""

from __future__ import annotations

from pathlib import Path

from lol_build.application.cog_preview import _path_is_legal_beam
from lol_build.application.item_combat import duplicate_group_blockers
from lol_build.application.matchup import MatchupEngine

ROOT = Path(__file__).resolve().parents[1]

# Titanic Hydra and Stridebreaker both carry the locked "HYDRA_CLEAVE"
# same_passive group; Sterak's Gage and Maw of Malmortius both carry the
# locked "LIFELINE" shared_cooldown group (patch 16.17.1).
TITANIC_HYDRA = 3748
STRIDEBREAKER = 6631
STERAKS_GAGE = 3053
MAW_OF_MALMORTIUS = 3156
DEAD_MANS_PLATE = 3742


def _item_by_id() -> dict[int, dict[str, object]]:
    """Load the locked complete-item pool keyed by Riot identifier.

    :return: Every complete item's document, keyed by its numeric id.
    """
    engine = MatchupEngine(ROOT)
    return {item["id"]: item for item in engine.complete_items}


def test_duplicate_group_blockers_flags_a_repeated_same_passive_group() -> None:
    """Reject two Hydra-cleave items as an unresolved same-passive duplicate."""
    items = _item_by_id()
    portfolio = (items[TITANIC_HYDRA], items[STRIDEBREAKER])

    assert duplicate_group_blockers(portfolio) == ("UNRESOLVED_SAME_PASSIVE:HYDRA_CLEAVE",)


def test_duplicate_group_blockers_flags_a_repeated_shared_cooldown_group() -> None:
    """Reject two Lifeline items as an unresolved shared-cooldown duplicate."""
    items = _item_by_id()
    portfolio = (items[STERAKS_GAGE], items[MAW_OF_MALMORTIUS])

    assert duplicate_group_blockers(portfolio) == ("UNRESOLVED_SHARED_COOLDOWN:LIFELINE",)


def test_duplicate_group_blockers_allows_a_portfolio_with_no_repeated_group() -> None:
    """Clear a build whose groups only ever appear once."""
    items = _item_by_id()
    portfolio = (items[DEAD_MANS_PLATE], items[STRIDEBREAKER], items[STERAKS_GAGE])

    assert duplicate_group_blockers(portfolio) == ()


def test_path_is_legal_beam_excludes_a_repeated_same_passive_path() -> None:
    """Keep the search's own legality check consistent with the shared helper."""
    items = _item_by_id()

    assert not _path_is_legal_beam(
        (DEAD_MANS_PLATE, TITANIC_HYDRA, STRIDEBREAKER),
        item_by_id=items,
        budgets=(4000, 7000, 10000),
    )
    assert _path_is_legal_beam(
        (DEAD_MANS_PLATE, TITANIC_HYDRA, STERAKS_GAGE),
        item_by_id=items,
        budgets=(4000, 7000, 10000),
    )
