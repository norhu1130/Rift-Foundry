"""Focused regressions for the locked Sylas champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import (
    DamageOutput,
    EntityId,
    MissingHealthHealOutput,
)

ROOT = Path(__file__).resolve().parents[1]


def _context(*, as_actor: bool = True) -> ParticipantContext:
    """Build a level-13 Sylas-versus-Garen encounter.

    :param as_actor: Place Sylas in the actor role when true.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    cog = registry.require_cog("Sylas")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        cog.snapshot(level=13),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one named event.

    :param plan: Action plan containing the expected event.
    :param event_id: Exact stable identifier.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_sylas_is_modeled_with_locked_evidence() -> None:
    """Require evidence, the duel capabilities, and a deterministic plan."""
    cog = create_default_registry(ROOT).require_cog("Sylas")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    assert plan.events == tuple(sorted(plan.events, key=lambda e: (e.at_ms, e.sequence)))


def test_sylas_kingslayer_heal_grows_with_missing_health() -> None:
    """Heal for MinHealing, amplified as Sylas loses health, and pull with a knock-up."""
    cog = create_default_registry(ROOT).require_cog("Sylas")
    context = _context()
    plan = cog.build_action_plan(context)
    heal = _event(plan, "SYLAS_W_KINGSLAYER").outputs[1]

    assert isinstance(heal, MissingHealthHealOutput)
    assert heal.base_amount == Decimal(100) + Decimal("0.05") * context.snapshot.bonus_health
    assert heal.missing_health_ratio > 0
    assert len([e for e in plan.events if "PETRICITE_BURST" in e.id]) == 3
    window = cog.build_reaction_plan(context).cast_block_windows[0]
    assert window.source_event_id == "SYLAS_E2_ABDUCT"


def test_sylas_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Sylas is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Sylas")
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
