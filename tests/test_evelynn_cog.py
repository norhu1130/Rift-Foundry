"""Focused regressions for the locked Evelynn champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    EntityId,
    ResistanceReductionOutput,
)

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    evelynn_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
    opponent_item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a level-13 Evelynn-versus-Teemo direct-Cog context.

    :param evelynn_is_actor: Place Evelynn on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Evelynn.
    :param opponent_item_stats: Optional modifiers applied to the opponent.
    :return: Role-bound deterministic benchmark context.
    """
    registry = create_default_registry(ROOT)
    evelynn = registry.require_cog("Evelynn")
    teemo = registry.require_cog("Teemo")
    return ParticipantContext(
        EntityId.ACTOR if evelynn_is_actor else EntityId.TARGET,
        EntityId.TARGET if evelynn_is_actor else EntityId.ACTOR,
        evelynn.snapshot(level=13, item_stats=item_stats),
        teemo.snapshot(level=13, item_stats=opponent_item_stats),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Resolve one event by its stable Evelynn identifier.

    :param plan: Action plan exposing an ``events`` tuple.
    :param event_id: Exact event identifier to locate.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def _damage_outputs(event: object):
    """Select fixed damage outputs from one Evelynn action.

    :param event: Action event exposing an ``outputs`` tuple.
    :return: Outputs carrying a damage type and raw amount.
    """
    return tuple(output for output in event.outputs if hasattr(output, "damage_type"))


def test_evelynn_declares_modeled_capabilities_and_locked_evidence() -> None:
    """Distinguish Evelynn from a scaffold and retain three source forms."""
    evelynn = create_default_registry(ROOT).require_cog("Evelynn")

    assert evelynn.maturity is CogMaturity.MODELED_UNVERIFIED
    assert evelynn.capabilities == DUEL_CAPABILITIES
    assert evelynn.verification_blockers() == ("COG_MODEL_UNVERIFIED:Evelynn",)
    assert evelynn.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Evelynn.json",
        "data/raw/16.17.1/communitydragon/champions/28.json",
        "data/raw/16.17.1/communitydragon/champions/evelynn.bin.json",
    )
    assert all((ROOT / reference).is_file() for reference in evelynn.evidence_refs)


def test_evelynn_rotation_is_deterministic_and_anchors_locked_formulas() -> None:
    """Anchor Q marks, full W, empowered E, and amplified R formulas."""
    evelynn = create_default_registry(ROOT).require_cog("Evelynn")
    context = _context(item_stats={"AP": Decimal(100)})

    plan = evelynn.build_action_plan(context)
    assert plan == evelynn.build_action_plan(context)
    assert plan.model_id == "evelynn_q5_w5_e1_r2_level13_assassination_fixture_v1"

    q = _event(plan, "EVELYNN_Q_HATE_SPIKE_1")
    recast = _event(plan, "EVELYNN_Q_RECAST_1_1")
    empowered_e = _event(plan, "EVELYNN_E_EMPOWERED_WHIPLASH")
    ultimate = _event(plan, "EVELYNN_R_LAST_CARESS_EXECUTE_AMPLIFIED")
    assert _damage_outputs(q)[0].amount == 70
    assert [output.amount for output in _damage_outputs(recast)] == [70, 80]
    assert _damage_outputs(empowered_e)[0].amount == (
        context.opponent_snapshot.max_hp * Decimal("0.065")
    )
    assert _damage_outputs(ultimate)[0].amount == 780
    assert "EVELYNN_R_TARGET_CURRENT_HP_BELOW_30_PERCENT_ASSUMED" in plan.blockers
    assert "EVELYNN_DEMON_SHADE_STEALTH_AND_DETECTION_NOT_MODELED" in plan.blockers


def test_evelynn_ap_attack_speed_haste_and_hp_reach_modeled_channels() -> None:
    """Prove AP, AS, AH, and target HP alter represented outputs or cadence."""
    evelynn = create_default_registry(ROOT).require_cog("Evelynn")
    baseline = evelynn.build_action_plan(_context())
    powered = evelynn.build_action_plan(_context(item_stats={"AP": Decimal(100)}))
    faster = evelynn.build_action_plan(_context(item_stats={"ATTACK_SPEED": Decimal("0.50")}))
    hasted = evelynn.build_action_plan(_context(item_stats={"ABILITY_HASTE": Decimal(100)}))
    healthier_target = evelynn.build_action_plan(_context(opponent_item_stats={"HP": Decimal(500)}))

    assert (
        _damage_outputs(_event(powered, "EVELYNN_Q_HATE_SPIKE_1"))[0].amount
        - (_damage_outputs(_event(baseline, "EVELYNN_Q_HATE_SPIKE_1"))[0].amount)
        == 25
    )
    baseline_attacks = [event for event in baseline.events if event.id.startswith("EVELYNN_BASIC")]
    faster_attacks = [event for event in faster.events if event.id.startswith("EVELYNN_BASIC")]
    assert len(faster_attacks) > len(baseline_attacks)
    assert _event(baseline, "EVELYNN_Q_HATE_SPIKE_2").at_ms == 6501
    assert _event(hasted, "EVELYNN_Q_HATE_SPIKE_2").at_ms == 4501
    e_base = _damage_outputs(_event(baseline, "EVELYNN_E_EMPOWERED_WHIPLASH"))[0].amount
    e_health = _damage_outputs(_event(healthier_target, "EVELYNN_E_EMPOWERED_WHIPLASH"))[0].amount
    assert e_health - e_base == 20


