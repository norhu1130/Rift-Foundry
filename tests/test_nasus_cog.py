"""Focused regressions for the locked Nasus champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    EntityId,
    ResistanceReductionOutput,
)

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    nasus_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a level-13 Nasus-versus-Teemo direct-Cog context.

    :param nasus_is_actor: Place Nasus on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Nasus.
    :return: Role-bound deterministic benchmark context.
    """
    registry = create_default_registry(ROOT)
    nasus = registry.require_cog("Nasus")
    teemo = registry.require_cog("Teemo")
    return ParticipantContext(
        EntityId.ACTOR if nasus_is_actor else EntityId.TARGET,
        EntityId.TARGET if nasus_is_actor else EntityId.ACTOR,
        nasus.snapshot(level=13, item_stats=item_stats),
        teemo.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one named event from an action plan.

    :param plan: Action plan containing the expected event.
    :param event_id: Stable identifier of the requested event.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_nasus_declares_modeled_capabilities_and_three_locked_sources() -> None:
    """Distinguish Nasus's modeled Cog from a generated scaffold."""
    nasus = create_default_registry(ROOT).require_cog("Nasus")

    assert nasus.maturity is CogMaturity.MODELED_UNVERIFIED
    assert nasus.capabilities == DUEL_CAPABILITIES
    assert nasus.verification_blockers() == ("COG_MODEL_UNVERIFIED:Nasus",)
    assert nasus.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Nasus.json",
        "data/raw/16.17.1/communitydragon/champions/75.json",
        "data/raw/16.17.1/communitydragon/champions/nasus.bin.json",
    )
    assert all((ROOT / path).is_file() for path in nasus.evidence_refs)


def test_nasus_q_fixture_reset_and_r_cooldown_are_deterministic() -> None:
    """Anchor Q5's 300-stack fixture and R's fifty-percent cooldown reduction."""
    nasus = create_default_registry(ROOT).require_cog("Nasus")
    context = _context(item_stats={"AD": Decimal(40)})

    first = nasus.build_action_plan(context)
    repeated = nasus.build_action_plan(context)
    q_events = tuple(
        event for event in first.events if event.id.startswith("NASUS_Q_SIPHONING_STRIKE")
    )

    assert first == repeated
    assert first.model_id == "nasus_q5_w1_e5_r2_level13_synthetic_v1"
    assert tuple(event.at_ms for event in q_events) == (450, 2200, 3950, 5700, 7450)
    assert all(event.channel is ActionChannel.BASIC_ATTACK for event in q_events)
    assert all(
        event.outputs[0].amount == context.snapshot.attack_damage + 420 for event in q_events
    )
    assert "NASUS_Q_STACK_FIXTURE_300_ASSUMED" in first.blockers
    assert "NASUS_R_MAXIMUM_HEALTH_450_NOT_APPLIED" in first.blockers


def test_nasus_e_and_r_consume_ap_and_target_maximum_health() -> None:
    """Prove AP reaches Spirit Fire and the maximum-health sandstorm aura."""
    nasus = create_default_registry(ROOT).require_cog("Nasus")
    baseline_context = _context()
    powered_context = _context(item_stats={"AP": Decimal(100)})
    baseline = nasus.build_action_plan(baseline_context)
    powered = nasus.build_action_plan(powered_context)

    baseline_e = _event(baseline, "NASUS_E_SPIRIT_FIRE_INITIAL")
    powered_e = _event(powered, "NASUS_E_SPIRIT_FIRE_INITIAL")
    baseline_tick = _event(baseline, "NASUS_E_SPIRIT_FIRE_TICK_1")
    powered_tick = _event(powered, "NASUS_E_SPIRIT_FIRE_TICK_1")
    baseline_r = _event(baseline, "NASUS_R_SANDSTORM_TICK_1")
    powered_r = _event(powered, "NASUS_R_SANDSTORM_TICK_1")

    assert powered_e.outputs[0].amount - baseline_e.outputs[0].amount == 60
    assert powered_tick.outputs[0].amount - baseline_tick.outputs[0].amount == 12
    assert powered_r.outputs[0].amount - baseline_r.outputs[0].amount == (
        Decimal("0.005") * powered_context.opponent_snapshot.max_hp
    )
    reduction = baseline_e.outputs[1]
    assert isinstance(reduction, ResistanceReductionOutput)
    assert reduction.stat == "ARMOR"
    assert reduction.fraction_per_stack == Decimal("0.50")
    assert reduction.duration_ms == 5000


