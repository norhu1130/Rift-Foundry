"""Focused regression coverage for the locked Diana champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import ActionChannel, EntityId, ShieldOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    diana_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a level-13 Diana versus Garen direct-Cog context.

    :param diana_is_actor: Place Diana on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Diana.
    :return: Role-bound context for deterministic Diana tests.
    """
    registry = create_default_registry(ROOT)
    diana = registry.require_cog("Diana")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if diana_is_actor else EntityId.TARGET,
        EntityId.TARGET if diana_is_actor else EntityId.ACTOR,
        diana.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Find one named event in a Diana action plan.

    :param plan: Action plan containing the expected event.
    :param event_id: Champion-scoped identifier of the requested action.
    :return: Matching immutable action event.
    """
    return next(candidate for candidate in plan.events if candidate.id == event_id)


def _attacks(plan):
    """Collect Diana basic attacks from an action plan.

    :param plan: Diana action plan containing zero or more attacks.
    :return: Basic-attack events in chronological order.
    """
    return [event for event in plan.events if event.id.startswith("DIANA_BASIC_ATTACK_")]


def test_diana_declares_modeled_capabilities_and_locked_evidence() -> None:
    """Distinguish Diana's modeled behavior from its former scaffold."""
    diana = create_default_registry(ROOT).require_cog("Diana")

    assert diana.maturity is CogMaturity.MODELED_UNVERIFIED
    assert diana.capabilities == DUEL_CAPABILITIES
    assert diana.verification_blockers() == ("COG_MODEL_UNVERIFIED:Diana",)
    assert len(diana.evidence_refs) == 3
    assert all((ROOT / path).is_file() for path in diana.evidence_refs)


def test_diana_rotation_anchors_moonlight_reset_orbs_and_moonfall() -> None:
    """Anchor Q5/W5/E1/R2 formulas and the deterministic reset policy."""
    diana = create_default_registry(ROOT).require_cog("Diana")
    context = _context(item_stats={"AP": Decimal(100), "HP": Decimal(200)})
    plan = diana.build_action_plan(context)

    assert plan == diana.build_action_plan(context)
    assert plan.model_id == "diana_q5_w5_e1_r2_level13_moonlight_reset_v1"
    assert _event(plan, "DIANA_Q_CRESCENT_STRIKE_1").outputs[0].amount == 280
    assert _event(plan, "DIANA_E_LUNAR_RUSH_MOONLIGHT").outputs[0].amount == 110
    assert _event(plan, "DIANA_E_LUNAR_RUSH_RESET").outputs[0].amount == 110

    initial_shield = _event(plan, "DIANA_W_PALE_CASCADE_SHIELD").outputs[0]
    assert isinstance(initial_shield, ShieldOutput)
    assert initial_shield.amount == 157
    orbs = _event(plan, "DIANA_W_THREE_ORBS_AND_RESHIELD")
    assert [output.amount for output in orbs.outputs[:3]] == [86, 86, 86]
    assert isinstance(orbs.outputs[3], ShieldOutput)
    assert orbs.outputs[3].amount == 157

    pull = _event(plan, "DIANA_R_MOONFALL_PULL")
    assert [output.status for output in pull.outputs] == ["CC_AIRBORNE", "CC_SLOW"]
    assert _event(plan, "DIANA_R_MOONFALL_SINGLE_TARGET_DAMAGE").outputs[0].amount == 360
    assert "DIANA_R_MULTI_TARGET_AMPLIFICATION_NOT_MODELED" in plan.blockers
    assert "DIANA_POSITION_AND_COLLISION_NOT_MODELED" in plan.blockers


def test_diana_passive_cleave_and_attack_speed_are_modeled() -> None:
    """Apply Moonsilver magic damage to each third empowered attack."""
    diana = create_default_registry(ROOT).require_cog("Diana")
    plan = diana.build_action_plan(_context(item_stats={"AP": Decimal(100)}))
    attacks = _attacks(plan)

    assert len(attacks) >= 6
    assert [len(event.outputs) for event in attacks[:6]] == [1, 1, 2, 1, 1, 2]
    assert attacks[2].outputs[1].amount == 175
    assert attacks[5].outputs[1].amount == 175


