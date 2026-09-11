"""Focused regressions for the locked Sivir champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId, StatusOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(*, as_actor: bool = True) -> ParticipantContext:
    """Build a level-13 Sivir-versus-Garen encounter.

    :param as_actor: Place Sivir in the actor role when true.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    cog = registry.require_cog("Sivir")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        cog.snapshot(level=13),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def test_sivir_is_modeled_with_locked_evidence() -> None:
    """Require evidence, the duel capabilities, and a deterministic plan."""
    cog = create_default_registry(ROOT).require_cog("Sivir")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())


def test_sivir_spell_shield_carries_its_conditional_heal() -> None:
    """Open with a spell shield whose heal applies only on a blocked ability."""
    context = _context()
    plan = create_default_registry(ROOT).require_cog("Sivir").build_action_plan(context)
    shield = next(e for e in plan.events if e.id == "SIVIR_E_SPELL_SHIELD")
    heal = next(o for o in shield.outputs if o.status == "SPELL_SHIELD_HEAL")

    assert isinstance(heal, StatusOutput)
    assert heal.magnitude == Decimal("0.6") * context.snapshot.attack_damage
    assert len([e for e in plan.events if "BOOMERANG" in e.id]) == 2


def test_sivir_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Sivir is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Sivir")
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
