"""Focused regressions for the locked Gnar champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES, ActionPlan
from lol_build.cogs.registry import create_default_registry
from lol_build.core.combat import DamageType, apply_resistance
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    Combatant,
    DamageOutput,
    EntityId,
    StatModifierOutput,
    StatusOutput,
    simulate_timeline,
)

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    gnar_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
    opponent_item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a role-neutral level-13 Gnar-versus-Teemo context.

    :param gnar_is_actor: Place Gnar on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Gnar.
    :param opponent_item_stats: Optional permanent item modifiers applied to Teemo.
    :return: Role-bound deterministic benchmark context.
    """
    registry = create_default_registry(ROOT)
    gnar = registry.require_cog("Gnar")
    teemo = registry.require_cog("Teemo")
    return ParticipantContext(
        EntityId.ACTOR if gnar_is_actor else EntityId.TARGET,
        EntityId.TARGET if gnar_is_actor else EntityId.ACTOR,
        gnar.snapshot(level=13, item_stats=item_stats),
        teemo.snapshot(level=13, item_stats=opponent_item_stats),
        8000,
        3000,
    )


def _event(plan: ActionPlan, event_id: str) -> ActionEvent:
    """Resolve one champion-scoped event from a Gnar action plan.

    :param plan: Gnar action plan containing the expected event.
    :param event_id: Identifier of the requested action.
    :return: Matching immutable action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_gnar_declares_modeled_capabilities_and_three_locked_sources() -> None:
    """Distinguish Gnar's implemented Cog from a generated scaffold."""
    gnar = create_default_registry(ROOT).require_cog("Gnar")

    assert gnar.maturity is CogMaturity.MODELED_UNVERIFIED
    assert gnar.capabilities == DUEL_CAPABILITIES
    assert gnar.verification_blockers() == ("COG_MODEL_UNVERIFIED:Gnar",)
    assert gnar.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Gnar.json",
        "data/raw/16.17.1/communitydragon/champions/150.json",
        "data/raw/16.17.1/communitydragon/champions/gnar.bin.json",
    )
    assert all((ROOT / path).is_file() for path in gnar.evidence_refs)


def test_gnar_rotation_is_deterministic_and_marks_both_forms() -> None:
    """Anchor the fixed Mini-to-Mega state transition and skill order."""
    gnar = create_default_registry(ROOT).require_cog("Gnar")
    context = _context()

    first = gnar.build_action_plan(context)
    repeated = gnar.build_action_plan(context)
    mini = _event(first, "GNAR_START_MINI_FORM").outputs[0]
    mega = _event(first, "GNAR_TRANSFORM_TO_MEGA").outputs[0]

    assert first == repeated
    assert first.model_id == "gnar_q5_w5_e1_r2_mini_to_mega_level13_synthetic_v1"
    assert isinstance(mini, StatusOutput)
    assert (mini.status, mini.duration_ms) == ("GNAR_FORM_MINI", 3000)
    assert isinstance(mega, StatusOutput)
    assert (mega.status, mega.duration_ms) == ("GNAR_FORM_MEGA", 5000)
    assert _event(first, "GNAR_MINI_Q_BOOMERANG").at_ms < _event(
        first, "GNAR_TRANSFORM_TO_MEGA"
    ).at_ms
    assert _event(first, "GNAR_MEGA_E_CRUNCH").at_ms == 3100
    assert "GNAR_TRANSFORM_AT_3000MS_SYNTHETIC" in first.blockers
    assert "GNAR_TRANSFORM_MAX_HP_CURRENT_HP_SEMANTICS_NOT_EVALUATED" in first.blockers


def test_gnar_locked_spell_values_and_control_are_preserved() -> None:
    """Anchor Q5/W5/E1/R2 formulas without assuming a wall collision."""
    gnar = create_default_registry(ROOT).require_cog("Gnar")
    context = _context(item_stats={"AP": Decimal(100), "AD": Decimal(40)})
    plan = gnar.build_action_plan(context)
    mini_q = _event(plan, "GNAR_MINI_Q_BOOMERANG")
    mega_w = _event(plan, "GNAR_MEGA_W_WALLOP")
    ultimate = _event(plan, "GNAR_MEGA_R_GNAR")

    assert mini_q.outputs[0].amount == Decimal(165) + Decimal("1.25") * (
        context.snapshot.attack_damage
    )
    assert isinstance(mini_q.outputs[1], StatusOutput)
    assert (mini_q.outputs[1].status, mini_q.outputs[1].duration_ms) == (
        "CC_SLOW",
        2000,
    )
    assert mega_w.outputs[0].amount > Decimal(165) + context.snapshot.attack_damage
    hop_haste = _event(plan, "GNAR_MINI_E_HOP").outputs[2]
    assert isinstance(hop_haste, StatusOutput)
    assert (hop_haste.status, hop_haste.duration_ms, hop_haste.magnitude) == (
        "GNAR_MINI_E_ATTACK_SPEED",
        6000,
        Decimal("0.40"),
    )
    assert ultimate.outputs[0].amount == (
        Decimal(300)
        + context.snapshot.ability_power
        + Decimal("0.50") * context.snapshot.bonus_attack_damage
    )
    assert isinstance(ultimate.outputs[1], StatusOutput)
    assert ultimate.outputs[1].status == "CC_SLOW"
    assert "GNAR_R_WALL_COLLISION_BONUS_AND_STUN_NOT_EVALUATED" in plan.blockers


