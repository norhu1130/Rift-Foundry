"""Focused regressions for the locked Fiddlesticks champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import (
    ActionChannel,
    Combatant,
    CurrentHealthDamageOutput,
    EntityId,
    HealOutput,
    MissingHealthDamageOutput,
    StatusOutput,
    simulate_timeline,
)

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    fiddlesticks_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
    opponent_health: Decimal = Decimal(0),
) -> ParticipantContext:
    """Build a level-13 Fiddlesticks-versus-Teemo direct-Cog context.

    :param fiddlesticks_is_actor: Place Fiddlesticks on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Fiddlesticks.
    :param opponent_health: Additional maximum health applied to Teemo.
    :return: Role-bound deterministic benchmark context.
    """
    registry = create_default_registry(ROOT)
    fiddlesticks = registry.require_cog("Fiddlesticks")
    teemo = registry.require_cog("Teemo")
    return ParticipantContext(
        EntityId.ACTOR if fiddlesticks_is_actor else EntityId.TARGET,
        EntityId.TARGET if fiddlesticks_is_actor else EntityId.ACTOR,
        fiddlesticks.snapshot(level=13, item_stats=item_stats),
        teemo.snapshot(level=13, item_stats={"HP": opponent_health}),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Resolve one event by its stable Fiddlesticks identifier.

    :param plan: Action plan exposing an ``events`` tuple.
    :param event_id: Exact event identifier to locate.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def _fiddlesticks_only_timeline(context: ParticipantContext):
    """Simulate one Fiddlesticks plan without an opponent action schedule.

    :param context: Actor-bound context whose opponent becomes the target state.
    :return: Deterministic timeline result for Fiddlesticks outputs alone.
    """
    if context.self_entity is not EntityId.ACTOR:
        raise ValueError("Fiddlesticks-only helper requires actor role")
    registry = create_default_registry(ROOT)
    plan = registry.require_cog("Fiddlesticks").build_action_plan(context)
    actor = context.snapshot
    target = context.opponent_snapshot
    return simulate_timeline(
        duration_ms=context.duration_ms,
        horizon_ms=context.horizon_ms,
        actor=Combatant(
            EntityId.ACTOR,
            actor.max_hp,
            actor.max_hp,
            actor.armor,
            actor.magic_resistance,
            percent_armor_penetration=actor.percent_armor_penetration,
            flat_armor_penetration=actor.flat_armor_penetration,
            percent_magic_penetration=actor.percent_magic_penetration,
            flat_magic_penetration=actor.flat_magic_penetration,
            tenacity=actor.tenacity,
        ),
        target=Combatant(
            EntityId.TARGET,
            target.max_hp,
            target.max_hp,
            target.armor,
            target.magic_resistance,
            tenacity=target.tenacity,
        ),
        events=plan.events,
    )


def test_fiddlesticks_declares_modeled_capabilities_and_locked_evidence() -> None:
    """Distinguish Fiddlesticks from a scaffold and retain all source forms."""
    fiddlesticks = create_default_registry(ROOT).require_cog("Fiddlesticks")

    assert fiddlesticks.maturity is CogMaturity.MODELED_UNVERIFIED
    assert fiddlesticks.capabilities == DUEL_CAPABILITIES
    assert fiddlesticks.verification_blockers() == ("COG_MODEL_UNVERIFIED:Fiddlesticks",)
    assert fiddlesticks.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Fiddlesticks.json",
        "data/raw/16.17.1/communitydragon/champions/9.json",
        "data/raw/16.17.1/communitydragon/champions/fiddlesticks.bin.json",
    )
    assert all((ROOT / reference).is_file() for reference in fiddlesticks.evidence_refs)


def test_fiddlesticks_rotation_is_deterministic_and_uses_locked_formulas() -> None:
    """Anchor Q5/W5/E1/R2 damage, drain, and control to locked values."""
    fiddlesticks = create_default_registry(ROOT).require_cog("Fiddlesticks")
    context = _context(item_stats={"AP": Decimal(100)})

    first = fiddlesticks.build_action_plan(context)
    repeated = fiddlesticks.build_action_plan(context)
    r_start = _event(first, "FIDDLESTICKS_R_CROWSTORM_CHANNEL_START")
    r_tick = _event(first, "FIDDLESTICKS_R_CROWSTORM_TICK_1")
    q = _event(first, "FIDDLESTICKS_Q_TERRIFY_RECENTLY_FEARED")
    e = _event(first, "FIDDLESTICKS_E_REAP_CENTER_1")
    w_tick = _event(first, "FIDDLESTICKS_W_BOUNTIFUL_HARVEST_TICK_1")
    w_final = _event(first, "FIDDLESTICKS_W_BOUNTIFUL_HARVEST_TICK_8")

    assert first == repeated
    assert first.model_id == "fiddlesticks_w5_q5_e1_r2_level13_unseen_ambush_v1"
    assert isinstance(r_start.outputs[0], StatusOutput)
    assert r_start.outputs[0].duration_ms == 1500
    assert r_tick.outputs[0].amount == Decimal(75)
    assert (r_tick.outputs[1].status, r_tick.outputs[1].duration_ms) == (
        "CC_FEAR",
        2000,
    )
    assert isinstance(q.outputs[0], CurrentHealthDamageOutput)
    assert q.outputs[0].ratio == Decimal("0.18")
    assert e.outputs[0].amount == Decimal(120)
    assert w_tick.outputs[0].amount == Decimal("56.25")
    # Rank-five VampPercentage heals from each tick's resolved damage.
    assert w_tick.outputs[0].source_heal_ratio == Decimal("0.55")
    assert not any(isinstance(output, HealOutput) for output in w_tick.outputs)
    assert isinstance(w_final.outputs[-1], MissingHealthDamageOutput)
    assert w_final.outputs[-1].missing_health_ratio == Decimal("0.22")
    assert len([event for event in first.events if "CROWSTORM_TICK" in event.id]) == 20
    assert len([event for event in first.events if "HARVEST_TICK" in event.id]) == 8
    assert "FIDDLESTICKS_R_CHANNEL_CANCELLATION_CAUSALITY_NOT_MODELED" in first.blockers
    assert "FIDDLESTICKS_Q_CURRENT_HEALTH_RUNTIME_EXACTNESS_UNVERIFIED" in first.blockers
    assert "FIDDLESTICKS_MULTI_TARGET_DAMAGE_AND_HEALING_NOT_MODELED" in first.blockers


def test_fiddlesticks_ap_haste_and_target_hp_reach_modeled_channels() -> None:
    """Prove AP, haste, and opposing health alter represented outcomes."""
    fiddlesticks = create_default_registry(ROOT).require_cog("Fiddlesticks")
    baseline = fiddlesticks.build_action_plan(_context())
    powered = fiddlesticks.build_action_plan(_context(item_stats={"AP": Decimal(100)}))
    hasted = fiddlesticks.build_action_plan(_context(item_stats={"ABILITY_HASTE": Decimal(100)}))

    assert _event(powered, "FIDDLESTICKS_R_CROWSTORM_TICK_1").outputs[0].amount - _event(
        baseline, "FIDDLESTICKS_R_CROWSTORM_TICK_1"
    ).outputs[0].amount == Decimal("12.5")
    assert _event(powered, "FIDDLESTICKS_W_BOUNTIFUL_HARVEST_TICK_1").outputs[0].amount - _event(
        baseline, "FIDDLESTICKS_W_BOUNTIFUL_HARVEST_TICK_1"
    ).outputs[0].amount == Decimal("11.25")
    assert _event(hasted, "FIDDLESTICKS_E_REAP_CENTER_2").at_ms == 7150

    normal_hp = _fiddlesticks_only_timeline(_context())
    bonus_hp = _fiddlesticks_only_timeline(_context(opponent_health=Decimal(1000)))
    normal_q = next(
        entry
        for entry in normal_hp.log
        if entry.event_id == "FIDDLESTICKS_Q_TERRIFY_RECENTLY_FEARED"
        and entry.operation == "DAMAGE"
    )
    bonus_q = next(
        entry
        for entry in bonus_hp.log
        if entry.event_id == "FIDDLESTICKS_Q_TERRIFY_RECENTLY_FEARED"
        and entry.operation == "DAMAGE"
    )
    assert bonus_q.raw_amount is not None
    assert normal_q.raw_amount is not None
    assert bonus_q.raw_amount > normal_q.raw_amount


def test_fiddlesticks_reaction_exposes_fear_silence_and_slow_semantics() -> None:
    """Keep full-action fear separate from silence and movement-only slow."""
    fiddlesticks = create_default_registry(ROOT).require_cog("Fiddlesticks")
    reaction = fiddlesticks.build_reaction_plan(
        _context(item_stats={"ABILITY_HASTE": Decimal(100)})
    )

    fear = reaction.cast_block_windows[0]
    silences = tuple(
        window for window in reaction.cast_block_windows if window.control_type.value == "SILENCE"
    )
    slows = tuple(
        window for window in reaction.cast_block_windows if window.control_type.value == "SLOW"
    )
    assert fear.control_type.value == "FEAR"
    assert fear.tenacity_reducible is True
    assert fear.blocked_channels == (
        ActionChannel.BASIC_ATTACK,
        ActionChannel.ABILITY,
        ActionChannel.MOVEMENT,
        ActionChannel.ITEM_ACTIVE,
    )
    assert fear.source_event_id == "FIDDLESTICKS_R_CROWSTORM_TICK_1"
    assert len(silences) == len(slows) == 2
    assert all(window.blocked_channels == (ActionChannel.ABILITY,) for window in silences)
    assert all(window.blocked_channels == (ActionChannel.MOVEMENT,) for window in slows)


def test_fiddlesticks_role_reversal_and_teemo_blind_preserve_spell_channels() -> None:
    """Keep Fiddlesticks role-neutral while blind cancels attacks, not spells."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Fiddlesticks", "Teemo"))
    as_opponent = engine.evaluate(MatchupRequest("Teemo", "Fiddlesticks"))

    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    actor_q = next(
        entry
        for entry in as_actor.timeline.log
        if entry.event_id == "FIDDLESTICKS_Q_TERRIFY_RECENTLY_FEARED"
        and entry.operation == "DAMAGE"
    )
    opponent_q = next(
        entry
        for entry in as_opponent.timeline.log
        if entry.event_id == "FIDDLESTICKS_Q_TERRIFY_RECENTLY_FEARED"
        and entry.operation == "DAMAGE"
    )
    assert actor_q.recipient is EntityId.TARGET
    assert opponent_q.recipient is EntityId.ACTOR
    assert any(
        entry.event_id.startswith("FIDDLESTICKS_BASIC_ATTACK_")
        and entry.action_channel is ActionChannel.BASIC_ATTACK
        and entry.status == "CANCELLED"
        for entry in as_opponent.timeline.log
    )
    assert any(
        entry.event_id.startswith("FIDDLESTICKS_R_CROWSTORM_TICK_")
        and entry.operation == "DAMAGE"
        and entry.status == "APPLIED"
        for entry in as_opponent.timeline.log
    )


