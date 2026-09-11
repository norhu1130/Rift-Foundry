"""Focused regressions for the locked Rell champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId, ResistanceReductionOutput, ShieldOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(*, as_actor: bool = True) -> ParticipantContext:
    """Build a level-13 Rell-versus-Garen encounter.

    :param as_actor: Place Rell in the actor role when true.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    cog = registry.require_cog("Rell")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        cog.snapshot(level=13),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def test_rell_is_modeled_with_locked_evidence() -> None:
    """Require evidence, the duel capabilities, and a deterministic plan."""
    cog = create_default_registry(ROOT).require_cog("Rell")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())


def test_rell_shreds_resistances_and_shields_on_crash_down() -> None:
    """Strip 3% per hit up to five stacks and shield for the rank-five value."""
    context = _context()
    plan = create_default_registry(ROOT).require_cog("Rell").build_action_plan(context)
    crash = next(e for e in plan.events if e.id == "RELL_W_CRASH_DOWN")
    shred = [o for o in crash.outputs if isinstance(o, ResistanceReductionOutput)]

    assert {(o.stat, o.fraction_per_stack, o.max_stacks) for o in shred} == {
        ("ARMOR", Decimal("0.03"), 5),
        ("MAGIC_RESISTANCE", Decimal("0.03"), 5),
    }
    shield = next(o for o in crash.outputs if isinstance(o, ShieldOutput))
    assert shield.amount == Decimal(100) + Decimal("0.11") * context.snapshot.max_hp


def test_rell_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Rell is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Rell")
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
