"""Focused regressions for the locked Ekko champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, EntityId, HealOutput, ShieldOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    ekko_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a level-13 Ekko-versus-Teemo direct-Cog context.

    :param ekko_is_actor: Place Ekko on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Ekko.
    :return: Role-bound deterministic benchmark context.
    """
    registry = create_default_registry(ROOT)
    ekko = registry.require_cog("Ekko")
    teemo = registry.require_cog("Teemo")
    return ParticipantContext(
        EntityId.ACTOR if ekko_is_actor else EntityId.TARGET,
        EntityId.TARGET if ekko_is_actor else EntityId.ACTOR,
        ekko.snapshot(level=13, item_stats=item_stats),
        teemo.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Resolve one event by its stable Ekko identifier.

    :param plan: Action plan exposing an ``events`` tuple.
    :param event_id: Exact event identifier to locate.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def _damage_outputs(event: object):
    """Select fixed damage outputs from one action event.

    :param event: Action event exposing an ``outputs`` tuple.
    :return: Outputs carrying a damage type and raw amount.
    """
    return tuple(output for output in event.outputs if hasattr(output, "damage_type"))


def test_ekko_declares_modeled_capabilities_and_locked_evidence() -> None:
    """Distinguish Ekko from a scaffold and retain all three source forms."""
    ekko = create_default_registry(ROOT).require_cog("Ekko")

    assert ekko.maturity is CogMaturity.MODELED_UNVERIFIED
    assert ekko.capabilities == DUEL_CAPABILITIES
    assert ekko.verification_blockers() == ("COG_MODEL_UNVERIFIED:Ekko",)
    assert ekko.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Ekko.json",
        "data/raw/16.17.1/communitydragon/champions/245.json",
        "data/raw/16.17.1/communitydragon/champions/ekko.bin.json",
    )
    assert all((ROOT / reference).is_file() for reference in ekko.evidence_refs)


def test_ekko_rotation_is_deterministic_and_uses_locked_formulas() -> None:
    """Anchor Q, E, W, R, and Z-Drive values to the locked fixture."""
    ekko = create_default_registry(ROOT).require_cog("Ekko")
    context = _context(item_stats={"AP": Decimal(100)})

    first = ekko.build_action_plan(context)
    repeated = ekko.build_action_plan(context)
    q_out = _event(first, "EKKO_Q_TIMEWINDER_OUT_1")
    q_return = _event(first, "EKKO_Q_TIMEWINDER_RETURN_1")
    e_attack = _event(first, "EKKO_E_PHASE_DIVE_ATTACK_1")
    w = _event(first, "EKKO_W_PARALLEL_CONVERGENCE_DETONATE")
    ultimate = _event(first, "EKKO_R_CHRONOBREAK_RETURN")

    assert first == repeated
    assert first.model_id == "ekko_q5_e5_w1_r2_level13_rewind_fixture_v1"
    assert _damage_outputs(q_out)[0].amount == Decimal(160)
    assert _damage_outputs(q_return)[0].amount == Decimal(200)
    assert _damage_outputs(e_attack)[1].amount == Decimal(190)
    assert any(output.amount == Decimal(195) for output in _damage_outputs(q_return))
    assert isinstance(w.outputs[0], ShieldOutput)
    assert w.outputs[0].amount == Decimal(250)
    assert _damage_outputs(ultimate)[0].amount == Decimal(525)
    assert isinstance(ultimate.outputs[1], HealOutput)
    assert ultimate.outputs[1].amount == Decimal(210)
    assert "EKKO_Q_OUTGOING_DAMAGE_DDRAGON_BIN_DISAGREEMENT" in first.blockers
    assert "EKKO_R_FOUR_SECOND_POSITION_HISTORY_NOT_MODELED" in first.blockers


