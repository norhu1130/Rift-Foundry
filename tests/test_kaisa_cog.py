"""Focused regression tests for the locked Kai'Sa champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import (
    ActionChannel,
    DamageOutput,
    EntityId,
    MissingHealthDamageOutput,
    ShieldOutput,
)

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    item_stats: dict[str, Decimal] | None = None,
    kaisa_is_actor: bool = True,
) -> ParticipantContext:
    """Build a level-13 Kai'Sa-versus-Garen direct-call context.

    :param item_stats: Optional permanent Kai'Sa item-stat modifiers.
    :param kaisa_is_actor: Put Kai'Sa on the actor side when true.
    :return: Role-bound context accepted by the Kai'Sa Cog.
    """
    registry = create_default_registry(ROOT)
    kaisa = registry.require_cog("Kaisa")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if kaisa_is_actor else EntityId.TARGET,
        EntityId.TARGET if kaisa_is_actor else EntityId.ACTOR,
        kaisa.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def test_kaisa_declares_modeled_capabilities_and_locked_evidence() -> None:
    """Distinguish Kai'Sa from a scaffold and retain all source forms."""
    kaisa = create_default_registry(ROOT).require_cog("Kaisa")

    assert kaisa.maturity is CogMaturity.MODELED_UNVERIFIED
    assert kaisa.capabilities == DUEL_CAPABILITIES
    assert kaisa.verification_blockers() == ("COG_MODEL_UNVERIFIED:Kaisa",)
    assert kaisa.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Kaisa.json",
        "data/raw/16.17.1/communitydragon/champions/145.json",
        "data/raw/16.17.1/communitydragon/champions/kaisa.bin.json",
    )
    assert all((ROOT / reference).is_file() for reference in kaisa.evidence_refs)


def test_kaisa_plan_anchors_spells_plasma_and_is_deterministic() -> None:
    """Anchor Q5/W1/R2 formulas and the first five-stack detonation."""
    kaisa = create_default_registry(ROOT).require_cog("Kaisa")
    context = _context(item_stats={"AD": Decimal(40), "AP": Decimal(100)})

    first = kaisa.build_action_plan(context)
    second = kaisa.build_action_plan(context)
    w = next(event for event in first.events if event.id == "KAISA_W_VOID_SEEKER")
    r = next(event for event in first.events if event.id == "KAISA_R_KILLER_INSTINCT")
    q = next(event for event in first.events if event.id == "KAISA_Q_ICATHIAN_RAIN_ISOLATED")
    detonation = next(
        event
        for event in first.events
        if event.id.startswith("KAISA_PASSIVE_PLASMA_DETONATION_ATTACK_")
    )

    assert first == second
    assert first.model_id == "kaisa_q5_w1_e5_r2_level13_isolated_v1"
    assert w.outputs[0] == DamageOutput(
        context.opponent_entity,
        Decimal(30) + Decimal("1.30") * context.snapshot.attack_damage + Decimal(45),
        w.outputs[0].damage_type,
    )
    assert isinstance(r.outputs[0], ShieldOutput)
    assert r.outputs[0].amount == (
        Decimal(150) + Decimal("1.35") * context.snapshot.attack_damage + Decimal(120)
    )
    assert q.outputs[0].amount == (
        Decimal(100) + Decimal("0.55") * Decimal(40) + Decimal(20)
    ) * Decimal("2.25")
    assert isinstance(detonation.outputs[-1], MissingHealthDamageOutput)
    assert detonation.outputs[-1].missing_health_ratio == Decimal("0.21")
    assert "KAISA_EVOLUTION_THRESHOLDS_NOT_EVALUATED" in first.blockers
    assert "KAISA_Q_MULTI_TARGET_SPLIT_NOT_MODELED" in first.blockers


