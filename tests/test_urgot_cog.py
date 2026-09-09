"""Focused regressions for the locked Urgot champion Cog."""

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
    """Build a level-13 Urgot-versus-Garen encounter.

    :param as_actor: Place Urgot in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Urgot.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    urgot = registry.require_cog("Urgot")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        urgot.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def test_urgot_metadata_all_physical_damage_and_r_fear() -> None:
    """Require evidence, all-physical damage, and R applying fear not a stun."""
    cog = create_default_registry(ROOT).require_cog("Urgot")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    for event in plan.events:
        for output in event.outputs:
            if isinstance(output, DamageOutput) and event.channel.value == "ABILITY":
                assert output.damage_type.value == "PHYSICAL"


def test_urgot_reaction_plan_exposes_stun_and_fear() -> None:
    """Expose the Disdain stun and the Fear Beyond Death fear."""
    cog = create_default_registry(ROOT).require_cog("Urgot")
    reactions = cog.build_reaction_plan(_context())

    types = {window.control_type for window in reactions.cast_block_windows}
    assert types == {ControlType.STUN, ControlType.FEAR}


def test_urgot_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Urgot is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Urgot")
    actor_plan = cog.build_action_plan(_context(as_actor=True))
    target_plan = cog.build_action_plan(_context(as_actor=False))

    actor_ids = {event.id.split("_", 1)[1] for event in actor_plan.events}
    target_ids = {event.id.split("_", 1)[1] for event in target_plan.events}
    assert actor_ids == target_ids
    for event in target_plan.events:
        assert event.source is EntityId.TARGET
        for output in event.outputs:
            if isinstance(output, DamageOutput):
                assert output.recipient is EntityId.ACTOR
