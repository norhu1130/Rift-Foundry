"""Focused regressions for the locked Anivia champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.champions.wip.anivia import AniviaCog
from lol_build.cogs.registry import ChampionCogRegistry, create_default_registry
from lol_build.core.timeline import (
    ActionChannel,
    DeathPreventionOutput,
    EntityId,
    StatusOutput,
)

ROOT = Path(__file__).resolve().parents[1]


def _registry_with_anivia() -> ChampionCogRegistry:
    """Replace the manifest-loaded Anivia instance with the modeled Cog.

    :return: Default registry containing the locally modeled Anivia class.
    """
    registry = create_default_registry(ROOT)
    scaffold = registry.require_cog("Anivia")
    registry.add_cog(AniviaCog(scaffold.document, scaffold.detail_root), override=True)
    return registry


def _context(
    *,
    anivia_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a level-13 Anivia-versus-Garen direct-Cog context.

    :param anivia_is_actor: Place Anivia on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Anivia.
    :return: Role-bound deterministic benchmark context.
    """
    registry = _registry_with_anivia()
    anivia = registry.require_cog("Anivia")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if anivia_is_actor else EntityId.TARGET,
        EntityId.TARGET if anivia_is_actor else EntityId.ACTOR,
        anivia.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Resolve one event by its stable Anivia identifier.

    :param plan: Action plan exposing an ``events`` tuple.
    :param event_id: Exact event identifier to locate.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_anivia_declares_modeled_capabilities_and_locked_evidence() -> None:
    """Distinguish modeled Anivia behavior and retain all source forms."""
    anivia = _registry_with_anivia().require_cog("Anivia")

    assert anivia.maturity is CogMaturity.MODELED_UNVERIFIED
    assert anivia.capabilities == DUEL_CAPABILITIES
    assert anivia.verification_blockers() == ("COG_MODEL_UNVERIFIED:Anivia",)
    assert anivia.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Anivia.json",
        "data/raw/16.17.1/communitydragon/champions/34.json",
        "data/raw/16.17.1/communitydragon/champions/anivia.bin.json",
    )
    assert all((ROOT / reference).is_file() for reference in anivia.evidence_refs)


def test_anivia_rotation_is_deterministic_and_uses_locked_formulas() -> None:
    """Anchor Q5/E5/R2 damage, chill multiplier, storm growth, and stun."""
    anivia = _registry_with_anivia().require_cog("Anivia")
    context = _context(item_stats={"AP": Decimal(100)})
    first = anivia.build_action_plan(context)

    assert first == anivia.build_action_plan(context)
    assert first.model_id == "anivia_q5_e5_w1_r2_level13_chilled_storm_v1"
    q_pass = _event(first, "ANIVIA_Q_FLASH_FROST_1_PASSTHROUGH")
    q_burst = _event(first, "ANIVIA_Q_FLASH_FROST_1_DETONATION")
    frostbite = _event(first, "ANIVIA_E_FROSTBITE_1_CHILLED")
    early_storm = _event(first, "ANIVIA_R_GLACIAL_STORM_TICK_1")
    full_storm = _event(first, "ANIVIA_R_GLACIAL_STORM_TICK_4")

    assert q_pass.outputs[0].amount == 155
    assert q_burst.outputs[0].amount == 245
    assert isinstance(q_burst.outputs[1], StatusOutput)
    assert (q_burst.outputs[1].status, q_burst.outputs[1].duration_ms) == (
        "CC_STUN",
        1500,
    )
    assert frostbite.outputs[0].amount == 420
    assert early_storm.outputs[0].amount == Decimal("43.75")
    assert full_storm.outputs[0].amount == Decimal("131.25")
    assert "ANIVIA_R_CHANNEL_CANCEL_CAUSALITY_NOT_MODELED" in first.blockers
    assert "ANIVIA_W_WALL_TERRAIN_AND_DISPLACEMENT_NOT_MODELED" in first.blockers


def test_anivia_rebirth_uses_limited_death_prevention_contract() -> None:
    """Represent passive readiness without claiming Egg health or revival."""
    anivia = _registry_with_anivia().require_cog("Anivia")
    plan = anivia.build_action_plan(_context())
    passive = _event(plan, "ANIVIA_PASSIVE_REBIRTH_READY")
    prevention = next(
        output for output in passive.outputs if isinstance(output, DeathPreventionOutput)
    )

    assert passive.channel is ActionChannel.PASSIVE
    assert prevention.recipient is EntityId.ACTOR
    assert prevention.health_floor == 1
    assert prevention.duration_ms == 8000
    assert "ANIVIA_REBIRTH_REPLACEMENT_HEALTH_POOL_NOT_MODELED" in plan.blockers
    assert "ANIVIA_REBIRTH_REVIVAL_CONDITION_NOT_MODELED" in plan.blockers


