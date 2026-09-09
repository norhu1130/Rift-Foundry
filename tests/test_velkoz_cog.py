"""Focused regressions for the locked Vel'Koz champion Cog."""

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
    """Build a level-13 Vel'Koz-versus-Garen encounter.

    :param as_actor: Place Vel'Koz in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Vel'Koz.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    velkoz = registry.require_cog("Velkoz")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        velkoz.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def test_velkoz_metadata_two_w_hits_and_e_knockup_are_explicit() -> None:
    """Require evidence, both W hits, and E's knock-up rather than a stun."""
    cog = create_default_registry(ROOT).require_cog("Velkoz")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    assert len([e for e in plan.events if "W_VOID_RIFT" in e.id]) == 2
    for event in plan.events:
        for output in event.outputs:
            if isinstance(output, DamageOutput) and event.channel.value == "ABILITY":
                assert output.damage_type.value == "MAGIC"


def test_velkoz_reaction_plan_exposes_a_knockup_not_a_stun() -> None:
    """Expose Tectonic Disruption as a knock-up, matching its locked text."""
    cog = create_default_registry(ROOT).require_cog("Velkoz")
    reactions = cog.build_reaction_plan(_context())

    assert len(reactions.cast_block_windows) == 1
    assert reactions.cast_block_windows[0].control_type is ControlType.AIRBORNE


def test_velkoz_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Vel'Koz is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Velkoz")
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
