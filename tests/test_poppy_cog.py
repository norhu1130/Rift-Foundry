"""Focused regressions for the locked Poppy champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import (
    CurrentHealthDamageOutput,
    DamageOutput,
    EntityId,
    StatModifierOutput,
)

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *, as_actor: bool = True, item_stats: dict[str, Decimal] | None = None
) -> ParticipantContext:
    """Build a level-13 Poppy-versus-Garen encounter.

    :param as_actor: Place Poppy in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Poppy.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    poppy = registry.require_cog("Poppy")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        poppy.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one named Poppy event.

    :param plan: Action plan containing the expected event.
    :param event_id: Exact stable identifier.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_poppy_metadata_stun_double_hit_and_resist_buff_are_explicit() -> None:
    """Require evidence, the E stun, two Q hits, and the W resist buff."""
    cog = create_default_registry(ROOT).require_cog("Poppy")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    assert len([e for e in plan.events if "Q_HAMMER_SHOCK" in e.id]) == 2
    e_outputs = _event(plan, "POPPY_E_HEROIC_CHARGE").outputs
    assert isinstance(e_outputs[0], DamageOutput)
    w_outputs = _event(plan, "POPPY_W_STEADFAST_PRESENCE_RESIST").outputs
    assert all(isinstance(output, StatModifierOutput) for output in w_outputs)
    q_outputs = _event(plan, "POPPY_Q_HAMMER_SHOCK_1").outputs
    assert any(isinstance(output, CurrentHealthDamageOutput) for output in q_outputs)


def test_poppy_reaction_plan_exposes_the_e_stun() -> None:
    """Expose the Heroic Charge stun as a control window on the reaction plan."""
    cog = create_default_registry(ROOT).require_cog("Poppy")
    reactions = cog.build_reaction_plan(_context())

    assert len(reactions.cast_block_windows) == 1
    window = reactions.cast_block_windows[0]
    assert window.control_type is ControlType.STUN
    assert window.start_ms == cog._E_AT_MS
    assert window.end_ms == cog._E_AT_MS + cog._E_STUN_MS


def test_poppy_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Poppy is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Poppy")
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
