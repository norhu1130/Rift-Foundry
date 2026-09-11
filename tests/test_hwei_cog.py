"""Focused regressions for the locked Hwei champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import ActionChannel, DamageOutput, EntityId

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    as_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a level-13 Hwei-versus-Garen encounter.

    :param as_actor: Place Hwei in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Hwei.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    hwei = registry.require_cog("Hwei")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        hwei.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Locate an event by its stable identifier.

    :param plan: Action plan exposing an events tuple.
    :param event_id: Exact event identifier to locate.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def _damage(plan: object, event_id: str) -> Decimal:
    """Read the first damage amount from a named event.

    :param plan: Action plan containing the event.
    :param event_id: Exact damaging event identifier.
    :return: Raw damage amount on the first damage output.
    """
    return next(
        output.amount
        for output in _event(plan, event_id).outputs
        if isinstance(output, DamageOutput)
    )


def test_hwei_metadata_and_locked_evidence_are_complete() -> None:
    """Require full capability routing and the three locked evidence forms."""
    cog = create_default_registry(ROOT).require_cog("Hwei")

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert len(cog.evidence_refs) == 3
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)


def test_hwei_rotation_models_selected_subjects_and_periodic_damage() -> None:
    """Anchor the chosen spellbook variants, passive, and DOT schedules."""
    cog = create_default_registry(ROOT).require_cog("Hwei")
    plan = cog.build_action_plan(_context())

    assert plan == cog.build_action_plan(_context())
    assert _event(plan, "HWEI_WE_STIRRING_LIGHTS")
    assert _event(plan, "HWEI_EQ_GRIM_VISAGE")
    assert _event(plan, "HWEI_QQ_DEVASTATING_FIRE")
    assert _event(plan, "HWEI_PASSIVE_SIGNATURE_EQ_R")
    assert len([event for event in plan.events if "SPIRALING_DESPAIR_DOT" in event.id]) == 12
    assert len([event for event in plan.events if "MOLTEN_FISSURE_LAVA" in event.id]) == 2
    assert "HWEI_QW_WQ_WW_EW_EE_VARIANTS_OUTSIDE_SELECTED_ROTATION" in plan.blockers


def test_hwei_ap_and_haste_feed_damage_and_second_disaster_cast() -> None:
    """Exercise AP ratios and haste-dependent access to the QE follow-up."""
    cog = create_default_registry(ROOT).require_cog("Hwei")
    base = cog.build_action_plan(_context())
    powered = cog.build_action_plan(
        _context(item_stats={"AP": Decimal(100), "ABILITY_HASTE": Decimal(100)})
    )

    assert _damage(powered, "HWEI_QQ_DEVASTATING_FIRE") > _damage(base, "HWEI_QQ_DEVASTATING_FIRE")
    base_qe = [event for event in base.events if "MOLTEN_FISSURE" in event.id]
    powered_qe = [event for event in powered.events if "MOLTEN_FISSURE" in event.id]
    assert len(base_qe) == 3
    assert len(powered_qe) == 6
    assert powered_qe[0].at_ms < base_qe[0].at_ms


def test_hwei_control_and_role_reversal_remain_causal() -> None:
    """Preserve control categories and reverse every hostile recipient."""
    cog = create_default_registry(ROOT).require_cog("Hwei")
    reaction = cog.build_reaction_plan(_context(item_stats={"ABILITY_HASTE": Decimal(100)}))
    reversed_plan = cog.build_action_plan(_context(as_actor=False))

    assert tuple(window.control_type for window in reaction.cast_block_windows) == (
        ControlType.FEAR,
        ControlType.SLOW,
        ControlType.SLOW,
    )
    assert reaction.cast_block_windows[0].blocked_channels == (
        ActionChannel.BASIC_ATTACK,
        ActionChannel.ABILITY,
        ActionChannel.MOVEMENT,
    )
    assert all(event.source is EntityId.TARGET for event in reversed_plan.events)
    assert any(
        isinstance(output, DamageOutput) and output.recipient is EntityId.ACTOR
        for event in reversed_plan.events
        for output in event.outputs
    )


def test_hwei_item_policy_rejects_unrepresented_resource_channels() -> None:
    """Accept modeled combat stats while rejecting absent resource effects."""
    cog = create_default_registry(ROOT).require_cog("Hwei")

    assert (
        cog.item_candidate_blocker({"id": 1, "stats": {"AP": {}, "ABILITY_HASTE": {}, "HP": {}}})
        is None
    )
    assert (
        cog.item_candidate_blocker({"id": 2, "stats": {"MANA": {}, "OMNIVAMP": {}}})
        == "HWEI_ITEM_STAT_NOT_MODELED:2:MANA,OMNIVAMP"
    )
