"""Focused regressions for the locked Singed champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId, StatModifierOutput, StatusOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *, as_actor: bool = True, item_stats: dict[str, Decimal] | None = None
) -> ParticipantContext:
    """Build a level-13 Singed-versus-Garen encounter.

    :param as_actor: Place Singed in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Singed.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    singed = registry.require_cog("Singed")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        singed.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one named Singed event.

    :param plan: Action plan containing the expected event.
    :param event_id: Exact stable identifier.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_singed_metadata_poison_ticks_and_fling_root_are_explicit() -> None:
    """Require evidence, repeated Q ticks, and E's damage and root."""
    cog = create_default_registry(ROOT).require_cog("Singed")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    assert len([e for e in plan.events if "Q_POISON_TRAIL_TICK" in e.id]) > 20
    r_outputs = _event(plan, "SINGED_R_INSANITY_POTION").outputs
    assert all(isinstance(output, StatModifierOutput) for output in r_outputs)
    e_outputs = _event(plan, "SINGED_E_FLING").outputs
    assert isinstance(e_outputs[0], DamageOutput)
    ticks = [e for e in plan.events if "Q_POISON_TRAIL_TICK" in e.id]
    assert all(
        any(
            isinstance(output, StatusOutput)
            and output.status == "HEALING_REDUCTION"
            and output.magnitude == Decimal("0.40")
            for output in tick.outputs
        )
        for tick in ticks
    )


def test_singed_reaction_plan_exposes_the_e_root() -> None:
    """Expose the Fling root as a control window."""
    cog = create_default_registry(ROOT).require_cog("Singed")
    reactions = cog.build_reaction_plan(_context())

    assert len(reactions.cast_block_windows) == 1
    assert reactions.cast_block_windows[0].control_type is ControlType.ROOT


def test_singed_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Singed is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Singed")
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
