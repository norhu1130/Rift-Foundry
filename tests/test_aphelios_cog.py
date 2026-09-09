"""Focused regression tests for the locked Aphelios champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import ActionChannel, DamageOutput, EntityId, StatusOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    item_stats: dict[str, Decimal] | None = None,
    aphelios_is_actor: bool = True,
) -> ParticipantContext:
    """Build a level-13 Aphelios-versus-Garen direct-call context.

    :param item_stats: Optional permanent Aphelios item-stat modifiers.
    :param aphelios_is_actor: Put Aphelios on the actor side when true.
    :return: Role-bound context accepted by the Aphelios Cog.
    """
    registry = create_default_registry(ROOT)
    aphelios = registry.require_cog("Aphelios")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if aphelios_is_actor else EntityId.TARGET,
        EntityId.TARGET if aphelios_is_actor else EntityId.ACTOR,
        aphelios.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Find one event by its stable identifier.

    :param plan: Aphelios action plan under inspection.
    :param event_id: Exact event identifier to locate.
    :return: Matching action event.
    """
    return next(candidate for candidate in plan.events if candidate.id == event_id)


def test_aphelios_declares_modeled_capabilities_and_locked_evidence() -> None:
    """Distinguish Aphelios from a scaffold and retain all source forms."""
    aphelios = create_default_registry(ROOT).require_cog("Aphelios")

    assert aphelios.maturity is CogMaturity.MODELED_UNVERIFIED
    assert aphelios.capabilities == DUEL_CAPABILITIES
    assert aphelios.verification_blockers() == ("COG_MODEL_UNVERIFIED:Aphelios",)
    assert aphelios.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Aphelios.json",
        "data/raw/16.17.1/communitydragon/champions/523.json",
        "data/raw/16.17.1/communitydragon/champions/aphelios.bin.json",
    )
    assert all((ROOT / reference).is_file() for reference in aphelios.evidence_refs)


def test_aphelios_plan_is_deterministic_and_anchors_gravitum_formulas() -> None:
    """Anchor passive allocation, Gravitum Q, R2, and critical formulas."""
    aphelios = create_default_registry(ROOT).require_cog("Aphelios")
    context = _context(
        item_stats={
            "AD": Decimal(40),
            "AP": Decimal(100),
            "CRITICAL_STRIKE_CHANCE": Decimal("0.25"),
        }
    )

    first = aphelios.build_action_plan(context)
    second = aphelios.build_action_plan(context)
    ultimate = _event(first, "APHELIOS_R_MOONLIGHT_VIGIL")
    followup = _event(first, "APHELIOS_R_GRAVITUM_FOLLOWUP_ATTACK")
    eclipse = _event(first, "APHELIOS_Q_BINDING_ECLIPSE")

    assert first == second
    assert first.model_id == "aphelios_gravitum_calibrum_l13_locked_v1"
    assert isinstance(ultimate.outputs[0], DamageOutput)
    expected_bonus_ad = context.snapshot.bonus_attack_damage + Decimal(24)
    assert ultimate.outputs[0].amount == (
        Decimal(175) + Decimal("0.20") * expected_bonus_ad + Decimal(100)
    ) * Decimal("1.075")
    assert followup.outputs[0].amount == (
        context.snapshot.attack_damage + Decimal(24)
    ) * Decimal("1.25")
    assert isinstance(followup.outputs[1], StatusOutput)
    assert followup.outputs[1].magnitude == Decimal("0.99")
    assert eclipse.outputs[0].amount == (
        Decimal(140) + Decimal("0.50") * expected_bonus_ad + Decimal(70)
    )
    assert eclipse.outputs[1].duration_ms == 1000
    assert "APHELIOS_WEAPON_AMMUNITION_AND_QUEUE_NOT_MODELED" in first.blockers
    assert "APHELIOS_SEVERUM_NATIVE_SUSTAIN_OUTSIDE_FIXED_FIXTURE" in first.blockers