def test_kaisa_ad_ap_and_attack_speed_affect_represented_outputs() -> None:
    """Prove AD, AP, and attack speed alter their modeled Kai'Sa channels."""
    kaisa = create_default_registry(ROOT).require_cog("Kaisa")
    baseline = kaisa.build_action_plan(_context())
    more_ad = kaisa.build_action_plan(_context(item_stats={"AD": Decimal(50)}))
    more_ap = kaisa.build_action_plan(_context(item_stats={"AP": Decimal(100)}))
    more_speed = kaisa.build_action_plan(_context(item_stats={"ATTACK_SPEED": Decimal("0.50")}))

    def event(plan: object, event_id: str) -> object:
        """Find one named action in a plan used by this sensitivity test.

        :param plan: Action plan whose events are searched.
        :param event_id: Exact event identifier to locate.
        :return: Matching immutable action event.
        """
        return next(candidate for candidate in plan.events if candidate.id == event_id)

    assert (
        event(more_ad, "KAISA_Q_ICATHIAN_RAIN_ISOLATED").outputs[0].amount
        > event(baseline, "KAISA_Q_ICATHIAN_RAIN_ISOLATED").outputs[0].amount
    )
    assert (
        event(more_ap, "KAISA_W_VOID_SEEKER").outputs[0].amount
        > event(baseline, "KAISA_W_VOID_SEEKER").outputs[0].amount
    )
    baseline_attacks = [
        item for item in baseline.events if item.channel is ActionChannel.BASIC_ATTACK
    ]
    faster_attacks = [
        item for item in more_speed.events if item.channel is ActionChannel.BASIC_ATTACK
    ]
    assert faster_attacks[0].at_ms < baseline_attacks[0].at_ms
    assert len(faster_attacks) > len(baseline_attacks)


def test_kaisa_role_reversal_and_teemo_blind_are_channel_correct() -> None:
    """Keep Kai'Sa symmetric and let blind cancel attacks but not spells."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Kaisa", "Teemo"))
    as_opponent = engine.evaluate(MatchupRequest("Teemo", "Kaisa"))

    actor_q = next(
        entry
        for entry in as_actor.timeline.log
        if entry.event_id == "KAISA_Q_ICATHIAN_RAIN_ISOLATED" and entry.operation == "DAMAGE"
    )
    opponent_q = next(
        entry
        for entry in as_opponent.timeline.log
        if entry.event_id == "KAISA_Q_ICATHIAN_RAIN_ISOLATED" and entry.operation == "DAMAGE"
    )
    assert actor_q.recipient is EntityId.TARGET
    assert opponent_q.recipient is EntityId.ACTOR
    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    assert any(
        entry.event_id.startswith("KAISA_BASIC_ATTACK_")
        and entry.status == "CANCELLED"
        and entry.action_channel is ActionChannel.BASIC_ATTACK
        for entry in as_opponent.timeline.log
    )
    assert opponent_q.status == "APPLIED"


def test_kaisa_engagement_reaction_and_item_policy_preserve_boundaries() -> None:
    """Expose E/R mobility while rejecting unsupported item-stat channels."""
    kaisa = create_default_registry(ROOT).require_cog("Kaisa")
    context = _context()
    reaction = kaisa.build_reaction_plan(context)

    assert kaisa.engagement_speed_multiplier(context) > Decimal(1)
    assert kaisa.engagement_dash_distance(context) == Decimal(2500)
    assert reaction.model_id == "kaisa_r2_shield_e5_base_reaction_v1"
    assert reaction.events == ()
    assert (
        kaisa.item_candidate_blocker(
            {
                "id": 1,
                "stats": {
                    "AD": {},
                    "AP": {},
                    "ATTACK_SPEED": {},
                    "CRITICAL_STRIKE_CHANCE": {},
                },
            }
        )
        is None
    )
    assert (
        kaisa.item_candidate_blocker({"id": 2, "stats": {"ABILITY_HASTE": {}, "LIFESTEAL": {}}})
        == "KAISA_ITEM_STAT_NOT_MODELED:2:ABILITY_HASTE"
    )
