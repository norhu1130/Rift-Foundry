"""Focused regressions for the locked Wukong champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId, ResistanceReductionOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *, as_actor: bool = True, item_stats: dict[str, Decimal] | None = None
) -> ParticipantContext:
    """Build a level-13 Wukong-versus-Garen encounter.

    :param as_actor: Place Wukong in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Wukong.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    wukong = registry.require_cog("MonkeyKing")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        wukong.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one stable event from a Wukong plan.

    :param plan: Action plan containing the expected event.
    :param event_id: Exact event identifier to locate.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_wukong_metadata_q_shred_and_double_cyclone_are_explicit() -> None:
    """Require evidence, Q armor reduction, clone creation, and sixteen R ticks."""
    cog = create_default_registry(ROOT).require_cog("MonkeyKing")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    assert len([event for event in plan.events if "R_CYCLONE" in event.id]) == 16
    q = _event(plan, "MONKEY_KING_Q_CRUSHING_BLOW_1")
    assert isinstance(q.outputs[1], ResistanceReductionOutput)
    assert q.outputs[1].fraction_per_stack == Decimal("0.30")
    assert _event(plan, "MONKEY_KING_W_WARRIOR_TRICKSTER").at_ms == 150


def test_wukong_stats_engagement_and_knockups_are_connected() -> None:
    """Exercise AD, AP, attack speed, dash reach, and two airborne windows."""
    cog = create_default_registry(ROOT).require_cog("MonkeyKing")
    base = cog.build_action_plan(_context())
    powered = cog.build_action_plan(
        _context(
            item_stats={"AD": Decimal(100), "AP": Decimal(100), "ATTACK_SPEED": Decimal("0.5")}
        )
    )

    assert (
        _event(powered, "MONKEY_KING_E_NIMBUS_STRIKE").outputs[0].amount
        > _event(base, "MONKEY_KING_E_NIMBUS_STRIKE").outputs[0].amount
    )
    assert (
        _event(powered, "MONKEY_KING_R_CYCLONE_1_TICK_1").outputs[0].amount
        > _event(base, "MONKEY_KING_R_CYCLONE_1_TICK_1").outputs[0].amount
    )
    assert len([event for event in powered.events if "BASIC_ATTACK" in event.id]) > len(
        [event for event in base.events if "BASIC_ATTACK" in event.id]
    )
    reaction = cog.build_reaction_plan(_context())
    assert len(reaction.cast_block_windows) == 2
    assert all(
        window.control_type is ControlType.AIRBORNE for window in reaction.cast_block_windows
    )
    assert cog.engagement_dash_distance(_context()) == 950


def test_wukong_role_reversal_and_item_policy_are_honest() -> None:
    """Reverse all outputs and retain unsupported item and passive blockers."""
    cog = create_default_registry(ROOT).require_cog("MonkeyKing")
    plan = cog.build_action_plan(_context(as_actor=False))

    assert all(event.source is EntityId.TARGET for event in plan.events)
    assert any(
        isinstance(output, DamageOutput) and output.recipient is EntityId.ACTOR
        for event in plan.events
        for output in event.outputs
    )
    assert "MONKEY_KING_PASSIVE_ARMOR_AND_REGEN_STACKS_NOT_MODELED" in plan.blockers
    assert (
        cog.item_candidate_blocker({"id": 4, "stats": {"MANA": {}, "OMNIVAMP": {}}})
        == "MONKEY_KING_ITEM_STAT_NOT_MODELED:4:MANA,OMNIVAMP"
    )
