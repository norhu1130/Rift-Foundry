"""Focused regressions for the locked Veigar champion Cog."""

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
    """Build a level-13 Veigar-versus-Garen encounter.

    :param as_actor: Place Veigar in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Veigar.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    veigar = registry.require_cog("Veigar")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        veigar.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one named Veigar event.

    :param plan: Action plan containing the expected event.
    :param event_id: Exact stable identifier.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_veigar_metadata_cage_stun_and_magic_damage_are_explicit() -> None:
    """Require evidence, the E stun, and all-magic damage output."""
    cog = create_default_registry(ROOT).require_cog("Veigar")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    for event in plan.events:
        for output in event.outputs:
            if isinstance(output, DamageOutput) and event.channel.value == "ABILITY":
                assert output.damage_type.value == "MAGIC"
    assert _event(plan, "VEIGAR_W_DARK_MATTER").at_ms == (
        cog._W_AT_MS + cog._W_IMPACT_DELAY_MS
    )


def test_veigar_reaction_plan_exposes_the_e_stun() -> None:
    """Expose the Event Horizon cage stun as a control window."""
    cog = create_default_registry(ROOT).require_cog("Veigar")
    reactions = cog.build_reaction_plan(_context())

    assert len(reactions.cast_block_windows) == 1
    window = reactions.cast_block_windows[0]
    assert window.control_type is ControlType.STUN


def test_veigar_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Veigar is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Veigar")
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
