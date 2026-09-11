"""Focused regression coverage for the locked Annie champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext, create_default_registry
from lol_build.cogs.base import DUEL_CAPABILITIES, CogCapability
from lol_build.core.timeline import DamageOutput, EntityId, ShieldOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(*, annie_is_actor: bool = True, item_stats=None) -> ParticipantContext:
    """Build a level-13 Annie versus Garen direct-Cog context.

    :param annie_is_actor: Place Annie on the actor side when true.
    :param item_stats: Optional aggregate stats applied to Annie.
    :return: Role-bound context for deterministic unit tests.
    """
    registry = create_default_registry(ROOT)
    annie = registry.require_cog("Annie")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if annie_is_actor else EntityId.TARGET,
        EntityId.TARGET if annie_is_actor else EntityId.ACTOR,
        annie.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def test_annie_declares_modeled_capabilities_and_three_locked_sources() -> None:
    """Distinguish Annie's modeled Cog from a generated scaffold."""
    annie = create_default_registry(ROOT).require_cog("Annie")

    assert annie.maturity is CogMaturity.MODELED_UNVERIFIED
    assert annie.capabilities == DUEL_CAPABILITIES | {CogCapability.MULTI_TARGET}
    assert annie.verification_blockers() == ("COG_MODEL_UNVERIFIED:Annie",)
    assert annie.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Annie.json",
        "data/raw/16.17.1/communitydragon/champions/1.json",
        "data/raw/16.17.1/communitydragon/champions/annie.bin.json",
    )
    assert all((ROOT / path).is_file() for path in annie.evidence_refs)


def test_annie_rotation_is_deterministic_and_uses_locked_rank_values() -> None:
    """Anchor Q5/W5/E1/R2 outputs and the second Pyromania cycle."""
    annie = create_default_registry(ROOT).require_cog("Annie")
    context = _context(item_stats={"AP": Decimal(100)})

    first = annie.build_action_plan(context)
    second = annie.build_action_plan(context)

    assert first == second
    assert first.model_id == "annie_q5_w5_e1_r2_level13_synthetic_v1"
    expected = {
        "ANNIE_R_SUMMON_TIBBERS": Decimal(350),
        "ANNIE_Q_DISINTEGRATE_1": Decimal(340),
        "ANNIE_W_INCINERATE_1": Decimal(310),
        "ANNIE_Q_DISINTEGRATE_2": Decimal(340),
        "ANNIE_W_INCINERATE_2_PYROMANIA": Decimal(310),
    }
    for event_id, amount in expected.items():
        event = next(event for event in first.events if event.id == event_id)
        output = event.outputs[0]
        assert isinstance(output, DamageOutput)
        assert output.amount == amount
    shield_event = next(event for event in first.events if event.id == "ANNIE_E_MOLTEN_SHIELD")
    shield = shield_event.outputs[0]
    assert isinstance(shield, ShieldOutput)
    assert shield.amount == 100
    assert shield.duration_ms == 3000
    assert "ANNIE_E_REFLECT_TRIGGER_NOT_MODELED" in first.blockers
    assert "ANNIE_TIBBERS_SUMMON_AI_NOT_MODELED" in first.blockers


def test_annie_ap_changes_spells_and_shield_but_not_basic_attacks() -> None:
    """Keep AP sensitivity confined to the locked spell formula channels."""
    annie = create_default_registry(ROOT).require_cog("Annie")
    baseline = annie.build_action_plan(_context())
    powered = annie.build_action_plan(_context(item_stats={"AP": Decimal(100)}))

    baseline_q = next(event for event in baseline.events if event.id == "ANNIE_Q_DISINTEGRATE_1")
    powered_q = next(event for event in powered.events if event.id == "ANNIE_Q_DISINTEGRATE_1")
    baseline_attack = next(event for event in baseline.events if event.id == "ANNIE_BASIC_ATTACK_1")
    powered_attack = next(event for event in powered.events if event.id == "ANNIE_BASIC_ATTACK_1")
    assert powered_q.outputs[0].amount - baseline_q.outputs[0].amount == 80
    assert powered_attack.outputs[0].amount == baseline_attack.outputs[0].amount


def test_annie_pyromania_is_reducible_and_follows_role_reversal() -> None:
    """Keep the same stun contract when Annie occupies either participant role."""
    annie = create_default_registry(ROOT).require_cog("Annie")
    reaction = annie.build_reaction_plan(_context())

    assert tuple(window.end_ms - window.start_ms for window in reaction.cast_block_windows) == (
        1750,
        350,
    )
    assert all(window.tenacity_reducible for window in reaction.cast_block_windows)
    assert all(window.control_type.value == "STUN" for window in reaction.cast_block_windows)

    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Annie", "Garen"))
    as_target = engine.evaluate(MatchupRequest("Garen", "Annie"))
    assert as_actor.actor_action_model == as_target.opponent_action_model
    assert as_actor.actor_reaction_model == as_target.opponent_reaction_model
    actor_r = next(
        entry
        for entry in as_actor.timeline.log
        if entry.event_id == "ANNIE_R_SUMMON_TIBBERS" and entry.operation == "DAMAGE"
    )
    target_r = next(
        entry
        for entry in as_target.timeline.log
        if entry.event_id == "ANNIE_R_SUMMON_TIBBERS" and entry.operation == "DAMAGE"
    )
    assert actor_r.recipient is EntityId.TARGET
    assert target_r.recipient is EntityId.ACTOR


def test_teemo_blind_cancels_annie_attacks_without_cancelling_abilities() -> None:
    """Verify blind respects action channels in a real two-Cog simulation."""
    evaluation = MatchupEngine(ROOT).evaluate(MatchupRequest("Annie", "Teemo"))

    first_attack = next(
        entry for entry in evaluation.timeline.log if entry.event_id == "ANNIE_BASIC_ATTACK_1"
    )
    first_q = next(
        entry
        for entry in evaluation.timeline.log
        if entry.event_id == "ANNIE_Q_DISINTEGRATE_1" and entry.operation == "DAMAGE"
    )
    assert first_attack.status == "CANCELLED"
    assert first_q.status == "APPLIED"


def test_annie_item_policy_rejects_only_unrepresented_stat_channels() -> None:
    """Allow AP while rejecting fixed-policy haste and resource stats."""
    annie = create_default_registry(ROOT).require_cog("Annie")

    assert annie.item_candidate_blocker({"id": 1, "stats": {"AP": {}}}) is None
    assert (
        annie.item_candidate_blocker({"id": 2, "stats": {"ABILITY_HASTE": {}, "MANA": {}}})
        == "ANNIE_ITEM_STAT_NOT_MODELED:2:ABILITY_HASTE,MANA"
    )
