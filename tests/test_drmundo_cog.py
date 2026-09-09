"""Focused regressions for the locked Dr. Mundo champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES, ActionPlan
from lol_build.cogs.champions.wip.drmundo import DrMundoCog
from lol_build.cogs.registry import create_default_registry
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionEvent, EntityId, HealOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    mundo_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
    opponent_item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a role-neutral level-13 Mundo-versus-Teemo context.

    :param mundo_is_actor: Place Dr. Mundo on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Mundo.
    :param opponent_item_stats: Optional item modifiers applied to Teemo.
    :return: Role-bound deterministic benchmark context.
    """
    registry = create_default_registry(ROOT)
    mundo = registry.require_cog("DrMundo")
    teemo = registry.require_cog("Teemo")
    return ParticipantContext(
        EntityId.ACTOR if mundo_is_actor else EntityId.TARGET,
        EntityId.TARGET if mundo_is_actor else EntityId.ACTOR,
        mundo.snapshot(level=13, item_stats=item_stats),
        teemo.snapshot(level=13, item_stats=opponent_item_stats),
        8000,
        3000,
    )


def _event(plan: ActionPlan, event_id: str) -> ActionEvent:
    """Resolve one event from a Dr. Mundo action plan.

    :param plan: Action plan containing the expected event.
    :param event_id: Stable identifier of the requested action.
    :return: Matching immutable action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_drmundo_declares_modeled_capabilities_and_locked_evidence() -> None:
    """Distinguish Mundo's model from a scaffold and retain three sources."""
    mundo = create_default_registry(ROOT).require_cog("DrMundo")

    assert mundo.maturity is CogMaturity.MODELED_UNVERIFIED
    assert mundo.capabilities == DUEL_CAPABILITIES
    assert mundo.verification_blockers() == ("COG_MODEL_UNVERIFIED:DrMundo",)
    assert mundo.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/DrMundo.json",
        "data/raw/16.17.1/communitydragon/champions/36.json",
        "data/raw/16.17.1/communitydragon/champions/drmundo.bin.json",
    )
    assert all((ROOT / reference).is_file() for reference in mundo.evidence_refs)


def test_drmundo_rotation_is_deterministic_and_keeps_dynamic_blockers() -> None:
    """Anchor Q5/W1/E5/R2 scheduling without hiding state assumptions."""
    mundo = create_default_registry(ROOT).require_cog("DrMundo")
    context = _context()

    first = mundo.build_action_plan(context)
    repeated = mundo.build_action_plan(context)

    assert first == repeated
    assert first.model_id == "drmundo_q5_w1_e5_r2_level13_synthetic_v1"
    assert len([event for event in first.events if "HEART_ZAPPER_TICK" in event.id]) == 12
    assert len([event for event in first.events if "MAXIMUM_DOSAGE_HEAL" in event.id]) == 7
    assert "DRMUNDO_Q_CURRENT_HEALTH_FROZEN_AT_OPENING_SNAPSHOT" in first.blockers
    assert "DRMUNDO_W_LIVE_GRAY_HEALTH_ACCUMULATION_NOT_MODELED" in first.blockers
    assert "DRMUNDO_E_MISSING_HEALTH_DAMAGE_AMPLIFICATION_NOT_MODELED" in first.blockers
    assert "DRMUNDO_PASSIVE_CANISTER_PICKUP_NOT_MODELED" in first.blockers


def test_drmundo_q_applies_champion_minimum_and_monster_maximum_correctly() -> None:
    """Keep Q's minimum universal and its maximum monster-only."""
    assert DrMundoCog._q_damage_for_health(Decimal(500)) == Decimal(280)
    assert DrMundoCog._q_damage_for_health(Decimal(3000)) == Decimal(900)
    assert DrMundoCog._q_damage_for_health(Decimal(3000), target_is_monster=True) == Decimal(550)


def test_drmundo_health_ad_and_attack_speed_reach_modeled_outputs() -> None:
    """Prove chassis stats affect E conversion, direct AD, and cadence."""
    mundo = create_default_registry(ROOT).require_cog("DrMundo")
    baseline = mundo.build_action_plan(_context())
    health = mundo.build_action_plan(_context(item_stats={"HP": Decimal(500)}))
    attack = mundo.build_action_plan(_context(item_stats={"AD": Decimal(50)}))
    speed = mundo.build_action_plan(_context(item_stats={"ATTACK_SPEED": Decimal("0.50")}))

    baseline_e = _event(baseline, "DRMUNDO_E_BLUNT_FORCE_TRAUMA")
    health_e = _event(health, "DRMUNDO_E_BLUNT_FORCE_TRAUMA")
    attack_e = _event(attack, "DRMUNDO_E_BLUNT_FORCE_TRAUMA")
    baseline_attacks = [event for event in baseline.events if "BASIC_ATTACK" in event.id]
    speed_attacks = [event for event in speed.events if "BASIC_ATTACK" in event.id]

    assert health_e.outputs[1].amount - baseline_e.outputs[1].amount == Decimal(41)
    assert attack_e.outputs[1].amount - baseline_e.outputs[1].amount == Decimal(50)
    assert len(speed_attacks) > len(baseline_attacks)
    assert mundo.engagement_speed_multiplier(_context()) == Decimal("1.25")


