"""Focused regression tests for the locked Volibear champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext, create_default_registry
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.core.timeline import (
    DamageOutput,
    EntityId,
    HealOutput,
    ShieldOutput,
)

ROOT = Path(__file__).resolve().parents[1]


def _context(*, volibear_is_actor: bool = True, item_stats=None) -> ParticipantContext:
    """Build a level-13 Volibear versus Garen unit-test context."""
    registry = create_default_registry(ROOT)
    volibear = registry.require_cog("Volibear")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if volibear_is_actor else EntityId.TARGET,
        EntityId.TARGET if volibear_is_actor else EntityId.ACTOR,
        volibear.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def test_volibear_declares_modeled_capabilities_and_three_locked_sources() -> None:
    """Distinguish the Volibear model from a generated champion scaffold."""
    volibear = create_default_registry(ROOT).require_cog("Volibear")

    assert volibear.maturity is CogMaturity.MODELED_UNVERIFIED
    assert volibear.capabilities == DUEL_CAPABILITIES
    assert volibear.verification_blockers() == ("COG_MODEL_UNVERIFIED:Volibear",)
    assert len(volibear.evidence_refs) == 3
    assert all((ROOT / ref).is_file() for ref in volibear.evidence_refs)


def test_volibear_rotation_is_deterministic_and_keeps_w_at_five_seconds() -> None:
    """Keep W reuse independent from attack-speed-sensitive attack cadence."""
    volibear = create_default_registry(ROOT).require_cog("Volibear")
    baseline = volibear.build_action_plan(_context())
    repeated = volibear.build_action_plan(_context())
    faster = volibear.build_action_plan(_context(item_stats={"ATTACK_SPEED": Decimal("0.50")}))

    assert baseline == repeated
    assert baseline.model_id == "volibear_q5_w5_e1_r2_level13_synthetic_v1"
    baseline_w = tuple(
        event.at_ms for event in baseline.events if event.id.startswith("VOLIBEAR_W")
    )
    faster_w = tuple(event.at_ms for event in faster.events if event.id.startswith("VOLIBEAR_W"))
    assert baseline_w == faster_w == (900, 5900)
    baseline_attacks = tuple(
        event for event in baseline.events if event.id.startswith("VOLIBEAR_PASSIVE_ATTACK")
    )
    faster_attacks = tuple(
        event for event in faster.events if event.id.startswith("VOLIBEAR_PASSIVE_ATTACK")
    )
    assert len(faster_attacks) > len(baseline_attacks)
    assert "VOLIBEAR_W2_MISSING_HEALTH_HEAL_NOT_EVALUATED" in baseline.blockers


def test_volibear_locked_formulas_respond_to_ad_ap_health_and_target_health() -> None:
    """Anchor modeled spell outputs to the locked rank values and stat channels."""
    volibear = create_default_registry(ROOT).require_cog("Volibear")
    context = _context(
        item_stats={
            "AD": Decimal(100),
            "AP": Decimal(100),
            "HP": Decimal(500),
        }
    )
    plan = volibear.build_action_plan(context)
    q = next(event for event in plan.events if event.id == "VOLIBEAR_Q_THUNDERING_SMASH")
    w1 = next(event for event in plan.events if event.id == "VOLIBEAR_W1_FRENZIED_MAUL")
    w2 = next(event for event in plan.events if event.id == "VOLIBEAR_W2_FRENZIED_MAUL")
    e = next(event for event in plan.events if event.id == "VOLIBEAR_E_SKY_SPLITTER")
    r = next(event for event in plan.events if event.id == "VOLIBEAR_R_STORMBRINGER")
    passive = next(event for event in plan.events if event.id == "VOLIBEAR_PASSIVE_ATTACK_1")

    expected_w1 = (
        Decimal(105)
        + Decimal("1.10") * context.snapshot.attack_damage
        + Decimal("0.06") * context.snapshot.bonus_health
    )
    assert isinstance(q.outputs[0], DamageOutput)
    assert q.outputs[0].amount == (
        Decimal(50)
        + context.snapshot.attack_damage
        + Decimal("1.60") * context.snapshot.bonus_attack_damage
    )
    assert w1.outputs[0].amount == expected_w1
    assert w2.outputs[0].amount == expected_w1 * Decimal("1.75")
    assert isinstance(w2.outputs[1], HealOutput)
    assert w2.outputs[1].amount == 80
    assert e.outputs[0].amount == (
        Decimal(80)
        + Decimal("0.70") * context.snapshot.ability_power
        + Decimal("0.11") * context.opponent_snapshot.max_hp
    )
    assert r.outputs[0].amount == (
        Decimal(500)
        + Decimal("1.25") * context.snapshot.ability_power
        + Decimal("2.50") * context.snapshot.bonus_attack_damage
    )
    assert passive.outputs[1].amount == Decimal(85)


def test_volibear_reaction_exposes_shield_stun_and_engagement() -> None:
    """Keep defensive and pursuit mechanics attached to Volibear's own context."""
    volibear = create_default_registry(ROOT).require_cog("Volibear")
    context = _context(item_stats={"AP": Decimal(100), "HP": Decimal(500)})
    reaction = volibear.build_reaction_plan(context)

    shield = reaction.events[0].outputs[0]
    assert isinstance(shield, ShieldOutput)
    assert shield.amount == Decimal("0.14") * context.snapshot.max_hp + Decimal(75)
    assert shield.duration_ms == 3000
    stun = reaction.cast_block_windows[0]
    assert stun.source_event_id == "VOLIBEAR_Q_THUNDERING_SMASH"
    assert stun.tenacity_reducible is True
    assert stun.end_ms - stun.start_ms == 1000
    assert volibear.engagement_speed_multiplier(context) == Decimal("1.52")
    assert volibear.engagement_dash_distance(context) == Decimal(700)


