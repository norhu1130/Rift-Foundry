"""Focused regressions for the locked Riven champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import (
    DamageOutput,
    EntityId,
    MissingHealthDamageOutput,
    ShieldOutput,
)

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *, as_actor: bool = True, item_stats: dict[str, Decimal] | None = None
) -> ParticipantContext:
    """Build a level-13 Riven-versus-Garen encounter.

    :param as_actor: Place Riven in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Riven.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    riven = registry.require_cog("Riven")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        riven.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one named Riven event.

    :param plan: Action plan containing the expected event.
    :param event_id: Exact stable identifier.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_riven_metadata_shield_stun_triple_slash_and_missing_health_r() -> None:
    """Require evidence, the E shield, three Q hits, and R's missing-health scale."""
    cog = create_default_registry(ROOT).require_cog("Riven")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    assert isinstance(_event(plan, "RIVEN_E_VALOR").outputs[0], ShieldOutput)
    assert len([e for e in plan.events if "Q_BROKEN_WINGS" in e.id]) == 3
    r_outputs = _event(plan, "RIVEN_R_BLADE_OF_THE_EXILE").outputs
    assert isinstance(r_outputs[0], MissingHealthDamageOutput)


def test_riven_reaction_plan_exposes_stun_and_knockup() -> None:
    """Expose the Ki Burst stun and third Broken Wings knock-up."""
    cog = create_default_registry(ROOT).require_cog("Riven")
    reactions = cog.build_reaction_plan(_context())

    types = {window.control_type for window in reactions.cast_block_windows}
    assert types == {ControlType.STUN, ControlType.AIRBORNE}


def test_riven_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Riven is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Riven")
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