def test_drmundo_w_r_and_health_costs_are_explicit_outputs() -> None:
    """Represent W recovery, R regeneration, and spell health payments."""
    mundo = create_default_registry(ROOT).require_cog("DrMundo")
    context = _context(item_stats={"HP": Decimal(500)})
    plan = mundo.build_action_plan(context)
    w_start = _event(plan, "DRMUNDO_W_HEART_ZAPPER_START")
    w_recast = _event(plan, "DRMUNDO_W_HEART_ZAPPER_RECAST")
    e = _event(plan, "DRMUNDO_E_BLUNT_FORCE_TRAUMA")
    r_tick = _event(plan, "DRMUNDO_R_MAXIMUM_DOSAGE_HEAL_1")

    assert w_start.outputs[0].recipient is context.self_entity
    assert w_start.outputs[0].damage_type is DamageType.TRUE
    assert w_start.outputs[0].amount == Decimal("0.08") * context.snapshot.max_hp
    assert isinstance(w_recast.outputs[1], HealOutput)
    assert w_recast.outputs[1].amount > 0
    assert w_recast.outputs[0].amount == (
        Decimal(20) + Decimal("0.07") * context.snapshot.bonus_health
    )
    assert e.outputs[0].recipient is context.self_entity
    assert e.outputs[0].amount == Decimal(70)
    assert isinstance(r_tick.outputs[0], HealOutput)
    assert r_tick.outputs[0].amount == Decimal("0.04") * context.snapshot.max_hp


def test_drmundo_role_reversal_and_teemo_blind_preserve_channels() -> None:
    """Keep Mundo role-neutral while blind cancels attacks but not spells."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("DrMundo", "Teemo"))
    as_opponent = engine.evaluate(MatchupRequest("Teemo", "DrMundo"))

    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    assert any(
        entry.event_id.startswith("DRMUNDO_BASIC_ATTACK_") and entry.status == "CANCELLED"
        for entry in as_actor.timeline.log
    )
    assert any(
        entry.event_id == "DRMUNDO_E_BLUNT_FORCE_TRAUMA" and entry.status == "CANCELLED"
        for entry in as_actor.timeline.log
    )
    target_q = next(
        entry
        for entry in as_opponent.timeline.log
        if entry.event_id == "DRMUNDO_Q_INFECTED_BONESAW_1"
        and entry.operation == "DAMAGE"
        and entry.recipient is EntityId.ACTOR
    )
    assert target_q.status == "APPLIED"


def test_drmundo_policy_and_reactions_keep_unmodeled_state_honest() -> None:
    """Accept represented stats and retain passive or lane-state blockers."""
    mundo = create_default_registry(ROOT).require_cog("DrMundo")

    assert (
        mundo.item_candidate_blocker(
            {"id": 1, "stats": {"AD": {}, "HP": {}, "ATTACK_SPEED": {}, "ARMOR": {}}}
        )
        is None
    )
    assert (
        mundo.item_candidate_blocker(
            {"id": 2, "stats": {"ABILITY_HASTE": {}, "MANA": {}, "OMNIVAMP": {}}}
        )
        == "DRMUNDO_ITEM_STAT_NOT_MODELED:2:ABILITY_HASTE,MANA,OMNIVAMP"
    )
    assert mundo.build_reaction_plan(_context()).blockers == (
        "DRMUNDO_PASSIVE_FIRST_IMMOBILIZING_EFFECT_ONLY_NOT_MODELED",
        "DRMUNDO_PASSIVE_HEALTH_COST_AND_CANISTER_STATE_NOT_MODELED",
        "DRMUNDO_W_INCOMING_DAMAGE_STORAGE_REQUIRES_LIVE_HEALTH_TRACE",
    )
    amount, blockers = mundo.lane_sustain_extra_health(
        _context(), duration_ms=30_000, no_damage_delay_ms=8_000
    )
    assert amount == 0
    assert blockers == (
        "DRMUNDO_LANE_PASSIVE_REGEN_HEALTH_TRACE_NOT_MODELED",
        "DRMUNDO_LANE_Q_HEALTH_COST_REFUND_HIT_RATE_NOT_MODELED",
    )
