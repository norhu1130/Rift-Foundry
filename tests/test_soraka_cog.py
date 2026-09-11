"""Focused regressions for the locked Soraka champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import ActionChannel, EntityId, HealOutput, StatusOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    soraka_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a level-13 Soraka-versus-Teemo direct-Cog context.

    :param soraka_is_actor: Place Soraka on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Soraka.
    :return: Role-bound deterministic benchmark context.
    """
    registry = create_default_registry(ROOT)
    soraka = registry.require_cog("Soraka")
    teemo = registry.require_cog("Teemo")
    return ParticipantContext(
        EntityId.ACTOR if soraka_is_actor else EntityId.TARGET,
        EntityId.TARGET if soraka_is_actor else EntityId.ACTOR,
        soraka.snapshot(level=13, item_stats=item_stats),
        teemo.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Resolve one event by its stable Soraka identifier.

    :param plan: Action plan exposing an ``events`` tuple.
    :param event_id: Exact event identifier to locate.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_soraka_declares_modeled_capabilities_and_locked_evidence() -> None:
    """Distinguish Soraka from a scaffold and retain all source forms."""
    soraka = create_default_registry(ROOT).require_cog("Soraka")

    assert soraka.maturity is CogMaturity.MODELED_UNVERIFIED
    assert soraka.capabilities == DUEL_CAPABILITIES
    assert soraka.verification_blockers() == ("COG_MODEL_UNVERIFIED:Soraka",)
    assert soraka.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Soraka.json",
        "data/raw/16.17.1/communitydragon/champions/16.json",
        "data/raw/16.17.1/communitydragon/champions/soraka.bin.json",
    )
    assert all((ROOT / reference).is_file() for reference in soraka.evidence_refs)


def test_soraka_rotation_is_deterministic_and_uses_locked_formulas() -> None:
    """Anchor Q5/W5/E1/R2 damage, healing, control, and timing values."""
    soraka = create_default_registry(ROOT).require_cog("Soraka")
    context = _context(item_stats={"AP": Decimal(100)})

    first = soraka.build_action_plan(context)
    repeated = soraka.build_action_plan(context)
    q = _event(first, "SORAKA_Q_STARCALL_1")
    q_heal = _event(first, "SORAKA_Q_REJUVENATION_HEAL_1")
    e_initial = _event(first, "SORAKA_E_EQUINOX_INITIAL")
    e_expire = _event(first, "SORAKA_E_EQUINOX_EXPIRE")
    ultimate = _event(first, "SORAKA_R_WISH_SELF")

    assert first == repeated
    assert first.model_id == "soraka_q5_w5_e1_r2_level13_locked_v1"
    assert q.outputs[0].amount == 260
    assert isinstance(q.outputs[1], StatusOutput)
    assert (q.outputs[1].status, q.outputs[1].duration_ms) == ("CC_SLOW", 1500)
    assert q_heal.at_ms == 2600
    assert isinstance(q_heal.outputs[0], HealOutput)
    assert q_heal.outputs[0].amount == 150
    assert e_initial.outputs[0].amount == 110
    assert isinstance(e_initial.outputs[1], StatusOutput)
    assert e_initial.outputs[1].status == "CC_SILENCE"
    assert e_expire.outputs[0].amount == 110
    assert isinstance(e_expire.outputs[1], StatusOutput)
    assert (e_expire.outputs[1].status, e_expire.outputs[1].duration_ms) == (
        "CC_ROOT",
        1000,
    )
    assert isinstance(ultimate.outputs[0], HealOutput)
    assert ultimate.outputs[0].amount == 300


def test_soraka_ap_and_attack_speed_change_only_represented_channels() -> None:
    """Prove AP scales spells and heals while attack speed adds attacks."""
    soraka = create_default_registry(ROOT).require_cog("Soraka")
    baseline = soraka.build_action_plan(_context())
    powered = soraka.build_action_plan(_context(item_stats={"AP": Decimal(100)}))
    faster = soraka.build_action_plan(_context(item_stats={"ATTACK_SPEED": Decimal("0.50")}))

    assert (
        _event(powered, "SORAKA_Q_STARCALL_1").outputs[0].amount
        - _event(baseline, "SORAKA_Q_STARCALL_1").outputs[0].amount
        == 35
    )
    assert (
        _event(powered, "SORAKA_Q_REJUVENATION_HEAL_1").outputs[0].amount
        - _event(baseline, "SORAKA_Q_REJUVENATION_HEAL_1").outputs[0].amount
        == 30
    )
    assert (
        _event(powered, "SORAKA_R_WISH_SELF").outputs[0].amount
        - _event(baseline, "SORAKA_R_WISH_SELF").outputs[0].amount
        == 50
    )
    baseline_attacks = [
        event for event in baseline.events if event.id.startswith("SORAKA_BASIC_ATTACK_")
    ]
    faster_attacks = [
        event for event in faster.events if event.id.startswith("SORAKA_BASIC_ATTACK_")
    ]
    assert len(faster_attacks) > len(baseline_attacks)


