"""Focused regression coverage for the locked Orianna champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import (
    ActionChannel,
    EntityId,
    ShieldOutput,
    StatModifierOutput,
    StatusOutput,
)

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    orianna_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a level-13 Orianna versus Garen direct-Cog context.

    :param orianna_is_actor: Place Orianna on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Orianna.
    :return: Role-bound context for deterministic Orianna tests.
    """
    registry = create_default_registry(ROOT)
    orianna = registry.require_cog("Orianna")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if orianna_is_actor else EntityId.TARGET,
        EntityId.TARGET if orianna_is_actor else EntityId.ACTOR,
        orianna.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Find one named action in an Orianna plan.

    :param plan: Action plan containing the expected event.
    :param event_id: Champion-scoped identifier of the requested action.
    :return: Matching immutable action event.
    """
    return next(candidate for candidate in plan.events if candidate.id == event_id)


def test_orianna_declares_modeled_capabilities_and_locked_evidence() -> None:
    """Distinguish Orianna's modeled behavior from its former scaffold."""
    orianna = create_default_registry(ROOT).require_cog("Orianna")

    assert orianna.maturity is CogMaturity.MODELED_UNVERIFIED
    assert orianna.capabilities == DUEL_CAPABILITIES
    assert orianna.verification_blockers() == ("COG_MODEL_UNVERIFIED:Orianna",)
    assert len(orianna.evidence_refs) == 3
    assert all((ROOT / path).is_file() for path in orianna.evidence_refs)


def test_orianna_ball_fixture_rotation_uses_locked_rank_values() -> None:
    """Anchor Q5/W5/E1/R2 formulas, ball ordering, and self effects."""
    orianna = create_default_registry(ROOT).require_cog("Orianna")
    context = _context(item_stats={"AP": Decimal(100)})
    plan = orianna.build_action_plan(context)

    assert plan == orianna.build_action_plan(context)
    assert plan.model_id == "orianna_q5_w5_e1_r2_ball_fixture_v1"
    q = _event(plan, "ORIANNA_Q_COMMAND_ATTACK_TARGET_FIXTURE")
    w = _event(plan, "ORIANNA_W_COMMAND_DISSONANCE_TARGET")
    ultimate = _event(plan, "ORIANNA_R_COMMAND_SHOCKWAVE")
    protect = _event(plan, "ORIANNA_E_COMMAND_PROTECT_RETURN_SELF")
    self_haste = _event(plan, "ORIANNA_W_COMMAND_DISSONANCE_SELF_HASTE")

    assert q.outputs[0].amount == 235
    assert w.outputs[0].amount == 310
    assert isinstance(w.outputs[1], StatusOutput)
    assert (w.outputs[1].status, w.outputs[1].duration_ms) == ("CC_SLOW", 2000)
    assert ultimate.outputs[0].amount == 460
    assert isinstance(ultimate.outputs[1], StatusOutput)
    assert (ultimate.outputs[1].status, ultimate.outputs[1].duration_ms) == (
        "CC_AIRBORNE",
        750,
    )
    assert protect.outputs[0].amount == 90
    assert isinstance(protect.outputs[1], ShieldOutput)
    assert protect.outputs[1].amount == 100
    assert protect.outputs[1].recipient is EntityId.ACTOR
    assert isinstance(self_haste.outputs[0], StatModifierOutput)
    assert self_haste.outputs[0].amount == context.snapshot.move_speed * Decimal("0.40")
    assert "ORIANNA_BALL_POSITION_AND_TRAVEL_CAUSALITY_NOT_MODELED" in plan.blockers
    assert "ORIANNA_MULTI_TARGET_EFFECTS_NOT_MODELED" in plan.blockers


def test_orianna_ap_and_attack_speed_reach_distinct_channels() -> None:
    """Prove AP scales spells and Windup while attack speed adds attacks."""
    orianna = create_default_registry(ROOT).require_cog("Orianna")
    baseline = orianna.build_action_plan(_context())
    powered = orianna.build_action_plan(_context(item_stats={"AP": Decimal(100)}))
    faster = orianna.build_action_plan(_context(item_stats={"ATTACK_SPEED": Decimal("0.50")}))

    expected_spell_deltas = {
        "ORIANNA_Q_COMMAND_ATTACK_TARGET_FIXTURE": Decimal(55),
        "ORIANNA_W_COMMAND_DISSONANCE_TARGET": Decimal(80),
        "ORIANNA_R_COMMAND_SHOCKWAVE": Decimal(110),
        "ORIANNA_E_COMMAND_PROTECT_RETURN_SELF": Decimal(30),
    }
    for event_id, expected in expected_spell_deltas.items():
        assert (
            _event(powered, event_id).outputs[0].amount
            - _event(baseline, event_id).outputs[0].amount
            == expected
        )
    assert (
        _event(powered, "ORIANNA_BASIC_ATTACK_1").outputs[1].amount
        - _event(baseline, "ORIANNA_BASIC_ATTACK_1").outputs[1].amount
        == 15
    )
    assert len(
        [event for event in faster.events if event.id.startswith("ORIANNA_BASIC_ATTACK_")]
    ) > len([event for event in baseline.events if event.id.startswith("ORIANNA_BASIC_ATTACK_")])


