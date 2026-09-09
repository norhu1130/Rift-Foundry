"""Focused regression coverage for the locked Syndra champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import ActionChannel, DamageOutput, EntityId, StatusOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(*, syndra_is_actor: bool = True, item_stats=None) -> ParticipantContext:
    """Build a level-13 Syndra versus Garen direct-Cog context.

    :param syndra_is_actor: Place Syndra on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Syndra.
    :return: Role-bound context for deterministic Syndra tests.
    """
    registry = create_default_registry(ROOT)
    syndra = registry.require_cog("Syndra")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if syndra_is_actor else EntityId.TARGET,
        EntityId.TARGET if syndra_is_actor else EntityId.ACTOR,
        syndra.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id):
    """Find one stable event in a Syndra action plan.

    :param plan: Action plan containing the requested event.
    :param event_id: Champion-scoped action identifier.
    :return: Matching action event.
    """
    return next(candidate for candidate in plan.events if candidate.id == event_id)


def test_syndra_declares_modeled_capabilities_and_three_locked_sources() -> None:
    """Distinguish Syndra's modeled Cog from its former empty scaffold."""
    syndra = create_default_registry(ROOT).require_cog("Syndra")

    assert syndra.maturity is CogMaturity.MODELED_UNVERIFIED
    assert syndra.capabilities == DUEL_CAPABILITIES
    assert syndra.verification_blockers() == ("COG_MODEL_UNVERIFIED:Syndra",)
    assert len(syndra.evidence_refs) == 3
    assert all((ROOT / path).is_file() for path in syndra.evidence_refs)


def test_syndra_rotation_is_deterministic_and_tracks_five_spheres() -> None:
    """Anchor Q5/E5/W1/R2 values and the fixed five-sphere ultimate."""
    syndra = create_default_registry(ROOT).require_cog("Syndra")
    context = _context(item_stats={"AP": Decimal(100)})
    first = syndra.build_action_plan(context)

    assert first == syndra.build_action_plan(context)
    assert first.model_id == "syndra_q5_e5_w1_r2_level13_five_sphere_v1"
    q_events = [event for event in first.events if event.id.startswith("SYNDRA_Q_")]
    assert [event.at_ms for event in q_events] == [100, 1250, 6000]
    assert all(event.outputs[0].amount == 300 for event in q_events)

    e = _event(first, "SYNDRA_E_SCATTER_THE_WEAK_SPHERE_STUN")
    assert e.outputs[0].amount == 260
    assert isinstance(e.outputs[1], StatusOutput)
    assert (e.outputs[1].status, e.outputs[1].duration_ms) == ("CC_STUN", 1250)

    w = _event(first, "SYNDRA_W_FORCE_OF_WILL_THROW")
    assert tuple(output.amount for output in w.outputs[:2]) == (
        Decimal(135),
        Decimal("18.9000"),
    )
    assert isinstance(w.outputs[2], StatusOutput)
    assert w.outputs[2].duration_ms == 1500
    assert w.outputs[2].magnitude == Decimal("0.25")

    ultimate = _event(first, "SYNDRA_R_UNLEASHED_POWER_FIVE_SPHERES")
    assert isinstance(ultimate.outputs[0], DamageOutput)
    assert ultimate.outputs[0].amount == 700
    assert "SYNDRA_R_FIVE_SPHERE_PROXIMITY_ASSUMED" in first.blockers
    assert "SYNDRA_R_EXECUTE_THRESHOLD_NOT_MODELED" in first.blockers


