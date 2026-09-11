"""Focused regressions for the locked Yorick champion Cog."""

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
    """Build a level-13 Yorick-versus-Garen encounter.

    :param as_actor: Place Yorick in the actor role when true.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    cog = registry.require_cog("Yorick")
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


def test_yorick_is_modeled_with_locked_evidence() -> None:
    """Require evidence, the duel capabilities, and a deterministic plan."""
    cog = create_default_registry(ROOT).require_cog("Yorick")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())


def test_yorick_last_rites_heals_flat_plus_missing_health() -> None:
    """Heal the level-13 QHeal curve plus 10% of missing health."""
    cog = create_default_registry(ROOT).require_cog("Yorick")
    heal = _event(cog.build_action_plan(_context()), "YORICK_Q_LAST_RITES").outputs[1]

    assert isinstance(heal, MissingHealthHealOutput)
    assert heal.missing_health_ratio == Decimal("0.10")
    # 10 at level 1, +2 per level through 6, +3 per level 7-12, +5 at 13.
    assert heal.base_amount == Decimal(10) + 5 * 2 + 6 * 3 + 5


def test_yorick_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Yorick is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Yorick")
    actor_plan = cog.build_action_plan(_context(as_actor=True))
    target_plan = cog.build_action_plan(_context(as_actor=False))

    assert {e.id.split("_", 1)[1] for e in actor_plan.events} == {
        e.id.split("_", 1)[1] for e in target_plan.events
    }
    for event in target_plan.events:
        assert event.source is EntityId.TARGET
        for output in event.outputs:
            if isinstance(output, DamageOutput):
                assert output.recipient is EntityId.ACTOR
