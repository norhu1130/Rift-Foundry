"""Focused coverage for the locked Jax champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext, create_default_registry
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.core.timeline import DamageOutput, EntityId, StatusOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(*, jax_is_actor: bool = True, item_stats=None) -> ParticipantContext:
    """Build the fixed level-13 Jax versus Garen unit-test context.

    :param jax_is_actor: Place Jax on the actor side when true.
    :param item_stats: Optional Jax item stat modifiers.
    :return: Role-bound participant context suitable for direct Cog calls.
    """
    registry = create_default_registry(ROOT)
    jax = registry.require_cog("Jax")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if jax_is_actor else EntityId.TARGET,
        EntityId.TARGET if jax_is_actor else EntityId.ACTOR,
        jax.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def test_jax_declares_modeled_capabilities_and_locked_evidence() -> None:
    registry = create_default_registry(ROOT)
    jax = registry.require_cog("Jax")

    assert jax.maturity is CogMaturity.MODELED_UNVERIFIED
    assert jax.capabilities == DUEL_CAPABILITIES
    assert jax.verification_blockers() == ("COG_MODEL_UNVERIFIED:Jax",)
    assert jax.evidence_refs == (
        "data/curated/champions/24.json",
        "data/raw/16.17.1/en_US/champion/Jax.json",
        "data/raw/16.17.1/communitydragon/champions/24.json",
        "data/raw/16.17.1/communitydragon/champions/jax.bin.json",
    )
    assert all((ROOT / path).is_file() for path in jax.evidence_refs)


def test_jax_action_plan_is_deterministic_and_uses_locked_rank_values() -> None:
    registry = create_default_registry(ROOT)
    jax = registry.require_cog("Jax")
    context = _context(item_stats={"AP": Decimal(100), "ATTACK_SPEED": Decimal("0.25")})

    first = jax.build_action_plan(context)
    second = jax.build_action_plan(context)

    assert first == second
    assert first.model_id == "jax_q1_w5_e5_r2_level13_synthetic_v1"
    assert jax.engagement_dash_distance(context) == 700
    empower = next(
        event for event in first.events if event.id == "JAX_GENERIC_ATTACK_W_EMPOWER_1"
    )
    assert tuple(output.amount for output in empower.outputs)[:2] == (
        context.snapshot.attack_damage,
        Decimal(250),
    )
    third_attack = tuple(
        event for event in first.events if event.channel.value == "BASIC_ATTACK"
    )[2]
    assert len(third_attack.outputs) >= 2
    assert isinstance(third_attack.outputs[-1], DamageOutput)
    assert third_attack.outputs[-1].amount == Decimal(190)
    counter_strike = next(
        event for event in first.events if event.id == "JAX_E_COUNTER_STRIKE_DAMAGE"
    )
    assert isinstance(counter_strike.outputs[0], DamageOutput)
    assert counter_strike.outputs[0].amount == (
        Decimal(160)
        + Decimal(70)
        + Decimal("0.04") * context.opponent_snapshot.max_hp
    )
    assert isinstance(counter_strike.outputs[1], StatusOutput)
    assert counter_strike.outputs[1].duration_ms == 1000


def test_jax_reaction_models_basic_attack_dodge_and_reducible_stun() -> None:
    registry = create_default_registry(ROOT)
    jax = registry.require_cog("Jax")

    reaction = jax.build_reaction_plan(_context())

    dodge, stun = reaction.cast_block_windows
    assert dodge.blocked_channels[0].value == "BASIC_ATTACK"
    assert dodge.tenacity_reducible is False
    assert dodge.source_event_id == "JAX_E_DEFENSIVE_STANCE"
    assert stun.tenacity_reducible is True
    assert stun.source_event_id == "JAX_E_COUNTER_STRIKE_DAMAGE"
    assert "JAX_E_AOE_DAMAGE_REDUCTION_NOT_EVALUATED" in reaction.blockers


def test_jax_counter_strike_follows_jax_across_role_reversal() -> None:
    engine = MatchupEngine(ROOT)

    jax_actor = engine.evaluate(MatchupRequest("Jax", "Garen"))
    jax_target = engine.evaluate(MatchupRequest("Garen", "Jax"))

    assert jax_actor.actor_action_model == jax_target.opponent_action_model
    assert jax_actor.actor_reaction_model == jax_target.opponent_reaction_model
    assert next(
        entry for entry in jax_actor.timeline.log if entry.event_id == "GAREN_Q_STRIKE"
    ).status == "CANCELLED"
    assert next(
        entry for entry in jax_target.timeline.log if entry.event_id == "GAREN_Q_STRIKE"
    ).status == "CANCELLED"
    actor_e = next(
        entry
        for entry in jax_actor.timeline.log
        if entry.event_id == "JAX_E_COUNTER_STRIKE_DAMAGE" and entry.operation == "DAMAGE"
    )
    target_e = next(
        entry
        for entry in jax_target.timeline.log
        if entry.event_id == "JAX_E_COUNTER_STRIKE_DAMAGE" and entry.operation == "DAMAGE"
    )
    assert actor_e.recipient is EntityId.TARGET
    assert target_e.recipient is EntityId.ACTOR


def test_jax_item_policy_rejects_only_unrepresented_stat_channels() -> None:
    registry = create_default_registry(ROOT)
    jax = registry.require_cog("Jax")

    assert jax.item_candidate_blocker({"id": 1, "stats": {"AD": {}}}) is None
    assert jax.item_candidate_blocker(
        {"id": 2, "stats": {"ABILITY_HASTE": {}, "MANA": {}}}
    ) == "JAX_ITEM_STAT_NOT_MODELED:2:ABILITY_HASTE,MANA"
