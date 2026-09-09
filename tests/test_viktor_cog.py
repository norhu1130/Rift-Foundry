"""Focused regressions for the locked Viktor champion Cog."""

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
    """Build a level-13 Viktor-versus-Garen encounter.

    :param as_actor: Place Viktor in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Viktor.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    viktor = registry.require_cog("Viktor")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        viktor.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one named Viktor event.

    :param plan: Action plan containing the expected event.
    :param event_id: Exact stable identifier.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_viktor_metadata_shield_empowered_attack_laser_and_storm() -> None:
    """Require evidence, the Q shield, the laser pair, and R's storm ticks."""
    cog = create_default_registry(ROOT).require_cog("Viktor")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    assert isinstance(
        _event(plan, "VIKTOR_Q_SIPHON_POWER_SHIELD").outputs[0], ShieldOutput
    )
    assert len(_event(plan, "VIKTOR_Q_SIPHON_POWER_EMPOWERED_ATTACK").outputs) == 2
    assert len([e for e in plan.events if "R_ARCANE_STORM" in e.id]) == 4


def test_viktor_reaction_plan_exposes_the_w_stun() -> None:
    """Expose the Gravity Field stun as a control window."""
    cog = create_default_registry(ROOT).require_cog("Viktor")
    reactions = cog.build_reaction_plan(_context())

    assert len(reactions.cast_block_windows) == 1
    assert reactions.cast_block_windows[0].control_type is ControlType.STUN


def test_viktor_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Viktor is the actor or target."""
    cog = create_default_registry(ROOT).require_cog("Viktor")
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