def test_diana_ap_attack_speed_and_haste_reach_distinct_channels() -> None:
    """Prove AP, attack speed, and haste affect represented mechanics."""
    diana = create_default_registry(ROOT).require_cog("Diana")
    baseline = diana.build_action_plan(_context())
    powered = diana.build_action_plan(_context(item_stats={"AP": Decimal(100)}))
    faster = diana.build_action_plan(_context(item_stats={"ATTACK_SPEED": Decimal("0.50")}))
    hasted = diana.build_action_plan(_context(item_stats={"ABILITY_HASTE": Decimal(100)}))

    expected_ap_deltas = {
        "DIANA_Q_CRESCENT_STRIKE_1": Decimal(70),
        "DIANA_E_LUNAR_RUSH_MOONLIGHT": Decimal(60),
        "DIANA_R_MOONFALL_SINGLE_TARGET_DAMAGE": Decimal(60),
    }
    for event_id, expected in expected_ap_deltas.items():
        assert (
            _event(powered, event_id).outputs[0].amount
            - _event(baseline, event_id).outputs[0].amount
            == expected
        )
    assert len(_attacks(faster)) > len(_attacks(baseline))
    assert [
        event.at_ms for event in hasted.events if event.id.startswith("DIANA_Q_CRESCENT_STRIKE_")
    ] == [100, 3100, 6100]
    assert (
        len([event for event in baseline.events if event.id.startswith("DIANA_Q_CRESCENT_STRIKE_")])
        == 2
    )


def test_diana_moonfall_control_and_roles_are_symmetric() -> None:
    """Keep Moonfall's non-tenacity pull and reducible slow role-neutral."""
    diana = create_default_registry(ROOT).require_cog("Diana")
    pull, slow = diana.build_reaction_plan(_context()).cast_block_windows

    assert pull.control_type.value == "AIRBORNE"
    assert pull.tenacity_reducible is False
    assert pull.blocked_channels == (
        ActionChannel.BASIC_ATTACK,
        ActionChannel.ABILITY,
        ActionChannel.MOVEMENT,
    )
    assert slow.control_type.value == "SLOW"
    assert slow.tenacity_reducible is True
    assert slow.blocked_channels == (ActionChannel.MOVEMENT,)
    assert diana.engagement_dash_distance(_context()) == 825

    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Diana", "Garen"))
    as_target = engine.evaluate(MatchupRequest("Garen", "Diana"))
    assert as_actor.actor_action_model == as_target.opponent_action_model
    assert as_actor.actor_reaction_model == as_target.opponent_reaction_model
    actor_damage = next(
        entry
        for entry in as_actor.timeline.log
        if entry.event_id == "DIANA_Q_CRESCENT_STRIKE_1" and entry.operation == "DAMAGE"
    )
    target_damage = next(
        entry
        for entry in as_target.timeline.log
        if entry.event_id == "DIANA_Q_CRESCENT_STRIKE_1" and entry.operation == "DAMAGE"
    )
    assert actor_damage.recipient is EntityId.TARGET
    assert target_damage.recipient is EntityId.ACTOR


def test_teemo_blind_cancels_diana_attacks_but_not_abilities() -> None:
    """Keep Diana's spell sequence independent from the blinded attack channel."""
    result = MatchupEngine(ROOT).evaluate(MatchupRequest("Diana", "Teemo"))

    assert any(
        entry.event_id == "DIANA_BASIC_ATTACK_1" and entry.status == "CANCELLED"
        for entry in result.timeline.log
    )
    for event_id in (
        "DIANA_Q_CRESCENT_STRIKE_1",
        "DIANA_E_LUNAR_RUSH_MOONLIGHT",
        "DIANA_W_THREE_ORBS_AND_RESHIELD",
        "DIANA_R_MOONFALL_SINGLE_TARGET_DAMAGE",
    ):
        assert any(
            entry.event_id == event_id and entry.operation == "DAMAGE" and entry.status == "APPLIED"
            for entry in result.timeline.log
        )


def test_diana_item_policy_accepts_haste_and_rejects_unmodeled_stats() -> None:
    """Allow represented rotation stats while blocking resource and sustain gaps."""
    diana = create_default_registry(ROOT).require_cog("Diana")

    assert (
        diana.item_candidate_blocker(
            {
                "id": 1,
                "stats": {
                    "AP": {},
                    "HP": {},
                    "ATTACK_SPEED": {},
                    "ABILITY_HASTE": {},
                },
            }
        )
        is None
    )
    assert (
        diana.item_candidate_blocker({"id": 2, "stats": {"HEAL_SHIELD_POWER": {}, "MANA": {}}})
        == "DIANA_ITEM_STAT_NOT_MODELED:2:HEAL_SHIELD_POWER,MANA"
    )
