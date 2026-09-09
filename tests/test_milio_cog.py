"""Focused regressions for the locked Milio champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId, HealOutput, ShieldOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *, as_actor: bool = True, item_stats: dict[str, Decimal] | None = None
) -> ParticipantContext:
    """Build a level-13 Milio-versus-Garen encounter.

    :param as_actor: Place Milio in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Milio.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    milio = registry.require_cog("Milio")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        milio.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one named Milio event.

    :param plan: Action plan containing the requested event.
    :param event_id: Exact stable identifier.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_milio_metadata_rotation_and_support_outputs_are_explicit() -> None:
    """Require evidence, two E charges, W ticks, Q damage, and R healing."""
    cog = create_default_registry(ROOT).require_cog("Milio")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    assert len([event for event in plan.events if "MILIO_E_WARM_HUGS" in event.id]) == 2
    assert len([event for event in plan.events if "MILIO_W_COZY_CAMPFIRE" in event.id]) == 6
    assert isinstance(_event(plan, "MILIO_E_WARM_HUGS_CHARGE_1").outputs[0], ShieldOutput)
    assert isinstance(_event(plan, "MILIO_R_BREATH_OF_LIFE_SELF_HEAL").outputs[0], HealOutput)


def test_milio_ap_and_control_channels_are_connected() -> None:
    """Exercise AP scaling plus distinct airborne and slow control windows."""
    cog = create_default_registry(ROOT).require_cog("Milio")
    base = cog.build_action_plan(_context())
    powered = cog.build_action_plan(_context(item_stats={"AP": Decimal(100)}))

    assert (
        _event(powered, "MILIO_Q_ULTRA_MEGA_FIRE_KICK").outputs[0].amount
        - _event(base, "MILIO_Q_ULTRA_MEGA_FIRE_KICK").outputs[0].amount
        == 120
    )
    assert (
        _event(powered, "MILIO_E_WARM_HUGS_CHARGE_1").outputs[0].amount
        - _event(base, "MILIO_E_WARM_HUGS_CHARGE_1").outputs[0].amount
        == 45
    )
    airborne, slow = cog.build_reaction_plan(_context()).cast_block_windows
    assert airborne.control_type is ControlType.AIRBORNE
    assert airborne.tenacity_reducible is False
    assert slow.control_type is ControlType.SLOW
    assert slow.tenacity_reducible is True


def test_milio_role_reversal_sustain_and_unsupported_ally_channels_are_honest() -> None:
    """Reverse outputs and retain blockers for ally and resource-dependent effects."""
    cog = create_default_registry(ROOT).require_cog("Milio")
    plan = cog.build_action_plan(_context(as_actor=False))

    assert all(event.source is EntityId.TARGET for event in plan.events)
    assert any(
        isinstance(output, DamageOutput) and output.recipient is EntityId.ACTOR
        for event in plan.events
        for output in event.outputs
    )
    assert any(
        isinstance(output, HealOutput) and output.recipient is EntityId.TARGET
        for event in plan.events
        for output in event.outputs
    )
    sustain, blockers = cog.lane_sustain_extra_health(
        _context(), duration_ms=30_000, no_damage_delay_ms=8000
    )
    assert sustain == 0
    assert blockers == ("MILIO_W_REQUIRES_MANA_AND_SELF_TARGET_VALIDATION",)
    assert "MILIO_R_CLEANSE_AND_TEMPORARY_TENACITY_NOT_MODELED" in plan.blockers
    assert (
        cog.item_candidate_blocker({"id": 2, "stats": {"MANA": {}, "OMNIVAMP": {}}})
        == "MILIO_ITEM_STAT_NOT_MODELED:2:MANA,OMNIVAMP"
    )
