"""Focused regressions for the locked Rumble champion Cog."""

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
    """Build a level-13 Rumble-versus-Garen encounter.

    :param as_actor: Place Rumble in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Rumble.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    rumble = registry.require_cog("Rumble")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        rumble.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one named Rumble event.

    :param plan: Action plan containing the expected event.
    :param event_id: Exact stable identifier.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_rumble_metadata_all_magic_damage_and_channel_timing() -> None:
    """Require evidence, all-magic damage, and Q resolving after its channel."""
    cog = create_default_registry(ROOT).require_cog("Rumble")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    for event in plan.events:
        for output in event.outputs:
            if isinstance(output, DamageOutput) and event.channel.value == "ABILITY":
                assert output.damage_type.value == "MAGIC"
    q_event = _event(plan, "RUMBLE_Q_FLAMESPITTER")
    assert q_event.at_ms == cog._Q_AT_MS + cog._Q_CHANNEL_MS
    r_event = _event(plan, "RUMBLE_R_THE_EQUALIZER")
    assert r_event.at_ms == cog._R_AT_MS + cog._R_BURN_MS


def test_rumble_reaction_plan_applies_no_hostile_control() -> None:
    """Report an empty control window set, matching Rumble's kit."""
    cog = create_default_registry(ROOT).require_cog("Rumble")
    reactions = cog.build_reaction_plan(_context())

    assert reactions.cast_block_windows == ()


def test_rumble_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Rumble is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Rumble")
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
