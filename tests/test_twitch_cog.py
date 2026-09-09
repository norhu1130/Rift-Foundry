"""Focused regressions for the locked Twitch champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *, as_actor: bool = True, item_stats: dict[str, Decimal] | None = None
) -> ParticipantContext:
    """Build a level-13 Twitch-versus-Garen encounter.

    :param as_actor: Place Twitch in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Twitch.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    twitch = registry.require_cog("Twitch")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        twitch.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one named Twitch event.

    :param plan: Action plan containing the expected event.
    :param event_id: Exact stable identifier.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_twitch_metadata_expunge_deals_split_physical_and_magic_damage() -> None:
    """Require evidence and Expunge's stack-based physical and magic hits."""
    cog = create_default_registry(ROOT).require_cog("Twitch")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    outputs = _event(plan, "TWITCH_E_EXPUNGE").outputs
    types = {output.damage_type.value for output in outputs if isinstance(output, DamageOutput)}
    assert types == {"PHYSICAL", "MAGIC"}


def test_twitch_reaction_plan_applies_no_hostile_control() -> None:
    """Report an empty control window set, matching Twitch's kit."""
    cog = create_default_registry(ROOT).require_cog("Twitch")
    reactions = cog.build_reaction_plan(_context())

    assert reactions.cast_block_windows == ()


def test_twitch_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Twitch is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Twitch")
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
