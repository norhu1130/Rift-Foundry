"""Focused regressions for the locked Trundle champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES, ActionPlan
from lol_build.cogs.registry import create_default_registry
from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    Combatant,
    DamageOutput,
    EntityId,
    HealOutput,
    ResistanceReductionOutput,
    StatModifierOutput,
    StatusOutput,
    simulate_timeline,
)

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    trundle_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
    opponent_item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a role-neutral level-13 Trundle-versus-Teemo context.

    :param trundle_is_actor: Place Trundle on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Trundle.
    :param opponent_item_stats: Optional permanent item modifiers applied to Teemo.
    :return: Role-bound deterministic benchmark context.
    """
    registry = create_default_registry(ROOT)
    trundle = registry.require_cog("Trundle")
    teemo = registry.require_cog("Teemo")
    return ParticipantContext(
        EntityId.ACTOR if trundle_is_actor else EntityId.TARGET,
        EntityId.TARGET if trundle_is_actor else EntityId.ACTOR,
        trundle.snapshot(level=13, item_stats=item_stats),
        teemo.snapshot(level=13, item_stats=opponent_item_stats),
        8000,
        3000,
    )


def _event(plan: ActionPlan, event_id: str) -> ActionEvent:
    """Resolve one champion-scoped event from an action plan.

    :param plan: Trundle action plan containing the expected event.
    :param event_id: Identifier of the requested action.
    :return: Matching immutable action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_trundle_declares_modeled_capabilities_and_three_locked_sources() -> None:
    """Distinguish Trundle's implemented Cog from a generated scaffold."""
    trundle = create_default_registry(ROOT).require_cog("Trundle")

    assert trundle.maturity is CogMaturity.MODELED_UNVERIFIED
    assert trundle.capabilities == DUEL_CAPABILITIES
    assert trundle.verification_blockers() == ("COG_MODEL_UNVERIFIED:Trundle",)
    assert trundle.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Trundle.json",
        "data/raw/16.17.1/communitydragon/champions/48.json",
        "data/raw/16.17.1/communitydragon/champions/trundle.bin.json",
    )
    assert all((ROOT / path).is_file() for path in trundle.evidence_refs)


def test_trundle_rotation_and_q_attack_resets_are_deterministic() -> None:
    """Anchor the Q5/W5/E1/R2 policy and three reset attacks."""
    trundle = create_default_registry(ROOT).require_cog("Trundle")
    context = _context()

    first = trundle.build_action_plan(context)
    repeated = trundle.build_action_plan(context)
    q_events = tuple(event for event in first.events if event.id.startswith("TRUNDLE_Q_"))

    assert first == repeated
    assert first.model_id == "trundle_q5_w5_e1_r2_level13_synthetic_v1"
    assert tuple(event.at_ms for event in q_events) == (501, 4001, 7501)
    assert all(event.channel is ActionChannel.BASIC_ATTACK for event in q_events)
    assert "TRUNDLE_Q_ATTACK_RESET_TIMING_UNVERIFIED" in first.blockers
    assert "TRUNDLE_E_TERRAIN_AND_DISPLACEMENT_NOT_EVALUATED" in first.blockers


def test_trundle_q_consumes_ad_and_w_consumes_attack_speed_and_movement() -> None:
    """Prove represented fighter stats alter Q, attack cadence, and pursuit."""
    trundle = create_default_registry(ROOT).require_cog("Trundle")
    baseline_context = _context()
    attack_context = _context(item_stats={"AD": Decimal(40)})
    speed_context = _context(item_stats={"ATTACK_SPEED": Decimal("0.25")})
    baseline = trundle.build_action_plan(baseline_context)
    attack = trundle.build_action_plan(attack_context)
    speed = trundle.build_action_plan(speed_context)

    baseline_q = _event(baseline, "TRUNDLE_Q_CHOMP_1")
    attack_q = _event(attack, "TRUNDLE_Q_CHOMP_1")
    baseline_second = _event(baseline, "TRUNDLE_BASIC_ATTACK_2")
    speed_second = _event(speed, "TRUNDLE_BASIC_ATTACK_2")

    assert attack_q.outputs[0].amount - baseline_q.outputs[0].amount == 62
    assert speed_second.at_ms < baseline_second.at_ms
    assert trundle.engagement_speed_multiplier(baseline_context) == Decimal("1.52")
    assert (
        trundle.item_candidate_blocker(
            {"id": 1, "stats": {"AD": {}, "AP": {}, "HP": {}, "ATTACK_SPEED": {}}}
        )
        is None
    )
    assert (
        trundle.item_candidate_blocker({"id": 2, "stats": {"ABILITY_HASTE": {}, "LIFESTEAL": {}}})
        == "TRUNDLE_ITEM_STAT_NOT_MODELED:2:ABILITY_HASTE,LIFESTEAL"
    )


def test_trundle_e_emits_locked_rank_one_slow_without_fabricating_terrain() -> None:
    """Keep E's slow numeric while terrain and displacement remain blockers."""
    trundle = create_default_registry(ROOT).require_cog("Trundle")
    plan = trundle.build_action_plan(_context())
    pillar = _event(plan, "TRUNDLE_E_PILLAR_SLOW")
    slow = pillar.outputs[0]

    assert isinstance(slow, StatusOutput)
    assert slow.status == "CC_SLOW"
    assert slow.duration_ms == 6000
    assert slow.magnitude == Decimal("0.34")
    assert (
        "TRUNDLE_E_TERRAIN_PATHING_NOT_EVALUATED"
        in trundle.build_reaction_plan(_context()).blockers
    )


