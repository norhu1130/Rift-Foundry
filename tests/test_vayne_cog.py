"""Focused regression tests for the locked Vayne champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext, create_default_registry
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, DamageOutput, EntityId

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    vayne_is_actor: bool = True,
    vayne_items: dict[str, Decimal] | None = None,
    opponent_items: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build the level-13 Vayne versus Garen benchmark context.

    :param vayne_is_actor: Place Vayne on the actor side when true.
    :param vayne_items: Optional item-derived modifiers for Vayne.
    :param opponent_items: Optional item-derived modifiers for Garen.
    :return: Role-bound context suitable for direct Vayne Cog calls.
    """
    registry = create_default_registry(ROOT)
    vayne = registry.require_cog("Vayne")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if vayne_is_actor else EntityId.TARGET,
        EntityId.TARGET if vayne_is_actor else EntityId.ACTOR,
        vayne.snapshot(level=13, item_stats=vayne_items),
        garen.snapshot(level=13, item_stats=opponent_items),
        8000,
        3000,
    )


def _true_damage(plan) -> tuple[DamageOutput, ...]:
    """Collect Silver Bolts outputs from an action plan.

    :param plan: Vayne action plan returned by the Cog.
    :return: Ordered true-damage outputs in the modeled rotation.
    """
    return tuple(
        output
        for event in plan.events
        for output in event.outputs
        if isinstance(output, DamageOutput) and output.damage_type is DamageType.TRUE
    )


def test_vayne_declares_modeled_capabilities_and_three_locked_sources() -> None:
    """Distinguish Vayne's model from a generated scaffold."""
    vayne = create_default_registry(ROOT).require_cog("Vayne")

    assert vayne.maturity is CogMaturity.MODELED_UNVERIFIED
    assert vayne.capabilities == DUEL_CAPABILITIES
    assert vayne.verification_blockers() == ("COG_MODEL_UNVERIFIED:Vayne",)
    assert len(vayne.evidence_refs) == 3
    assert all((ROOT / ref).is_file() for ref in vayne.evidence_refs)


def test_vayne_rotation_is_deterministic_and_tumble_resets_attack_clock() -> None:
    """Anchor the R2-reduced Q schedule and deterministic attack reset."""
    vayne = create_default_registry(ROOT).require_cog("Vayne")
    context = _context()

    first = vayne.build_action_plan(context)
    repeated = vayne.build_action_plan(context)
    tumble_times = tuple(event.at_ms for event in first.events if "Q_TUMBLE_ATTACK" in event.id)
    interval = vayne._attack_interval_ms(context.snapshot.attack_speed)

    assert first == repeated
    assert first.model_id == "vayne_q5_w5_e1_r2_level13_locked_v1"
    assert tumble_times == (300, 1500, 2700, 3900, 5100, 6300, 7500)
    for tumble_time in tumble_times:
        ordinary_after = next(
            (
                event.at_ms
                for event in first.events
                if "BASIC_ATTACK" in event.id and event.at_ms > tumble_time
            ),
            None,
        )
        if ordinary_after is not None and ordinary_after < tumble_time + 1200:
            assert ordinary_after == tumble_time + interval
    assert "VAYNE_ATTACK_AND_TUMBLE_TIMING_UNVERIFIED" in first.blockers


def test_vayne_damage_responds_to_ad_ap_attack_speed_and_target_health() -> None:
    """Keep Q, W, E, and cadence connected to their represented stat channels."""
    vayne = create_default_registry(ROOT).require_cog("Vayne")
    baseline_context = _context()
    scaled_context = _context(
        vayne_items={
            "AD": Decimal(100),
            "AP": Decimal(100),
            "ATTACK_SPEED": Decimal("1.50"),
        },
        opponent_items={"HP": Decimal(3000)},
    )
    baseline = vayne.build_action_plan(baseline_context)
    scaled = vayne.build_action_plan(scaled_context)

    baseline_q = next(event for event in baseline.events if "Q_TUMBLE_ATTACK" in event.id)
    scaled_q = next(event for event in scaled.events if "Q_TUMBLE_ATTACK" in event.id)
    scaled_e = next(event for event in scaled.events if "E_CONDEMN" in event.id)
    expected_combat_ad = scaled_context.snapshot.attack_damage + Decimal(50)

    assert scaled_q.outputs[0].amount == expected_combat_ad
    assert scaled_q.outputs[1].amount == (Decimal("1.15") * expected_combat_ad + Decimal(50))
    assert scaled_q.outputs[1].amount > baseline_q.outputs[1].amount
    assert scaled_e.outputs[0].amount == Decimal(125)
    assert len(
        tuple(event for event in scaled.events if event.channel is ActionChannel.BASIC_ATTACK)
    ) > len(
        tuple(event for event in baseline.events if event.channel is ActionChannel.BASIC_ATTACK)
    )
    assert _true_damage(baseline)[0].amount == max(
        Decimal(100), Decimal("0.10") * baseline_context.opponent_snapshot.max_hp
    )
    assert _true_damage(scaled)[0].amount == (
        Decimal("0.10") * scaled_context.opponent_snapshot.max_hp
    )


