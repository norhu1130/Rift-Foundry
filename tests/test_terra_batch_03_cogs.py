"""Focused contract regressions for the accepted third Terra Cog batch."""

from pathlib import Path

import pytest

from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES, CogCapability
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId

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


EXPECTED_EVENT_TOKENS = {
    "Kayn": ("_Q_", "_W_", "_R_"),
    "Kennen": ("_Q_", "_W_", "_R_"),
    "Khazix": ("_Q_", "_W_", "_E_"),
    "Kindred": ("_Q_", "_W_"),
    "Kled": ("_Q_", "_E_"),
    "KogMaw": ("_W_", "_R_"),
    "KSante": ("_Q_", "_W_"),
    "Leblanc": ("_Q_", "_W_", "_R_"),
    "LeeSin": ("_Q_", "_R_"),
    "Leona": ("_Q_", "_W_", "_E_", "_R_"),
}


def _context(champion: str, *, as_actor: bool) -> ParticipantContext:
    """Build one level-13 role-bound matchup against Garen.

    :param champion: Locked champion key for the Cog under test.
    :param as_actor: Put the tested champion in the actor role when true.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    cog = registry.require_cog(champion)
    opponent = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        cog.snapshot(level=13),
        opponent.snapshot(level=13),
        8000,
        3000,
    )


@pytest.mark.parametrize("champion", tuple(EXPECTED_EVENT_TOKENS))
def test_batch_three_metadata_and_ability_surface(champion: str) -> None:
    """Require evidence and multiple champion-scoped ability events.

    :param champion: Locked champion key selected by pytest.
    :return: None.
    """
    cog = create_default_registry(ROOT).require_cog(champion)
    plan = cog.build_action_plan(_context(champion, as_actor=True))

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == expected_capabilities(champion)
    assert len(cog.evidence_refs) == 3
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    for token in EXPECTED_EVENT_TOKENS[champion]:
        assert any(token in event.id for event in plan.events), (champion, token)
    assert plan.blockers


@pytest.mark.parametrize("champion", tuple(EXPECTED_EVENT_TOKENS))
def test_batch_three_is_deterministic_and_role_symmetric(champion: str) -> None:
    """Keep schedules repeatable and bind hostile damage to the opposite role.

    :param champion: Locked champion key selected by pytest.
    :return: None.
    """
    cog = create_default_registry(ROOT).require_cog(champion)
    actor_context = _context(champion, as_actor=True)
    target_context = _context(champion, as_actor=False)
    actor_plan = cog.build_action_plan(actor_context)
    target_plan = cog.build_action_plan(target_context)

    assert actor_plan == cog.build_action_plan(actor_context)
    assert cog.build_reaction_plan(actor_context) == cog.build_reaction_plan(actor_context)
    assert all(event.source is EntityId.ACTOR for event in actor_plan.events)
    assert all(event.source is EntityId.TARGET for event in target_plan.events)
    assert any(
        isinstance(output, DamageOutput) and output.recipient is EntityId.TARGET
        for event in actor_plan.events
        for output in event.outputs
    )
    assert any(
        isinstance(output, DamageOutput) and output.recipient is EntityId.ACTOR
        for event in target_plan.events
        for output in event.outputs
    )
    assert cog.engagement_dash_distance(actor_context) >= 0
