"""Focused regressions for the locked Ivern champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import ActionChannel, EntityId, ShieldOutput, StatusOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    ivern_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a level-13 Ivern-versus-Teemo direct-Cog context.

    :param ivern_is_actor: Place Ivern on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Ivern.
    :return: Role-bound deterministic benchmark context.
    """
    registry = create_default_registry(ROOT)
    ivern = registry.require_cog("Ivern")
    teemo = registry.require_cog("Teemo")
    return ParticipantContext(
        EntityId.ACTOR if ivern_is_actor else EntityId.TARGET,
        EntityId.TARGET if ivern_is_actor else EntityId.ACTOR,
        ivern.snapshot(level=13, item_stats=item_stats),
        teemo.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Resolve one event by its stable Ivern identifier.

    :param plan: Action plan exposing an ``events`` tuple.
    :param event_id: Exact event identifier to locate.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_ivern_declares_modeled_capabilities_and_locked_evidence() -> None:
    """Distinguish Ivern from a scaffold and retain all source forms."""
    ivern = create_default_registry(ROOT).require_cog("Ivern")

    assert ivern.maturity is CogMaturity.MODELED_UNVERIFIED
    assert ivern.capabilities == DUEL_CAPABILITIES
    assert ivern.verification_blockers() == ("COG_MODEL_UNVERIFIED:Ivern",)
    assert ivern.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Ivern.json",
        "data/raw/16.17.1/communitydragon/champions/427.json",
        "data/raw/16.17.1/communitydragon/champions/ivern.bin.json",
    )
    assert all((ROOT / reference).is_file() for reference in ivern.evidence_refs)


def test_ivern_rotation_is_deterministic_and_uses_locked_formulas() -> None:
    """Anchor Q5/W1/E5 damage, shield, control, and timing values."""
    ivern = create_default_registry(ROOT).require_cog("Ivern")
    context = _context(item_stats={"AP": Decimal(100)})

    first = ivern.build_action_plan(context)
    repeated = ivern.build_action_plan(context)
    rootcaller = _event(first, "IVERN_Q_ROOTCALLER")
    triggerseed = _event(first, "IVERN_E_TRIGGERSEED_SELF")
    detonation = _event(first, "IVERN_E_TRIGGERSEED_DETONATE")
    attack = _event(first, "IVERN_BASIC_ATTACK_BRUSHMAKER_1")

    assert first == repeated
    assert first.model_id == "ivern_q5_w1_e5_r2_level13_locked_v1"
    assert rootcaller.outputs[0].amount == 330
    assert isinstance(rootcaller.outputs[1], StatusOutput)
    assert (rootcaller.outputs[1].status, rootcaller.outputs[1].duration_ms) == (
        "CC_ROOT",
        2000,
    )
    assert isinstance(triggerseed.outputs[0], ShieldOutput)
    assert triggerseed.outputs[0].amount == 285
    assert detonation.outputs[0].amount == 230
    assert isinstance(detonation.outputs[1], StatusOutput)
    assert (detonation.outputs[1].status, detonation.outputs[1].duration_ms) == (
        "CC_SLOW",
        2000,
    )
    assert attack.outputs[1].amount == 40


def test_ivern_ap_and_attack_speed_reach_represented_channels() -> None:
    """Prove AP scales spells and W while attack speed adds attacks."""
    ivern = create_default_registry(ROOT).require_cog("Ivern")
    baseline = ivern.build_action_plan(_context())
    powered = ivern.build_action_plan(_context(item_stats={"AP": Decimal(100)}))
    faster = ivern.build_action_plan(_context(item_stats={"ATTACK_SPEED": Decimal("0.50")}))

    assert (
        _event(powered, "IVERN_Q_ROOTCALLER").outputs[0].amount
        - _event(baseline, "IVERN_Q_ROOTCALLER").outputs[0].amount
        == 70
    )
    assert (
        _event(powered, "IVERN_E_TRIGGERSEED_SELF").outputs[0].amount
        - _event(baseline, "IVERN_E_TRIGGERSEED_SELF").outputs[0].amount
        == 50
    )
    baseline_attacks = [
        event for event in baseline.events if event.id.startswith("IVERN_BASIC_ATTACK_BRUSHMAKER_")
    ]
    faster_attacks = [
        event for event in faster.events if event.id.startswith("IVERN_BASIC_ATTACK_BRUSHMAKER_")
    ]
    assert len(faster_attacks) > len(baseline_attacks)