def test_vayne_condemn_does_not_invent_a_wall_stun() -> None:
    """Represent base E damage while preserving geometry-dependent blockers."""
    vayne = create_default_registry(ROOT).require_cog("Vayne")
    plan = vayne.build_action_plan(_context())
    reaction = vayne.build_reaction_plan(_context())
    condemn = next(event for event in plan.events if "E_CONDEMN" in event.id)

    assert len(condemn.outputs) in {1, 2}
    assert all(not hasattr(output, "status") for output in condemn.outputs)
    assert reaction.cast_block_windows == ()
    assert "VAYNE_E_TERRAIN_COLLISION_DAMAGE_AND_STUN_NOT_MODELED" in plan.blockers
    assert "VAYNE_E_TERRAIN_COLLISION_DAMAGE_AND_STUN_NOT_MODELED" in reaction.blockers
    assert "VAYNE_R_TUMBLE_INVISIBILITY_TARGETING_NOT_MODELED" in reaction.blockers


def test_vayne_blind_cancels_attacks_and_their_silver_bolts_outputs() -> None:
    """Ensure Teemo blind cancels Vayne's attack-bound Q and W damage."""
    evaluation = MatchupEngine(ROOT).evaluate(MatchupRequest("Vayne", "Teemo"))

    cancelled = tuple(
        entry
        for entry in evaluation.timeline.log
        if entry.event_id.startswith("VAYNE_") and entry.status == "CANCELLED"
    )
    assert cancelled
    assert all(entry.action_channel is ActionChannel.BASIC_ATTACK for entry in cancelled)
    assert any("Q_TUMBLE_ATTACK" in entry.event_id for entry in cancelled)
    assert not any(
        entry.event_id == cancelled[0].event_id and entry.damage_type is DamageType.TRUE
        for entry in evaluation.timeline.log
        if entry.status == "APPLIED"
    )


def test_vayne_actions_follow_vayne_across_role_reversal() -> None:
    """Keep Vayne mechanics attached to the champion in either request role."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Vayne", "Garen"))
    as_opponent = engine.evaluate(MatchupRequest("Garen", "Vayne"))

    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    actor_q = next(
        entry
        for entry in as_actor.timeline.log
        if "VAYNE_Q_TUMBLE_ATTACK" in entry.event_id and entry.operation == "DAMAGE"
    )
    opponent_q = next(
        entry
        for entry in as_opponent.timeline.log
        if "VAYNE_Q_TUMBLE_ATTACK" in entry.event_id and entry.operation == "DAMAGE"
    )
    assert actor_q.recipient is EntityId.TARGET
    assert opponent_q.recipient is EntityId.ACTOR


def test_vayne_item_policy_rejects_unrepresented_stat_channels() -> None:
    """Allow represented damage stats while rejecting unresolved resources."""
    vayne = create_default_registry(ROOT).require_cog("Vayne")

    assert (
        vayne.item_candidate_blocker(
            {"id": 1, "stats": {"AD": {}, "AP": {}, "ATTACK_SPEED": {}, "HP": {}}}
        )
        is None
    )
    assert (
        vayne.item_candidate_blocker(
            {"id": 2, "stats": {"ABILITY_HASTE": {}, "CRITICAL_STRIKE_CHANCE": {}}}
        )
        == "VAYNE_ITEM_STAT_NOT_MODELED:2:ABILITY_HASTE"
    )
