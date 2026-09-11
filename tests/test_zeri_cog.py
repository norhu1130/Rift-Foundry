"""Focused regressions for the locked Zeri champion Cog."""

from pathlib import Path

from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId

ROOT = Path(__file__).resolve().parents[1]


def _context(*, as_actor: bool = True) -> ParticipantContext:
    """Build a level-13 Zeri-versus-Garen encounter.

    :param as_actor: Place Zeri in the actor role when true.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    cog = registry.require_cog("Zeri")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        cog.snapshot(level=13),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def test_zeri_is_modeled_with_locked_evidence() -> None:
    """Require evidence, the duel capabilities, and a deterministic plan."""
    cog = create_default_registry(ROOT).require_cog("Zeri")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())


def test_zeri_bursts_on_capped_attack_timer_and_carries_buffs() -> None:
    """Fire Burst Fire as attacks and add energized and overcharged damage."""
    plan = create_default_registry(ROOT).require_cog("Zeri").build_action_plan(_context())
    bursts = [e for e in plan.events if e.id.startswith("ZERI_Q_BURST_FIRE")]

    assert bursts
    assert all(e.channel.value == "BASIC_ATTACK" for e in bursts)
    assert len(bursts[0].outputs) == 2
    assert any(len(e.outputs) == 3 for e in bursts)


def test_zeri_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Zeri is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Zeri")
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