def test_orianna_windup_stacks_twice_and_then_caps() -> None:
    """Anchor the passive's locked fifteen-percent two-stack progression."""
    orianna = create_default_registry(ROOT).require_cog("Orianna")
    attacks = [
        event
        for event in orianna.build_action_plan(_context()).events
        if event.id.startswith("ORIANNA_BASIC_ATTACK_")
    ]
    magic = [event.outputs[1].amount for event in attacks]

    assert magic[1] == magic[0] * Decimal("1.15")
    assert magic[2] == magic[0] * Decimal("1.30")
    assert all(amount == magic[2] for amount in magic[2:])


def test_orianna_control_defenses_and_roles_are_symmetric() -> None:
    """Keep displacement, slow, shields, and E defenses attached to Orianna."""
    orianna = create_default_registry(ROOT).require_cog("Orianna")
    reaction = orianna.build_reaction_plan(_context())
    slow, displacement = reaction.cast_block_windows

    assert slow.control_type.value == "SLOW"
    assert slow.tenacity_reducible is True
    assert slow.blocked_channels == (ActionChannel.MOVEMENT,)
    assert displacement.control_type.value == "AIRBORNE"
    assert displacement.tenacity_reducible is False
    assert displacement.blocked_channels == (
        ActionChannel.BASIC_ATTACK,
        ActionChannel.ABILITY,
        ActionChannel.MOVEMENT,
    )
    assert len(reaction.damage_windows) == 2
    assert all(window.recipient is EntityId.ACTOR for window in reaction.damage_windows)
    assert all(window.multiplier < 1 for window in reaction.damage_windows)

    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Orianna", "Nasus"))
    as_target = engine.evaluate(MatchupRequest("Nasus", "Orianna"))
    assert as_actor.actor_action_model == as_target.opponent_action_model
    assert as_actor.actor_reaction_model == as_target.opponent_reaction_model
    actor_shield = next(
        entry
        for entry in as_actor.timeline.log
        if entry.event_id == "ORIANNA_E_COMMAND_PROTECT_RETURN_SELF" and entry.operation == "SHIELD"
    )
    target_shield = next(
        entry
        for entry in as_target.timeline.log
        if entry.event_id == "ORIANNA_E_COMMAND_PROTECT_RETURN_SELF" and entry.operation == "SHIELD"
    )
    assert actor_shield.recipient is EntityId.ACTOR
    assert target_shield.recipient is EntityId.TARGET


def test_teemo_blind_cancels_orianna_attacks_but_not_ball_spells() -> None:
    """Keep ball abilities independent from the blinded attack channel."""
    result = MatchupEngine(ROOT).evaluate(MatchupRequest("Orianna", "Teemo"))

    assert any(
        entry.event_id == "ORIANNA_BASIC_ATTACK_1" and entry.status == "CANCELLED"
        for entry in result.timeline.log
    )
    for event_id in (
        "ORIANNA_Q_COMMAND_ATTACK_TARGET_FIXTURE",
        "ORIANNA_W_COMMAND_DISSONANCE_TARGET",
        "ORIANNA_R_COMMAND_SHOCKWAVE",
        "ORIANNA_E_COMMAND_PROTECT_RETURN_SELF",
    ):
        assert any(
            entry.event_id == event_id and entry.operation == "DAMAGE" and entry.status == "APPLIED"
            for entry in result.timeline.log
        )


def test_orianna_item_policy_rejects_unrepresented_rotation_stats() -> None:
    """Allow represented channels while blocking fixed-policy omissions."""
    orianna = create_default_registry(ROOT).require_cog("Orianna")

    assert (
        orianna.item_candidate_blocker({"id": 1, "stats": {"AP": {}, "HP": {}, "ATTACK_SPEED": {}}})
        is None
    )
    assert (
        orianna.item_candidate_blocker({"id": 2, "stats": {"ABILITY_HASTE": {}, "MANA": {}}})
        == "ORIANNA_ITEM_STAT_NOT_MODELED:2:ABILITY_HASTE,MANA"
    )
