"""Focused regression tests for the locked Sett champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext, create_default_registry
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    DamageOutput,
    EntityId,
    ShieldOutput,
    StatusOutput,
)

ROOT = Path(__file__).resolve().parents[1]


def _context(*, sett_is_actor: bool = True, item_stats=None) -> ParticipantContext:
    """Build a fixed level-13 Sett versus Garen test context.

    :param sett_is_actor: Place Sett on the actor side when true.
    :param item_stats: Optional Sett item-stat modifiers.
    :return: Role-bound context suitable for direct Cog calls.
    """
    registry = create_default_registry(ROOT)
    sett = registry.require_cog("Sett")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if sett_is_actor else EntityId.TARGET,
        EntityId.TARGET if sett_is_actor else EntityId.ACTOR,
        sett.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13, item_stats={"HP": Decimal(600)}),
        8000,
        3000,
    )


def test_sett_declares_modeled_capabilities_and_locked_evidence() -> None:
    """Distinguish Sett's curated model from a generated scaffold."""
    sett = create_default_registry(ROOT).require_cog("Sett")

    assert sett.maturity is CogMaturity.MODELED_UNVERIFIED
    assert sett.capabilities == DUEL_CAPABILITIES
    assert sett.verification_blockers() == ("COG_MODEL_UNVERIFIED:Sett",)
    assert len(sett.evidence_refs) == 3
    assert all((ROOT / path).is_file() for path in sett.evidence_refs)


def test_sett_rotation_is_deterministic_and_alternates_punches() -> None:
    """Preserve deterministic left/right attacks and Q's two-hit scope."""
    sett = create_default_registry(ROOT).require_cog("Sett")
    context = _context(item_stats={"AD": Decimal(100)})

    first = sett.build_action_plan(context)
    second = sett.build_action_plan(context)
    punches = tuple(event for event in first.events if event.channel is ActionChannel.BASIC_ATTACK)

    assert first == second
    assert first.model_id == "sett_q5_w5_e1_r2_level13_synthetic_v1"
    assert punches[0].id.startswith("SETT_Q_LEFT")
    assert punches[1].id.startswith("SETT_Q_RIGHT")
    assert len(punches[0].outputs) == 2
    assert len(punches[1].outputs) == 3
    assert len(punches[2].outputs) == 1
    assert len(punches[3].outputs) == 2
    assert punches[1].outputs[1].amount == Decimal("120")
    assert "SETT_W_DYNAMIC_GRIT_ACCUMULATION_NOT_MODELED" in first.blockers


def test_sett_formulas_respond_to_ad_health_attack_speed_and_target_bonus_health() -> None:
    """Anchor every supported offensive stat channel to a modeled output."""
    sett = create_default_registry(ROOT).require_cog("Sett")
    baseline = sett.build_action_plan(_context())
    scaled_context = _context(
        item_stats={
            "AD": Decimal(100),
            "HP": Decimal(500),
            "ATTACK_SPEED": Decimal("0.50"),
        }
    )
    scaled = sett.build_action_plan(scaled_context)
    scaled_w = next(event for event in scaled.events if event.id.startswith("SETT_W_"))
    scaled_r = next(event for event in scaled.events if event.id == "SETT_R_SHOW_STOPPER")
    scaled_e = next(event for event in scaled.events if event.id.startswith("SETT_E_"))

    max_grit = Decimal("0.50") * scaled_context.snapshot.max_hp
    assert isinstance(scaled_w.outputs[0], ShieldOutput)
    assert scaled_w.outputs[0].amount == max_grit
    assert scaled_w.outputs[0].decay_delay_ms == 750
    assert isinstance(scaled_w.outputs[1], DamageOutput)
    assert scaled_w.outputs[1].damage_type is DamageType.TRUE
    assert scaled_w.outputs[1].amount == Decimal(160) + max_grit * Decimal("0.50")
    assert scaled_r.outputs[0].amount == Decimal(300) + Decimal(120) + Decimal(300)
    assert scaled_e.outputs[0].amount == (
        Decimal(50) + Decimal("0.60") * scaled_context.snapshot.attack_damage
    )
    baseline_punches = tuple(
        event for event in baseline.events if event.channel is ActionChannel.BASIC_ATTACK
    )
    scaled_punches = tuple(
        event for event in scaled.events if event.channel is ActionChannel.BASIC_ATTACK
    )
    assert len(scaled_punches) > len(baseline_punches)


def test_sett_duel_e_slows_without_fabricating_two_sided_stun() -> None:
    """Keep Facebreaker's stun gated by the absent second-enemy condition."""
    sett = create_default_registry(ROOT).require_cog("Sett")
    plan = sett.build_action_plan(_context())
    e = next(event for event in plan.events if event.id.startswith("SETT_E_"))
    controls = tuple(output for output in e.outputs if isinstance(output, StatusOutput))
    reaction = sett.build_reaction_plan(_context())

    assert tuple(output.status for output in controls) == ("CC_SLOW",)
    assert reaction.cast_block_windows[1].control_type.value == "SLOW"
    assert all(window.control_type.value != "STUN" for window in reaction.cast_block_windows)
    assert "SETT_E_TWO_SIDED_STUN_CONDITION_UNMET_DUEL" in plan.blockers


def test_sett_suppression_and_outputs_follow_role_reversal() -> None:
    """Keep Sett's actions and control attached to Sett in either request role."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Sett", "Garen"))
    as_opponent = engine.evaluate(MatchupRequest("Garen", "Sett"))

    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    actor_w = next(
        entry
        for entry in as_actor.timeline.log
        if entry.event_id.startswith("SETT_W_") and entry.operation == "SHIELD"
    )
    opponent_w = next(
        entry
        for entry in as_opponent.timeline.log
        if entry.event_id.startswith("SETT_W_") and entry.operation == "SHIELD"
    )
    assert actor_w.recipient is EntityId.ACTOR
    assert opponent_w.recipient is EntityId.TARGET
    assert any(
        entry.status == "CANCELLED" and entry.detail == "OPPONENT_CAST_BLOCK:sett_r_suppression"
        for entry in as_actor.timeline.log
    )
    assert any(
        entry.status == "CANCELLED" and entry.detail == "OPPONENT_CAST_BLOCK:sett_r_suppression"
        for entry in as_opponent.timeline.log
    )


def test_sett_item_policy_accepts_chassis_stats_and_rejects_fixed_policy_gaps() -> None:
    """Allow supported Sett scaling while excluding unmodeled item channels."""
    sett = create_default_registry(ROOT).require_cog("Sett")

    assert (
        sett.item_candidate_blocker({"id": 1, "stats": {"AD": {}, "HP": {}, "ATTACK_SPEED": {}}})
        is None
    )
    assert (
        sett.item_candidate_blocker(
            {"id": 2, "stats": {"ABILITY_HASTE": {}, "HEAL_SHIELD_POWER": {}}}
        )
        == "SETT_ITEM_STAT_NOT_MODELED:2:ABILITY_HASTE,HEAL_SHIELD_POWER"
    )
