"""Focused regressions for the locked Draven champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES, ActionPlan, ControlType
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import ActionChannel, ActionEvent, DamageOutput, EntityId

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    item_stats: dict[str, Decimal] | None = None,
    draven_is_actor: bool = True,
) -> ParticipantContext:
    """Build a role-neutral level-13 Draven-versus-Teemo context.

    :param item_stats: Optional permanent item modifiers applied to Draven.
    :param draven_is_actor: Place Draven on the actor side when true.
    :return: Role-bound deterministic benchmark context.
    """
    registry = create_default_registry(ROOT)
    draven = registry.require_cog("Draven")
    teemo = registry.require_cog("Teemo")
    return ParticipantContext(
        EntityId.ACTOR if draven_is_actor else EntityId.TARGET,
        EntityId.TARGET if draven_is_actor else EntityId.ACTOR,
        draven.snapshot(level=13, item_stats=item_stats),
        teemo.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan: ActionPlan, event_id: str) -> ActionEvent:
    """Resolve one champion-scoped event from an action plan.

    :param plan: Draven action plan containing the expected event.
    :param event_id: Identifier of the requested action.
    :return: Matching immutable action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_draven_declares_modeled_capabilities_and_three_locked_sources() -> None:
    """Distinguish Draven's model from a scaffold and retain its evidence."""
    draven = create_default_registry(ROOT).require_cog("Draven")

    assert draven.maturity is CogMaturity.MODELED_UNVERIFIED
    assert draven.capabilities == DUEL_CAPABILITIES
    assert draven.verification_blockers() == ("COG_MODEL_UNVERIFIED:Draven",)
    assert draven.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Draven.json",
        "data/raw/16.17.1/communitydragon/champions/119.json",
        "data/raw/16.17.1/communitydragon/champions/draven.bin.json",
    )
    assert all((ROOT / reference).is_file() for reference in draven.evidence_refs)


def test_draven_rotation_is_deterministic_and_anchors_locked_rank_values() -> None:
    """Anchor Q5, W5, E1, R2, fixed catches, and both ultimate passes."""
    draven = create_default_registry(ROOT).require_cog("Draven")
    context = _context(item_stats={"AD": Decimal(40)})

    first = draven.build_action_plan(context)
    repeated = draven.build_action_plan(context)
    q = _event(first, "DRAVEN_Q_SPINNING_AXE_ATTACK_1")
    e = _event(first, "DRAVEN_E_STAND_ASIDE_1")
    outward = _event(first, "DRAVEN_R_WHIRLING_DEATH_OUTWARD")
    returning = _event(first, "DRAVEN_R_WHIRLING_DEATH_RETURN")
    catches = tuple(event for event in first.events if "FIXED_AXE_CATCH" in event.id)
    recasts = tuple(event for event in first.events if "RESET_RECAST" in event.id)

    assert first == repeated
    assert first.model_id == "draven_q5_w5_e1_r2_fixed_catches_level13_v1"
    assert isinstance(q.outputs[0], DamageOutput)
    assert q.outputs[0].amount == (
        context.snapshot.attack_damage
        + Decimal(60)
        + Decimal("1.15") * context.snapshot.bonus_attack_damage
    )
    assert e.outputs[0].amount == Decimal(75) + Decimal("0.50") * Decimal(40)
    assert outward.outputs[0].amount == Decimal(300) + Decimal("1.30") * Decimal(40)
    assert returning.outputs[0].amount == outward.outputs[0].amount
    assert len(catches) == len(recasts)
    assert all(
        recast.at_ms == catch.at_ms + 1
        for catch, recast in zip(catches, recasts, strict=True)
    )
    assert "DRAVEN_Q_AXE_LANDING_POSITION_NOT_MODELED" in first.blockers
    assert "DRAVEN_R_ADORATION_EXECUTE_NOT_MODELED" in first.blockers
    assert "DRAVEN_R_MULTI_TARGET_DAMAGE_REDUCTION_NOT_MODELED" in first.blockers


