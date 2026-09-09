"""Focused regressions for the locked Corki champion Cog."""

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
    DamageOutput,
    EntityId,
    StatModifierOutput,
)

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    corki_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a role-neutral level-13 Corki-versus-Teemo context.

    :param corki_is_actor: Place Corki on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Corki.
    :return: Role-bound deterministic benchmark context.
    """
    registry = create_default_registry(ROOT)
    corki = registry.require_cog("Corki")
    teemo = registry.require_cog("Teemo")
    return ParticipantContext(
        EntityId.ACTOR if corki_is_actor else EntityId.TARGET,
        EntityId.TARGET if corki_is_actor else EntityId.ACTOR,
        corki.snapshot(level=13, item_stats=item_stats),
        teemo.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan: ActionPlan, event_id: str) -> ActionEvent:
    """Resolve one champion-scoped event from an action plan.

    :param plan: Corki action plan containing the expected event.
    :param event_id: Identifier of the requested action.
    :return: Matching immutable action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def _damages(event: ActionEvent) -> tuple[DamageOutput, ...]:
    """Select fixed damage outputs from one Corki event.

    :param event: Action event containing mixed output types.
    :return: Damage outputs in declared order.
    """
    return tuple(output for output in event.outputs if isinstance(output, DamageOutput))


def test_corki_declares_modeled_capabilities_and_three_locked_sources() -> None:
    """Distinguish Corki's implemented Cog from a generated scaffold."""
    corki = create_default_registry(ROOT).require_cog("Corki")

    assert corki.maturity is CogMaturity.MODELED_UNVERIFIED
    assert corki.capabilities == DUEL_CAPABILITIES
    assert corki.verification_blockers() == ("COG_MODEL_UNVERIFIED:Corki",)
    assert corki.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Corki.json",
        "data/raw/16.17.1/communitydragon/champions/42.json",
        "data/raw/16.17.1/communitydragon/champions/corki.bin.json",
    )
    assert all((ROOT / path).is_file() for path in corki.evidence_refs)


def test_corki_rotation_is_deterministic_and_anchors_locked_spell_values() -> None:
    """Anchor Q5, W1, E5, R2, and the preloaded Big One fixture."""
    corki = create_default_registry(ROOT).require_cog("Corki")
    context = _context(item_stats={"AD": Decimal(40), "AP": Decimal(100)})

    first = corki.build_action_plan(context)
    repeated = corki.build_action_plan(context)
    q = _event(first, "CORKI_Q_PHOSPHORUS_BOMB_1")
    w = _event(first, "CORKI_W_VALKYRIE_FULL_TRAIL")
    e_ticks = tuple(event for event in first.events if event.id.startswith("CORKI_E_"))
    small = _event(first, "CORKI_R_MISSILE_1")
    big = _event(first, "CORKI_R_THE_BIG_ONE")

    assert first == repeated
    assert first.model_id == "corki_q5_w1_e5_r2_level13_preloaded_v1"
    assert _damages(q)[0].amount == 390
    assert _damages(w)[0].amount == 380
    assert len(e_ticks) == 16
    assert sum(_damages(event)[0].amount for event in e_ticks) == 376
    assert _damages(small)[0].amount == 204
    assert _damages(big)[0].amount == 408
    assert "CORKI_R_AMMO_RECHARGE_AND_ATTACK_REFUND_NOT_MODELED" in first.blockers
    assert "CORKI_PACKAGE_NOT_PRESENT_IN_LOCKED_CLASSIC_SPELL_SET" in first.blockers


def test_corki_rapid_reload_keeps_physical_attack_and_bonus_true_damage() -> None:
    """Keep passive true damage additive and attacks on the blindable channel."""
    corki = create_default_registry(ROOT).require_cog("Corki")
    context = _context(item_stats={"CRITICAL_STRIKE_CHANCE": Decimal("0.25")})
    attack = _event(corki.build_action_plan(context), "CORKI_RAPID_RELOAD_ATTACK_1")
    outputs = _damages(attack)

    assert attack.channel is ActionChannel.BASIC_ATTACK
    assert tuple(output.damage_type for output in outputs) == (
        DamageType.PHYSICAL,
        DamageType.TRUE,
    )
    assert outputs[0].amount == context.snapshot.attack_damage * Decimal("1.25")
    assert outputs[1].amount == context.snapshot.attack_damage * Decimal("0.25")


