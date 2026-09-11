"""Focused regressions for the locked Blitzcrank champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES, ActionPlan
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    EntityId,
    StatModifierOutput,
    StatusOutput,
)

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    blitzcrank_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a role-neutral level-13 Blitzcrank-versus-Teemo context.

    :param blitzcrank_is_actor: Place Blitzcrank on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Blitzcrank.
    :return: Role-bound deterministic benchmark context.
    """
    registry = create_default_registry(ROOT)
    blitzcrank = registry.require_cog("Blitzcrank")
    teemo = registry.require_cog("Teemo")
    return ParticipantContext(
        EntityId.ACTOR if blitzcrank_is_actor else EntityId.TARGET,
        EntityId.TARGET if blitzcrank_is_actor else EntityId.ACTOR,
        blitzcrank.snapshot(level=13, item_stats=item_stats),
        teemo.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan: ActionPlan, event_id: str) -> ActionEvent:
    """Resolve one champion-scoped event from a Blitzcrank action plan.

    :param plan: Blitzcrank action plan containing the expected event.
    :param event_id: Identifier of the requested action.
    :return: Matching immutable action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def _attacks(plan: ActionPlan) -> tuple[ActionEvent, ...]:
    """Select ordinary Blitzcrank attacks from one action plan.

    :param plan: Blitzcrank action plan containing ordinary attacks.
    :return: Chronological ordinary basic-attack events.
    """
    return tuple(event for event in plan.events if event.id.startswith("BLITZCRANK_BASIC_ATTACK_"))


def test_blitzcrank_declares_modeled_capabilities_and_three_sources() -> None:
    """Distinguish Blitzcrank's implemented Cog from its former scaffold."""
    blitzcrank = create_default_registry(ROOT).require_cog("Blitzcrank")

    assert blitzcrank.maturity is CogMaturity.MODELED_UNVERIFIED
    assert blitzcrank.capabilities == DUEL_CAPABILITIES
    assert blitzcrank.verification_blockers() == ("COG_MODEL_UNVERIFIED:Blitzcrank",)
    assert blitzcrank.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Blitzcrank.json",
        "data/raw/16.17.1/communitydragon/champions/53.json",
        "data/raw/16.17.1/communitydragon/champions/blitzcrank.bin.json",
    )
    assert all((ROOT / path).is_file() for path in blitzcrank.evidence_refs)


def test_blitzcrank_rotation_is_deterministic_and_uses_locked_values() -> None:
    """Anchor Q5/E5/W1/R2 outputs and Static Field mark ordering."""
    blitzcrank = create_default_registry(ROOT).require_cog("Blitzcrank")
    context = _context(item_stats={"AP": Decimal(100), "AD": Decimal(40)})

    first = blitzcrank.build_action_plan(context)
    repeated = blitzcrank.build_action_plan(context)
    q = _event(first, "BLITZCRANK_Q_ROCKET_GRAB_HIT")
    fist = _event(first, "BLITZCRANK_E_POWER_FIST_ATTACK")
    zap = _event(first, "BLITZCRANK_R_PASSIVE_ZAP_POWER_FIST")
    ultimate = _event(first, "BLITZCRANK_R_STATIC_FIELD_ACTIVE")
    native_mana = Decimal(267) + Decimal(40) * blitzcrank.growth_multiplier(13)

    assert first == repeated
    assert first.model_id == "blitzcrank_q5_e5_w1_r2_hook_fixture_level13_v1"
    assert q.outputs[0].amount == 410
    assert fist.outputs[0].amount == Decimal(2) * context.snapshot.attack_damage + 25
    assert zap.outputs[0].amount == Decimal(100) + Decimal(40) + Decimal("0.02") * native_mana
    assert ultimate.outputs[0].amount == 500
    assert zap.at_ms == fist.at_ms + 1000
    assert "BLITZCRANK_Q_DAMAGE_LOCKED_SOURCES_DISAGREE_290_VS_310" in first.blockers
    assert "BLITZCRANK_R_ACTIVE_SHIELD_DESTRUCTION_NOT_MODELED" in first.blockers


def test_blitzcrank_ap_attack_speed_and_move_speed_reach_outputs() -> None:
    """Prove AP, attack speed, and movement speed alter distinct channels."""
    blitzcrank = create_default_registry(ROOT).require_cog("Blitzcrank")
    baseline = blitzcrank.build_action_plan(_context())
    power = blitzcrank.build_action_plan(_context(item_stats={"AP": Decimal(100)}))
    speed = blitzcrank.build_action_plan(_context(item_stats={"ATTACK_SPEED": Decimal("0.50")}))
    movement = blitzcrank.build_action_plan(_context(item_stats={"MOVE_SPEED_FLAT": Decimal(100)}))

    assert (
        _event(power, "BLITZCRANK_Q_ROCKET_GRAB_HIT").outputs[0].amount
        - _event(baseline, "BLITZCRANK_Q_ROCKET_GRAB_HIT").outputs[0].amount
        == 120
    )
    assert (
        _event(power, "BLITZCRANK_E_POWER_FIST_ATTACK").outputs[0].amount
        - _event(baseline, "BLITZCRANK_E_POWER_FIST_ATTACK").outputs[0].amount
        == 25
    )
    assert (
        _event(power, "BLITZCRANK_R_PASSIVE_ZAP_POWER_FIST").outputs[0].amount
        - _event(baseline, "BLITZCRANK_R_PASSIVE_ZAP_POWER_FIST").outputs[0].amount
        == 40
    )
    assert len(_attacks(speed)) > len(_attacks(baseline))
    baseline_w = _event(baseline, "BLITZCRANK_W_OVERDRIVE_START").outputs[0]
    movement_w = _event(movement, "BLITZCRANK_W_OVERDRIVE_START").outputs[0]
    assert isinstance(baseline_w, StatModifierOutput)
    assert isinstance(movement_w, StatModifierOutput)
    assert movement_w.amount - baseline_w.amount == 60