def test_volibear_actions_and_protection_follow_role_reversal() -> None:
    """Keep Volibear mechanics role-neutral in both request positions."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Volibear", "Ashe"))
    as_opponent = engine.evaluate(MatchupRequest("Ashe", "Volibear"))

    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    actor_w = next(
        entry
        for entry in as_actor.timeline.log
        if entry.event_id == "VOLIBEAR_W1_FRENZIED_MAUL" and entry.operation == "DAMAGE"
    )
    opponent_w = next(
        entry
        for entry in as_opponent.timeline.log
        if entry.event_id == "VOLIBEAR_W1_FRENZIED_MAUL" and entry.operation == "DAMAGE"
    )
    actor_shield = next(
        entry for entry in as_actor.timeline.log if entry.event_id == "VOLIBEAR_E_SELF_SHIELD"
    )
    opponent_shield = next(
        entry for entry in as_opponent.timeline.log if entry.event_id == "VOLIBEAR_E_SELF_SHIELD"
    )
    assert actor_w.recipient is EntityId.TARGET
    assert opponent_w.recipient is EntityId.ACTOR
    assert actor_shield.recipient is EntityId.ACTOR
    assert opponent_shield.recipient is EntityId.TARGET


def test_volibear_item_policy_rejects_only_unrepresented_stat_channels() -> None:
    """Keep supported chassis stats while rejecting unmodeled resource channels."""
    volibear = create_default_registry(ROOT).require_cog("Volibear")

    assert (
        volibear.item_candidate_blocker(
            {"id": 1, "stats": {"AD": {}, "AP": {}, "HP": {}, "ATTACK_SPEED": {}}}
        )
        is None
    )
    assert (
        volibear.item_candidate_blocker({"id": 2, "stats": {"ABILITY_HASTE": {}, "MANA": {}}})
        == "VOLIBEAR_ITEM_STAT_NOT_MODELED:2:ABILITY_HASTE,MANA"
    )


def test_volibear_lane_sustain_requires_same_target_w_mark_evidence() -> None:
    """Avoid inventing lane recovery when W mark continuity is unknown."""
    volibear = create_default_registry(ROOT).require_cog("Volibear")

    amount, blockers = volibear.lane_sustain_extra_health(
        _context(),
        duration_ms=30_000,
        no_damage_delay_ms=8_000,
    )

    assert amount == 0
    assert blockers == ("VOLIBEAR_LANE_W_MARK_TARGET_CONTINUITY_NOT_MODELED",)
