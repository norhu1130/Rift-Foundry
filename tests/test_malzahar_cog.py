"""Focused regressions for the locked Malzahar champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId

ROOT = Path(__file__).resolve().parents[1]


def _context(*, as_actor: bool = True, ap: str = "0") -> ParticipantContext:
    """Build a level-13 Malzahar-versus-Garen encounter.

    :param as_actor: Place Malzahar in the actor role when true.
    :param ap: Item ability power supplied as decimal text.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    malzahar = registry.require_cog("Malzahar")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        malzahar.snapshot(level=13, item_stats={"AP": Decimal(ap)}),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def test_malzahar_metadata_refresh_segments_and_channel_are_complete() -> None:
    """Require evidence and deterministic E, voidling, and R tick groups."""
    cog = create_default_registry(ROOT).require_cog("Malzahar")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    assert any("E_MALEFIC_VISIONS_Q_REFRESH" in event.id for event in plan.events)
    assert any("E_MALEFIC_VISIONS_R_REFRESH" in event.id for event in plan.events)
    assert len([event for event in plan.events if "R_NETHER_GRASP_TICK" in event.id]) == 20
    assert any("THREE_VOIDLINGS_ATTACK" in event.id for event in plan.events)


def test_malzahar_reaction_and_ap_scaling_preserve_mechanics() -> None:
    """Anchor passive immunity, silence, suppression, and spell AP scaling."""
    cog = create_default_registry(ROOT).require_cog("Malzahar")
    reaction = cog.build_reaction_plan(_context())
    base = cog.build_action_plan(_context())
    powered = cog.build_action_plan(_context(ap="100"))

    assert reaction.damage_windows[0].multiplier == Decimal("0.10")
    assert reaction.control_immunity_windows[0].control_types == (ControlType.ALL,)
    assert tuple(window.control_type for window in reaction.cast_block_windows) == (
        ControlType.SILENCE,
        ControlType.SUPPRESSION,
    )
    base_q = next(event for event in base.events if event.id == "MALZAHAR_Q_CALL_OF_THE_VOID")
    powered_q = next(event for event in powered.events if event.id == "MALZAHAR_Q_CALL_OF_THE_VOID")
    assert next(o.amount for o in powered_q.outputs if isinstance(o, DamageOutput)) > next(
        o.amount for o in base_q.outputs if isinstance(o, DamageOutput)
    )


def test_malzahar_role_reversal_and_item_policy_are_honest() -> None:
    """Reverse hostile recipients and reject absent resource channels."""
    cog = create_default_registry(ROOT).require_cog("Malzahar")
    plan = cog.build_action_plan(_context(as_actor=False))

    assert all(event.source is EntityId.TARGET for event in plan.events)
    assert any(
        isinstance(output, DamageOutput) and output.recipient is EntityId.ACTOR
        for event in plan.events
        for output in event.outputs
    )
    assert (
        cog.item_candidate_blocker({"id": 2, "stats": {"MANA": {}, "OMNIVAMP": {}}})
        == "MALZAHAR_ITEM_STAT_NOT_MODELED:2:MANA,OMNIVAMP"
    )
