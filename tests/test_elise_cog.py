"""Focused regressions for the locked Elise champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES, ActionPlan
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import (
    ActionChannel,
    CurrentHealthDamageOutput,
    EntityId,
    HealOutput,
    MissingHealthDamageOutput,
)

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    elise_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
    opponent_item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a role-neutral level-13 Elise-versus-Garen context.

    :param elise_is_actor: Place Elise on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Elise.
    :param opponent_item_stats: Optional permanent item modifiers applied to Garen.
    :return: Role-bound deterministic benchmark context.
    """
    registry = create_default_registry(ROOT)
    elise = registry.require_cog("Elise")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if elise_is_actor else EntityId.TARGET,
        EntityId.TARGET if elise_is_actor else EntityId.ACTOR,
        elise.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13, item_stats=opponent_item_stats),
        8000,
        3000,
    )


def _event(plan: ActionPlan, event_id: str):
    """Resolve one event by its stable Elise identifier.

    :param plan: Elise action plan containing the expected event.
    :param event_id: Exact identifier of the requested action.
    :return: Matching immutable action event.
    """
    return next(candidate for candidate in plan.events if candidate.id == event_id)


def _attacks(plan: ActionPlan) -> list:
    """Collect Spider Form basic attacks from an action plan.

    :param plan: Elise action plan containing zero or more attacks.
    :return: Spider Form attacks in deterministic order.
    """
    return [event for event in plan.events if event.id.startswith("ELISE_SPIDER_ATTACK_")]


def test_elise_declares_modeled_capabilities_and_locked_sources() -> None:
    """Distinguish Elise's implemented Cog from a generated scaffold."""
    elise = create_default_registry(ROOT).require_cog("Elise")

    assert elise.maturity is CogMaturity.MODELED_UNVERIFIED
    assert elise.capabilities == DUEL_CAPABILITIES
    assert elise.verification_blockers() == ("COG_MODEL_UNVERIFIED:Elise",)
    assert elise.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Elise.json",
        "data/raw/16.17.1/communitydragon/champions/60.json",
        "data/raw/16.17.1/communitydragon/champions/elise.bin.json",
    )
    assert all((ROOT / reference).is_file() for reference in elise.evidence_refs)


def test_elise_rotation_is_deterministic_and_crosses_both_forms() -> None:
    """Anchor the Human-to-Spider sequence and its honest model boundaries."""
    elise = create_default_registry(ROOT).require_cog("Elise")
    context = _context()

    first = elise.build_action_plan(context)
    repeated = elise.build_action_plan(context)

    assert first == repeated
    assert first.model_id == "elise_q5_w5_e3_r3_human_to_spider_level13_locked_v1"
    assert _event(first, "ELISE_HUMAN_E_COCOON").at_ms == 100
    assert _event(first, "ELISE_R_TRANSFORM_SPIDER").at_ms == 1200
    assert _event(first, "ELISE_SPIDER_E_RAPPEL_ASCEND").at_ms == 1400
    assert _event(first, "ELISE_SPIDER_E_RAPPEL_DESCEND").at_ms == 1900
    assert "ELISE_SPIDERLING_AI_AND_ATTACKS_NOT_MODELED" in first.blockers
    assert "ELISE_RAPPEL_TARGET_GEOMETRY_NOT_MODELED" in first.blockers


def test_elise_q_uses_runtime_current_and_missing_health_outputs() -> None:
    """Preserve the two opposing Q health-ratio semantics in typed outputs."""
    elise = create_default_registry(ROOT).require_cog("Elise")
    plan = elise.build_action_plan(_context(item_stats={"AP": Decimal(100)}))
    human_q = _event(plan, "ELISE_HUMAN_Q_NEUROTOXIN")
    spider_q = _event(plan, "ELISE_SPIDER_Q_VENOMOUS_BITE_1")

    current = human_q.outputs[0]
    missing = spider_q.outputs[0]
    assert isinstance(current, CurrentHealthDamageOutput)
    assert current.ratio == Decimal("0.07")
    assert isinstance(missing, MissingHealthDamageOutput)
    assert missing.base_amount == 170
    assert missing.missing_health_ratio == Decimal("0.11")
    assert "ELISE_Q_RUNTIME_CURRENT_HEALTH_CLIENT_VALIDATION_PENDING" in plan.blockers


