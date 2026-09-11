"""Focused regressions for the locked Skarner champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId, ShieldOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(*, as_actor: bool = True) -> ParticipantContext:
    """Build a level-13 Skarner-versus-Garen encounter.

    :param as_actor: Place Skarner in the actor role when true.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    cog = registry.require_cog("Skarner")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        cog.snapshot(level=13),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def test_skarner_is_modeled_with_locked_evidence() -> None:
    """Require evidence, the duel capabilities, and a deterministic plan."""
    cog = create_default_registry(ROOT).require_cog("Skarner")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())


def test_skarner_shields_suppresses_and_burns_with_quaking() -> None:
    """Shield 8% max health, suppress, and burn Quaking over eight ticks."""
    cog = create_default_registry(ROOT).require_cog("Skarner")
    context = _context()
    plan = cog.build_action_plan(context)
    shields = [o for e in plan.events for o in e.outputs if isinstance(o, ShieldOutput)]
    ticks = [e for e in plan.events if "QUAKING_TICK" in e.id]
    ratio = (Decimal(5) + Decimal(4) * 12 / Decimal(17)) / Decimal(100)

    assert [s.amount for s in shields] == [Decimal("0.08") * context.snapshot.max_hp]
    assert ticks
    assert ticks[0].outputs[0].amount == ratio * context.opponent_snapshot.max_hp / 8
    window = cog.build_reaction_plan(context).cast_block_windows[0]
    assert window.control_type is ControlType.SUPPRESSION


def test_skarner_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Skarner is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Skarner")
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
