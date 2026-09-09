"""Focused regressions for the locked Sejuani champion Cog."""

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
    """Build a level-13 Sejuani-versus-Garen encounter.

    :param as_actor: Place Sejuani in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Sejuani.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    sejuani = registry.require_cog("Sejuani")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        sejuani.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def test_sejuani_metadata_double_strike_knockup_and_stun_are_explicit() -> None:
    """Require evidence, both W hits, the Q knock-up, and the R stun."""
    cog = create_default_registry(ROOT).require_cog("Sejuani")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    assert len([e for e in plan.events if "W_WINTERS_WRATH" in e.id]) == 2


def test_sejuani_reaction_plan_exposes_knockup_and_stun() -> None:
    """Expose the Arctic Assault knock-up and Glacial Prison stun."""
    cog = create_default_registry(ROOT).require_cog("Sejuani")
    reactions = cog.build_reaction_plan(_context())

    types = {window.control_type for window in reactions.cast_block_windows}
    assert types == {ControlType.AIRBORNE, ControlType.STUN}


def test_sejuani_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Sejuani is the actor or target."""
    cog = create_default_registry(ROOT).require_cog("Sejuani")
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