def test_elise_ap_attack_speed_and_haste_reach_distinct_outputs() -> None:
    """Prove AP, attack speed, and haste affect represented model channels."""
    elise = create_default_registry(ROOT).require_cog("Elise")
    baseline = elise.build_action_plan(_context())
    powered = elise.build_action_plan(_context(item_stats={"AP": Decimal(100)}))
    faster = elise.build_action_plan(
        _context(item_stats={"ATTACK_SPEED": Decimal("0.50")})
    )
    hasted = elise.build_action_plan(
        _context(item_stats={"ABILITY_HASTE": Decimal(100)})
    )

    assert (
        _event(powered, "ELISE_HUMAN_W_VOLATILE_SPIDERLING").outputs[0].amount
        - _event(baseline, "ELISE_HUMAN_W_VOLATILE_SPIDERLING").outputs[0].amount
        == 75
    )
    powered_attack = _attacks(powered)[0]
    baseline_attack = _attacks(baseline)[0]
    assert powered_attack.outputs[1].amount - baseline_attack.outputs[1].amount == Decimal("25.5")
    assert isinstance(powered_attack.outputs[2], HealOutput)
    assert powered_attack.outputs[2].amount - baseline_attack.outputs[2].amount == Decimal("13.6")
    assert len(_attacks(faster)) > len(_attacks(baseline))
    assert len(
        [event for event in hasted.events if event.id.startswith("ELISE_SPIDER_Q_")]
    ) > len(
        [event for event in baseline.events if event.id.startswith("ELISE_SPIDER_Q_")]
    )


def test_elise_cocoon_and_rappel_reactions_are_typed() -> None:
    """Represent reducible Cocoon control separately from Rappel immunity."""
    elise = create_default_registry(ROOT).require_cog("Elise")
    context = _context()
    reaction = elise.build_reaction_plan(context)
    cocoon = reaction.cast_block_windows[0]
    immunity = reaction.control_immunity_windows[0]
    avoidance = reaction.damage_windows[0]

    assert cocoon.control_type.value == "STUN"
    assert cocoon.tenacity_reducible is True
    assert cocoon.blocked_channels == (
        ActionChannel.BASIC_ATTACK,
        ActionChannel.ABILITY,
        ActionChannel.MOVEMENT,
    )
    assert immunity.control_types[0].value == "ALL"
    assert immunity.recipient is EntityId.ACTOR
    assert avoidance.recipient is EntityId.ACTOR
    assert avoidance.multiplier == 0
    assert elise.engagement_dash_distance(context) == 825


def test_elise_role_reversal_and_teemo_interaction_preserve_ownership() -> None:
    """Keep Elise role-neutral and expose the Cocoon-versus-Blind interaction."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Elise", "Teemo"))
    as_opponent = engine.evaluate(MatchupRequest("Teemo", "Elise"))

    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    human_q = next(
        entry
        for entry in as_actor.timeline.log
        if entry.event_id == "ELISE_HUMAN_Q_NEUROTOXIN"
        and entry.operation == "DAMAGE"
    )
    mirrored_q = next(
        entry
        for entry in as_opponent.timeline.log
        if entry.event_id == "ELISE_HUMAN_Q_NEUROTOXIN"
        and entry.operation == "DAMAGE"
    )
    assert human_q.recipient is EntityId.TARGET
    assert mirrored_q.recipient is EntityId.ACTOR
    assert any(
        entry.event_id == "TEEMO_Q_BLINDING_DART" and entry.status == "CANCELLED"
        for entry in as_actor.timeline.log
    )


def test_elise_item_policy_accepts_rotation_stats_and_rejects_gaps() -> None:
    """Allow represented stats while rejecting resource and generic sustain gaps."""
    elise = create_default_registry(ROOT).require_cog("Elise")

    assert elise.item_candidate_blocker(
        {
            "id": 1,
            "stats": {
                "AP": {},
                "AD": {},
                "HP": {},
                "ATTACK_SPEED": {},
                "ABILITY_HASTE": {},
            },
        }
    ) is None
    assert elise.item_candidate_blocker(
        {"id": 2, "stats": {"HEAL_SHIELD_POWER": {}, "MANA": {}}}
    ) == "ELISE_ITEM_STAT_NOT_MODELED:2:HEAL_SHIELD_POWER,MANA"