def test_evelynn_full_allure_and_last_caress_reactions_are_separate() -> None:
    """Model charm, MR shred, and untargetability without conflation."""
    evelynn = create_default_registry(ROOT).require_cog("Evelynn")
    context = _context()
    action_plan = evelynn.build_action_plan(context)
    reaction = evelynn.build_reaction_plan(context)

    trigger = _event(action_plan, "EVELYNN_W_ALLURE_FULL_TRIGGER")
    reduction = trigger.outputs[0]
    assert isinstance(reduction, ResistanceReductionOutput)
    assert reduction.stat == "MAGIC_RESISTANCE"
    assert reduction.fraction_per_stack == Decimal("0.45")
    assert reduction.duration_ms == 4000
    assert trigger.outputs[1].status == "CC_CHARM"
    assert trigger.outputs[1].duration_ms == 2250

    charm = reaction.cast_block_windows[0]
    assert charm.control_type is ControlType.CHARM
    assert charm.tenacity_reducible is True
    assert charm.source_event_id == "EVELYNN_W_ALLURE_FULL_TRIGGER"
    untargetable = reaction.damage_windows[0]
    assert untargetable.recipient is EntityId.ACTOR
    assert untargetable.damage_types == (
        DamageType.PHYSICAL,
        DamageType.MAGIC,
        DamageType.TRUE,
    )
    assert untargetable.multiplier == 0


def test_evelynn_role_reversal_and_teemo_blind_preserve_ability_damage() -> None:
    """Keep Evelynn role-neutral while blind cancels only basic attacks."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Evelynn", "Teemo"))
    as_opponent = engine.evaluate(MatchupRequest("Teemo", "Evelynn"))

    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    actor_q = next(
        entry
        for entry in as_actor.timeline.log
        if entry.event_id == "EVELYNN_Q_HATE_SPIKE_1" and entry.operation == "DAMAGE"
    )
    opponent_q = next(
        entry
        for entry in as_opponent.timeline.log
        if entry.event_id == "EVELYNN_Q_HATE_SPIKE_1" and entry.operation == "DAMAGE"
    )
    assert actor_q.recipient is EntityId.TARGET
    assert opponent_q.recipient is EntityId.ACTOR
    assert actor_q.status == opponent_q.status == "APPLIED"
    assert any(
        entry.event_id.startswith("EVELYNN_BASIC_ATTACK_")
        and entry.action_channel is ActionChannel.BASIC_ATTACK
        and entry.status == "CANCELLED"
        for entry in as_opponent.timeline.log
    )
    assert any(
        entry.event_id == "EVELYNN_R_LAST_CARESS_EXECUTE_AMPLIFIED"
        and entry.operation == "DAMAGE"
        and entry.status == "APPLIED"
        for entry in as_opponent.timeline.log
    )


def test_evelynn_sustain_engagement_and_item_policy_remain_state_honest() -> None:
    """Expose useful policy channels while preserving dynamic-state blockers."""
    evelynn = create_default_registry(ROOT).require_cog("Evelynn")

    assert evelynn.engagement_dash_distance(_context()) == 400
    assert (
        evelynn.item_candidate_blocker(
            {
                "id": 1,
                "stats": {
                    "AP": {},
                    "ATTACK_SPEED": {},
                    "ABILITY_HASTE": {},
                    "HP": {},
                    "MAGIC_RESISTANCE": {},
                },
            }
        )
        is None
    )
    assert (
        evelynn.item_candidate_blocker(
            {"id": 2, "stats": {"CRITICAL_STRIKE_CHANCE": {}, "MANA": {}}}
        )
        == "EVELYNN_ITEM_STAT_NOT_MODELED:2:CRITICAL_STRIKE_CHANCE,MANA"
    )
    baseline, blockers = evelynn.lane_sustain_extra_health(
        _context(), duration_ms=30_000, no_damage_delay_ms=8_000
    )
    powered, powered_blockers = evelynn.lane_sustain_extra_health(
        _context(item_stats={"AP": Decimal(100)}),
        duration_ms=30_000,
        no_damage_delay_ms=8_000,
    )
    assert baseline == 490
    assert powered == 740
    assert blockers == powered_blockers
    assert "EVELYNN_LANE_PASSIVE_CURRENT_HP_AND_THRESHOLD_HEADROOM_NOT_MODELED" in blockers
