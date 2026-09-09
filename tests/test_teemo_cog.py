"""Focused regression tests for the locked Teemo Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs.base import CogCapability, CogMaturity, ParticipantContext
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import ActionChannel, DamageOutput, EntityId, StatusOutput

ROOT = Path(__file__).resolve().parents[1]


def test_teemo_declares_modeled_unverified_capabilities_and_evidence() -> None:
    """Distinguish the Teemo model from a generated champion scaffold."""
    teemo = create_default_registry(ROOT).require_cog("Teemo")

    assert teemo.maturity is CogMaturity.MODELED_UNVERIFIED
    assert teemo.has_capability(CogCapability.REACTION_MODEL)
    assert teemo.has_capability(CogCapability.RECOMMENDATION)
    assert teemo.verification_blockers() == ("COG_MODEL_UNVERIFIED:Teemo",)
    assert any(ref.endswith("teemo.bin.json") for ref in teemo.evidence_refs)


def test_teemo_q_and_toxic_shot_use_locked_rank_five_values() -> None:
    """Keep Q blind and E impact formulas anchored to the locked snapshot."""
    registry = create_default_registry(ROOT)
    teemo = registry.require_cog("Teemo")
    garen = registry.require_cog("Garen")
    context = ParticipantContext(
        EntityId.ACTOR,
        EntityId.TARGET,
        teemo.snapshot(
            level=13,
            item_stats={"AP": Decimal(100), "AD": Decimal(40)},
        ),
        garen.snapshot(level=13),
        8000,
        3000,
    )

    first = teemo.build_action_plan(context)
    second = teemo.build_action_plan(context)
    q = next(event for event in first.events if event.id == "TEEMO_Q_BLINDING_DART")
    attack = next(event for event in first.events if event.id == "TEEMO_E_ATTACK_1")
    poison = next(event for event in first.events if event.id == "TEEMO_E_POISON_TICK_1")

    assert first == second
    assert isinstance(q.outputs[0], DamageOutput)
    assert q.outputs[0].amount == Decimal(330)
    assert isinstance(q.outputs[1], StatusOutput)
    assert q.outputs[1].status == "CC_BLIND"
    assert q.outputs[1].duration_ms == 3000
    assert attack.outputs[1].amount == Decimal(97)
    assert poison.outputs[0].amount == Decimal(41)
    assert "TEEMO_E_POISON_REFRESH_PHASE_UNVERIFIED" in first.blockers


def test_teemo_blind_blocks_only_basic_attacks_and_tenacity_shortens_it() -> None:
    """Allow an ability during blind and restore an attack shortened by tenacity."""
    engine = MatchupEngine(ROOT)
    garen = engine.evaluate(MatchupRequest("Garen", "Teemo"))
    no_tenacity = engine.evaluate(MatchupRequest("Jax", "Teemo"))
    with_tenacity = engine.evaluate(MatchupRequest("Jax", "Teemo", actor_item_ids=(3111,)))

    assert any(
        entry.event_id == "GAREN_Q_STRIKE"
        and entry.action_channel is ActionChannel.BASIC_ATTACK
        and entry.status == "CANCELLED"
        for entry in garen.timeline.log
    )
    assert any(
        entry.event_id == "GAREN_E_TICK_1"
        and entry.action_channel is ActionChannel.ABILITY
        and entry.status == "APPLIED"
        for entry in garen.timeline.log
    )
    no_tenacity_cancelled = sum(
        entry.status == "CANCELLED" and entry.action_channel is ActionChannel.BASIC_ATTACK
        for entry in no_tenacity.timeline.log
    )
    with_tenacity_cancelled = sum(
        entry.status == "CANCELLED" and entry.action_channel is ActionChannel.BASIC_ATTACK
        for entry in with_tenacity.timeline.log
    )
    assert with_tenacity_cancelled < no_tenacity_cancelled


def test_teemo_blind_and_damage_follow_teemo_across_role_reversal() -> None:
    """Keep Teemo behavior attached to the champion instead of request position."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Teemo", "Garen"))
    as_opponent = engine.evaluate(MatchupRequest("Garen", "Teemo"))

    actor_q = next(
        entry for entry in as_actor.timeline.log if entry.event_id == "TEEMO_Q_BLINDING_DART"
    )
    opponent_q = next(
        entry
        for entry in as_opponent.timeline.log
        if entry.event_id == "TEEMO_Q_BLINDING_DART"
    )
    assert actor_q.recipient is EntityId.TARGET
    assert opponent_q.recipient is EntityId.ACTOR
    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
