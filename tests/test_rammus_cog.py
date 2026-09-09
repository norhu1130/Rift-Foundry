"""Focused regressions for the locked Rammus champion Cog."""

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
    """Build a level-13 Rammus-versus-Garen encounter.

    :param as_actor: Place Rammus in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Rammus.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    rammus = registry.require_cog("Rammus")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        rammus.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one named Rammus event.

    :param plan: Action plan containing the expected event.
    :param event_id: Exact stable identifier.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_rammus_metadata_defense_roll_taunt_and_slam_are_explicit() -> None:
    """Require evidence, the W buff, the Q hit, the E taunt, and the R hit."""
    cog = create_default_registry(ROOT).require_cog("Rammus")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    w_outputs = _event(plan, "RAMMUS_W_DEFENSIVE_BALL_CURL").outputs
    assert all(isinstance(output, StatModifierOutput) for output in w_outputs)
    q_outputs = _event(plan, "RAMMUS_Q_POWERBALL").outputs
    assert isinstance(q_outputs[0], DamageOutput)
    assert q_outputs[0].damage_type.value == "MAGIC"
    e_outputs = _event(plan, "RAMMUS_E_PUNCTURING_TAUNT").outputs
    assert isinstance(e_outputs[0], StatusOutput)
    r_outputs = _event(plan, "RAMMUS_R_SOARING_SLAM").outputs
    assert isinstance(r_outputs[0], DamageOutput)


def test_rammus_reaction_plan_exposes_the_e_taunt() -> None:
    """Expose the Puncturing Taunt lock as a control window."""
    cog = create_default_registry(ROOT).require_cog("Rammus")
    reactions = cog.build_reaction_plan(_context())

    assert len(reactions.cast_block_windows) == 1
    window = reactions.cast_block_windows[0]
    assert window.control_type is ControlType.TAUNT
    assert window.start_ms == cog._E_AT_MS
    assert window.end_ms == cog._E_AT_MS + cog._E_TAUNT_MS


def test_rammus_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Rammus is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Rammus")
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
