"""Focused regressions for the locked Shyvana champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId, HealOutput, ShieldOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(*, as_actor: bool = True, item_stats=None) -> ParticipantContext:
    """Build a level-13 Shyvana-versus-Garen encounter.

    :param as_actor: Place Shyvana in the actor role when true.
    :param item_stats: Optional permanent item modifiers applied to Shyvana.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    cog = registry.require_cog("Shyvana")
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


def test_shyvana_is_modeled_with_locked_evidence() -> None:
    """Require evidence, the duel capabilities, and a deterministic plan."""
    cog = create_default_registry(ROOT).require_cog("Shyvana")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())


def test_shyvana_stays_in_human_form_without_the_dragon_heal() -> None:
    """Shield for the flat rank-five value and never heal outside Dragon Form."""
    plan = create_default_registry(ROOT).require_cog("Shyvana").build_action_plan(_context())

    assert [s.amount for s in _outputs(plan, ShieldOutput)] == [Decimal(140)]
    assert not _outputs(plan, HealOutput)
    assert "SHYVANA_W_HEAL_IS_DRAGON_FORM_ONLY" in plan.blockers


def test_shyvana_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Shyvana is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Shyvana")
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
