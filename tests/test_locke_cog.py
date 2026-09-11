"""Focused regressions for the locked Locke champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId, ExecuteOutput, HealthCostOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    as_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a level-13 Locke-versus-Garen encounter.

    :param as_actor: Place Locke in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Locke.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    locke = registry.require_cog("Locke")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        locke.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Locate an event by stable identifier.

    :param plan: Action plan exposing an events tuple.
    :param event_id: Exact event identifier to locate.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_locke_metadata_and_evidence_are_complete() -> None:
    """Require complete routing and all three Locke evidence forms."""
    cog = create_default_registry(ROOT).require_cog("Locke")

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)


def test_locke_rotation_models_three_marks_health_cost_and_execute() -> None:
    """Anchor Q ammunition, W payments, and R's execute output."""
    cog = create_default_registry(ROOT).require_cog("Locke")
    plan = cog.build_action_plan(_context())

    assert plan == cog.build_action_plan(_context())
    assert len([event for event in plan.events if "Q_RITUAL_NAIL_" in event.id]) == 3
    costs = [event for event in plan.events if "W_CURRENT_HEALTH_COST" in event.id]
    assert len(costs) == 6
    assert all(isinstance(event.outputs[0], HealthCostOutput) for event in costs)
    purgatory = _event(plan, "LOCKE_R_PURGATORY")
    assert any(isinstance(output, ExecuteOutput) for output in purgatory.outputs)


def test_locke_ap_and_attack_speed_reach_distinct_outputs() -> None:
    """Exercise spell ratios, W speed scaling, and attack cadence."""
    cog = create_default_registry(ROOT).require_cog("Locke")
    base_context = _context()
    powered_context = _context(item_stats={"AP": Decimal(100), "ATTACK_SPEED": Decimal("0.5")})
    base = cog.build_action_plan(base_context)
    powered = cog.build_action_plan(powered_context)

    base_q = next(
        output.amount
        for output in _event(base, "LOCKE_Q_RITUAL_NAIL_1").outputs
        if isinstance(output, DamageOutput)
    )
    powered_q = next(
        output.amount
        for output in _event(powered, "LOCKE_Q_RITUAL_NAIL_1").outputs
        if isinstance(output, DamageOutput)
    )
    base_attacks = [event for event in base.events if event.id.startswith("LOCKE_BASIC_ATTACK")]
    powered_attacks = [
        event for event in powered.events if event.id.startswith("LOCKE_BASIC_ATTACK")
    ]
    assert powered_q > base_q
    assert len(powered_attacks) > len(base_attacks)
    assert cog.engagement_speed_multiplier(powered_context) > cog.engagement_speed_multiplier(
        base_context
    )


def test_locke_control_role_reversal_and_sustain_are_honest() -> None:
    """Preserve slow windows, reverse recipients, and avoid free W sustain."""
    cog = create_default_registry(ROOT).require_cog("Locke")
    reaction = cog.build_reaction_plan(_context())
    reversed_plan = cog.build_action_plan(_context(as_actor=False))

    assert all(window.control_type is ControlType.SLOW for window in reaction.cast_block_windows)
    assert all(event.source is EntityId.TARGET for event in reversed_plan.events)
    assert any(
        isinstance(output, DamageOutput) and output.recipient is EntityId.ACTOR
        for event in reversed_plan.events
        for output in event.outputs
    )
    sustain, blockers = cog.lane_sustain_extra_health(
        _context(), duration_ms=30_000, no_damage_delay_ms=8000
    )
    assert sustain == 0
    assert blockers == ("LOCKE_W_RECOVERY_REQUIRES_DAMAGE_HISTORY",)


def test_locke_item_policy_rejects_unrepresented_resource_channels() -> None:
    """Accept modeled stats while rejecting mana and generic drain value."""
    cog = create_default_registry(ROOT).require_cog("Locke")

    assert (
        cog.item_candidate_blocker({"id": 1, "stats": {"AP": {}, "ATTACK_SPEED": {}, "HP": {}}})
        is None
    )
    assert (
        cog.item_candidate_blocker({"id": 2, "stats": {"MANA": {}, "OMNIVAMP": {}}})
        == "LOCKE_ITEM_STAT_NOT_MODELED:2:MANA"
    )