def test_syndra_ap_reaches_every_modeled_spell_damage_channel() -> None:
    """Prove AP changes Q, W, E, R, and upgraded W true damage."""
    syndra = create_default_registry(ROOT).require_cog("Syndra")
    baseline = syndra.build_action_plan(_context())
    powered = syndra.build_action_plan(_context(item_stats={"AP": Decimal(100)}))

    expected_magic_deltas = {
        "SYNDRA_Q_DARK_SPHERE_1": Decimal(70),
        "SYNDRA_E_SCATTER_THE_WEAK_SPHERE_STUN": Decimal(60),
        "SYNDRA_W_FORCE_OF_WILL_THROW": Decimal(65),
        "SYNDRA_R_UNLEASHED_POWER_FIVE_SPHERES": Decimal(100),
    }
    for event_id, expected in expected_magic_deltas.items():
        assert (
            _event(powered, event_id).outputs[0].amount
            - _event(baseline, event_id).outputs[0].amount
            == expected
        )
    assert (
        _event(powered, "SYNDRA_W_FORCE_OF_WILL_THROW").outputs[1].amount
        > _event(baseline, "SYNDRA_W_FORCE_OF_WILL_THROW").outputs[1].amount
    )


def test_syndra_stun_slow_and_models_follow_role_reversal() -> None:
    """Keep Syndra's outgoing damage and control role-neutral."""
    syndra = create_default_registry(ROOT).require_cog("Syndra")
    stun, slow = syndra.build_reaction_plan(_context()).cast_block_windows

    assert (stun.control_type.value, stun.end_ms - stun.start_ms) == ("STUN", 1250)
    assert stun.blocked_channels == (
        ActionChannel.BASIC_ATTACK,
        ActionChannel.ABILITY,
    )
    assert (slow.control_type.value, slow.end_ms - slow.start_ms) == ("SLOW", 1500)
    assert slow.blocked_channels == (ActionChannel.MOVEMENT,)
    assert stun.tenacity_reducible is slow.tenacity_reducible is True

    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Syndra", "Garen"))
    as_target = engine.evaluate(MatchupRequest("Garen", "Syndra"))
    assert as_actor.actor_action_model == as_target.opponent_action_model
    assert as_actor.actor_reaction_model == as_target.opponent_reaction_model
    actor_q = next(
        entry
        for entry in as_actor.timeline.log
        if entry.event_id == "SYNDRA_Q_DARK_SPHERE_1" and entry.operation == "DAMAGE"
    )
    target_q = next(
        entry
        for entry in as_target.timeline.log
        if entry.event_id == "SYNDRA_Q_DARK_SPHERE_1" and entry.operation == "DAMAGE"
    )
    assert actor_q.recipient is EntityId.TARGET
    assert target_q.recipient is EntityId.ACTOR


def test_teemo_blind_cancels_syndra_attacks_but_not_spells() -> None:
    """Keep Syndra's ability rotation independent from the blinded attack channel."""
    result = MatchupEngine(ROOT).evaluate(MatchupRequest("Syndra", "Teemo"))

    assert any(
        entry.event_id == "SYNDRA_BASIC_ATTACK_1" and entry.status == "CANCELLED"
        for entry in result.timeline.log
    )
    for event_id in (
        "SYNDRA_Q_DARK_SPHERE_1",
        "SYNDRA_E_SCATTER_THE_WEAK_SPHERE_STUN",
        "SYNDRA_W_FORCE_OF_WILL_THROW",
        "SYNDRA_R_UNLEASHED_POWER_FIVE_SPHERES",
    ):
        assert any(
            entry.event_id == event_id
            and entry.operation == "DAMAGE"
            and entry.status == "APPLIED"
            for entry in result.timeline.log
        )


def test_syndra_item_policy_rejects_unrepresented_fixed_rotation_stats() -> None:
    """Allow AP and chassis stats while blocking haste and mana channels."""
    syndra = create_default_registry(ROOT).require_cog("Syndra")

    assert syndra.item_candidate_blocker(
        {"id": 1, "stats": {"AP": {}, "HP": {}, "ATTACK_SPEED": {}}}
    ) is None
    assert syndra.item_candidate_blocker(
        {"id": 2, "stats": {"ABILITY_HASTE": {}, "MANA": {}}}
    ) == "SYNDRA_ITEM_STAT_NOT_MODELED:2:ABILITY_HASTE,MANA"