def test_anivia_ap_attack_speed_and_haste_reach_distinct_channels() -> None:
    """Prove AP changes formulas while speed and haste add eligible events."""
    anivia = _registry_with_anivia().require_cog("Anivia")
    baseline = anivia.build_action_plan(_context())
    powered = anivia.build_action_plan(_context(item_stats={"AP": Decimal(100)}))
    faster = anivia.build_action_plan(_context(item_stats={"ATTACK_SPEED": Decimal("0.50")}))
    hasted = anivia.build_action_plan(_context(item_stats={"ABILITY_HASTE": Decimal(100)}))

    assert (
        _event(powered, "ANIVIA_Q_FLASH_FROST_1_PASSTHROUGH").outputs[0].amount
        - _event(baseline, "ANIVIA_Q_FLASH_FROST_1_PASSTHROUGH").outputs[0].amount
        == 25
    )
    assert (
        _event(powered, "ANIVIA_E_FROSTBITE_1_CHILLED").outputs[0].amount
        - _event(baseline, "ANIVIA_E_FROSTBITE_1_CHILLED").outputs[0].amount
        == 110
    )
    assert len([event for event in faster.events if "BASIC_ATTACK" in event.id]) > len(
        [event for event in baseline.events if "BASIC_ATTACK" in event.id]
    )
    assert len([event for event in hasted.events if "FROSTBITE" in event.id]) > len(
        [event for event in baseline.events if "FROSTBITE" in event.id]
    )
    assert _event(hasted, "ANIVIA_Q_FLASH_FROST_2_PASSTHROUGH").at_ms == 3600


def test_anivia_control_and_matchup_models_follow_role_reversal() -> None:
    """Keep Anivia's stuns, slow, damage, and passive attached to her role."""
    anivia = _registry_with_anivia().require_cog("Anivia")
    reaction = anivia.build_reaction_plan(_context())
    stun = reaction.cast_block_windows[0]
    slow = reaction.cast_block_windows[-1]

    assert stun.control_type.value == "STUN"
    assert stun.tenacity_reducible is True
    assert stun.blocked_channels == (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY)
    assert slow.control_type.value == "SLOW"
    assert slow.blocked_channels == (ActionChannel.MOVEMENT,)

    engine = MatchupEngine(ROOT, registry=_registry_with_anivia())
    as_actor = engine.evaluate(MatchupRequest("Anivia", "Garen"))
    as_target = engine.evaluate(MatchupRequest("Garen", "Anivia"))
    assert as_actor.actor_action_model == as_target.opponent_action_model
    assert as_actor.actor_reaction_model == as_target.opponent_reaction_model
    actor_q = next(
        entry
        for entry in as_actor.timeline.log
        if entry.event_id == "ANIVIA_Q_FLASH_FROST_1_PASSTHROUGH" and entry.operation == "DAMAGE"
    )
    target_q = next(
        entry
        for entry in as_target.timeline.log
        if entry.event_id == "ANIVIA_Q_FLASH_FROST_1_PASSTHROUGH" and entry.operation == "DAMAGE"
    )
    assert actor_q.recipient is EntityId.TARGET
    assert target_q.recipient is EntityId.ACTOR


def test_teemo_blind_cancels_anivia_attacks_but_not_ice_spells() -> None:
    """Keep Anivia's ability channel independent from Teemo's blind."""
    result = MatchupEngine(ROOT, registry=_registry_with_anivia()).evaluate(
        MatchupRequest("Anivia", "Teemo")
    )

    assert any(
        entry.event_id.startswith("ANIVIA_BASIC_ATTACK_") and entry.status == "CANCELLED"
        for entry in result.timeline.log
    )
    for event_id in (
        "ANIVIA_Q_FLASH_FROST_1_PASSTHROUGH",
        "ANIVIA_Q_FLASH_FROST_1_DETONATION",
        "ANIVIA_E_FROSTBITE_1_CHILLED",
        "ANIVIA_R_GLACIAL_STORM_TICK_1",
    ):
        assert any(
            entry.event_id == event_id and entry.operation == "DAMAGE" and entry.status == "APPLIED"
            for entry in result.timeline.log
        )


def test_anivia_item_policy_accepts_haste_and_blocks_unrepresented_stats() -> None:
    """Allow modeled AP, speed, and haste while rejecting resource assumptions."""
    anivia = _registry_with_anivia().require_cog("Anivia")

    assert (
        anivia.item_candidate_blocker(
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
        anivia.item_candidate_blocker({"id": 2, "stats": {"MANA": {}, "OMNIVAMP": {}}})
        == "ANIVIA_ITEM_STAT_NOT_MODELED:2:MANA"
    )