def test_soraka_w_scope_is_explicit_instead_of_healing_an_enemy() -> None:
    """Keep ally-only W and its health cost outside the two-enemy timeline."""
    soraka = create_default_registry(ROOT).require_cog("Soraka")
    plan = soraka.build_action_plan(_context())

    assert not any(event.id.startswith("SORAKA_W_") for event in plan.events)
    assert "SORAKA_W_ALLY_TARGET_NOT_REPRESENTABLE_IN_TWO_COMBATANT_DUEL" in plan.blockers
    assert "SORAKA_W_HEALTH_COST_NOT_APPLIED_WITHOUT_VALID_ALLY_CAST" in plan.blockers
    assert "SORAKA_R_ALLY_HEALING_NOT_REPRESENTABLE_IN_TWO_COMBATANT_DUEL" in plan.blockers


def test_soraka_reaction_separates_silence_root_and_slow_channels() -> None:
    """Preserve Equinox cast blocking separately from movement control."""
    soraka = create_default_registry(ROOT).require_cog("Soraka")
    reaction = soraka.build_reaction_plan(_context())
    by_id = {window.id: window for window in reaction.cast_block_windows}

    silence = by_id["soraka_e_equinox_silence"]
    root = by_id["soraka_e_equinox_root"]
    slow = by_id["soraka_q_starcall_slow_1"]
    assert silence.control_type.value == "SILENCE"
    assert silence.blocked_channels == (ActionChannel.ABILITY,)
    assert silence.tenacity_reducible is True
    assert root.control_type.value == "ROOT"
    assert root.blocked_channels == (ActionChannel.MOVEMENT,)
    assert root.tenacity_reducible is True
    assert slow.control_type.value == "SLOW"
    assert slow.blocked_channels == (ActionChannel.MOVEMENT,)


def test_soraka_role_reversal_and_teemo_blind_preserve_spell_channels() -> None:
    """Keep Soraka symmetric while blind cancels attacks but not abilities."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Soraka", "Teemo"))
    as_opponent = engine.evaluate(MatchupRequest("Teemo", "Soraka"))

    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    assert any(
        entry.event_id.startswith("SORAKA_BASIC_ATTACK_")
        and entry.action_channel is ActionChannel.BASIC_ATTACK
        and entry.status == "CANCELLED"
        for entry in as_opponent.timeline.log
    )
    for event_id in (
        "SORAKA_Q_STARCALL_1",
        "SORAKA_E_EQUINOX_INITIAL",
        "SORAKA_R_WISH_SELF",
    ):
        assert any(
            entry.event_id == event_id and entry.status == "APPLIED"
            for entry in as_opponent.timeline.log
        )


def test_soraka_item_and_lane_policies_keep_unsupported_healing_explicit() -> None:
    """Allow represented stats while blocking heal power and lane assumptions."""
    soraka = create_default_registry(ROOT).require_cog("Soraka")

    assert (
        soraka.item_candidate_blocker(
            {"id": 1, "stats": {"AP": {}, "AD": {}, "ATTACK_SPEED": {}, "HP": {}}}
        )
        is None
    )
    assert (
        soraka.item_candidate_blocker(
            {"id": 2, "stats": {"ABILITY_HASTE": {}, "HEAL_SHIELD_POWER": {}, "MANA": {}}}
        )
        == "SORAKA_ITEM_STAT_NOT_MODELED:2:ABILITY_HASTE,HEAL_SHIELD_POWER,MANA"
    )
    amount, blockers = soraka.lane_sustain_extra_health(
        _context(),
        duration_ms=30_000,
        no_damage_delay_ms=8_000,
    )
    assert amount == 0
    assert blockers == (
        "SORAKA_LANE_Q_CHAMPION_HIT_SCHEDULE_NOT_MODELED",
        "SORAKA_LANE_W_ALLY_AND_HEALTH_COST_SCHEDULE_NOT_MODELED",
        "SORAKA_LANE_MANA_BUDGET_NOT_MODELED",
    )