def test_nasus_w_progressively_slows_opponent_attack_cadence() -> None:
    """Anchor W1's five attack-speed multipliers and causal source event."""
    nasus = create_default_registry(ROOT).require_cog("Nasus")
    reaction = nasus.build_reaction_plan(_context())

    assert tuple(window.multiplier for window in reaction.attack_cadence_windows) == (
        Decimal("0.7375"),
        Decimal("0.7150"),
        Decimal("0.6925"),
        Decimal("0.6700"),
        Decimal("0.6475"),
    )
    assert all(
        window.source_event_id == "NASUS_W_WITHER" for window in reaction.attack_cadence_windows
    )

    result = MatchupEngine(ROOT).evaluate(MatchupRequest("Nasus", "Teemo"))
    first_teemo_attack = next(
        entry
        for entry in result.timeline.log
        if entry.event_id == "TEEMO_E_ATTACK_1" and entry.operation == "DAMAGE"
    )
    assert first_teemo_attack.at_ms > 400


def test_nasus_r_resistance_windows_cover_both_damage_channels() -> None:
    """Keep R2's fixed armor and magic-resistance grants in Nasus's reaction plan."""
    nasus = create_default_registry(ROOT).require_cog("Nasus")
    context = _context()
    reaction = nasus.build_reaction_plan(context)
    armor, magic_resistance = reaction.damage_windows

    assert armor.recipient is EntityId.ACTOR
    assert armor.damage_types == (DamageType.PHYSICAL,)
    expected_armor = (Decimal(100) + context.snapshot.armor) / (
        Decimal(155) + context.snapshot.armor
    )
    assert abs(armor.multiplier - expected_armor) < Decimal("1e-26")
    assert magic_resistance.damage_types == (DamageType.MAGIC,)
    expected_magic_resistance = (Decimal(100) + context.snapshot.magic_resistance) / (
        Decimal(155) + context.snapshot.magic_resistance
    )
    assert abs(magic_resistance.multiplier - expected_magic_resistance) < Decimal("1e-26")


def test_nasus_role_reversal_and_teemo_blind_preserve_action_ownership() -> None:
    """Keep Nasus role-neutral while blind cancels attacks but not spell output."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Nasus", "Teemo"))
    as_opponent = engine.evaluate(MatchupRequest("Teemo", "Nasus"))

    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    assert any(
        entry.event_id.startswith("NASUS_Q_SIPHONING_STRIKE") and entry.status == "CANCELLED"
        for entry in as_actor.timeline.log
    )
    for event_id in (
        "NASUS_E_SPIRIT_FIRE_INITIAL",
        "NASUS_R_SANDSTORM_TICK_1",
    ):
        assert any(
            entry.event_id == event_id and entry.operation == "DAMAGE" and entry.status == "APPLIED"
            for entry in as_actor.timeline.log
        )
    opponent_r = next(
        entry
        for entry in as_opponent.timeline.log
        if entry.event_id == "NASUS_R_SANDSTORM_TICK_1" and entry.operation == "DAMAGE"
    )
    assert opponent_r.recipient is EntityId.ACTOR


def test_nasus_item_policy_is_honest_about_haste_and_stat_sensitivity() -> None:
    """Allow represented chassis stats while rejecting unscheduled haste."""
    nasus = create_default_registry(ROOT).require_cog("Nasus")
    baseline_context = _context()
    attack_context = _context(item_stats={"AD": Decimal(40)})
    health_context = _context(item_stats={"HP": Decimal(500)})

    baseline_q = _event(
        nasus.build_action_plan(baseline_context),
        "NASUS_Q_SIPHONING_STRIKE_1",
    )
    attack_q = _event(
        nasus.build_action_plan(attack_context),
        "NASUS_Q_SIPHONING_STRIKE_1",
    )
    assert attack_q.outputs[0].amount - baseline_q.outputs[0].amount == 40
    assert health_context.snapshot.max_hp - baseline_context.snapshot.max_hp == 500
    assert (
        nasus.item_candidate_blocker(
            {"id": 1, "stats": {"AD": {}, "AP": {}, "HP": {}, "ATTACK_SPEED": {}}}
        )
        is None
    )
    assert (
        nasus.item_candidate_blocker({"id": 2, "stats": {"ABILITY_HASTE": {}, "MANA": {}}})
        == "NASUS_ITEM_STAT_NOT_MODELED:2:ABILITY_HASTE,MANA"
    )
