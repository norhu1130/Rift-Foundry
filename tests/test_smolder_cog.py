"""Focused regressions for the locked Smolder champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId, HealOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(*, as_actor: bool = True, item_stats=None) -> ParticipantContext:
    """Build a level-13 Smolder-versus-Garen encounter.

    :param as_actor: Place Smolder in the actor role when true.
    :param item_stats: Optional permanent item modifiers applied to Smolder.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    cog = registry.require_cog("Smolder")
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


def test_smolder_is_modeled_with_locked_evidence() -> None:
    """Require evidence, the duel capabilities, and a deterministic plan."""
    cog = create_default_registry(ROOT).require_cog("Smolder")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())


def test_smolder_breath_lifesteal_follows_lifestealmod_and_mom_heals() -> None:
    """Apply half of Smolder's life steal to Q and heal from his mom's breath."""
    cog = create_default_registry(ROOT).require_cog("Smolder")
    plan = cog.build_action_plan(_context(item_stats={"LIFESTEAL": Decimal("0.20")}))
    breaths = [e for e in plan.events if "SUPER_SCORCHER_BREATH" in e.id]

    assert breaths
    assert all(e.outputs[0].source_heal_ratio == Decimal("0.10") for e in breaths)
    assert _outputs(plan, HealOutput) == [HealOutput(EntityId.ACTOR, Decimal(135))]


def test_smolder_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Smolder is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Smolder")
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
