"""Focused regression tests for the locked Mordekaiser champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import (
    CogMaturity,
    ControlType,
    ParticipantContext,
    create_default_registry,
)
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    DamageOutput,
    EntityId,
    HealOutput,
    ShieldOutput,
)

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    mordekaiser_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
    opponent_item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a fixed level-13 Mordekaiser versus Garen context.

    :param mordekaiser_is_actor: Place Mordekaiser on the actor side when true.
    :param item_stats: Optional Mordekaiser item-stat modifiers.
    :param opponent_item_stats: Optional Garen item-stat modifiers.
    :return: Role-bound context suitable for direct Cog calls.
    """
    registry = create_default_registry(ROOT)
    mordekaiser = registry.require_cog("Mordekaiser")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if mordekaiser_is_actor else EntityId.TARGET,
        EntityId.TARGET if mordekaiser_is_actor else EntityId.ACTOR,
        mordekaiser.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13, item_stats=opponent_item_stats),
        8000,
        3000,
    )


def test_mordekaiser_declares_modeled_capabilities_and_three_sources() -> None:
    """Distinguish Mordekaiser's model from a generated champion scaffold."""
    mordekaiser = create_default_registry(ROOT).require_cog("Mordekaiser")

    assert mordekaiser.maturity is CogMaturity.MODELED_UNVERIFIED
    assert mordekaiser.capabilities == DUEL_CAPABILITIES
    assert mordekaiser.verification_blockers() == ("COG_MODEL_UNVERIFIED:Mordekaiser",)
    assert len(mordekaiser.evidence_refs) == 3
    assert all((ROOT / path).is_file() for path in mordekaiser.evidence_refs)


def test_mordekaiser_rotation_is_deterministic_and_activates_passive_at_three_hits() -> None:
    """Keep the E/Q/attack opener and subsequent aura schedule stable."""
    mordekaiser = create_default_registry(ROOT).require_cog("Mordekaiser")
    context = _context()

    first = mordekaiser.build_action_plan(context)
    second = mordekaiser.build_action_plan(context)
    attacks = tuple(event for event in first.events if event.channel is ActionChannel.BASIC_ATTACK)
    aura = tuple(event for event in first.events if event.id.startswith("MORDEKAISER_PASSIVE_AURA"))

    assert first == second
    assert first.model_id == "mordekaiser_p_q5_w1_e5_r2_level13_synthetic_v1"
    assert attacks[0].at_ms == 1500
    assert aura[0].at_ms == 2500
    assert all(event.channel is ActionChannel.PASSIVE for event in aura)
    assert "MORDEKAISER_PASSIVE_ACTIVATION_DEPENDENCY_NOT_EVALUATED" in first.blockers


def test_mordekaiser_q_e_passive_and_w_respond_to_ap_and_health() -> None:
    """Anchor offensive AP scaling and maximum-health sustain channels."""
    mordekaiser = create_default_registry(ROOT).require_cog("Mordekaiser")
    baseline_context = _context()
    scaled_context = _context(
        item_stats={"AP": Decimal(100), "HP": Decimal(500)},
        opponent_item_stats={"AP": Decimal(50), "AD": Decimal(100)},
    )
    baseline = mordekaiser.build_action_plan(baseline_context)
    scaled = mordekaiser.build_action_plan(scaled_context)

    baseline_q = next(event for event in baseline.events if event.id.endswith("OBLITERATE_1"))
    scaled_q = next(event for event in scaled.events if event.id.endswith("OBLITERATE_1"))
    baseline_e = next(event for event in baseline.events if event.id.endswith("DEATHS_GRASP"))
    scaled_e = next(event for event in scaled.events if event.id.endswith("DEATHS_GRASP"))
    shield_event = next(event for event in scaled.events if event.id.endswith("SHIELD"))
    heal_event = next(event for event in scaled.events if event.id.endswith("HEAL"))
    first_attack = next(
        event for event in scaled.events if event.id.startswith("MORDEKAISER_BASIC_ATTACK")
    )
    first_aura = next(
        event for event in scaled.events if event.id.startswith("MORDEKAISER_PASSIVE_AURA")
    )

    realm_ad = (
        scaled_context.snapshot.attack_damage
        + Decimal("0.10") * scaled_context.opponent_snapshot.attack_damage
    )
    realm_ap = (
        scaled_context.snapshot.ability_power
        + Decimal("0.10") * scaled_context.opponent_snapshot.ability_power
    )
    expected_q = Decimal("1.50") * (
        Decimal(220) + Decimal(20) + Decimal("1.20") * realm_ad + Decimal("0.70") * realm_ap
    )
    assert isinstance(scaled_q.outputs[0], DamageOutput)
    assert scaled_q.outputs[0].amount == expected_q
    assert scaled_q.outputs[0].amount > baseline_q.outputs[0].amount
    assert scaled_e.outputs[0].amount == Decimal(140) + Decimal("0.45") * realm_ap
    assert scaled_e.outputs[0].amount > baseline_e.outputs[0].amount
    assert isinstance(shield_event.outputs[0], ShieldOutput)
    assert shield_event.outputs[0].amount == (Decimal("0.05") * scaled_context.snapshot.max_hp)
    assert isinstance(heal_event.outputs[0], HealOutput)
    assert heal_event.outputs[0].amount == (Decimal("0.35") * shield_event.outputs[0].amount)
    assert first_attack.outputs[0].amount == realm_ad
    assert first_attack.outputs[1].amount == Decimal("0.40") * realm_ap
    assert first_aura.outputs[0].damage_type is DamageType.MAGIC


