"""Focused regressions for the locked Yuumi champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId, HealOutput, ShieldOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(*, as_actor: bool = True) -> ParticipantContext:
    """Build a level-13 Yuumi-versus-Garen encounter.

    :param as_actor: Place Yuumi in the actor role when true.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    cog = registry.require_cog("Yuumi")
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


def test_yuumi_is_modeled_with_locked_evidence() -> None:
    """Require evidence, the duel capabilities, and a deterministic plan."""
    cog = create_default_registry(ROOT).require_cog("Yuumi")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())


def test_yuumi_heals_once_from_feline_friendship_and_shields_with_zoomies() -> None:
    """Heal on the first champion hit only and shield for the rank-five value."""
    plan = create_default_registry(ROOT).require_cog("Yuumi").build_action_plan(_context())

    assert _outputs(plan, HealOutput) == [
        HealOutput(EntityId.ACTOR, Decimal(20) + Decimal(90) * 12 / Decimal(17))
    ]
    assert _outputs(plan, ShieldOutput)[0].amount == Decimal(165)
    waves = [e for e in plan.events if "FINAL_CHAPTER_WAVE" in e.id]
    assert len(waves) == 5


def test_yuumi_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Yuumi is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Yuumi")
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
