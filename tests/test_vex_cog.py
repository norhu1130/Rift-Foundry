"""Focused regressions for the locked Vex champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId, ShieldOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *, as_actor: bool = True, item_stats: dict[str, Decimal] | None = None
) -> ParticipantContext:
    """Build a level-13 Vex-versus-Garen encounter.

    :param as_actor: Place Vex in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Vex.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    vex = registry.require_cog("Vex")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        vex.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one named Vex event.

    :param plan: Action plan containing the expected event.
    :param event_id: Exact stable identifier.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_vex_metadata_shield_and_mark_recast_are_explicit() -> None:
    """Require evidence, the W shield, and both Shadow Surge hits."""
    cog = create_default_registry(ROOT).require_cog("Vex")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    w_outputs = _event(plan, "VEX_W_PERSONAL_SPACE").outputs
    assert any(isinstance(output, ShieldOutput) for output in w_outputs)
    assert len([e for e in plan.events if "R_SHADOW_SURGE" in e.id]) == 2
    for event in plan.events:
        for output in event.outputs:
            if isinstance(output, DamageOutput) and event.channel.value == "ABILITY":
                assert output.damage_type.value == "MAGIC"


def test_vex_reaction_plan_applies_no_hostile_control() -> None:
    """Report an empty control window set, matching Vex's kit."""
    cog = create_default_registry(ROOT).require_cog("Vex")
    reactions = cog.build_reaction_plan(_context())

    assert reactions.cast_block_windows == ()


def test_vex_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Vex is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Vex")
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
