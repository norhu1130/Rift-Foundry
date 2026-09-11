"""Focused regressions for the locked Ezreal champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import ActionChannel, DamageOutput, EntityId, StatusOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    ezreal_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a level-13 Ezreal-versus-Teemo direct-Cog context.

    :param ezreal_is_actor: Place Ezreal on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Ezreal.
    :return: Role-bound deterministic benchmark context.
    """
    registry = create_default_registry(ROOT)
    ezreal = registry.require_cog("Ezreal")
    teemo = registry.require_cog("Teemo")
    return ParticipantContext(
        EntityId.ACTOR if ezreal_is_actor else EntityId.TARGET,
        EntityId.TARGET if ezreal_is_actor else EntityId.ACTOR,
        ezreal.snapshot(level=13, item_stats=item_stats),
        teemo.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Resolve one event by its stable Ezreal identifier.

    :param plan: Action plan exposing an ``events`` tuple.
    :param event_id: Exact event identifier to locate.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def _damage_outputs(event: object) -> tuple[DamageOutput, ...]:
    """Select damage outputs from one Ezreal action.

    :param event: Action event exposing an ``outputs`` tuple.
    :return: Damage outputs in causal resolution order.
    """
    return tuple(output for output in event.outputs if isinstance(output, DamageOutput))


def test_ezreal_declares_modeled_capabilities_and_locked_evidence() -> None:
    """Distinguish Ezreal from a scaffold and retain all three source forms."""
    ezreal = create_default_registry(ROOT).require_cog("Ezreal")

    assert ezreal.maturity is CogMaturity.MODELED_UNVERIFIED
    assert ezreal.capabilities == DUEL_CAPABILITIES
    assert ezreal.verification_blockers() == ("COG_MODEL_UNVERIFIED:Ezreal",)
    assert ezreal.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Ezreal.json",
        "data/raw/16.17.1/communitydragon/champions/81.json",
        "data/raw/16.17.1/communitydragon/champions/ezreal.bin.json",
    )
    assert all((ROOT / reference).is_file() for reference in ezreal.evidence_refs)


def test_ezreal_rotation_is_deterministic_and_uses_locked_formulas() -> None:
    """Anchor Q5, E5, W1, R2, cooldown refund, and passive markers."""
    ezreal = create_default_registry(ROOT).require_cog("Ezreal")
    context = _context(item_stats={"AD": Decimal(40), "AP": Decimal(100)})

    first = ezreal.build_action_plan(context)
    repeated = ezreal.build_action_plan(context)
    ultimate = _event(first, "EZREAL_R_TRUESHOT_BARRAGE")
    shift = _event(first, "EZREAL_E_ARCANE_SHIFT_1")
    first_q = _event(first, "EZREAL_Q_MYSTIC_SHOT_1")
    third_q = _event(first, "EZREAL_Q_MYSTIC_SHOT_3")
    second_w = _event(first, "EZREAL_W_ESSENCE_FLUX_2")

    assert first == repeated
    assert first.model_id == "ezreal_q5_e5_w1_r2_level13_locked_v1"
    assert _damage_outputs(ultimate)[0].amount == Decimal(700)
    assert _damage_outputs(shift)[0].amount == Decimal(379)
    assert _damage_outputs(shift)[1].amount == Decimal(210)
    assert _damage_outputs(first_q)[0].amount == (
        Decimal(120) + Decimal("1.30") * context.snapshot.attack_damage + Decimal(40)
    )
    assert tuple(
        event.at_ms for event in first.events if event.id.startswith("EZREAL_Q_MYSTIC_SHOT_")
    ) == (1900, 4900, 7900)
    assert second_w.at_ms == 6200
    assert len(_damage_outputs(third_q)) == 2
    assert _damage_outputs(third_q)[1].amount == Decimal(210)
    assert any(
        isinstance(output, StatusOutput) and output.status == "EZREAL_RISING_SPELL_FORCE_STACK"
        for output in first_q.outputs
    )
    assert "EZREAL_Q_COOLDOWN_REFUND_REQUIRES_ASSUMED_HIT" in first.blockers
    assert "EZREAL_R_PRIOR_UNIT_HIT_DAMAGE_REDUCTION_NOT_MODELED" in first.blockers


