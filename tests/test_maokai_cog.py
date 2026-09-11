"""Focused regressions for the locked Maokai champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId, HealOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *, as_actor: bool = True, item_stats: dict[str, Decimal] | None = None
) -> ParticipantContext:
    """Build a level-13 Maokai-versus-Garen encounter.

    :param as_actor: Place Maokai in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Maokai.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    maokai = registry.require_cog("Maokai")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        maokai.snapshot(level=13, item_stats=item_stats),
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


def test_maokai_metadata_rotation_and_passive_heal_are_complete() -> None:
    """Require locked evidence, all spells, and one Sap Magic heal."""
    cog = create_default_registry(ROOT).require_cog("Maokai")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    for event_id in (
        "MAOKAI_R_NATURES_GRASP_MAX_ROOT",
        "MAOKAI_E_SAPLING_NORMAL_EXPLOSION",
        "MAOKAI_W_TWISTED_ADVANCE",
        "MAOKAI_Q_BRAMBLE_SMASH",
    ):
        assert _event(plan, event_id)
    assert any(
        isinstance(output, HealOutput)
        for output in _event(plan, "MAOKAI_PASSIVE_SAP_MAGIC_ATTACK").outputs
    )


def test_maokai_hp_ap_and_control_types_reach_distinct_mechanics() -> None:
    """Exercise AP/bonus-health scaling and typed displacement windows."""
    cog = create_default_registry(ROOT).require_cog("Maokai")
    base = cog.build_action_plan(_context())
    powered = cog.build_action_plan(_context(item_stats={"AP": Decimal(100), "HP": Decimal(500)}))
    base_e = next(
        output.amount
        for output in _event(base, "MAOKAI_E_SAPLING_NORMAL_EXPLOSION").outputs
        if isinstance(output, DamageOutput)
    )
    powered_e = next(
        output.amount
        for output in _event(powered, "MAOKAI_E_SAPLING_NORMAL_EXPLOSION").outputs
        if isinstance(output, DamageOutput)
    )
    reaction = cog.build_reaction_plan(_context())

    assert powered_e > base_e
    assert tuple(window.control_type for window in reaction.cast_block_windows) == (
        ControlType.ROOT,
        ControlType.SLOW,
        ControlType.ROOT,
        ControlType.AIRBORNE,
        ControlType.SLOW,
    )
    assert reaction.cast_block_windows[3].tenacity_reducible is False


def test_maokai_role_reversal_sustain_and_item_policy_are_honest() -> None:
    """Reverse damage and avoid claiming unconditional lane sustain."""
    cog = create_default_registry(ROOT).require_cog("Maokai")
    plan = cog.build_action_plan(_context(as_actor=False))

    assert all(event.source is EntityId.TARGET for event in plan.events)
    assert any(
        isinstance(output, DamageOutput) and output.recipient is EntityId.ACTOR
        for event in plan.events
        for output in event.outputs
    )
    sustain, blockers = cog.lane_sustain_extra_health(
        _context(), duration_ms=30_000, no_damage_delay_ms=8000
    )
    assert sustain == 0
    assert blockers == ("MAOKAI_PASSIVE_REQUIRES_BASIC_ATTACK_TARGET",)
    assert (
        cog.item_candidate_blocker({"id": 2, "stats": {"MANA": {}, "OMNIVAMP": {}}})
        == "MAOKAI_ITEM_STAT_NOT_MODELED:2:MANA,OMNIVAMP"
    )
