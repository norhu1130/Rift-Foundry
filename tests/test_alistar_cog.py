"""Focused regressions for the locked Alistar champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES, ActionPlan
from lol_build.cogs.registry import create_default_registry
from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    EntityId,
    HealOutput,
    RemoveStatusOutput,
    StatusOutput,
)

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    alistar_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a role-neutral level-13 Alistar-versus-Teemo context.

    :param alistar_is_actor: Place Alistar on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Alistar.
    :return: Role-bound deterministic benchmark context.
    """
    registry = create_default_registry(ROOT)
    alistar = registry.require_cog("Alistar")
    teemo = registry.require_cog("Teemo")
    return ParticipantContext(
        EntityId.ACTOR if alistar_is_actor else EntityId.TARGET,
        EntityId.TARGET if alistar_is_actor else EntityId.ACTOR,
        alistar.snapshot(level=13, item_stats=item_stats),
        teemo.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan: ActionPlan, event_id: str) -> ActionEvent:
    """Resolve one event by its stable Alistar identifier.

    :param plan: Alistar action plan containing the expected event.
    :param event_id: Exact identifier of the requested event.
    :return: Matching immutable action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def _events_starting(plan: ActionPlan, prefix: str) -> tuple[ActionEvent, ...]:
    """Select events whose identifier begins with one prefix.

    :param plan: Alistar action plan to search.
    :param prefix: Champion-scoped event identifier prefix.
    :return: Chronological matching events.
    """
    return tuple(event for event in plan.events if event.id.startswith(prefix))


def test_alistar_declares_modeled_capabilities_and_locked_evidence() -> None:
    """Distinguish Alistar from a scaffold and retain all source forms."""
    alistar = create_default_registry(ROOT).require_cog("Alistar")

    assert alistar.maturity is CogMaturity.MODELED_UNVERIFIED
    assert alistar.capabilities == DUEL_CAPABILITIES
    assert alistar.verification_blockers() == ("COG_MODEL_UNVERIFIED:Alistar",)
    assert alistar.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Alistar.json",
        "data/raw/16.17.1/communitydragon/champions/12.json",
        "data/raw/16.17.1/communitydragon/champions/alistar.bin.json",
    )
    assert all((ROOT / reference).is_file() for reference in alistar.evidence_refs)


def test_alistar_rotation_is_deterministic_and_uses_locked_formulas() -> None:
    """Anchor Q5/W5/E1/R2 and empowered-attack values to locked data."""
    alistar = create_default_registry(ROOT).require_cog("Alistar")
    context = _context(item_stats={"AP": Decimal(100), "AD": Decimal(40)})

    first = alistar.build_action_plan(context)
    repeated = alistar.build_action_plan(context)
    headbutt = _event(first, "ALISTAR_W_HEADBUTT_1")
    pulverize = _event(first, "ALISTAR_Q_PULVERIZE_1")
    pulses = _events_starting(first, "ALISTAR_E_TRAMPLE_1_PULSE_")
    empowered = next(event for event in first.events if "E_EMPOWERED_ATTACK" in event.id)
    ultimate = _event(first, "ALISTAR_R_UNBREAKABLE_WILL")

    assert first == repeated
    assert first.model_id == "alistar_q5_w5_e1_r2_level13_wq_fixture_v1"
    assert headbutt.outputs[0].amount == 375
    assert pulverize.outputs[0].amount == 300
    assert len(pulses) == 10
    assert sum((event.outputs[0].amount for event in pulses), Decimal(0)) == 150
    assert empowered.outputs[0].amount == context.snapshot.attack_damage
    assert empowered.outputs[1].amount == 200
    assert isinstance(empowered.outputs[2], StatusOutput)
    assert isinstance(ultimate.outputs[0], RemoveStatusOutput)
    assert ultimate.outputs[0].group == "CROWD_CONTROL_EXCEPT_AIRBORNE_AND_SUPPRESSION"
    assert "ALISTAR_PASSIVE_NEARBY_UNIT_DEATH_CHARGES_NOT_MODELED" in first.blockers


def test_alistar_ap_attack_speed_and_haste_change_represented_outputs() -> None:
    """Prove AP, attack speed, and haste alter their modeled channels."""
    alistar = create_default_registry(ROOT).require_cog("Alistar")
    baseline = alistar.build_action_plan(_context())
    powered = alistar.build_action_plan(_context(item_stats={"AP": Decimal(100)}))
    rapid = alistar.build_action_plan(
        _context(item_stats={"ATTACK_SPEED": Decimal("0.50")})
    )
    hasted_context = _context(
        item_stats={"ABILITY_HASTE": Decimal(200), "HP": Decimal(500)}
    )
    hasted = alistar.build_action_plan(hasted_context)

    assert (
        _event(powered, "ALISTAR_W_HEADBUTT_1").outputs[0].amount
        - _event(baseline, "ALISTAR_W_HEADBUTT_1").outputs[0].amount
        == 100
    )
    assert (
        _event(powered, "ALISTAR_Q_PULVERIZE_1").outputs[0].amount
        - _event(baseline, "ALISTAR_Q_PULVERIZE_1").outputs[0].amount
        == 80
    )
    assert len(_events_starting(rapid, "ALISTAR_BASIC_ATTACK_")) > len(
        _events_starting(baseline, "ALISTAR_BASIC_ATTACK_")
    )
    assert len(_events_starting(hasted, "ALISTAR_W_HEADBUTT_")) == 3
    passive_heals = tuple(
        output
        for event in hasted.events
        for output in event.outputs
        if isinstance(output, HealOutput)
    )
    assert passive_heals == (
        HealOutput(EntityId.ACTOR, Decimal("0.05") * hasted_context.snapshot.max_hp),
    )


def test_alistar_reaction_models_r_reduction_and_distinct_control() -> None:
    """Expose R defense, airborne displacement, and reducible E stun."""
    alistar = create_default_registry(ROOT).require_cog("Alistar")
    reaction = alistar.build_reaction_plan(_context())

    reduction = reaction.damage_windows[0]
    headbutt, pulverize, empowered = reaction.cast_block_windows
    assert reduction.recipient is EntityId.ACTOR
    assert reduction.damage_types == (DamageType.PHYSICAL, DamageType.MAGIC)
    assert reduction.multiplier == Decimal("0.35")
    assert (reduction.start_ms, reduction.end_ms) == (0, 7000)
    assert headbutt.control_type is pulverize.control_type is ControlType.AIRBORNE
    assert headbutt.tenacity_reducible is pulverize.tenacity_reducible is False
    assert empowered.control_type is ControlType.STUN
    assert empowered.tenacity_reducible is True
    assert empowered.source_event_id is not None
    assert "E_EMPOWERED_ATTACK" in empowered.source_event_id


def test_alistar_role_reversal_and_teemo_blind_preserve_ability_channels() -> None:
    """Keep Alistar role-neutral while blind cancels only attack events."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Alistar", "Teemo"))
    as_opponent = engine.evaluate(MatchupRequest("Teemo", "Alistar"))

    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    assert any(
        entry.event_id.startswith("ALISTAR_BASIC_ATTACK_")
        and entry.action_channel is ActionChannel.BASIC_ATTACK
        and entry.status == "CANCELLED"
        for entry in as_actor.timeline.log
    )
    for event_id in ("ALISTAR_W_HEADBUTT_1", "ALISTAR_Q_PULVERIZE_1"):
        assert any(
            entry.event_id == event_id
            and entry.operation == "DAMAGE"
            and entry.status == "APPLIED"
            for entry in as_actor.timeline.log
        )
    reversed_q = next(
        entry
        for entry in as_opponent.timeline.log
        if entry.event_id == "ALISTAR_Q_PULVERIZE_1" and entry.operation == "DAMAGE"
    )
    assert reversed_q.recipient is EntityId.ACTOR


