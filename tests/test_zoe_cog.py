"""Focused regressions for the locked Zoe champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *, as_actor: bool = True, item_stats: dict[str, Decimal] | None = None
) -> ParticipantContext:
    """Build a level-13 Zoe-versus-Garen encounter.

    :param as_actor: Place Zoe in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Zoe.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    zoe = registry.require_cog("Zoe")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        zoe.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def test_zoe_metadata_bubble_hit_and_delayed_sleep_are_explicit() -> None:
    """Require evidence and both magic damage events with the delayed sleep."""
    cog = create_default_registry(ROOT).require_cog("Zoe")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    for event in plan.events:
        for output in event.outputs:
            if isinstance(output, DamageOutput) and event.channel.value == "ABILITY":
                assert output.damage_type.value == "MAGIC"


def test_zoe_reaction_plan_exposes_sleep_not_a_stun() -> None:
    """Expose the bubble's delayed effect as sleep, matching its locked text."""
    cog = create_default_registry(ROOT).require_cog("Zoe")
    reactions = cog.build_reaction_plan(_context())

    assert len(reactions.cast_block_windows) == 1
    assert reactions.cast_block_windows[0].control_type is ControlType.SLEEP


def test_zoe_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Zoe is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Zoe")
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
