"""Focused regressions for the locked Mel champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import (
    ActionChannel,
    DamageOutput,
    EntityId,
    ShieldOutput,
    StatModifierOutput,
)

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *, as_actor: bool = True, item_stats: dict[str, Decimal] | None = None
) -> ParticipantContext:
    """Build a level-13 Mel-versus-Garen encounter.

    :param as_actor: Place Mel in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Mel.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    mel = registry.require_cog("Mel")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        mel.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one stable event from a Mel action plan.

    :param plan: Action plan containing the expected event.
    :param event_id: Exact event identifier to locate.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_mel_metadata_and_locked_rotation_are_explicit() -> None:
    """Require evidence, maturity, deterministic hits, and Overwhelm assumptions."""
    cog = create_default_registry(ROOT).require_cog("Mel")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    assert len([event for event in plan.events if "MEL_Q_RADIANT_VOLLEY_1" in event.id]) == 10
    assert len([event for event in plan.events if "MEL_E_SOLAR_SNARE_AREA" in event.id]) == 4
    assert "MEL_R_FIFTEEN_OVERWHELM_STACKS_FROM_E_AND_Q_ASSUMED" in plan.blockers


def test_mel_ap_haste_shield_and_passive_missiles_are_connected() -> None:
    """Exercise AP scaling, Q cooldown, W shield, and the enhanced attack."""
    cog = create_default_registry(ROOT).require_cog("Mel")
    base = cog.build_action_plan(_context())
    powered = cog.build_action_plan(
        _context(item_stats={"AP": Decimal(100), "ABILITY_HASTE": Decimal(100)})
    )

    assert len([event for event in powered.events if "MEL_Q_RADIANT_VOLLEY" in event.id]) > len(
        [event for event in base.events if "MEL_Q_RADIANT_VOLLEY" in event.id]
    )
    assert (
        _event(powered, "MEL_E_SOLAR_SNARE_CENTER").outputs[0].amount
        - _event(base, "MEL_E_SOLAR_SNARE_CENTER").outputs[0].amount
        == 70
    )
    rebuttal = _event(powered, "MEL_W_REBUTTAL")
    assert isinstance(rebuttal.outputs[0], ShieldOutput)
    assert rebuttal.outputs[0].amount == 150
    assert isinstance(rebuttal.outputs[1], StatModifierOutput)
    enhanced = _event(powered, "MEL_BASIC_ATTACK_1")
    assert len(enhanced.outputs) == 2
    assert enhanced.outputs[1].amount > _event(base, "MEL_BASIC_ATTACK_1").outputs[1].amount


def test_mel_reflection_is_blocked_and_control_is_not_overstated() -> None:
    """Expose movement control while refusing generic projectile immunity."""
    cog = create_default_registry(ROOT).require_cog("Mel")
    reaction = cog.build_reaction_plan(_context())

    root, slow = reaction.cast_block_windows
    assert root.control_type is ControlType.ROOT
    assert slow.control_type is ControlType.SLOW
    assert root.blocked_channels == slow.blocked_channels == (ActionChannel.MOVEMENT,)
    assert not reaction.damage_windows
    assert not reaction.control_immunity_windows
    assert "MEL_W_PROJECTILE_REFLECTION_REQUIRES_PROJECTILE_METADATA" in reaction.blockers
    assert cog.engagement_speed_multiplier(_context()) == Decimal("1.40")


def test_mel_role_reversal_and_item_policy_remain_symmetric() -> None:
    """Reverse recipients and reject item channels absent from the fixture."""
    cog = create_default_registry(ROOT).require_cog("Mel")
    reversed_plan = cog.build_action_plan(_context(as_actor=False))

    assert all(event.source is EntityId.TARGET for event in reversed_plan.events)
    assert any(
        isinstance(output, DamageOutput) and output.recipient is EntityId.ACTOR
        for event in reversed_plan.events
        for output in event.outputs
    )
    assert (
        cog.item_candidate_blocker({"id": 1, "stats": {"MANA": {}, "OMNIVAMP": {}}})
        == "MEL_ITEM_STAT_NOT_MODELED:1:MANA,OMNIVAMP"
    )
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Mel", "Garen"))
    as_target = engine.evaluate(MatchupRequest("Garen", "Mel"))
    assert as_actor.actor_action_model == as_target.opponent_action_model
    assert as_actor.actor_reaction_model == as_target.opponent_reaction_model