def test_alistar_item_policy_and_lane_sustain_remain_state_honest() -> None:
    """Accept represented stats while exposing absent passive charge inputs."""
    alistar = create_default_registry(ROOT).require_cog("Alistar")

    assert alistar.item_candidate_blocker(
        {
            "id": 1,
            "stats": {
                "AD": {},
                "AP": {},
                "ATTACK_SPEED": {},
                "ABILITY_HASTE": {},
                "HP": {},
                "ARMOR": {},
                "MAGIC_RESISTANCE": {},
            },
        }
    ) is None
    assert alistar.item_candidate_blocker(
        {"id": 2, "stats": {"HEAL_SHIELD_POWER": {}, "MANA": {}, "OMNIVAMP": {}}}
    ) == "ALISTAR_ITEM_STAT_NOT_MODELED:2:HEAL_SHIELD_POWER,MANA,OMNIVAMP"
    amount, blockers = alistar.lane_sustain_extra_health(
        _context(),
        duration_ms=30_000,
        no_damage_delay_ms=8_000,
    )
    assert amount == 0
    assert blockers == (
        "ALISTAR_LANE_NEARBY_UNIT_DEATH_SCHEDULE_NOT_MODELED",
        "ALISTAR_LANE_CHAMPION_CONTROL_SCHEDULE_NOT_MODELED",
    )