def test_mordekaiser_e_exposes_pull_and_nonreducible_reaction() -> None:
    """Represent Death's Grasp displacement without treating it as tenacity CC."""
    mordekaiser = create_default_registry(ROOT).require_cog("Mordekaiser")
    context = _context()
    plan = mordekaiser.build_action_plan(context)
    reaction = mordekaiser.build_reaction_plan(context)
    e = next(event for event in plan.events if event.id.endswith("DEATHS_GRASP"))

    assert e.outputs[1].status == "CC_AIRBORNE"
    assert mordekaiser.engagement_dash_distance(context) == Decimal(250)
    assert reaction.cast_block_windows[0].source_event_id == e.id
    assert reaction.cast_block_windows[0].tenacity_reducible is False
    assert reaction.cast_block_windows[0].control_type is ControlType.AIRBORNE


def test_mordekaiser_actions_and_sustain_follow_role_reversal() -> None:
    """Keep Mordekaiser's outgoing and self-directed effects role-neutral."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Mordekaiser", "Teemo"))
    as_opponent = engine.evaluate(MatchupRequest("Teemo", "Mordekaiser"))

    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    actor_q = next(
        entry
        for entry in as_actor.timeline.log
        if entry.event_id == "MORDEKAISER_Q_OBLITERATE_1" and entry.operation == "DAMAGE"
    )
    opponent_q = next(
        entry
        for entry in as_opponent.timeline.log
        if entry.event_id == "MORDEKAISER_Q_OBLITERATE_1" and entry.operation == "DAMAGE"
    )
    actor_shield = next(
        entry
        for entry in as_actor.timeline.log
        if entry.event_id == "MORDEKAISER_W_INDESTRUCTIBLE_SHIELD"
    )
    opponent_shield = next(
        entry
        for entry in as_opponent.timeline.log
        if entry.event_id == "MORDEKAISER_W_INDESTRUCTIBLE_SHIELD"
    )
    assert actor_q.recipient is EntityId.TARGET
    assert opponent_q.recipient is EntityId.ACTOR
    assert actor_shield.recipient is EntityId.ACTOR
    assert opponent_shield.recipient is EntityId.TARGET


def test_teemo_blind_cancels_mordekaiser_attacks_but_not_spells_or_aura() -> None:
    """Keep blind scoped to attacks while preserving ability and passive channels."""
    evaluation = MatchupEngine(ROOT).evaluate(MatchupRequest("Mordekaiser", "Teemo"))

    first_attack = next(
        entry
        for entry in evaluation.timeline.log
        if entry.event_id == "MORDEKAISER_BASIC_ATTACK_1" and entry.operation == "ACTION"
    )
    q = next(
        entry
        for entry in evaluation.timeline.log
        if entry.event_id == "MORDEKAISER_Q_OBLITERATE_1" and entry.operation == "DAMAGE"
    )
    aura = next(
        entry
        for entry in evaluation.timeline.log
        if entry.event_id == "MORDEKAISER_PASSIVE_AURA_TICK_1" and entry.operation == "DAMAGE"
    )

    assert first_attack.status == "CANCELLED"
    assert q.status == "APPLIED"
    assert aura.status == "APPLIED"
    assert "MORDEKAISER_PASSIVE_ACTIVATION_DEPENDENCY_NOT_EVALUATED" in evaluation.blockers


def test_mordekaiser_item_policy_and_lane_sustain_are_state_honest() -> None:
    """Accept represented chassis stats and reject dynamic sustain claims."""
    mordekaiser = create_default_registry(ROOT).require_cog("Mordekaiser")

    assert (
        mordekaiser.item_candidate_blocker(
            {"id": 1, "stats": {"AP": {}, "HP": {}, "ATTACK_SPEED": {}}}
        )
        is None
    )
    assert (
        mordekaiser.item_candidate_blocker(
            {"id": 2, "stats": {"ABILITY_HASTE": {}, "HEAL_SHIELD_POWER": {}}}
        )
        == "MORDEKAISER_ITEM_STAT_NOT_MODELED:2:ABILITY_HASTE"
    )
    amount, blockers = mordekaiser.lane_sustain_extra_health(
        _context(),
        duration_ms=30_000,
        no_damage_delay_ms=8_000,
    )
    assert amount == 0
    assert blockers == ("MORDEKAISER_LANE_W_DYNAMIC_SHIELD_RESOURCE_NOT_MODELED",)