def test_ivern_blocks_unrepresentable_ally_and_daisy_behavior() -> None:
    """Keep ally buffs and Daisy outside the two-participant timeline."""
    ivern = create_default_registry(ROOT).require_cog("Ivern")
    plan = ivern.build_action_plan(_context())

    assert not any(event.id.startswith("IVERN_R_") for event in plan.events)
    assert "IVERN_Q_ALLY_DASH_NOT_REPRESENTABLE_IN_TWO_COMBATANT_DUEL" in plan.blockers
    assert "IVERN_W_ALLY_ATTACK_BUFF_NOT_REPRESENTABLE_IN_TWO_COMBATANT_DUEL" in plan.blockers
    assert "IVERN_E_ALLY_AND_DAISY_TARGETS_NOT_REPRESENTABLE" in plan.blockers
    assert "IVERN_R_DAISY_PET_ENTITY_NOT_REPRESENTABLE" in plan.blockers


def test_ivern_reaction_and_engagement_preserve_control_contracts() -> None:
    """Expose Rootcaller and Triggerseed movement control plus Q engage range."""
    ivern = create_default_registry(ROOT).require_cog("Ivern")
    context = _context()
    reaction = ivern.build_reaction_plan(context)
    root, slow = reaction.cast_block_windows

    assert root.control_type.value == "ROOT"
    assert root.blocked_channels == (ActionChannel.MOVEMENT,)
    assert root.end_ms - root.start_ms == 2000
    assert root.tenacity_reducible is True
    assert slow.control_type.value == "SLOW"
    assert slow.blocked_channels == (ActionChannel.MOVEMENT,)
    assert slow.end_ms - slow.start_ms == 2000
    assert ivern.engagement_dash_distance(context) == 1125
    assert ivern.engagement_speed_multiplier(context) == 1


def test_ivern_role_reversal_and_blind_preserve_spell_channels() -> None:
    """Keep Ivern symmetric while blind cancels enhanced basic attacks."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Ivern", "Teemo"))
    as_opponent = engine.evaluate(MatchupRequest("Teemo", "Ivern"))

    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    assert any(
        entry.event_id.startswith("IVERN_BASIC_ATTACK_BRUSHMAKER_")
        and entry.action_channel is ActionChannel.BASIC_ATTACK
        and entry.status == "CANCELLED"
        for entry in as_opponent.timeline.log
    )
    for event_id in ("IVERN_Q_ROOTCALLER", "IVERN_E_TRIGGERSEED_DETONATE"):
        assert any(
            entry.event_id == event_id and entry.status == "APPLIED"
            for entry in as_opponent.timeline.log
        )


def test_ivern_item_policy_accepts_live_stats_and_rejects_model_gaps() -> None:
    """Allow represented stats while blocking resources and shield power."""
    ivern = create_default_registry(ROOT).require_cog("Ivern")

    assert (
        ivern.item_candidate_blocker(
            {
                "id": 1,
                "stats": {
                    "AP": {},
                    "AD": {},
                    "ATTACK_SPEED": {},
                    "HP": {},
                    "ARMOR": {},
                    "MAGIC_RESISTANCE": {},
                },
            }
        )
        is None
    )
    assert (
        ivern.item_candidate_blocker(
            {
                "id": 2,
                "stats": {
                    "ABILITY_HASTE": {},
                    "HEAL_SHIELD_POWER": {},
                    "MANA": {},
                },
            }
        )
        == "IVERN_ITEM_STAT_NOT_MODELED:2:ABILITY_HASTE,HEAL_SHIELD_POWER,MANA"
    )
