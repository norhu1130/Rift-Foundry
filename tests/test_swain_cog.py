"""Focused regressions for the locked Swain champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId, HealOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *, as_actor: bool = True, item_stats: dict[str, Decimal] | None = None
) -> ParticipantContext:
    """Build a level-13 Swain-versus-Garen encounter.

    :param as_actor: Place Swain in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Swain.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    swain = registry.require_cog("Swain")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        swain.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def test_swain_metadata_root_and_drain_ticks_are_explicit() -> None:
    """Require evidence, the E root, and R's half-second drain-and-heal ticks."""
    cog = create_default_registry(ROOT).require_cog("Swain")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    ticks = [e for e in plan.events if "R_DEMONIC_ASCENSION_TICK" in e.id]
    # Demon Power lasts DemonPowerMax / DemonPowerDegen = 5 s, ticking every 0.5 s;
    # cast at 2.9 s, all ten ticks land inside the eight-second encounter.
    assert len(ticks) == 10
    assert all(isinstance(tick.outputs[1], HealOutput) for tick in ticks)
    assert (
        ticks[0].outputs[0].amount
        == (Decimal(25) + Decimal("0.04") * _context().snapshot.ability_power) / 2
    )
    for event in plan.events:
        for output in event.outputs:
            if isinstance(output, DamageOutput) and event.channel.value == "ABILITY":
                assert output.damage_type.value == "MAGIC"


def test_swain_reaction_plan_exposes_the_e_root() -> None:
    """Expose the Nevermove root as a control window."""
    cog = create_default_registry(ROOT).require_cog("Swain")
    reactions = cog.build_reaction_plan(_context())

    assert len(reactions.cast_block_windows) == 1
    assert reactions.cast_block_windows[0].control_type is ControlType.ROOT


def test_swain_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Swain is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Swain")
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
