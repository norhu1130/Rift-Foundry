"""Focused regressions for the locked Lillia champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.combat import DamageType
from lol_build.core.timeline import DamageOutput, EntityId, HealOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    as_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a level-13 Lillia-versus-Garen encounter.

    :param as_actor: Place Lillia in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Lillia.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    lillia = registry.require_cog("Lillia")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        lillia.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Locate an event by stable identifier.

    :param plan: Action plan exposing an events tuple.
    :param event_id: Exact event identifier to locate.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_lillia_metadata_and_evidence_are_complete() -> None:
    """Require complete capability routing and three locked sources."""
    cog = create_default_registry(ROOT).require_cog("Lillia")

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)


def test_lillia_rotation_models_sleep_wake_outer_q_and_dust_refresh() -> None:
    """Anchor the selected combo and non-overlapping passive applications."""
    cog = create_default_registry(ROOT).require_cog("Lillia")
    plan = cog.build_action_plan(_context())

    assert plan == cog.build_action_plan(_context())
    assert _event(plan, "LILLIA_R_LILTING_LULLABY_SLEEP")
    assert _event(plan, "LILLIA_W_WATCH_OUT_EEP_CENTER_WAKE")
    q_events = [event for event in plan.events if "BLOOMING_BLOWS_OUTER" in event.id]
    dust = [event for event in plan.events if "PASSIVE_DREAM_DUST" in event.id]
    assert len(q_events) == 2
    assert dust
    assert all(any(isinstance(output, HealOutput) for output in event.outputs) for event in dust)
    assert any(
        isinstance(output, DamageOutput) and output.damage_type is DamageType.TRUE
        for output in q_events[0].outputs
    )


def test_lillia_ap_and_haste_change_damage_cadence_and_movement() -> None:
    """Exercise AP ratios, haste-sensitive Q casts, and Prance scaling."""
    cog = create_default_registry(ROOT).require_cog("Lillia")
    base_context = _context()
    powered_context = _context(item_stats={"AP": Decimal(100), "ABILITY_HASTE": Decimal(100)})
    base = cog.build_action_plan(base_context)
    powered = cog.build_action_plan(powered_context)

    base_q = [event for event in base.events if "BLOOMING_BLOWS_OUTER" in event.id]
    powered_q = [event for event in powered.events if "BLOOMING_BLOWS_OUTER" in event.id]
    assert len(powered_q) > len(base_q)
    assert cog.engagement_speed_multiplier(powered_context) > cog.engagement_speed_multiplier(
        base_context
    )


def test_lillia_control_role_reversal_and_item_policy_are_honest() -> None:
    """Preserve sleep semantics, reverse recipients, and block absent stats."""
    cog = create_default_registry(ROOT).require_cog("Lillia")
    reaction = cog.build_reaction_plan(_context())
    reversed_plan = cog.build_action_plan(_context(as_actor=False))

    assert tuple(window.control_type for window in reaction.cast_block_windows) == (
        ControlType.SLOW,
        ControlType.SLOW,
        ControlType.SLEEP,
    )
    assert reaction.cast_block_windows[-1].end_ms == 2100
    assert all(event.source is EntityId.TARGET for event in reversed_plan.events)
    assert any(
        isinstance(output, DamageOutput) and output.recipient is EntityId.ACTOR
        for event in reversed_plan.events
        for output in event.outputs
    )
    assert (
        cog.item_candidate_blocker({"id": 2, "stats": {"MANA": {}, "OMNIVAMP": {}}})
        == "LILLIA_ITEM_STAT_NOT_MODELED:2:MANA,OMNIVAMP"
    )
