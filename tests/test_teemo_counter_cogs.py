"""Regression tests for the locked Olaf, Tryndamere, and Malphite Cogs."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs.base import CogCapability, CogMaturity, ParticipantContext
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import ActionChannel, DamageOutput, DeathPreventionOutput, EntityId

ROOT = Path(__file__).resolve().parents[1]


def _context(champion: str, *, item_stats: dict[str, Decimal] | None = None) -> ParticipantContext:
    """Build a level-13 actor context against locked Teemo.

    :param champion: Champion whose action plan is under test.
    :param item_stats: Optional normalized stats added to the champion snapshot.
    :return: Role-bound deterministic benchmark context.
    """
    registry = create_default_registry(ROOT)
    cog = registry.require_cog(champion)
    teemo = registry.require_cog("Teemo")
    return ParticipantContext(
        EntityId.ACTOR,
        EntityId.TARGET,
        cog.snapshot(level=13, item_stats=item_stats),
        teemo.snapshot(level=13),
        8000,
        3000,
    )


def test_counter_cogs_are_modeled_unverified_with_locked_evidence() -> None:
    """Distinguish all three models from generated champion scaffolds."""
    registry = create_default_registry(ROOT)

    for champion in ("Olaf", "Tryndamere", "Malphite"):
        cog = registry.require_cog(champion)
        assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
        assert cog.has_capability(CogCapability.ABILITY_ROTATION)
        assert cog.has_capability(CogCapability.REACTION_MODEL)
        assert cog.has_capability(CogCapability.RECOMMENDATION)
        assert any(ref.endswith(f"/{champion.casefold()}.bin.json") for ref in cog.evidence_refs)


def test_olaf_uses_locked_q_and_e_formulas_deterministically() -> None:
    """Anchor Olaf Q5 and E5 outputs to bonus and total attack damage."""
    registry = create_default_registry(ROOT)
    olaf = registry.require_cog("Olaf")
    context = _context("Olaf", item_stats={"AD": Decimal(40)})

    first = olaf.build_action_plan(context)
    second = olaf.build_action_plan(context)
    q = next(event for event in first.events if event.id == "OLAF_Q_UNDERTOW")
    e = next(event for event in first.events if event.id == "OLAF_E_RECKLESS_SWING_1")

    assert first == second
    assert isinstance(q.outputs[0], DamageOutput)
    r_bonus_ad = Decimal(20) + Decimal("0.25") * context.snapshot.attack_damage
    assert q.outputs[0].amount == Decimal(310) + r_bonus_ad
    assert isinstance(e.outputs[0], DamageOutput)
    assert e.outputs[0].amount == Decimal(250) + Decimal("0.50") * (
        context.snapshot.attack_damage + r_bonus_ad
    )
    assert "OLAF_R_CC_IMMUNITY_NOT_ENFORCED_BY_CAST_BLOCK_MODEL" not in first.blockers


def test_tryndamere_uses_locked_e_formula_and_death_prevention() -> None:
    """Anchor E5 and the rank-two Undying Rage health floor."""
    registry = create_default_registry(ROOT)
    tryndamere = registry.require_cog("Tryndamere")
    context = _context("Tryndamere", item_stats={"AD": Decimal(40), "AP": Decimal(100)})

    plan = tryndamere.build_action_plan(context)
    e = next(event for event in plan.events if event.id == "TRYNDAMERE_E_SPINNING_SLASH")
    ultimate = next(event for event in plan.events if event.id == "TRYNDAMERE_R_UNDYING_RAGE")

    assert e.outputs[0].amount == Decimal(360)
    death_prevention = next(
        output for output in ultimate.outputs if isinstance(output, DeathPreventionOutput)
    )
    assert death_prevention.health_floor == Decimal(50)
    assert death_prevention.duration_ms == 5000
    assert "TRYNDAMERE_FURY_AND_CRITICAL_STRIKES_NOT_MODELED" in plan.blockers
    assert "TRYNDAMERE_R_DEATH_FLOOR_NOT_ENFORCED_BY_TIMELINE" not in plan.blockers


def test_malphite_uses_locked_spell_scalings_and_cadence_window() -> None:
    """Anchor Malphite's spell damage and causally linked E cadence reduction."""
    registry = create_default_registry(ROOT)
    malphite = registry.require_cog("Malphite")
    context = _context("Malphite", item_stats={"AP": Decimal(100), "ARMOR": Decimal(50)})

    plan = malphite.build_action_plan(context)
    q = next(event for event in plan.events if event.id == "MALPHITE_Q_SEISMIC_SHARD")
    e = next(event for event in plan.events if event.id == "MALPHITE_E_GROUND_SLAM")
    r = next(event for event in plan.events if event.id == "MALPHITE_R_UNSTOPPABLE_FORCE")

    assert q.outputs[0].amount == Decimal(330)
    assert r.outputs[0].amount == Decimal(390)
    assert e.outputs[0].amount == (Decimal(240) + Decimal("0.60") * context.snapshot.armor)
    assert e.outputs[1].status == "MALPHITE_ATTACK_SPEED_REDUCTION"
    assert e.outputs[2].stat == "ATTACK_SPEED_MULTIPLIER"
    reaction = malphite.build_reaction_plan(context)
    cadence = reaction.attack_cadence_windows[0]
    assert cadence.source_event_id == "MALPHITE_E_GROUND_SLAM"
    assert cadence.multiplier == Decimal("0.50")
    assert "MALPHITE_E_ATTACK_SPEED_REDUCTION_SCHEDULE_NOT_REBUILT" not in plan.blockers


