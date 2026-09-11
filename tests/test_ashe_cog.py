"""Focused regression tests for the locked Ashe champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import ActionChannel, DamageOutput, EntityId, StatusOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(*, item_stats=None, ashe_is_actor: bool = True) -> ParticipantContext:
    """Build a level-13 Ashe versus Garen direct-call context.

    :param item_stats: Optional permanent Ashe item-stat modifiers.
    :param ashe_is_actor: Put Ashe on the actor side when true.
    :return: Role-bound context accepted by the Ashe Cog.
    """
    registry = create_default_registry(ROOT)
    ashe = registry.require_cog("Ashe")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if ashe_is_actor else EntityId.TARGET,
        EntityId.TARGET if ashe_is_actor else EntityId.ACTOR,
        ashe.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def test_ashe_declares_modeled_capabilities_and_three_locked_sources() -> None:
    """Distinguish Ashe's model from a scaffold and retain all evidence types."""
    ashe = create_default_registry(ROOT).require_cog("Ashe")

    assert ashe.maturity is CogMaturity.MODELED_UNVERIFIED
    assert ashe.capabilities == DUEL_CAPABILITIES
    assert ashe.verification_blockers() == ("COG_MODEL_UNVERIFIED:Ashe",)
    assert ashe.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Ashe.json",
        "data/raw/16.17.1/communitydragon/champions/22.json",
        "data/raw/16.17.1/communitydragon/champions/ashe.bin.json",
    )
    assert all((ROOT / ref).is_file() for ref in ashe.evidence_refs)


def test_ashe_plan_is_deterministic_and_uses_locked_rank_values() -> None:
    """Anchor W5, Q4, Frost Shot, and R2 values to locked source data."""
    ashe = create_default_registry(ROOT).require_cog("Ashe")
    context = _context(item_stats={"AP": Decimal(100), "AD": Decimal(40)})

    first = ashe.build_action_plan(context)
    second = ashe.build_action_plan(context)
    volley = next(event for event in first.events if event.id == "ASHE_W_VOLLEY_1")
    frost = next(event for event in first.events if event.id == "ASHE_FROST_ATTACK_1")
    flurry = next(event for event in first.events if event.id == "ASHE_Q_FLURRY_ATTACK_1")
    arrow = next(event for event in first.events if event.id == "ASHE_R_ENCHANTED_CRYSTAL_ARROW")

    assert first == second
    assert first.model_id == "ashe_w5_q4_e1_r2_level13_locked_v1"
    assert ashe.engagement_speed_multiplier(context) == Decimal(1)
    assert context.snapshot.attack_range == Decimal(600)
    assert isinstance(volley.outputs[0], DamageOutput)
    assert volley.outputs[0].amount == Decimal(200) + context.snapshot.attack_damage
    assert isinstance(frost.outputs[1], StatusOutput)
    assert frost.outputs[1].status == "CC_SLOW"
    assert frost.outputs[1].duration_ms == 2000
    assert frost.outputs[1].magnitude == (
        Decimal("0.20") + Decimal("0.10") * Decimal(12) / Decimal(17)
    )
    assert flurry.outputs[0].amount == Decimal("1.25") * context.snapshot.attack_damage
    assert arrow.outputs[0].amount == Decimal(520)
    assert arrow.outputs[1].duration_ms == 1000
    assert "ASHE_Q_FOCUS_STACK_RESOLUTION_NOT_CAUSALLY_MODELED" in first.blockers
    assert "ASHE_R_DISTANCE_BASED_STUN_NOT_MODELED_MINIMUM_USED" in first.blockers


def test_ashe_attack_damage_and_attack_speed_change_the_modeled_rotation() -> None:
    """Prove offensive item stats affect damage and attack event count."""
    ashe = create_default_registry(ROOT).require_cog("Ashe")
    baseline = ashe.build_action_plan(_context())
    more_ad = ashe.build_action_plan(_context(item_stats={"AD": Decimal(50)}))
    more_speed = ashe.build_action_plan(_context(item_stats={"ATTACK_SPEED": Decimal("0.50")}))

    baseline_w = next(event for event in baseline.events if event.id == "ASHE_W_VOLLEY_1")
    more_ad_w = next(event for event in more_ad.events if event.id == "ASHE_W_VOLLEY_1")
    baseline_attacks = tuple(
        event for event in baseline.events if event.channel is ActionChannel.BASIC_ATTACK
    )
    faster_attacks = tuple(
        event for event in more_speed.events if event.channel is ActionChannel.BASIC_ATTACK
    )

    assert more_ad_w.outputs[0].amount - baseline_w.outputs[0].amount == Decimal(50)
    assert len(faster_attacks) > len(baseline_attacks)


def test_ashe_r_reaction_is_reducible_and_follows_role_reversal() -> None:
    """Keep Ashe's stun attached to her regardless of request position."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Ashe", "Garen"))
    as_opponent = engine.evaluate(MatchupRequest("Garen", "Ashe"))
    reaction = create_default_registry(ROOT).require_cog("Ashe").build_reaction_plan(_context())

    stun = reaction.cast_block_windows[0]
    assert stun.tenacity_reducible is True
    assert stun.control_type.value == "STUN"
    assert stun.source_event_id == "ASHE_R_ENCHANTED_CRYSTAL_ARROW"
    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    actor_arrow = next(
        entry
        for entry in as_actor.timeline.log
        if entry.event_id == "ASHE_R_ENCHANTED_CRYSTAL_ARROW" and entry.operation == "DAMAGE"
    )
    opponent_arrow = next(
        entry
        for entry in as_opponent.timeline.log
        if entry.event_id == "ASHE_R_ENCHANTED_CRYSTAL_ARROW" and entry.operation == "DAMAGE"
    )
    assert actor_arrow.recipient is EntityId.TARGET
    assert opponent_arrow.recipient is EntityId.ACTOR


def test_teemo_blind_cancels_ashe_attacks_but_not_her_abilities() -> None:
    """Apply blind through the shared basic-attack channel without blocking spells."""
    result = MatchupEngine(ROOT).evaluate(MatchupRequest("Teemo", "Ashe"))

    assert any(
        entry.event_id.startswith("ASHE_FROST_ATTACK_")
        and entry.action_channel is ActionChannel.BASIC_ATTACK
        and entry.status == "CANCELLED"
        for entry in result.timeline.log
    )
    assert (
        next(
            entry
            for entry in result.timeline.log
            if entry.event_id == "ASHE_W_VOLLEY_1" and entry.operation == "DAMAGE"
        ).status
        == "APPLIED"
    )


def test_ashe_item_policy_blocks_only_unrepresented_stat_channels() -> None:
    """Keep candidate eligibility aligned with actually consumed item stats."""
    ashe = create_default_registry(ROOT).require_cog("Ashe")

    assert (
        ashe.item_candidate_blocker({"id": 1, "stats": {"AD": {}, "AP": {}, "ATTACK_SPEED": {}}})
        is None
    )
    assert (
        ashe.item_candidate_blocker(
            {"id": 2, "stats": {"ABILITY_HASTE": {}, "CRITICAL_STRIKE_CHANCE": {}}}
        )
        == "ASHE_ITEM_STAT_NOT_MODELED:2:ABILITY_HASTE,CRITICAL_STRIKE_CHANCE"
    )
