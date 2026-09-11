"""Focused regressions for the locked Zaahen champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId, HealOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(*, as_actor: bool = True, item_stats=None) -> ParticipantContext:
    """Build a level-13 Zaahen-versus-Garen encounter.

    :param as_actor: Place Zaahen in the actor role when true.
    :param item_stats: Optional permanent item modifiers applied to Zaahen.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    cog = registry.require_cog("Zaahen")
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


def test_zaahen_is_modeled_with_locked_evidence() -> None:
    """Require evidence, the duel capabilities, and a deterministic plan."""
    cog = create_default_registry(ROOT).require_cog("Zaahen")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())


def test_zaahen_deliverance_heals_a_third_of_its_damage_and_glaive_does_not() -> None:
    """Heal 33% of Grim Deliverance's damage and exclude the unexplained Q heal."""
    cog = create_default_registry(ROOT).require_cog("Zaahen")
    context = _context()
    plan = cog.build_action_plan(context)
    strike = next(e for e in plan.events if e.id == "ZAAHEN_R_GRIM_DELIVERANCE")

    assert strike.outputs[0].source_heal_ratio == Decimal("0.33")
    assert not _outputs(plan, HealOutput)
    assert "ZAAHEN_Q_HEAL_PERCENT_BASIS_NOT_IN_LOCKED_DATA" in plan.blockers
    window = cog.build_reaction_plan(context).damage_windows[0]
    assert window.multiplier == Decimal("0.5")


def test_zaahen_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Zaahen is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Zaahen")
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
