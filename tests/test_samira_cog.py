"""Focused regressions for the locked Samira champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId

ROOT = Path(__file__).resolve().parents[1]


def _context(*, as_actor: bool = True, item_stats=None) -> ParticipantContext:
    """Build a level-13 Samira-versus-Garen encounter.

    :param as_actor: Place Samira in the actor role when true.
    :param item_stats: Optional permanent item modifiers applied to Samira.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    cog = registry.require_cog("Samira")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        cog.snapshot(level=13, item_stats=item_stats),
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


def test_samira_is_modeled_with_locked_evidence() -> None:
    """Require evidence, the duel capabilities, and a deterministic plan."""
    cog = create_default_registry(ROOT).require_cog("Samira")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())


def test_samira_flair_applies_full_life_steal_and_ultimate_is_excluded() -> None:
    """Heal from Flair at LifestealMod 1 and disclose the missing shot count."""
    cog = create_default_registry(ROOT).require_cog("Samira")
    plan = cog.build_action_plan(_context(item_stats={"LIFESTEAL": Decimal("0.18")}))
    flairs = [e for e in plan.events if e.id.startswith("SAMIRA_Q_FLAIR")]

    assert len(flairs) == 3
    assert all(e.outputs[0].source_heal_ratio == Decimal("0.18") for e in flairs)
    assert "SAMIRA_R_SHOT_COUNT_ABSENT_FROM_LOCKED_DATA_VALUES" in plan.blockers


def test_samira_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Samira is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Samira")
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
