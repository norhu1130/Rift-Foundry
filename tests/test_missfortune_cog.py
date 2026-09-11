"""Focused regressions for the locked Miss Fortune champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *, as_actor: bool = True, item_stats: dict[str, Decimal] | None = None
) -> ParticipantContext:
    """Build a level-13 Miss-Fortune-versus-Garen encounter.

    :param as_actor: Place Miss Fortune in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Miss Fortune.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    champion = registry.require_cog("MissFortune")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        champion.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one named Miss Fortune event.

    :param plan: Action plan containing the requested event.
    :param event_id: Exact stable identifier.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_miss_fortune_metadata_ticks_and_channel_are_explicit() -> None:
    """Require evidence, eight E ticks, sixteen R waves, and determinism."""
    cog = create_default_registry(ROOT).require_cog("MissFortune")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    assert (
        len(
            [
                event
                for event in plan.events
                if "E_MAKE_IT_RAIN_" in event.id and not event.id.endswith("_CAST")
            ]
        )
        == 8
    )
    assert len([event for event in plan.events if "R_BULLET_TIME_WAVE" in event.id]) == 16
    assert "MISS_FORTUNE_Q_SECOND_TARGET_BOUNCE_NOT_MODELED" in plan.blockers


def test_miss_fortune_scalings_attack_clock_and_control_are_connected() -> None:
    """Exercise AD, AP, crit, W acceleration, and E slow semantics."""
    cog = create_default_registry(ROOT).require_cog("MissFortune")
    base = cog.build_action_plan(_context())
    powered = cog.build_action_plan(
        _context(
            item_stats={
                "AD": Decimal(100),
                "AP": Decimal(100),
                "ATTACK_SPEED": Decimal("0.5"),
                "CRITICAL_STRIKE_CHANCE": Decimal("0.5"),
            }
        )
    )

    assert (
        _event(powered, "MISS_FORTUNE_Q_DOUBLE_UP_PRIMARY").outputs[0].amount
        > _event(base, "MISS_FORTUNE_Q_DOUBLE_UP_PRIMARY").outputs[0].amount
    )
    assert (
        _event(powered, "MISS_FORTUNE_R_BULLET_TIME_WAVE_1").outputs[0].amount
        > _event(base, "MISS_FORTUNE_R_BULLET_TIME_WAVE_1").outputs[0].amount
    )
    assert len([event for event in powered.events if "BASIC_ATTACK" in event.id]) > len(
        [event for event in base.events if "BASIC_ATTACK" in event.id]
    )
    slow = cog.build_reaction_plan(_context()).cast_block_windows[0]
    assert slow.control_type is ControlType.SLOW
    assert slow.tenacity_reducible is True


def test_miss_fortune_role_reversal_and_item_policy_are_honest() -> None:
    """Reverse damage recipients and retain unsupported item-channel blockers."""
    cog = create_default_registry(ROOT).require_cog("MissFortune")
    plan = cog.build_action_plan(_context(as_actor=False))

    assert all(event.source is EntityId.TARGET for event in plan.events)
    assert any(
        isinstance(output, DamageOutput) and output.recipient is EntityId.ACTOR
        for event in plan.events
        for output in event.outputs
    )
    assert cog.engagement_speed_multiplier(_context()) > 1
    assert (
        cog.item_candidate_blocker({"id": 3, "stats": {"MANA": {}, "OMNIVAMP": {}}})
        == "MISS_FORTUNE_ITEM_STAT_NOT_MODELED:3:MANA"
    )
