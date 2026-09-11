"""Focused regressions for the locked Bard champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import (
    ActionChannel,
    EntityId,
    HealOutput,
    StatModifierOutput,
    StatusOutput,
)

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    bard_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a level-13 Bard-versus-Teemo direct-Cog context.

    :param bard_is_actor: Place Bard on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Bard.
    :return: Role-bound deterministic benchmark context.
    """
    registry = create_default_registry(ROOT)
    bard = registry.require_cog("Bard")
    teemo = registry.require_cog("Teemo")
    return ParticipantContext(
        EntityId.ACTOR if bard_is_actor else EntityId.TARGET,
        EntityId.TARGET if bard_is_actor else EntityId.ACTOR,
        bard.snapshot(level=13, item_stats=item_stats),
        teemo.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Resolve one event by its stable Bard identifier.

    :param plan: Action plan exposing an ``events`` tuple.
    :param event_id: Exact event identifier to locate.
    :return: Matching immutable action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def _events_with_prefix(plan: object, prefix: str) -> list[object]:
    """Collect chronologically ordered events sharing a Bard identifier prefix.

    :param plan: Action plan exposing an ``events`` tuple.
    :param prefix: Champion-scoped event prefix to match.
    :return: Matching events in the plan's deterministic order.
    """
    return [event for event in plan.events if event.id.startswith(prefix)]


def test_bard_declares_modeled_capabilities_and_locked_evidence() -> None:
    """Distinguish Bard from a scaffold and retain all three source forms."""
    bard = create_default_registry(ROOT).require_cog("Bard")

    assert bard.maturity is CogMaturity.MODELED_UNVERIFIED
    assert bard.capabilities == DUEL_CAPABILITIES
    assert bard.verification_blockers() == ("COG_MODEL_UNVERIFIED:Bard",)
    assert bard.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Bard.json",
        "data/raw/16.17.1/communitydragon/champions/432.json",
        "data/raw/16.17.1/communitydragon/champions/bard.bin.json",
    )
    assert all((ROOT / reference).is_file() for reference in bard.evidence_refs)


def test_bard_rotation_is_deterministic_and_anchors_locked_formulas() -> None:
    """Anchor Q5, charged W5, R2, and the fifteen-chime meep fixture."""
    bard = create_default_registry(ROOT).require_cog("Bard")
    context = _context(item_stats={"AP": Decimal(100)})

    first = bard.build_action_plan(context)
    repeated = bard.build_action_plan(context)
    q = _event(first, "BARD_Q_COSMIC_BINDING_STUN_1")
    meep = _event(first, "BARD_MEEP_ATTACK_1")
    shrine = _event(first, "BARD_W_PRECHARGED_SHRINE_SELF_CONSUME")
    ultimate = _event(first, "BARD_R_TEMPERED_FATE_TARGET_FIXTURE")

    assert first == repeated
    assert first.model_id == "bard_q5_w5_e1_r2_chime15_meep1_level13_v1"
    assert q.outputs[0].amount == 320
    assert isinstance(q.outputs[1], StatusOutput)
    assert (q.outputs[1].status, q.outputs[1].duration_ms) == ("CC_STUN", 1800)
    assert meep.outputs[1].amount == 88
    assert isinstance(shrine.outputs[0], HealOutput)
    assert shrine.outputs[0].amount == 270
    assert isinstance(shrine.outputs[1], StatModifierOutput)
    assert shrine.outputs[1].amount == context.snapshot.move_speed * Decimal("0.36")
    assert isinstance(ultimate.outputs[0], StatusOutput)
    assert (ultimate.outputs[0].status, ultimate.outputs[0].duration_ms) == (
        "CC_STASIS",
        2500,
    )
    assert "BARD_CHIME_COUNT_FIXED_AT_15_AND_MEEP_COUNT_FIXED_AT_1" in first.blockers
    assert "BARD_E_TERRAIN_PORTAL_GEOMETRY_AND_TRAVEL_NOT_MODELED" in first.blockers


def test_bard_ap_attack_speed_and_haste_reach_distinct_channels() -> None:
    """Prove AP scales outputs, speed adds attacks, and haste adds Q casts."""
    bard = create_default_registry(ROOT).require_cog("Bard")
    baseline = bard.build_action_plan(_context())
    powered = bard.build_action_plan(_context(item_stats={"AP": Decimal(100)}))
    faster = bard.build_action_plan(_context(item_stats={"ATTACK_SPEED": Decimal("0.50")}))
    hasted = bard.build_action_plan(_context(item_stats={"ABILITY_HASTE": Decimal(100)}))

    assert (
        _event(powered, "BARD_Q_COSMIC_BINDING_STUN_1").outputs[0].amount
        - _event(baseline, "BARD_Q_COSMIC_BINDING_STUN_1").outputs[0].amount
        == 80
    )
    assert (
        _event(powered, "BARD_MEEP_ATTACK_1").outputs[1].amount
        - _event(baseline, "BARD_MEEP_ATTACK_1").outputs[1].amount
        == 40
    )
    assert (
        _event(powered, "BARD_W_PRECHARGED_SHRINE_SELF_CONSUME").outputs[0].amount
        - _event(baseline, "BARD_W_PRECHARGED_SHRINE_SELF_CONSUME").outputs[0].amount
        == 70
    )
    baseline_attacks = [
        event for event in baseline.events if event.channel is ActionChannel.BASIC_ATTACK
    ]
    faster_attacks = [
        event for event in faster.events if event.channel is ActionChannel.BASIC_ATTACK
    ]
    assert len(faster_attacks) > len(baseline_attacks)
    assert len(_events_with_prefix(hasted, "BARD_Q_COSMIC_BINDING_")) > len(
        _events_with_prefix(baseline, "BARD_Q_COSMIC_BINDING_")
    )


