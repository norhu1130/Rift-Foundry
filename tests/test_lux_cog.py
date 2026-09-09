"""Focused regression coverage for the locked Lux champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import (
    ActionChannel,
    DamageOutput,
    EntityId,
    ShieldOutput,
    StatusOutput,
)

ROOT = Path(__file__).resolve().parents[1]


def _context(*, lux_is_actor: bool = True, item_stats=None) -> ParticipantContext:
    """Build a level-13 Lux versus Garen direct-Cog context.

    :param lux_is_actor: Place Lux on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Lux.
    :return: Role-bound context for deterministic Lux tests.
    """
    registry = create_default_registry(ROOT)
    lux = registry.require_cog("Lux")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if lux_is_actor else EntityId.TARGET,
        EntityId.TARGET if lux_is_actor else EntityId.ACTOR,
        lux.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def test_lux_declares_modeled_capabilities_and_three_locked_sources() -> None:
    """Distinguish Lux's modeled Cog from a generated scaffold."""
    lux = create_default_registry(ROOT).require_cog("Lux")

    assert lux.maturity is CogMaturity.MODELED_UNVERIFIED
    assert lux.capabilities == DUEL_CAPABILITIES
    assert lux.verification_blockers() == ("COG_MODEL_UNVERIFIED:Lux",)
    assert lux.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Lux.json",
        "data/raw/16.17.1/communitydragon/champions/99.json",
        "data/raw/16.17.1/communitydragon/champions/lux.bin.json",
    )
    assert all((ROOT / path).is_file() for path in lux.evidence_refs)


def test_lux_rotation_is_deterministic_and_uses_locked_rank_values() -> None:
    """Anchor E5/Q5/W1/R2 and level-13 Illumination formulas."""
    lux = create_default_registry(ROOT).require_cog("Lux")
    context = _context(item_stats={"AP": Decimal(100)})

    first = lux.build_action_plan(context)
    second = lux.build_action_plan(context)
    q = next(event for event in first.events if event.id == "LUX_Q_LIGHT_BINDING")
    e = next(
        event
        for event in first.events
        if event.id == "LUX_E_LUCENT_SINGULARITY_DETONATE"
    )
    r = next(event for event in first.events if event.id == "LUX_R_FINAL_SPARK")
    w = next(
        event
        for event in first.events
        if event.id == "LUX_W_PRISMATIC_BARRIER_OUTBOUND_SELF"
    )
    passive_attack = next(
        event
        for event in first.events
        if event.id == "LUX_PASSIVE_ILLUMINATION_Q_ATTACK"
    )

    assert first == second
    assert first.model_id == "lux_e5_q5_w1_r2_level13_locked_v1"
    assert isinstance(q.outputs[0], DamageOutput)
    assert q.outputs[0].amount == Decimal(315)
    assert isinstance(q.outputs[1], StatusOutput)
    assert q.outputs[1].status == "CC_ROOT"
    assert q.outputs[1].duration_ms == 2000
    assert e.outputs[0].amount == Decimal(345)
    assert tuple(output.amount for output in r.outputs) == (Decimal(185), Decimal(520))
    assert passive_attack.outputs[1].amount == Decimal(185)
    assert isinstance(w.outputs[0], ShieldOutput)
    assert w.outputs[0].amount == Decimal(80)
    assert w.outputs[0].duration_ms == 2500
    returning_w = next(
        event
        for event in first.events
        if event.id == "LUX_W_PRISMATIC_BARRIER_RETURN_SELF"
    )
    assert isinstance(returning_w.outputs[0], ShieldOutput)
    assert returning_w.outputs[0].amount == Decimal(80)
    assert "LUX_ILLUMINATION_MARK_STATE_NOT_CAUSALLY_MODELED" in first.blockers
    assert "LUX_W_RETURN_TIMING_UNVERIFIED" in first.blockers
    assert "LUX_W_ALLY_GEOMETRY_NOT_MODELED" in first.blockers


