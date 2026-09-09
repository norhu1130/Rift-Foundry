"""Focused regressions for the locked Talon champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *, as_actor: bool = True, item_stats: dict[str, Decimal] | None = None
) -> ParticipantContext:
    """Build a level-13 Talon-versus-Garen encounter.

    :param as_actor: Place Talon in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Talon.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    talon = registry.require_cog("Talon")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        talon.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def test_talon_metadata_leap_throw_return_and_ring_are_explicit() -> None:
    """Require evidence, the W return hit, and both R blade-ring hits."""
    cog = create_default_registry(ROOT).require_cog("Talon")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    assert len([e for e in plan.events if "W_RAKE" in e.id]) == 2
    assert len([e for e in plan.events if "R_SHADOW_ASSAULT" in e.id]) == 2
    for event in plan.events:
        for output in event.outputs:
            if isinstance(output, DamageOutput):
                assert output.damage_type.value == "PHYSICAL"


def test_talon_reaction_plan_applies_no_hostile_control() -> None:
    """Report an empty control window set, matching Talon's kit."""
    cog = create_default_registry(ROOT).require_cog("Talon")
    reactions = cog.build_reaction_plan(_context())

    assert reactions.cast_block_windows == ()


def test_talon_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Talon is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Talon")
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
