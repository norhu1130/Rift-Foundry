"""Focused regressions for the locked Viego champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import (
    DamageOutput,
    EntityId,
)

ROOT = Path(__file__).resolve().parents[1]


def _context(*, as_actor: bool = True) -> ParticipantContext:
    """Build a level-13 Viego-versus-Garen encounter.

    :param as_actor: Place Viego in the actor role when true.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    cog = registry.require_cog("Viego")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        cog.snapshot(level=13),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one named event.

    :param plan: Action plan containing the expected event.
    :param event_id: Exact stable identifier.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_viego_is_modeled_with_locked_evidence() -> None:
    """Require evidence, the duel capabilities, and a deterministic plan."""
    cog = create_default_registry(ROOT).require_cog("Viego")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())


def test_viego_second_strike_heals_after_ability_hits() -> None:
    """Heal from the primed second strike, never from an unprimed attack."""
    cog = create_default_registry(ROOT).require_cog("Viego")
    plan = cog.build_action_plan(_context())
    attacks = [e for e in plan.events if e.id.startswith("VIEGO_BASIC_ATTACK")]
    healing = [
        o
        for e in attacks
        for o in e.outputs
        if isinstance(o, DamageOutput) and o.source_heal_ratio > 0
    ]

    assert 1 <= len(healing) <= 3
    assert all(o.source_heal_ratio == Decimal("1.5") for o in healing)


def test_viego_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Viego is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Viego")
    actor_plan = cog.build_action_plan(_context(as_actor=True))
    target_plan = cog.build_action_plan(_context(as_actor=False))

    assert {e.id.split("_", 1)[1] for e in actor_plan.events} == {
        e.id.split("_", 1)[1] for e in target_plan.events
    }
    for event in target_plan.events:
        assert event.source is EntityId.TARGET
        for output in event.outputs:
            if isinstance(output, DamageOutput):
                assert output.recipient is EntityId.ACTOR