def test_draven_ad_attack_speed_critical_chance_and_haste_are_consumed() -> None:
    """Prove all principal offensive item stats alter represented outputs."""
    draven = create_default_registry(ROOT).require_cog("Draven")
    baseline = draven.build_action_plan(_context())
    more_ad = draven.build_action_plan(_context(item_stats={"AD": Decimal(50)}))
    more_speed = draven.build_action_plan(
        _context(item_stats={"ATTACK_SPEED": Decimal("0.50")})
    )
    more_crit = draven.build_action_plan(
        _context(item_stats={"CRITICAL_STRIKE_CHANCE": Decimal("0.25")})
    )
    more_haste = draven.build_action_plan(
        _context(item_stats={"ABILITY_HASTE": Decimal(150)})
    )

    baseline_q = _event(baseline, "DRAVEN_Q_SPINNING_AXE_ATTACK_1")
    ad_q = _event(more_ad, "DRAVEN_Q_SPINNING_AXE_ATTACK_1")
    crit_q = _event(more_crit, "DRAVEN_Q_SPINNING_AXE_ATTACK_1")
    baseline_attacks = tuple(
        event for event in baseline.events if "SPINNING_AXE_ATTACK" in event.id
    )
    faster_attacks = tuple(
        event for event in more_speed.events if "SPINNING_AXE_ATTACK" in event.id
    )
    haste_e = tuple(event for event in more_haste.events if "E_STAND_ASIDE" in event.id)

    assert ad_q.outputs[0].amount - baseline_q.outputs[0].amount == Decimal("107.50")
    assert crit_q.outputs[0].amount == baseline_q.outputs[0].amount * Decimal("1.25")
    assert len(faster_attacks) > len(baseline_attacks)
    assert tuple(event.at_ms for event in haste_e) == (150, 6550)


def test_draven_e_control_is_causal_and_preserves_control_semantics() -> None:
    """Expose E displacement and slow without treating airborne as tenacity CC."""
    draven = create_default_registry(ROOT).require_cog("Draven")
    context = _context()
    reaction = draven.build_reaction_plan(context)

    displacement, slow = reaction.cast_block_windows[:2]
    assert displacement.source_event_id == "DRAVEN_E_STAND_ASIDE_1"
    assert displacement.control_type is ControlType.AIRBORNE
    assert displacement.tenacity_reducible is False
    assert displacement.blocked_channels == (
        ActionChannel.BASIC_ATTACK,
        ActionChannel.ABILITY,
        ActionChannel.MOVEMENT,
    )
    assert slow.source_event_id == displacement.source_event_id
    assert slow.control_type is ControlType.SLOW
    assert slow.tenacity_reducible is True
    assert slow.blocked_channels == (ActionChannel.MOVEMENT,)


def test_draven_role_reversal_and_teemo_blind_are_channel_correct() -> None:
    """Keep Draven role-neutral and let blind cancel Q attacks but not R."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Draven", "Teemo"))
    as_opponent = engine.evaluate(MatchupRequest("Teemo", "Draven"))

    actor_r = next(
        entry
        for entry in as_actor.timeline.log
        if entry.event_id == "DRAVEN_R_WHIRLING_DEATH_OUTWARD"
        and entry.operation == "DAMAGE"
    )
    opponent_r = next(
        entry
        for entry in as_opponent.timeline.log
        if entry.event_id == "DRAVEN_R_WHIRLING_DEATH_OUTWARD"
        and entry.operation == "DAMAGE"
    )
    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    assert actor_r.recipient is EntityId.TARGET
    assert opponent_r.recipient is EntityId.ACTOR
    assert opponent_r.status == "APPLIED"
    assert any(
        entry.event_id.startswith("DRAVEN_Q_SPINNING_AXE_ATTACK_")
        and entry.status == "CANCELLED"
        and entry.action_channel is ActionChannel.BASIC_ATTACK
        for entry in as_opponent.timeline.log
    )


def test_draven_engagement_and_item_policy_preserve_model_boundaries() -> None:
    """Expose W pursuit while rejecting item channels absent from the fixture."""
    draven = create_default_registry(ROOT).require_cog("Draven")
    context = _context()

    assert draven.engagement_speed_multiplier(context) == Decimal("1.70")
    assert draven.item_candidate_blocker(
        {
            "id": 1,
            "stats": {
                "AD": {},
                "ATTACK_SPEED": {},
                "CRITICAL_STRIKE_CHANCE": {},
                "ABILITY_HASTE": {},
            },
        }
    ) is None
    assert draven.item_candidate_blocker(
        {"id": 2, "stats": {"AP": {}, "LIFESTEAL": {}, "MANA": {}}}
    ) == "DRAVEN_ITEM_STAT_NOT_MODELED:2:AP,LIFESTEAL,MANA"