def test_ekko_ap_attack_speed_and_haste_change_represented_outputs() -> None:
    """Prove AP, attack speed, and haste alter modeled damage or cadence."""
    ekko = create_default_registry(ROOT).require_cog("Ekko")
    baseline = ekko.build_action_plan(_context())
    scaled = ekko.build_action_plan(
        _context(
            item_stats={
                "AP": Decimal(100),
                "ATTACK_SPEED": Decimal("0.50"),
                "ABILITY_HASTE": Decimal(100),
            }
        )
    )

    assert _damage_outputs(_event(scaled, "EKKO_R_CHRONOBREAK_RETURN"))[0].amount - (
        _damage_outputs(_event(baseline, "EKKO_R_CHRONOBREAK_RETURN"))[0].amount
    ) == Decimal(175)
    assert len(
        [event for event in scaled.events if event.id.startswith("EKKO_BASIC_ATTACK_")]
    ) > len([event for event in baseline.events if event.id.startswith("EKKO_BASIC_ATTACK_")])
    assert _event(scaled, "EKKO_Q_TIMEWINDER_OUT_2").at_ms == 3600
    assert _event(baseline, "EKKO_Q_TIMEWINDER_OUT_2").at_ms == 7100
    assert _event(scaled, "EKKO_Q_TIMEWINDER_RETURN_2").at_ms == 5000


def test_ekko_reaction_models_q_slow_w_stun_and_r_untargetability() -> None:
    """Expose control and defense without conflating their response rules."""
    ekko = create_default_registry(ROOT).require_cog("Ekko")
    reaction = ekko.build_reaction_plan(_context())

    q_slow = reaction.cast_block_windows[0]
    w_stun = reaction.cast_block_windows[-1]
    invulnerability = reaction.damage_windows[0]
    assert q_slow.control_type is not None
    assert q_slow.control_type.value == "SLOW"
    assert q_slow.blocked_channels == (ActionChannel.MOVEMENT,)
    assert w_stun.control_type.value == "STUN"
    assert w_stun.tenacity_reducible is True
    assert w_stun.source_event_id == "EKKO_W_PARALLEL_CONVERGENCE_DETONATE"
    assert invulnerability.recipient is EntityId.ACTOR
    assert invulnerability.damage_types == (
        DamageType.PHYSICAL,
        DamageType.MAGIC,
        DamageType.TRUE,
    )
    assert invulnerability.multiplier == 0


def test_ekko_role_reversal_and_blind_preserve_ability_channels() -> None:
    """Keep Ekko role-neutral while blind cancels attacks but not Q or R."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Ekko", "Teemo"))
    as_opponent = engine.evaluate(MatchupRequest("Teemo", "Ekko"))

    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    actor_q = next(
        entry
        for entry in as_actor.timeline.log
        if entry.event_id == "EKKO_Q_TIMEWINDER_OUT_1" and entry.operation == "DAMAGE"
    )
    opponent_q = next(
        entry
        for entry in as_opponent.timeline.log
        if entry.event_id == "EKKO_Q_TIMEWINDER_OUT_1" and entry.operation == "DAMAGE"
    )
    assert actor_q.recipient is EntityId.TARGET
    assert opponent_q.recipient is EntityId.ACTOR
    assert actor_q.status == opponent_q.status == "APPLIED"
    assert any(
        entry.event_id.startswith("EKKO_E_PHASE_DIVE_ATTACK_")
        and entry.action_channel is ActionChannel.BASIC_ATTACK
        and entry.status == "CANCELLED"
        for entry in as_opponent.timeline.log
    )
    assert any(
        entry.event_id == "EKKO_R_CHRONOBREAK_RETURN"
        and entry.operation == "DAMAGE"
        and entry.status == "APPLIED"
        for entry in as_opponent.timeline.log
    )


def test_ekko_policy_and_lane_sustain_keep_state_honest() -> None:
    """Accept represented stats while retaining historical-state blockers."""
    ekko = create_default_registry(ROOT).require_cog("Ekko")

    assert (
        ekko.item_candidate_blocker(
            {
                "id": 1,
                "stats": {
                    "AP": {},
                    "ATTACK_SPEED": {},
                    "ABILITY_HASTE": {},
                    "HP": {},
                },
            }
        )
        is None
    )
    assert (
        ekko.item_candidate_blocker({"id": 2, "stats": {"CRITICAL_STRIKE_CHANCE": {}, "MANA": {}}})
        == "EKKO_ITEM_STAT_NOT_MODELED:2:MANA"
    )
    amount, blockers = ekko.lane_sustain_extra_health(
        _context(),
        duration_ms=30_000,
        no_damage_delay_ms=8_000,
    )
    assert amount == 0
    assert blockers == ("EKKO_LANE_R_FOUR_SECOND_HEALTH_AND_POSITION_TRACE_NOT_MODELED",)
    assert ekko.engagement_dash_distance(_context()) == 350