def test_gnar_ad_ap_health_and_attack_speed_reach_distinct_outputs() -> None:
    """Prove core fighter stats affect their represented model channels."""
    gnar = create_default_registry(ROOT).require_cog("Gnar")
    baseline_context = _context()
    baseline = gnar.build_action_plan(baseline_context)
    attack = gnar.build_action_plan(_context(item_stats={"AD": Decimal(40)}))
    power = gnar.build_action_plan(_context(item_stats={"AP": Decimal(100)}))
    health = gnar.build_action_plan(_context(item_stats={"HP": Decimal(500)}))
    speed = gnar.build_action_plan(
        _context(item_stats={"ATTACK_SPEED": Decimal("0.50")})
    )

    assert (
        _event(attack, "GNAR_MINI_Q_BOOMERANG").outputs[0].amount
        - _event(baseline, "GNAR_MINI_Q_BOOMERANG").outputs[0].amount
        == 50
    )
    baseline_proc = _event(baseline, "GNAR_MINI_ATTACK_2")
    power_proc = _event(power, "GNAR_MINI_ATTACK_2")
    assert power_proc.outputs[-1].amount - baseline_proc.outputs[-1].amount == 100
    assert (
        _event(health, "GNAR_MINI_E_HOP").outputs[0].amount
        - _event(baseline, "GNAR_MINI_E_HOP").outputs[0].amount
        == 30
    )
    assert len(
        [event for event in speed.events if event.id.startswith("GNAR_MINI_ATTACK_")]
    ) > len(
        [event for event in baseline.events if event.id.startswith("GNAR_MINI_ATTACK_")]
    )
    assert gnar.engagement_dash_distance(baseline_context) == 475


def test_gnar_mega_resists_apply_at_runtime_and_wallop_is_reducible() -> None:
    """Prove the form defense event and stun reaction retain causal semantics."""
    gnar = create_default_registry(ROOT).require_cog("Gnar")
    context = _context()
    reaction = gnar.build_reaction_plan(context)
    resist_event = reaction.events[0]
    modifiers = tuple(
        output for output in resist_event.outputs if isinstance(output, StatModifierOutput)
    )
    stun = reaction.cast_block_windows[0]

    assert {output.stat for output in modifiers} == {"ARMOR", "MAGIC_RESISTANCE"}
    assert all(output.amount > 0 for output in modifiers)
    assert stun.control_type.value == "STUN"
    assert stun.tenacity_reducible is True
    assert stun.source_event_id == "GNAR_MEGA_W_WALLOP"

    incoming = ActionEvent(
        "TEST_PHYSICAL_AFTER_TRANSFORM",
        3200,
        20_000,
        EntityId.TARGET,
        ActionChannel.ABILITY,
        (DamageOutput(EntityId.ACTOR, Decimal(200), DamageType.PHYSICAL),),
    )
    result = simulate_timeline(
        duration_ms=4000,
        horizon_ms=4000,
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
        events=(resist_event, incoming),
    )
    hit = next(entry for entry in result.log if entry.event_id == incoming.id)
    armor_bonus = next(output.amount for output in modifiers if output.stat == "ARMOR")
    expected = apply_resistance(
        Decimal(200),
        DamageType.PHYSICAL,
        armor=context.snapshot.armor + armor_bonus,
        magic_resistance=context.snapshot.magic_resistance,
    ).post_mitigation_damage
    assert hit.post_mitigation_amount == expected


def test_gnar_role_reversal_and_teemo_blind_preserve_action_ownership() -> None:
    """Keep Gnar role-neutral while Blind cancels attacks but not form spells."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Gnar", "Teemo"))
    as_opponent = engine.evaluate(MatchupRequest("Teemo", "Gnar"))

    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    assert any(
        entry.event_id.startswith("GNAR_MINI_ATTACK_") and entry.status == "CANCELLED"
        for entry in as_actor.timeline.log
    )
    for event_id in (
        "GNAR_MINI_Q_BOOMERANG",
        "GNAR_MEGA_Q_BOULDER",
        "GNAR_MEGA_W_WALLOP",
    ):
        assert any(
            entry.event_id == event_id
            and entry.operation == "DAMAGE"
            and entry.status == "APPLIED"
            for entry in as_actor.timeline.log
        )


def test_gnar_item_policy_rejects_unrepresented_rotation_stats() -> None:
    """Allow represented stats while rejecting fixed-schedule omissions."""
    gnar = create_default_registry(ROOT).require_cog("Gnar")

    assert (
        gnar.item_candidate_blocker(
            {"id": 1, "stats": {"AD": {}, "AP": {}, "HP": {}, "ATTACK_SPEED": {}}}
        )
        is None
    )
    assert (
        gnar.item_candidate_blocker(
            {"id": 2, "stats": {"ABILITY_HASTE": {}, "MANA": {}}}
        )
        == "GNAR_ITEM_STAT_NOT_MODELED:2:ABILITY_HASTE,MANA"
    )
