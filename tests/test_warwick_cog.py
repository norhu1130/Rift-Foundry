"""Focused regressions for the locked Warwick champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, EntityId

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    warwick_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
    opponent_health: Decimal = Decimal(0),
) -> ParticipantContext:
    """Build a level-13 Warwick-versus-Teemo direct-Cog context.

    :param warwick_is_actor: Place Warwick on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Warwick.
    :param opponent_health: Additional maximum health applied to Teemo.
    :return: Role-bound deterministic benchmark context.
    """
    registry = create_default_registry(ROOT)
    warwick = registry.require_cog("Warwick")
    teemo = registry.require_cog("Teemo")
    return ParticipantContext(
        EntityId.ACTOR if warwick_is_actor else EntityId.TARGET,
        EntityId.TARGET if warwick_is_actor else EntityId.ACTOR,
        warwick.snapshot(level=13, item_stats=item_stats),
        teemo.snapshot(level=13, item_stats={"HP": opponent_health}),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Resolve one event by its stable Warwick identifier.

    :param plan: Action plan exposing an ``events`` tuple.
    :param event_id: Exact event identifier to locate.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_warwick_declares_modeled_capabilities_and_locked_evidence() -> None:
    """Distinguish Warwick from a scaffold and retain all source forms."""
    warwick = create_default_registry(ROOT).require_cog("Warwick")

    assert warwick.maturity is CogMaturity.MODELED_UNVERIFIED
    assert warwick.capabilities == DUEL_CAPABILITIES
    assert warwick.verification_blockers() == ("COG_MODEL_UNVERIFIED:Warwick",)
    assert warwick.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Warwick.json",
        "data/raw/16.17.1/communitydragon/champions/19.json",
        "data/raw/16.17.1/communitydragon/champions/warwick.bin.json",
    )
    assert all((ROOT / reference).is_file() for reference in warwick.evidence_refs)


def test_warwick_rotation_is_deterministic_and_uses_locked_formulas() -> None:
    """Anchor W5/Q5/E1/R2 and passive outputs to locked values."""
    warwick = create_default_registry(ROOT).require_cog("Warwick")
    context = _context(item_stats={"AD": Decimal(100), "AP": Decimal(100)})

    first = warwick.build_action_plan(context)
    repeated = warwick.build_action_plan(context)
    q = _event(first, "WARWICK_Q_JAWS_OF_THE_BEAST")
    r = _event(first, "WARWICK_R_INFINITE_DURESS_HIT_1")
    attack = _event(first, "WARWICK_PASSIVE_ATTACK_1")
    passive = Decimal(6) + Decimal(49) * Decimal(12) / Decimal(17) + Decimal(15) + Decimal(10)

    assert first == repeated
    assert first.model_id == "warwick_w5_q5_e1_r2_level13_locked_v1"
    assert q.outputs[0].amount == (
        Decimal("1.20") * context.snapshot.attack_damage
        + Decimal(100)
        + Decimal("0.10") * context.opponent_snapshot.max_hp
    )
    assert q.outputs[1].amount == passive
    # The bite heals 75% of the damage both its outputs actually deal.
    assert len(q.outputs) == 2
    assert all(output.source_heal_ratio == Decimal("0.75") for output in q.outputs)
    assert all(output.source_heal_ratio == Decimal(1) for output in r.outputs[:2])
    assert r.outputs[0].amount == (Decimal(350) + Decimal("1.67") * Decimal(100)) / 3
    assert r.outputs[1].amount == passive
    assert attack.outputs[1].amount == passive
    assert "WARWICK_PASSIVE_SELF_HEALTH_THRESHOLDS_NOT_MODELED" in first.blockers
    assert "WARWICK_W_TARGET_HEALTH_THRESHOLDS_NOT_MODELED" in first.blockers


def test_warwick_stats_and_target_health_change_represented_outputs() -> None:
    """Prove AD, AP, attack speed, and target health alter the model."""
    warwick = create_default_registry(ROOT).require_cog("Warwick")
    baseline = warwick.build_action_plan(_context())
    scaled = warwick.build_action_plan(
        _context(
            item_stats={
                "AD": Decimal(50),
                "AP": Decimal(100),
                "ATTACK_SPEED": Decimal("0.50"),
            },
            opponent_health=Decimal(500),
        )
    )

    baseline_q = _event(baseline, "WARWICK_Q_JAWS_OF_THE_BEAST")
    scaled_q = _event(scaled, "WARWICK_Q_JAWS_OF_THE_BEAST")
    baseline_r = _event(baseline, "WARWICK_R_INFINITE_DURESS_HIT_1")
    scaled_r = _event(scaled, "WARWICK_R_INFINITE_DURESS_HIT_1")
    baseline_attacks = tuple(
        event for event in baseline.events if event.id.startswith("WARWICK_PASSIVE_ATTACK_")
    )
    scaled_attacks = tuple(
        event for event in scaled.events if event.id.startswith("WARWICK_PASSIVE_ATTACK_")
    )

    assert scaled_q.outputs[0].amount - baseline_q.outputs[0].amount == Decimal(210)
    assert scaled_q.outputs[1].amount - baseline_q.outputs[1].amount == Decimal("17.5")
    assert scaled_r.outputs[0].amount == (Decimal(350) + Decimal("1.67") * Decimal(50)) / Decimal(3)
    assert baseline_r.outputs[0].amount == (Decimal(350) / Decimal(3))
    assert len(scaled_attacks) > len(baseline_attacks)


def test_warwick_reaction_models_reduction_fear_and_suppression() -> None:
    """Expose E protection and both control channels without conflation."""
    warwick = create_default_registry(ROOT).require_cog("Warwick")
    reaction = warwick.build_reaction_plan(_context())

    reduction = reaction.damage_windows[0]
    suppression, fear = reaction.cast_block_windows
    assert reduction.recipient is EntityId.ACTOR
    assert reduction.damage_types == (DamageType.PHYSICAL, DamageType.MAGIC)
    assert reduction.multiplier == Decimal("0.65")
    assert suppression.control_type.value == "SUPPRESSION"
    assert suppression.tenacity_reducible is False
    assert suppression.source_event_id == "WARWICK_R_INFINITE_DURESS_HIT_1"
    assert fear.control_type.value == "FEAR"
    assert fear.tenacity_reducible is True
    assert fear.source_event_id == "WARWICK_E_PRIMAL_HOWL_RECAST"


def test_warwick_role_reversal_and_blind_preserve_channels() -> None:
    """Keep Warwick role-neutral while blind cancels attacks but not Q or R."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Warwick", "Teemo"))
    as_opponent = engine.evaluate(MatchupRequest("Teemo", "Warwick"))

    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    actor_q = next(
        entry
        for entry in as_actor.timeline.log
        if entry.event_id == "WARWICK_Q_JAWS_OF_THE_BEAST" and entry.operation == "DAMAGE"
    )
    opponent_q = next(
        entry
        for entry in as_opponent.timeline.log
        if entry.event_id == "WARWICK_Q_JAWS_OF_THE_BEAST" and entry.operation == "DAMAGE"
    )
    assert actor_q.recipient is EntityId.TARGET
    assert opponent_q.recipient is EntityId.ACTOR
    assert actor_q.status == opponent_q.status == "APPLIED"
    assert any(
        entry.event_id.startswith("WARWICK_PASSIVE_ATTACK_")
        and entry.action_channel is ActionChannel.BASIC_ATTACK
        and entry.status == "CANCELLED"
        for entry in as_opponent.timeline.log
    )
    assert any(
        entry.event_id.startswith("WARWICK_R_INFINITE_DURESS_HIT_")
        and entry.operation == "DAMAGE"
        and entry.status == "APPLIED"
        for entry in as_opponent.timeline.log
    )


def test_warwick_policy_and_lane_sustain_keep_state_honest() -> None:
    """Accept represented stats while retaining dynamic sustain blockers."""
    warwick = create_default_registry(ROOT).require_cog("Warwick")

    assert (
        warwick.item_candidate_blocker(
            {"id": 1, "stats": {"AD": {}, "AP": {}, "ATTACK_SPEED": {}, "HP": {}}}
        )
        is None
    )
    assert (
        warwick.item_candidate_blocker(
            {"id": 2, "stats": {"ABILITY_HASTE": {}, "LIFESTEAL": {}, "MANA": {}}}
        )
        == "WARWICK_ITEM_STAT_NOT_MODELED:2:ABILITY_HASTE,MANA"
    )
    amount, blockers = warwick.lane_sustain_extra_health(
        _context(),
        duration_ms=30_000,
        no_damage_delay_ms=8_000,
    )
    assert amount == 0
    assert blockers == (
        "WARWICK_LANE_SELF_HEALTH_THRESHOLD_TRACE_NOT_MODELED",
        "WARWICK_LANE_Q_TARGET_AND_RESOURCE_SCHEDULE_NOT_MODELED",
    )
