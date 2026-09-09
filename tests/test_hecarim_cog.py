"""Focused regressions for the locked Hecarim champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId, HealOutput, StatModifierOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    as_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a level-13 Hecarim-versus-Garen context.

    :param as_actor: Place Hecarim in the actor role when true.
    :param item_stats: Optional item modifiers for Hecarim.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    hecarim = registry.require_cog("Hecarim")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        hecarim.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Locate one event by stable identifier.

    :param plan: Action plan exposing an events tuple.
    :param event_id: Exact event identifier to locate.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_hecarim_metadata_and_evidence_are_complete() -> None:
    """Require recommendation capabilities and all locked evidence forms."""
    cog = create_default_registry(ROOT).require_cog("Hecarim")

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert len(cog.evidence_refs) == 3
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)


def test_hecarim_rotation_models_q_stacks_w_ticks_and_max_charge_entry() -> None:
    """Anchor defining stack, leech, resistance, and engagement events."""
    cog = create_default_registry(ROOT).require_cog("Hecarim")
    plan = cog.build_action_plan(_context())

    assert plan == cog.build_action_plan(_context())
    q_events = [event for event in plan.events if event.id.startswith("HECARIM_Q_RAMPAGE_")]
    w_ticks = [event for event in plan.events if "SPIRIT_OF_DREAD_TICK" in event.id]
    assert len(q_events) == 4
    assert len(w_ticks) == 8
    assert q_events[-1].id.endswith("STACKS_3")
    assert any(isinstance(output, HealOutput) for output in w_ticks[0].outputs)
    w_start = _event(plan, "HECARIM_W_SPIRIT_OF_DREAD_START")
    assert (
        len([output for output in w_start.outputs if isinstance(output, StatModifierOutput)]) == 2
    )
    assert cog.engagement_speed_multiplier(_context()) == Decimal("1.65")
    assert cog.engagement_dash_distance(_context()) == 1000


def test_hecarim_haste_movement_and_ap_feed_distinct_mechanics() -> None:
    """Exercise Q cadence, Warpath AD, and magical ability scaling."""
    cog = create_default_registry(ROOT).require_cog("Hecarim")
    base = cog.build_action_plan(_context())
    modified = cog.build_action_plan(
        _context(
            item_stats={
                "ABILITY_HASTE": Decimal(100),
                "MOVE_SPEED_FLAT": Decimal(50),
                "AP": Decimal(100),
            }
        )
    )

    base_q = [event for event in base.events if event.id.startswith("HECARIM_Q_RAMPAGE_")]
    modified_q = [event for event in modified.events if event.id.startswith("HECARIM_Q_RAMPAGE_")]
    assert len(modified_q) > len(base_q)
    base_e = next(
        output.amount
        for output in _event(base, "HECARIM_E_DEVASTATING_CHARGE_MAX_ATTACK").outputs
        if isinstance(output, DamageOutput)
    )
    modified_e = next(
        output.amount
        for output in _event(modified, "HECARIM_E_DEVASTATING_CHARGE_MAX_ATTACK").outputs
        if isinstance(output, DamageOutput)
    )
    base_r = next(
        output.amount
        for output in _event(base, "HECARIM_R_ONSLAUGHT_MAX_RANGE").outputs
        if isinstance(output, DamageOutput)
    )
    modified_r = next(
        output.amount
        for output in _event(modified, "HECARIM_R_ONSLAUGHT_MAX_RANGE").outputs
        if isinstance(output, DamageOutput)
    )
    assert modified_e > base_e
    assert modified_r > base_r


def test_hecarim_control_types_and_role_reversal_are_preserved() -> None:
    """Distinguish reducible fear from displacement after role reversal."""
    cog = create_default_registry(ROOT).require_cog("Hecarim")
    reaction = cog.build_reaction_plan(_context())
    reversed_plan = cog.build_action_plan(_context(as_actor=False))

    assert tuple(window.control_type for window in reaction.cast_block_windows) == (
        ControlType.FEAR,
        ControlType.AIRBORNE,
    )
    assert reaction.cast_block_windows[0].tenacity_reducible is True
    assert reaction.cast_block_windows[1].tenacity_reducible is False
    assert all(event.source is EntityId.TARGET for event in reversed_plan.events)
    assert any(
        isinstance(output, DamageOutput) and output.recipient is EntityId.ACTOR
        for event in reversed_plan.events
        for output in event.outputs
    )


def test_hecarim_lane_and_item_policies_remain_honest() -> None:
    """Avoid free lane healing and reject unrepresented resource channels."""
    cog = create_default_registry(ROOT).require_cog("Hecarim")
    sustain, blockers = cog.lane_sustain_extra_health(
        _context(),
        duration_ms=30_000,
        no_damage_delay_ms=8000,
    )

    assert sustain == 0
    assert blockers == ("HECARIM_W_LANE_HEAL_REQUIRES_NEARBY_DAMAGE",)
    assert (
        cog.item_candidate_blocker(
            {
                "id": 1,
                "stats": {
                    "AD": {},
                    "AP": {},
                    "ABILITY_HASTE": {},
                    "MOVE_SPEED_PERCENT": {},
                },
            }
        )
        is None
    )
    assert (
        cog.item_candidate_blocker({"id": 2, "stats": {"MANA": {}, "OMNIVAMP": {}}})
        == "HECARIM_ITEM_STAT_NOT_MODELED:2:MANA,OMNIVAMP"
    )