def test_trundle_r_consumes_ap_target_health_and_target_resistances() -> None:
    """Anchor R2 drain scaling and progressive forty-percent resistance steal."""
    trundle = create_default_registry(ROOT).require_cog("Trundle")
    baseline_context = _context()
    powered_context = _context(
        item_stats={"AP": Decimal(100)},
        opponent_item_stats={
            "HP": Decimal(800),
            "ARMOR": Decimal(100),
            "MAGIC_RESISTANCE": Decimal(80),
        },
    )
    baseline = trundle.build_action_plan(baseline_context)
    powered = trundle.build_action_plan(powered_context)
    baseline_initial = _event(baseline, "TRUNDLE_R_SUBJUGATE_INITIAL")
    powered_initial = _event(powered, "TRUNDLE_R_SUBJUGATE_INITIAL")

    baseline_damage = next(
        output for output in baseline_initial.outputs if isinstance(output, DamageOutput)
    )
    powered_damage = next(
        output for output in powered_initial.outputs if isinstance(output, DamageOutput)
    )
    powered_heal = next(
        output for output in powered_initial.outputs if isinstance(output, HealOutput)
    )
    assert baseline_damage.amount == baseline_context.opponent_snapshot.max_hp * Decimal("0.125")
    assert powered_damage.amount == powered_context.opponent_snapshot.max_hp * Decimal("0.135")
    assert powered_heal.amount == powered_damage.amount * Decimal("1.25")
    assert sum(
        next(output.amount for output in event.outputs if isinstance(output, DamageOutput))
        for event in powered.events
        if event.id.startswith("TRUNDLE_R_SUBJUGATE")
    ) == powered_context.opponent_snapshot.max_hp * Decimal("0.27")

    initial_reductions = tuple(
        output
        for output in powered_initial.outputs
        if isinstance(output, ResistanceReductionOutput)
    )
    initial_modifiers = tuple(
        output for output in powered_initial.outputs if isinstance(output, StatModifierOutput)
    )
    assert len(initial_reductions) == 8
    assert {output.fraction_per_stack for output in initial_reductions} == {Decimal("0.05")}
    assert {output.stat: output.amount for output in initial_modifiers} == {
        "ARMOR": powered_context.opponent_snapshot.armor * Decimal("0.20"),
        "MAGIC_RESISTANCE": powered_context.opponent_snapshot.magic_resistance * Decimal("0.20"),
    }
    assert (
        len(
            [
                output
                for event in powered.events
                if event.id.startswith("TRUNDLE_R_SUBJUGATE")
                for output in event.outputs
                if isinstance(output, ResistanceReductionOutput)
            ]
        )
        == 16
    )


def test_runtime_resistance_steal_reduces_incoming_damage_causally() -> None:
    """Prove R's runtime armor modifier reaches the shared resistance pipeline."""
    trundle = create_default_registry(ROOT).require_cog("Trundle")
    context = _context()
    initial = _event(trundle.build_action_plan(context), "TRUNDLE_R_SUBJUGATE_INITIAL")
    incoming = ActionEvent(
        "TEST_PHYSICAL_HIT",
        300,
        20_000,
        EntityId.TARGET,
        ActionChannel.ABILITY,
        (DamageOutput(EntityId.ACTOR, Decimal(200), DamageType.PHYSICAL),),
    )
    result = simulate_timeline(
        duration_ms=1000,
        horizon_ms=1000,
        actor=Combatant(
            EntityId.ACTOR,
            context.snapshot.max_hp,
            context.snapshot.max_hp,
            context.snapshot.armor,
            context.snapshot.magic_resistance,
        ),
        target=Combatant(
            EntityId.TARGET,
            context.opponent_snapshot.max_hp,
            context.opponent_snapshot.max_hp,
            context.opponent_snapshot.armor,
            context.opponent_snapshot.magic_resistance,
        ),
        events=(initial, incoming),
    )
    hit = next(entry for entry in result.log if entry.event_id == "TEST_PHYSICAL_HIT")
    expected_armor = context.snapshot.armor + Decimal("0.20") * (context.opponent_snapshot.armor)

    assert hit.post_mitigation_amount == Decimal(200) * Decimal(100) / (
        Decimal(100) + expected_armor
    )


def test_trundle_role_reversal_and_teemo_blind_preserve_action_ownership() -> None:
    """Keep Trundle role-neutral while blind cancels Q but not Subjugate."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Trundle", "Teemo"))
    as_opponent = engine.evaluate(MatchupRequest("Teemo", "Trundle"))

    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    assert any(
        entry.event_id == "TRUNDLE_Q_CHOMP_1" and entry.status == "CANCELLED"
        for entry in as_actor.timeline.log
    )
    assert any(
        entry.event_id == "TRUNDLE_R_SUBJUGATE_INITIAL"
        and entry.operation == "DAMAGE"
        and entry.status == "APPLIED"
        for entry in as_actor.timeline.log
    )
    opponent_r = next(
        entry
        for entry in as_opponent.timeline.log
        if entry.event_id == "TRUNDLE_R_SUBJUGATE_INITIAL" and entry.operation == "DAMAGE"
    )
    assert opponent_r.recipient is EntityId.ACTOR
