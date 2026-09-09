"""Focused regressions for the locked Taric champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import (
    DamageOutput,
    EntityId,
    HealOutput,
    ShieldOutput,
    StatModifierOutput,
)

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *, as_actor: bool = True, item_stats: dict[str, Decimal] | None = None
) -> ParticipantContext:
    """Build a level-13 Taric-versus-Garen encounter.

    :param as_actor: Place Taric in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Taric.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    taric = registry.require_cog("Taric")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        taric.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one named Taric event.

    :param plan: Action plan containing the expected event.
    :param event_id: Exact stable identifier.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_taric_metadata_shield_heal_and_stun_are_explicit() -> None:
    """Require evidence, the W shield/armor, the Q heal, and the E stun."""
    cog = create_default_registry(ROOT).require_cog("Taric")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    w_outputs = _event(plan, "TARIC_W_BASTION").outputs
    assert isinstance(w_outputs[0], StatModifierOutput)
    assert isinstance(w_outputs[1], ShieldOutput)
    assert isinstance(_event(plan, "TARIC_Q_STARLIGHTS_TOUCH").outputs[0], HealOutput)
    e_outputs = _event(plan, "TARIC_E_DAZZLE").outputs
    assert isinstance(e_outputs[0], DamageOutput)


def test_taric_reaction_plan_exposes_the_e_stun() -> None:
    """Expose the Dazzle stun as a control window."""
    cog = create_default_registry(ROOT).require_cog("Taric")
    reactions = cog.build_reaction_plan(_context())

    assert len(reactions.cast_block_windows) == 1
    assert reactions.cast_block_windows[0].control_type is ControlType.STUN


def test_taric_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Taric is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Taric")
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