def test_teemo_blind_respects_immunity_and_action_channel_dependency() -> None:
    """Honor Olaf immunity while blind still cancels other attack-centric output."""
    engine = MatchupEngine(ROOT)
    olaf = engine.evaluate(MatchupRequest("Olaf", "Teemo"))
    tryndamere = engine.evaluate(MatchupRequest("Tryndamere", "Teemo"))
    malphite = engine.evaluate(MatchupRequest("Malphite", "Teemo"))

    assert not any(
        entry.event_id.startswith("OLAF_BASIC_ATTACK_") and entry.status == "CANCELLED"
        for entry in olaf.timeline.log
    )
    assert any(
        entry.event_id == "OLAF_E_RECKLESS_SWING_1" and entry.status == "APPLIED"
        for entry in olaf.timeline.log
    )
    assert "OLAF_R_CC_IMMUNITY_NOT_ENFORCED_BY_CAST_BLOCK_MODEL" not in olaf.blockers

    assert any(
        entry.event_id.startswith("TRYNDAMERE_BASIC_ATTACK_") and entry.status == "CANCELLED"
        for entry in tryndamere.timeline.log
    )
    assert any(
        entry.event_id == "TRYNDAMERE_E_SPINNING_SLASH" and entry.status == "APPLIED"
        for entry in tryndamere.timeline.log
    )

    assert any(
        entry.event_id == "MALPHITE_W_THUNDERCLAP_ATTACK" and entry.status == "CANCELLED"
        for entry in malphite.timeline.log
    )
    assert any(
        entry.event_id == "MALPHITE_E_GROUND_SLAM"
        and entry.action_channel is ActionChannel.ABILITY
        and entry.status == "APPLIED"
        for entry in malphite.timeline.log
    )


def test_counter_cog_models_follow_champions_across_role_reversal() -> None:
    """Keep action and reaction ownership attached to each champion Cog."""
    engine = MatchupEngine(ROOT)

    for champion in ("Olaf", "Tryndamere", "Malphite"):
        as_actor = engine.evaluate(MatchupRequest(champion, "Teemo"))
        as_opponent = engine.evaluate(MatchupRequest("Teemo", champion))
        assert as_actor.actor_action_model == as_opponent.opponent_action_model
        assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
        assert as_actor.opponent_hp_lost == as_opponent.actor_hp_lost
        assert as_actor.actor_hp_lost == as_opponent.opponent_hp_lost
