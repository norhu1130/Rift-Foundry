"""Focused contract tests for Terra batch 02's ten champion Cogs."""

from decimal import Decimal
from pathlib import Path

import pytest

from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES, CogCapability
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import EntityId

ROOT = Path(__file__).resolve().parents[1]


#: Cogs in this batch whose area abilities have been widened to the whole
#: opposing side and therefore declare MULTI_TARGET.
_PROMOTED_TO_MULTI_TARGET = frozenset({"Karthus", "Leona"})


def expected_capabilities(champion: str) -> frozenset[CogCapability]:
    """Return the capability set a batch Cog is expected to declare.

    :param champion: Champion key under test.
    :return: Duel capabilities, plus MULTI_TARGET for promoted Cogs.
    """
    if champion in _PROMOTED_TO_MULTI_TARGET:
        return DUEL_CAPABILITIES | {CogCapability.MULTI_TARGET}
    return DUEL_CAPABILITIES
CHAMPIONS = (
    "JarvanIV",
    "Jayce",
    "Jhin",
    "Jinx",
    "Kalista",
    "Karma",
    "Karthus",
    "Kassadin",
    "Katarina",
    "Kayle",
)


def _context(name: str, *, target_side: bool = False) -> ParticipantContext:
    """Create a reversible level-13 direct-Cog fixture.

    :param name: Champion whose outgoing plan will be built.
    :param target_side: Bind that champion to target when true.
    :return: Deterministic participant context.
    """
    registry = create_default_registry(ROOT)
    champion = registry.require_cog(name)
    opponent = registry.require_cog("Garen")
    own, foe = (
        (EntityId.TARGET, EntityId.ACTOR) if target_side else (EntityId.ACTOR, EntityId.TARGET)
    )
    return ParticipantContext(
        own,
        foe,
        champion.snapshot(level=13, item_stats={"AP": Decimal(100)}),
        opponent.snapshot(level=13),
        8000,
        3000,
    )


@pytest.mark.parametrize("name", CHAMPIONS)
def test_batch_cogs_are_modeled_with_all_capabilities_and_locked_evidence(name: str) -> None:
    """Require source-backed, non-scaffold metadata for every owned Cog.

    :param name: Locked Data Dragon champion key.
    :return: None.
    """
    cog = create_default_registry(ROOT).require_cog(name)
    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == expected_capabilities(name)
    assert len(cog.evidence_refs) == 3
    assert all((ROOT / reference).is_file() for reference in cog.evidence_refs)
    assert cog.verification_blockers() == (f"COG_MODEL_UNVERIFIED:{name}",)


@pytest.mark.parametrize("name", CHAMPIONS)
def test_batch_cogs_have_deterministic_action_reaction_and_role_reversal(name: str) -> None:
    """Ensure action recipients and stable plans survive participant reversal.

    :param name: Locked Data Dragon champion key.
    :return: None.
    """
    cog = create_default_registry(ROOT).require_cog(name)
    actor = _context(name)
    target = _context(name, target_side=True)
    actor_plan = cog.build_action_plan(actor)
    target_plan = cog.build_action_plan(target)
    assert actor_plan == cog.build_action_plan(actor)
    assert actor_plan.model_id == target_plan.model_id
    assert actor_plan.blockers
    assert cog.build_reaction_plan(actor).model_id == cog.build_reaction_plan(target).model_id
    for event in actor_plan.events:
        for output in event.outputs:
            recipient = getattr(output, "recipient", None)
            if recipient is not None:
                assert recipient in {EntityId.ACTOR, EntityId.TARGET}


@pytest.mark.parametrize("name", CHAMPIONS)
def test_batch_cogs_item_policy_is_explicit(name: str) -> None:
    """Require a deterministic response for both live and unsupported item stats.

    :param name: Locked Data Dragon champion key.
    :return: None.
    """
    cog = create_default_registry(ROOT).require_cog(name)
    assert cog.item_candidate_blocker({"id": 1, "stats": {"AP": {}, "AD": {}}}) is None
    blocker = cog.item_candidate_blocker({"id": 2, "stats": {"MANA": {}}})
    assert blocker is not None
    assert blocker.startswith(f"{name.upper()}_ITEM_STAT_NOT_MODELED:2:")
