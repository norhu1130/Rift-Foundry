"""Focused regressions for the locked Gangplank champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId, HealOutput, RemoveStatusOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    as_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a level-13 Gangplank-versus-Garen context.

    :param as_actor: Place Gangplank in the actor role when true.
    :param item_stats: Optional item modifiers for Gangplank.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    gangplank = registry.require_cog("Gangplank")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        gangplank.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Locate one event by stable identifier.

    :param plan: Action plan exposing an events tuple.
    :param event_id: Exact identifier to locate.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_gangplank_metadata_and_evidence_are_complete() -> None:
    """Require recommendation capabilities and all three locked sources."""
    cog = create_default_registry(ROOT).require_cog("Gangplank")

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert len(cog.evidence_refs) == 3
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)


def test_gangplank_rotation_models_barrel_reset_citrus_and_twelve_waves() -> None:
    """Anchor the defining fixture events and transparent engine blockers."""
    cog = create_default_registry(ROOT).require_cog("Gangplank")
    plan = cog.build_action_plan(_context())

    assert plan == cog.build_action_plan(_context())
    assert len([event for event in plan.events if "CANNON_BARRAGE_WAVE" in event.id]) == 12
    assert _event(plan, "GANGPLANK_PASSIVE_TRIAL_BY_FIRE_AFTER_KEG")
    barrel_damage = next(
        output
        for output in _event(plan, "GANGPLANK_E_Q_POWDER_KEG_DETONATION").outputs
        if isinstance(output, DamageOutput)
    )
    assert barrel_damage.percent_resistance_penetration == Decimal("0.40")
    citrus = _event(plan, "GANGPLANK_W_REMOVE_SCURVY")
    assert any(isinstance(output, RemoveStatusOutput) for output in citrus.outputs)
    assert any(isinstance(output, HealOutput) for output in citrus.outputs)
    assert "GANGPLANK_BARREL_FORTY_PERCENT_ARMOR_IGNORE_NOT_MODELED" not in plan.blockers


def test_gangplank_ad_ap_and_haste_reach_distinct_events() -> None:
    """Verify damage scaling and Parrrley cooldown scheduling channels."""
    cog = create_default_registry(ROOT).require_cog("Gangplank")
    base = cog.build_action_plan(_context())
    powered = cog.build_action_plan(_context(item_stats={"AD": Decimal(50), "AP": Decimal(100)}))
    hasted = cog.build_action_plan(_context(item_stats={"ABILITY_HASTE": Decimal(100)}))

    base_barrel = next(
        output.amount
        for output in _event(base, "GANGPLANK_E_Q_POWDER_KEG_DETONATION").outputs
        if isinstance(output, DamageOutput)
    )
    powered_barrel = next(
        output.amount
        for output in _event(powered, "GANGPLANK_E_Q_POWDER_KEG_DETONATION").outputs
        if isinstance(output, DamageOutput)
    )
    base_wave = next(
        output.amount
        for output in _event(base, "GANGPLANK_R_CANNON_BARRAGE_WAVE_1").outputs
        if isinstance(output, DamageOutput)
    )
    powered_wave = next(
        output.amount
        for output in _event(powered, "GANGPLANK_R_CANNON_BARRAGE_WAVE_1").outputs
        if isinstance(output, DamageOutput)
    )
    assert powered_barrel > base_barrel
    assert powered_wave > base_wave
    assert (
        _event(hasted, "GANGPLANK_Q_PARRRLEY_DIRECT").at_ms
        < _event(base, "GANGPLANK_Q_PARRRLEY_DIRECT").at_ms
    )


def test_gangplank_reaction_and_role_reversal_remain_causal() -> None:
    """Keep slows movement-only and bind damage to the opposite participant."""
    cog = create_default_registry(ROOT).require_cog("Gangplank")
    reaction = cog.build_reaction_plan(_context())
    reversed_plan = cog.build_action_plan(_context(as_actor=False))

    assert tuple(window.control_type for window in reaction.cast_block_windows) == (
        ControlType.SLOW,
        ControlType.SLOW,
    )
    assert all(event.source is EntityId.TARGET for event in reversed_plan.events)
    assert any(
        isinstance(output, DamageOutput) and output.recipient is EntityId.ACTOR
        for event in reversed_plan.events
        for output in event.outputs
    )


def test_gangplank_item_policy_rejects_unrepresented_crit_and_resource_stats() -> None:
    """Accept modeled damage stats while rejecting unsupported channels."""
    cog = create_default_registry(ROOT).require_cog("Gangplank")

    assert (
        cog.item_candidate_blocker(
            {"id": 1, "stats": {"AD": {}, "AP": {}, "ABILITY_HASTE": {}, "HP": {}}}
        )
        is None
    )
    assert (
        cog.item_candidate_blocker({"id": 2, "stats": {"CRITICAL_STRIKE_CHANCE": {}, "MANA": {}}})
        == "GANGPLANK_ITEM_STAT_NOT_MODELED:2:CRITICAL_STRIKE_CHANCE,MANA"
    )
