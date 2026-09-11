"""Focused regressions for the locked Rakan champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId, HealOutput, ShieldOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(*, as_actor: bool = True) -> ParticipantContext:
    """Build a level-13 Rakan-versus-Garen encounter.

    :param as_actor: Place Rakan in the actor role when true.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    cog = registry.require_cog("Rakan")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        cog.snapshot(level=13),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _outputs(plan, kind):
    """Collect every output of one type from a plan.

    :param plan: Action plan to scan.
    :param kind: Output class to collect.
    :return: Matching outputs in event order.
    """
    return [o for e in plan.events for o in e.outputs if isinstance(o, kind)]


def test_rakan_is_modeled_with_locked_evidence() -> None:
    """Require evidence, the duel capabilities, and a deterministic plan."""
    cog = create_default_registry(ROOT).require_cog("Rakan")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())


def test_rakan_quill_heals_after_its_delay_and_feathers_shield() -> None:
    """Heal the level-13 TotalHeal after HealDelay and open with the passive shield."""
    plan = create_default_registry(ROOT).require_cog("Rakan").build_action_plan(_context())
    heal = next(e for e in plan.events if e.id == "RAKAN_Q_GLEAMING_QUILL_HEAL")
    quill = next(e for e in plan.events if e.id == "RAKAN_Q_GLEAMING_QUILL")

    assert heal.at_ms - quill.at_ms == 3000
    assert heal.outputs == (
        HealOutput(EntityId.ACTOR, Decimal(40) + Decimal(170) * 12 / Decimal(17)),
    )
    assert _outputs(plan, ShieldOutput)[0].amount == Decimal(30) + Decimal(195) * 12 / Decimal(17)


def test_rakan_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Rakan is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Rakan")
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