def test_corki_e_ticks_apply_four_flat_armor_and_mr_shred_steps() -> None:
    """Represent the locked twenty-point shred without treating it as percent."""
    corki = create_default_registry(ROOT).require_cog("Corki")
    plan = corki.build_action_plan(_context())
    shred = tuple(
        output
        for event in plan.events
        if event.id.startswith("CORKI_E_")
        for output in event.outputs
        if isinstance(output, StatModifierOutput)
    )

    assert len(shred) == 8
    assert {output.stat for output in shred} == {"ARMOR", "MAGIC_RESISTANCE"}
    assert {output.amount for output in shred} == {Decimal(-5)}
    assert sum(output.amount for output in shred if output.stat == "ARMOR") == -20
    assert all(output.recipient is EntityId.TARGET for output in shred)


def test_corki_ad_ap_attack_speed_and_haste_reach_represented_channels() -> None:
    """Prove all four offensive item dimensions affect the fixed schedule."""
    corki = create_default_registry(ROOT).require_cog("Corki")
    baseline = corki.build_action_plan(_context())
    scaled = corki.build_action_plan(
        _context(
            item_stats={
                "AD": Decimal(40),
                "AP": Decimal(100),
                "ATTACK_SPEED": Decimal("0.50"),
                "ABILITY_HASTE": Decimal(100),
            }
        )
    )

    assert _damages(_event(scaled, "CORKI_Q_PHOSPHORUS_BOMB_1"))[0].amount - (
        _damages(_event(baseline, "CORKI_Q_PHOSPHORUS_BOMB_1"))[0].amount
    ) == 150
    assert _damages(_event(scaled, "CORKI_W_VALKYRIE_FULL_TRAIL"))[0].amount - (
        _damages(_event(baseline, "CORKI_W_VALKYRIE_FULL_TRAIL"))[0].amount
    ) == 230
    assert len(
        [event for event in scaled.events if event.id.startswith("CORKI_RAPID_RELOAD_ATTACK_")]
    ) > len(
        [event for event in baseline.events if event.id.startswith("CORKI_RAPID_RELOAD_ATTACK_")]
    )
    assert _event(scaled, "CORKI_Q_PHOSPHORUS_BOMB_2").at_ms == 4400
    assert _event(baseline, "CORKI_Q_PHOSPHORUS_BOMB_2").at_ms == 7900


def test_corki_engagement_policy_sustain_and_item_policy_are_explicit() -> None:
    """Expose W reach while rejecting resource and unmodeled sustain stats."""
    corki = create_default_registry(ROOT).require_cog("Corki")
    context = _context()

    assert corki.engagement_dash_distance(context) == 600
    assert corki.lane_sustain_extra_health(
        context,
        duration_ms=30_000,
        no_damage_delay_ms=8_000,
    ) == (Decimal(0), ())
    assert (
        corki.item_candidate_blocker(
            {
                "id": 1,
                "stats": {
                    "AD": {},
                    "AP": {},
                    "ATTACK_SPEED": {},
                    "ABILITY_HASTE": {},
                    "CRITICAL_STRIKE_CHANCE": {},
                },
            }
        )
        is None
    )
    assert (
        corki.item_candidate_blocker(
            {"id": 2, "stats": {"MANA": {}, "LIFESTEAL": {}, "OMNIVAMP": {}}}
        )
        == "CORKI_ITEM_STAT_NOT_MODELED:2:LIFESTEAL,MANA,OMNIVAMP"
    )
    assert "CORKI_W_REACTIVE_ESCAPE_POLICY_NOT_MODELED" in (
        corki.build_reaction_plan(context).blockers
    )


def test_corki_role_reversal_and_teemo_blind_preserve_ability_channels() -> None:
    """Keep Corki role-neutral while blind cancels attacks but not missiles."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Corki", "Teemo"))
    as_opponent = engine.evaluate(MatchupRequest("Teemo", "Corki"))

    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    assert any(
        entry.event_id.startswith("CORKI_RAPID_RELOAD_ATTACK_")
        and entry.status == "CANCELLED"
        for entry in as_actor.timeline.log
    )
    assert any(
        entry.event_id == "CORKI_R_MISSILE_1"
        and entry.operation == "DAMAGE"
        and entry.status == "APPLIED"
        for entry in as_actor.timeline.log
    )
    opponent_missile = next(
        entry
        for entry in as_opponent.timeline.log
        if entry.event_id == "CORKI_R_MISSILE_1" and entry.operation == "DAMAGE"
    )
    assert opponent_missile.recipient is EntityId.ACTOR