def test_ezreal_ad_ap_attack_speed_and_haste_change_represented_outputs() -> None:
    """Prove core offensive stats alter formulas, cadence, or recast count."""
    ezreal = create_default_registry(ROOT).require_cog("Ezreal")
    baseline = ezreal.build_action_plan(_context())
    more_ad = ezreal.build_action_plan(_context(item_stats={"AD": Decimal(50)}))
    more_ap = ezreal.build_action_plan(_context(item_stats={"AP": Decimal(100)}))
    more_speed = ezreal.build_action_plan(_context(item_stats={"ATTACK_SPEED": Decimal("0.50")}))
    more_haste = ezreal.build_action_plan(_context(item_stats={"ABILITY_HASTE": Decimal(100)}))

    assert _damage_outputs(_event(more_ad, "EZREAL_Q_MYSTIC_SHOT_1"))[0].amount - (
        _damage_outputs(_event(baseline, "EZREAL_Q_MYSTIC_SHOT_1"))[0].amount
    ) == Decimal(65)
    assert _damage_outputs(_event(more_ap, "EZREAL_R_TRUESHOT_BARRAGE"))[0].amount - (
        _damage_outputs(_event(baseline, "EZREAL_R_TRUESHOT_BARRAGE"))[0].amount
    ) == Decimal(110)
    assert len(
        [event for event in more_speed.events if event.id.startswith("EZREAL_BASIC_ATTACK_")]
    ) > len([event for event in baseline.events if event.id.startswith("EZREAL_BASIC_ATTACK_")])
    assert len(
        [event for event in more_haste.events if event.id.startswith("EZREAL_Q_MYSTIC_SHOT_")]
    ) > len([event for event in baseline.events if event.id.startswith("EZREAL_Q_MYSTIC_SHOT_")])
    assert _event(more_haste, "EZREAL_E_ARCANE_SHIFT_2").at_ms == 4000


def test_ezreal_role_reversal_and_teemo_blind_are_channel_correct() -> None:
    """Keep Ezreal role-neutral while blind cancels attacks but not spells."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Ezreal", "Teemo"))
    as_opponent = engine.evaluate(MatchupRequest("Teemo", "Ezreal"))

    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    actor_q = next(
        entry
        for entry in as_actor.timeline.log
        if entry.event_id == "EZREAL_Q_MYSTIC_SHOT_1" and entry.operation == "DAMAGE"
    )
    opponent_q = next(
        entry
        for entry in as_opponent.timeline.log
        if entry.event_id == "EZREAL_Q_MYSTIC_SHOT_1" and entry.operation == "DAMAGE"
    )
    assert actor_q.recipient is EntityId.TARGET
    assert opponent_q.recipient is EntityId.ACTOR
    assert actor_q.status == opponent_q.status == "APPLIED"
    assert any(
        entry.event_id.startswith("EZREAL_BASIC_ATTACK_")
        and entry.action_channel is ActionChannel.BASIC_ATTACK
        and entry.status == "CANCELLED"
        for entry in as_opponent.timeline.log
    )


def test_ezreal_policy_engagement_and_reaction_keep_boundaries_explicit() -> None:
    """Accept represented stats and expose unresolved blink reactions."""
    ezreal = create_default_registry(ROOT).require_cog("Ezreal")
    context = _context()

    assert ezreal.engagement_dash_distance(context) == 475
    assert ezreal.engagement_speed_multiplier(context) == 1
    assert (
        ezreal.item_candidate_blocker(
            {
                "id": 1,
                "stats": {
                    "AD": {},
                    "AP": {},
                    "ATTACK_SPEED": {},
                    "ABILITY_HASTE": {},
                },
            }
        )
        is None
    )
    assert (
        ezreal.item_candidate_blocker(
            {"id": 2, "stats": {"CRITICAL_STRIKE_CHANCE": {}, "MANA": {}}}
        )
        == "EZREAL_ITEM_STAT_NOT_MODELED:2:CRITICAL_STRIKE_CHANCE,MANA"
    )
    reaction = ezreal.build_reaction_plan(context)
    assert reaction.events == ()
    assert reaction.cast_block_windows == ()
    assert reaction.blockers == (
        "EZREAL_E_REACTIVE_BLINK_TRIGGER_NOT_MODELED",
        "EZREAL_E_PROJECTILE_DODGE_AND_TARGET_SELECTION_NOT_MODELED",
    )


def test_ezreal_hostile_silence_cancels_spells_without_relabeling_attacks() -> None:
    """Let Garen silence cancel ability events through the shared CC engine."""
    result = MatchupEngine(ROOT).evaluate(MatchupRequest("Garen", "Ezreal"))

    assert any(
        entry.event_id.startswith("EZREAL_Q_MYSTIC_SHOT_")
        and entry.action_channel is ActionChannel.ABILITY
        and entry.status == "CANCELLED"
        for entry in result.timeline.log
    )
    assert all(
        entry.action_channel is ActionChannel.BASIC_ATTACK
        for entry in result.timeline.log
        if entry.event_id.startswith("EZREAL_BASIC_ATTACK_") and entry.operation == "DAMAGE"
    )
