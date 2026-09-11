"""Focused regressions for the locked Udyr champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import (
    DamageOutput,
    EntityId,
    HealOutput,
)

ROOT = Path(__file__).resolve().parents[1]


def _context(*, as_actor: bool = True) -> ParticipantContext:
    """Build a level-13 Udyr-versus-Garen encounter.

    :param as_actor: Place Udyr in the actor role when true.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    cog = registry.require_cog("Udyr")
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


def test_udyr_is_modeled_with_locked_evidence() -> None:
    """Require evidence, the duel capabilities, and a deterministic plan."""
    cog = create_default_registry(ROOT).require_cog("Udyr")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    assert plan.events == tuple(sorted(plan.events, key=lambda e: (e.at_ms, e.sequence)))


def test_udyr_mantle_heals_on_two_attacks_and_first_attack_stuns() -> None:
    """Heal on exactly two attacks after Iron Mantle and stun on the first attack."""
    cog = create_default_registry(ROOT).require_cog("Udyr")
    context = _context()
    plan = cog.build_action_plan(context)
    heals = [
        output
        for event in plan.events
        for output in event.outputs
        if isinstance(output, HealOutput)
    ]

    assert heals == [HealOutput(EntityId.ACTOR, Decimal("0.012") * context.snapshot.max_hp)] * 2
    first = _event(plan, "UDYR_BASIC_ATTACK_0")
    assert any(getattr(output, "status", None) == "CC_STUN" for output in first.outputs)


def test_udyr_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Udyr is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Udyr")
    actor_plan = cog.build_action_plan(_context(as_actor=True))
    target_plan = cog.build_action_plan(_context(as_actor=False))

    actor_ids = {event.id.split("_", 1)[1] for event in actor_plan.events}
    target_ids = {event.id.split("_", 1)[1] for event in target_plan.events}
    assert actor_ids == target_ids
    for event in target_plan.events:
        assert event.source is EntityId.TARGET
        for output in event.outputs:
            if isinstance(output, DamageOutput):
                assert output.recipient is EntityId.ACTOR