def test_fiddlesticks_item_policy_sustain_and_engagement_are_state_honest() -> None:
    """Accept modeled stats and retain unresolved lane and geometry state."""
    fiddlesticks = create_default_registry(ROOT).require_cog("Fiddlesticks")
    context = _context()

    assert fiddlesticks.engagement_speed_multiplier(context) == 1
    assert fiddlesticks.engagement_dash_distance(context) == 800
    assert (
        fiddlesticks.item_candidate_blocker(
            {
                "id": 1,
                "stats": {
                    "AP": {},
                    "ABILITY_HASTE": {},
                    "ATTACK_SPEED": {},
                    "HP": {},
                    "MAGIC_PENETRATION": {},
                },
            }
        )
        is None
    )
    assert (
        fiddlesticks.item_candidate_blocker(
            {"id": 2, "stats": {"HEAL_SHIELD_POWER": {}, "MANA": {}, "OMNIVAMP": {}}}
        )
        == "FIDDLESTICKS_ITEM_STAT_NOT_MODELED:2:HEAL_SHIELD_POWER,MANA"
    )
    amount, blockers = fiddlesticks.lane_sustain_extra_health(
        context,
        duration_ms=30_000,
        no_damage_delay_ms=8_000,
    )
    assert amount == 0
    assert blockers == (
        "FIDDLESTICKS_LANE_W_TARGET_CONTACT_SCHEDULE_NOT_MODELED",
        "FIDDLESTICKS_LANE_W_DAMAGE_TO_HEAL_TRACE_NOT_MODELED",
        "FIDDLESTICKS_LANE_MANA_BUDGET_NOT_MODELED",
    )
