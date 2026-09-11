"""Focused regressions for the locked Master Yi champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId, MissingHealthHealOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *, as_actor: bool = True, item_stats: dict[str, Decimal] | None = None
) -> ParticipantContext:
    """Build a level-13 Master-Yi-versus-Garen encounter.

    :param as_actor: Place Master Yi in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Master Yi.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    yi = registry.require_cog("MasterYi")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        yi.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def test_master_yi_metadata_attacks_and_meditate_are_complete() -> None:
    """Require evidence, deterministic attacks, Double Strike, and W healing."""
    cog = create_default_registry(ROOT).require_cog("MasterYi")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    assert any("DOUBLE_STRIKE" in event.id for event in plan.events)
    assert len([event for event in plan.events if "W_MEDITATE_TICK" in event.id]) == 2
    tick = (Decimal(120) + _context().snapshot.ability_power) / Decimal(8)
    assert all(
        event.outputs
        == (
            MissingHealthHealOutput(
                EntityId.ACTOR, tick / _context().snapshot.max_hp, base_amount=tick
            ),
        )
        for event in plan.events
        if "W_MEDITATE_TICK" in event.id
    )


def test_master_yi_attack_speed_haste_crit_and_reaction_are_connected() -> None:
    """Exercise attack clock, Q availability, expected crit, W DR, and slow immunity."""
    cog = create_default_registry(ROOT).require_cog("MasterYi")
    base = cog.build_action_plan(_context())
    powered = cog.build_action_plan(
        _context(
            item_stats={
                "ATTACK_SPEED": Decimal("0.8"),
                "ABILITY_HASTE": Decimal(100),
                "CRITICAL_STRIKE_CHANCE": Decimal("0.5"),
            }
        )
    )
    assert len([event for event in powered.events if "ATTACK_" in event.id]) > len(
        [event for event in base.events if "ATTACK_" in event.id]
    )
    assert len([event for event in powered.events if "Q_ALPHA_STRIKE" in event.id]) == 2
    reaction = cog.build_reaction_plan(_context())
    assert reaction.damage_windows[0].multiplier < reaction.damage_windows[1].multiplier
    assert reaction.control_immunity_windows[0].control_types == (ControlType.SLOW,)


def test_master_yi_role_reversal_sustain_and_item_policy_are_honest() -> None:
    """Reverse damage and avoid unconditional Meditate sustain claims."""
    cog = create_default_registry(ROOT).require_cog("MasterYi")
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
    assert blockers == ("MASTER_YI_W_REQUIRES_MANA_AND_MISSING_HEALTH_STATE",)
    assert (
        cog.item_candidate_blocker({"id": 2, "stats": {"MANA": {}, "OMNIVAMP": {}}})
        == "MASTER_YI_ITEM_STAT_NOT_MODELED:2:MANA"
    )