def test_lux_ap_changes_spells_shield_and_illumination() -> None:
    """Prove AP reaches every modeled Lux scaling channel."""
    lux = create_default_registry(ROOT).require_cog("Lux")
    baseline = lux.build_action_plan(_context())
    powered = lux.build_action_plan(_context(item_stats={"AP": Decimal(100)}))

    def event(plan, event_id):
        """Resolve one named action from a Lux plan.

        :param plan: Action plan containing the expected event.
        :param event_id: Stable identifier of the requested event.
        :return: Matching action event.
        """
        return next(candidate for candidate in plan.events if candidate.id == event_id)

    assert (
        event(powered, "LUX_Q_LIGHT_BINDING").outputs[0].amount
        - event(baseline, "LUX_Q_LIGHT_BINDING").outputs[0].amount
        == 75
    )
    assert (
        event(powered, "LUX_E_LUCENT_SINGULARITY_DETONATE").outputs[0].amount
        - event(baseline, "LUX_E_LUCENT_SINGULARITY_DETONATE").outputs[0].amount
        == 80
    )
    assert (
        event(powered, "LUX_R_FINAL_SPARK").outputs[1].amount
        - event(baseline, "LUX_R_FINAL_SPARK").outputs[1].amount
        == 120
    )
    assert (
        event(powered, "LUX_PASSIVE_ILLUMINATION_Q_ATTACK").outputs[1].amount
        - event(baseline, "LUX_PASSIVE_ILLUMINATION_Q_ATTACK").outputs[1].amount
        == 35
    )
    assert (
        event(powered, "LUX_W_PRISMATIC_BARRIER_OUTBOUND_SELF").outputs[0].amount
        - event(baseline, "LUX_W_PRISMATIC_BARRIER_OUTBOUND_SELF").outputs[0].amount
        == 40
    )


def test_lux_root_slow_and_outputs_follow_role_reversal() -> None:
    """Keep Lux's movement control and outputs attached to either role."""
    lux = create_default_registry(ROOT).require_cog("Lux")
    reaction = lux.build_reaction_plan(_context())

    root, slow = reaction.cast_block_windows
    assert root.control_type.value == "ROOT"
    assert root.end_ms - root.start_ms == 2000
    assert slow.control_type.value == "SLOW"
    assert slow.end_ms - slow.start_ms == 1400
    assert root.blocked_channels == slow.blocked_channels == (ActionChannel.MOVEMENT,)
    assert root.tenacity_reducible is True
    assert slow.tenacity_reducible is True

    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Lux", "Garen"))
    as_opponent = engine.evaluate(MatchupRequest("Garen", "Lux"))
    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    actor_shield = next(
        entry
        for entry in as_actor.timeline.log
        if entry.event_id == "LUX_W_PRISMATIC_BARRIER_OUTBOUND_SELF"
        and entry.operation == "SHIELD"
    )
    opponent_shield = next(
        entry
        for entry in as_opponent.timeline.log
        if entry.event_id == "LUX_W_PRISMATIC_BARRIER_OUTBOUND_SELF"
        and entry.operation == "SHIELD"
    )
    assert actor_shield.recipient is EntityId.ACTOR
    assert opponent_shield.recipient is EntityId.TARGET


def test_teemo_blind_cancels_lux_attacks_without_cancelling_abilities() -> None:
    """Keep Lux's spell damage independent from the blinded attack channel."""
    result = MatchupEngine(ROOT).evaluate(MatchupRequest("Lux", "Teemo"))

    assert any(
        entry.event_id == "LUX_PASSIVE_ILLUMINATION_Q_ATTACK"
        and entry.status == "CANCELLED"
        for entry in result.timeline.log
    )
    for event_id in (
        "LUX_Q_LIGHT_BINDING",
        "LUX_E_LUCENT_SINGULARITY_DETONATE",
        "LUX_R_FINAL_SPARK",
    ):
        assert any(
            entry.event_id == event_id
            and entry.operation == "DAMAGE"
            and entry.status == "APPLIED"
            for entry in result.timeline.log
        )


def test_lux_item_policy_rejects_only_unrepresented_stat_channels() -> None:
    """Allow AP and chassis stats while rejecting fixed-policy gaps."""
    lux = create_default_registry(ROOT).require_cog("Lux")

    assert lux.item_candidate_blocker(
        {"id": 1, "stats": {"AP": {}, "AD": {}, "ATTACK_SPEED": {}, "HP": {}}}
    ) is None
    assert lux.item_candidate_blocker(
        {"id": 2, "stats": {"ABILITY_HASTE": {}, "HEAL_SHIELD_POWER": {}}}
    ) == "LUX_ITEM_STAT_NOT_MODELED:2:ABILITY_HASTE,HEAL_SHIELD_POWER"
