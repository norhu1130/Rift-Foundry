"""Focused regressions for the locked Lulu champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import (
    DamageOutput,
    EntityId,
    MaxHealthModifierOutput,
    ShieldOutput,
)

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    as_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a level-13 Lulu-versus-Garen encounter.

    :param as_actor: Place Lulu in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Lulu.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    lulu = registry.require_cog("Lulu")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        lulu.snapshot(level=13, item_stats=item_stats),
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


def test_lulu_metadata_and_self_target_variants_are_complete() -> None:
    """Require locked evidence and self-target W/E/R without enemy variants."""
    cog = create_default_registry(ROOT).require_cog("Lulu")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    assert isinstance(_event(plan, "LULU_E_HELP_PIX_SELF").outputs[0], ShieldOutput)
    assert isinstance(
        _event(plan, "LULU_R_WILD_GROWTH_SELF").outputs[0], MaxHealthModifierOutput
    )
    assert all("POLYMORPH" not in event.id for event in plan.events)


def test_lulu_pix_attacks_and_ap_scaling_are_represented() -> None:
    """Anchor three Pix bolts per attack and AP-dependent defensive outputs."""
    cog = create_default_registry(ROOT).require_cog("Lulu")
    base = cog.build_action_plan(_context())
    powered = cog.build_action_plan(_context(item_stats={"AP": Decimal(100)}))

    attack = next(event for event in base.events if "BASIC_ATTACK_WITH_PIX" in event.id)
    assert len([output for output in attack.outputs if isinstance(output, DamageOutput)]) == 4
    base_shield = _event(base, "LULU_E_HELP_PIX_SELF").outputs[0]
    powered_shield = _event(powered, "LULU_E_HELP_PIX_SELF").outputs[0]
    assert powered_shield.amount > base_shield.amount
    assert cog.engagement_speed_multiplier(_context(item_stats={"AP": Decimal(100)})) > (
        cog.engagement_speed_multiplier(_context())
    )


def test_lulu_control_role_reversal_and_item_policy_are_honest() -> None:
    """Preserve airborne semantics, reverse damage, and block absent stats."""
    cog = create_default_registry(ROOT).require_cog("Lulu")
    reaction = cog.build_reaction_plan(_context())
    reversed_plan = cog.build_action_plan(_context(as_actor=False))

    assert reaction.cast_block_windows[0].control_type is ControlType.AIRBORNE
    assert reaction.cast_block_windows[0].tenacity_reducible is False
    assert all(event.source is EntityId.TARGET for event in reversed_plan.events)
    assert any(
        isinstance(output, DamageOutput) and output.recipient is EntityId.ACTOR
        for event in reversed_plan.events
        for output in event.outputs
    )
    assert (
        cog.item_candidate_blocker(
            {"id": 2, "stats": {"HEAL_SHIELD_POWER": {}, "MANA": {}}}
        )
        == "LULU_ITEM_STAT_NOT_MODELED:2:HEAL_SHIELD_POWER,MANA"
    )