def test_blitzcrank_engagement_and_overdrive_end_are_explicit() -> None:
    """Expose hook reach, initial speed, and the delayed self-slow."""
    blitzcrank = create_default_registry(ROOT).require_cog("Blitzcrank")
    context = _context()
    plan = blitzcrank.build_action_plan(context)
    end = _event(plan, "BLITZCRANK_W_OVERDRIVE_SELF_SLOW")

    assert blitzcrank.engagement_speed_multiplier(context) == Decimal("1.60")
    assert blitzcrank.engagement_dash_distance(context) == 1079
    assert end.at_ms == 5000
    assert isinstance(end.outputs[0], StatModifierOutput)
    assert end.outputs[0].amount == -context.snapshot.move_speed * Decimal("0.30")
    assert isinstance(end.outputs[1], StatusOutput)
    assert (end.outputs[1].status, end.outputs[1].duration_ms) == ("CC_SLOW", 1500)
    assert "BLITZCRANK_Q_PULL_DISTANCE_LANDING_POINT_NOT_EVALUATED" in plan.blockers
    assert "BLITZCRANK_W_MOVEMENT_SPEED_DECAY_APPROXIMATED_INITIAL_WINDOW" in plan.blockers


def test_blitzcrank_control_windows_preserve_distinct_semantics() -> None:
    """Keep Q/E displacement discrete and R silence tenacity-reducible."""
    blitzcrank = create_default_registry(ROOT).require_cog("Blitzcrank")
    reaction = blitzcrank.build_reaction_plan(_context())
    hook, fist, silence = reaction.cast_block_windows

    assert hook.control_type.value == fist.control_type.value == "AIRBORNE"
    assert hook.tenacity_reducible is fist.tenacity_reducible is False
    assert hook.source_event_id == "BLITZCRANK_Q_ROCKET_GRAB_HIT"
    assert fist.source_event_id == "BLITZCRANK_E_POWER_FIST_ATTACK"
    assert silence.control_type.value == "SILENCE"
    assert silence.tenacity_reducible is True
    assert silence.blocked_channels == (ActionChannel.ABILITY,)
    assert "BLITZCRANK_R_SHIELD_DESTRUCTION_REACTION_NOT_MODELED" in reaction.blockers


def test_blitzcrank_role_reversal_and_teemo_blind_preserve_channels() -> None:
    """Keep roles symmetric while blind cancels attacks but not hook or R."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Blitzcrank", "Teemo"))
    as_opponent = engine.evaluate(MatchupRequest("Teemo", "Blitzcrank"))

    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    assert any(
        entry.event_id == "BLITZCRANK_E_POWER_FIST_ATTACK"
        and entry.action_channel is ActionChannel.BASIC_ATTACK
        and entry.status == "CANCELLED"
        for entry in as_actor.timeline.log
    )
    for event_id in (
        "BLITZCRANK_Q_ROCKET_GRAB_HIT",
        "BLITZCRANK_R_STATIC_FIELD_ACTIVE",
    ):
        assert any(
            entry.event_id == event_id and entry.operation == "DAMAGE" and entry.status == "APPLIED"
            for entry in as_actor.timeline.log
        )
    opponent_q = next(
        entry
        for entry in as_opponent.timeline.log
        if entry.event_id == "BLITZCRANK_Q_ROCKET_GRAB_HIT" and entry.operation == "DAMAGE"
    )
    assert opponent_q.recipient is EntityId.ACTOR


def test_blitzcrank_item_policy_blocks_unrepresented_resources() -> None:
    """Accept represented combat stats while rejecting fixed-policy omissions."""
    blitzcrank = create_default_registry(ROOT).require_cog("Blitzcrank")

    assert (
        blitzcrank.item_candidate_blocker(
            {
                "id": 1,
                "stats": {
                    "AD": {},
                    "AP": {},
                    "ATTACK_SPEED": {},
                    "HP": {},
                    "MOVE_SPEED_FLAT": {},
                },
            }
        )
        is None
    )
    assert (
        blitzcrank.item_candidate_blocker(
            {"id": 2, "stats": {"ABILITY_HASTE": {}, "MANA": {}, "LIFESTEAL": {}}}
        )
        == "BLITZCRANK_ITEM_STAT_NOT_MODELED:2:ABILITY_HASTE,MANA"
    )