def test_bard_reaction_separates_q_branches_and_target_stasis() -> None:
    """Keep Q stun/slow and target-only R stasis semantically distinct."""
    bard = create_default_registry(ROOT).require_cog("Bard")
    reaction = bard.build_reaction_plan(_context(item_stats={"ABILITY_HASTE": Decimal(100)}))
    by_id = {window.id: window for window in reaction.cast_block_windows}

    stun = by_id["bard_q_stun_1"]
    slow = by_id["bard_q_slow_2"]
    stasis = by_id["bard_r_target_stasis_action_block"]
    assert stun.control_type.value == "STUN"
    assert stun.tenacity_reducible is True
    assert ActionChannel.ABILITY in stun.blocked_channels
    assert slow.control_type.value == "SLOW"
    assert slow.blocked_channels == (ActionChannel.MOVEMENT,)
    assert stasis.control_type.value == "ALL"
    assert stasis.tenacity_reducible is False
    assert ActionChannel.ITEM_ACTIVE in stasis.blocked_channels
    assert ActionChannel.PASSIVE not in stasis.blocked_channels
    assert reaction.damage_windows[0].recipient is EntityId.TARGET
    assert reaction.damage_windows[0].multiplier == 0
    assert reaction.damage_windows[0].end_ms == 5500
    assert "BARD_R_DAMAGE_IMMUNITY_CAUSAL_LINK_NOT_MODELED" in reaction.blockers


def test_bard_role_reversal_preserves_models_and_self_heal_recipient() -> None:
    """Keep Bard mechanics attached to Bard in either participant position."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Bard", "Garen"))
    as_opponent = engine.evaluate(MatchupRequest("Garen", "Bard"))

    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    actor_heal = next(
        entry
        for entry in as_actor.timeline.log
        if entry.event_id == "BARD_W_PRECHARGED_SHRINE_SELF_CONSUME" and entry.operation == "HEAL"
    )
    target_heal = next(
        entry
        for entry in as_opponent.timeline.log
        if entry.event_id == "BARD_W_PRECHARGED_SHRINE_SELF_CONSUME" and entry.operation == "HEAL"
    )
    assert actor_heal.recipient is EntityId.ACTOR
    assert target_heal.recipient is EntityId.TARGET


def test_teemo_blind_cancels_bard_meep_attack_but_not_abilities() -> None:
    """Keep a meep on the attack channel while Bard spells ignore blind."""
    result = MatchupEngine(ROOT).evaluate(MatchupRequest("Teemo", "Bard"))

    assert any(
        entry.event_id == "BARD_MEEP_ATTACK_1" and entry.status == "CANCELLED"
        for entry in result.timeline.log
    )
    assert any(
        entry.event_id == "BARD_W_PRECHARGED_SHRINE_SELF_CONSUME"
        and entry.operation == "HEAL"
        and entry.status == "APPLIED"
        for entry in result.timeline.log
    )


def test_bard_engagement_item_and_lane_policies_preserve_boundaries() -> None:
    """Expose shrine speed while rejecting portal and unsupported item claims."""
    bard = create_default_registry(ROOT).require_cog("Bard")
    context = _context(item_stats={"AP": Decimal(100)})

    assert bard.engagement_speed_multiplier(context) == Decimal("1.36")
    assert bard.engagement_dash_distance(context) == 0
    assert (
        bard.item_candidate_blocker(
            {
                "id": 1,
                "stats": {
                    "AP": {},
                    "AD": {},
                    "ATTACK_SPEED": {},
                    "ABILITY_HASTE": {},
                    "HP": {},
                },
            }
        )
        is None
    )
    assert (
        bard.item_candidate_blocker({"id": 2, "stats": {"HEAL_SHIELD_POWER": {}, "MANA": {}}})
        == "BARD_ITEM_STAT_NOT_MODELED:2:MANA"
    )
    amount, blockers = bard.lane_sustain_extra_health(
        context,
        duration_ms=30_000,
        no_damage_delay_ms=8_000,
    )
    assert amount == 0
    assert blockers == (
        "BARD_LANE_W_PLACEMENT_AND_CONSUMPTION_SCHEDULE_NOT_MODELED",
        "BARD_LANE_W_CHARGE_STATE_NOT_MODELED",
        "BARD_LANE_CHIME_AND_MANA_TIMELINE_NOT_MODELED",
    )
