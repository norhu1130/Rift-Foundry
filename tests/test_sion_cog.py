"""Focused regressions for the locked Sion champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId, ShieldOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *, as_actor: bool = True, item_stats: dict[str, Decimal] | None = None
) -> ParticipantContext:
    """Build a level-13 Sion-versus-Garen encounter.

    :param as_actor: Place Sion in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Sion.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    sion = registry.require_cog("Sion")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        sion.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one named Sion event.

    :param plan: Action plan containing the expected event.
    :param event_id: Exact stable identifier.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_sion_metadata_shield_detonate_shred_and_two_stuns_are_explicit() -> None:
    """Require evidence, the W shield, and both the Q and R stuns."""
    cog = create_default_registry(ROOT).require_cog("Sion")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    assert isinstance(
        _event(plan, "SION_W_SOUL_FURNACE_SHIELD").outputs[0], ShieldOutput
    )
    assert isinstance(_event(plan, "SION_Q_DECIMATING_SMASH").outputs[0], DamageOutput)
    assert isinstance(_event(plan, "SION_R_UNSTOPPABLE_ONSLAUGHT").outputs[0], DamageOutput)


def test_sion_reaction_plan_exposes_both_stuns() -> None:
    """Expose the Decimating Smash and Unstoppable Onslaught stuns."""
    cog = create_default_registry(ROOT).require_cog("Sion")
    reactions = cog.build_reaction_plan(_context())

    assert len(reactions.cast_block_windows) == 2
    assert all(window.control_type is ControlType.STUN for window in reactions.cast_block_windows)


def test_sion_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Sion is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Sion")
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