def test_aphelios_ad_ap_attack_speed_and_crit_change_represented_outputs() -> None:
    """Prove four principal offensive item stats affect the fixed fixture."""
    aphelios = create_default_registry(ROOT).require_cog("Aphelios")
    baseline = aphelios.build_action_plan(_context())
    more_ad = aphelios.build_action_plan(_context(item_stats={"AD": Decimal(50)}))
    more_ap = aphelios.build_action_plan(_context(item_stats={"AP": Decimal(100)}))
    more_speed = aphelios.build_action_plan(
        _context(item_stats={"ATTACK_SPEED": Decimal("0.50")})
    )
    more_crit = aphelios.build_action_plan(
        _context(item_stats={"CRITICAL_STRIKE_CHANCE": Decimal("0.25")})
    )

    assert _event(more_ad, "APHELIOS_Q_BINDING_ECLIPSE").outputs[0].amount > _event(
        baseline, "APHELIOS_Q_BINDING_ECLIPSE"
    ).outputs[0].amount
    assert _event(more_ap, "APHELIOS_R_MOONLIGHT_VIGIL").outputs[0].amount > _event(
        baseline, "APHELIOS_R_MOONLIGHT_VIGIL"
    ).outputs[0].amount
    baseline_attacks = tuple(
        entry for entry in baseline.events if entry.id.startswith("APHELIOS_GRAVITUM_ATTACK_")
    )
    faster_attacks = tuple(
        entry for entry in more_speed.events if entry.id.startswith("APHELIOS_GRAVITUM_ATTACK_")
    )
    assert len(faster_attacks) > len(baseline_attacks)
    assert _event(
        more_crit, "APHELIOS_R_GRAVITUM_FOLLOWUP_ATTACK"
    ).outputs[0].amount > _event(
        baseline, "APHELIOS_R_GRAVITUM_FOLLOWUP_ATTACK"
    ).outputs[0].amount


def test_aphelios_role_reversal_and_root_reaction_are_role_neutral() -> None:
    """Keep Gravitum damage and reducible root attached to either request side."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Aphelios", "Caitlyn"))
    as_opponent = engine.evaluate(MatchupRequest("Caitlyn", "Aphelios"))
    reaction = create_default_registry(ROOT).require_cog("Aphelios").build_reaction_plan(
        _context()
    )

    root = reaction.cast_block_windows[0]
    assert root.blocked_channels == (ActionChannel.MOVEMENT,)
    assert root.tenacity_reducible is True
    assert root.control_type.value == "ROOT"
    assert root.source_event_id == "APHELIOS_Q_BINDING_ECLIPSE"
    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    actor_q = next(
        entry
        for entry in as_actor.timeline.log
        if entry.event_id == "APHELIOS_Q_BINDING_ECLIPSE" and entry.operation == "DAMAGE"
    )
    opponent_q = next(
        entry
        for entry in as_opponent.timeline.log
        if entry.event_id == "APHELIOS_Q_BINDING_ECLIPSE" and entry.operation == "DAMAGE"
    )
    assert actor_q.recipient is EntityId.TARGET
    assert opponent_q.recipient is EntityId.ACTOR


def test_teemo_blind_cancels_aphelios_attacks_but_not_binding_eclipse() -> None:
    """Route blind through attacks without suppressing Aphelios's Q ability."""
    result = MatchupEngine(ROOT).evaluate(MatchupRequest("Teemo", "Aphelios"))

    assert any(
        entry.event_id.startswith("APHELIOS_GRAVITUM_ATTACK_")
        and entry.action_channel is ActionChannel.BASIC_ATTACK
        and entry.status == "CANCELLED"
        for entry in result.timeline.log
    )
    assert next(
        entry
        for entry in result.timeline.log
        if entry.event_id == "APHELIOS_Q_BINDING_ECLIPSE" and entry.operation == "DAMAGE"
    ).status == "APPLIED"


def test_aphelios_item_policy_matches_represented_stat_channels() -> None:
    """Allow consumed offense while rejecting unresolved sustain and resources."""
    aphelios = create_default_registry(ROOT).require_cog("Aphelios")

    assert aphelios.item_candidate_blocker(
        {
            "id": 1,
            "stats": {
                "AD": {},
                "AP": {},
                "ATTACK_SPEED": {},
                "CRITICAL_STRIKE_CHANCE": {},
            },
        }
    ) is None
    assert aphelios.item_candidate_blocker(
        {"id": 2, "stats": {"ABILITY_HASTE": {}, "LIFESTEAL": {}, "MANA": {}}}
    ) == "APHELIOS_ITEM_STAT_NOT_MODELED:2:ABILITY_HASTE,LIFESTEAL,MANA"
