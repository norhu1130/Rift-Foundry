"""Focused regressions for the locked Shaco champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId

ROOT = Path(__file__).resolve().parents[1]


def _context(*, as_actor: bool = True) -> ParticipantContext:
    """Build a level-13 Shaco-versus-Garen encounter.

    :param as_actor: Place Shaco in the actor role when true.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    cog = registry.require_cog("Shaco")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        cog.snapshot(level=13),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def test_shaco_is_modeled_with_locked_evidence() -> None:
    """Require evidence, the duel capabilities, and a deterministic plan."""
    cog = create_default_registry(ROOT).require_cog("Shaco")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())


def test_shaco_empowers_only_the_deceive_attack_and_poisons_every_attack() -> None:
    """Add Deceive's bonus once and the level-scaled shiv to every attack."""
    plan = create_default_registry(ROOT).require_cog("Shaco").build_action_plan(_context())
    attacks = [e for e in plan.events if e.id.startswith("SHACO_BASIC_ATTACK")]
    shiv = Decimal(15) + Decimal(35) * 12 / Decimal(17)

    assert len(attacks[0].outputs) == 4
    assert all(len(a.outputs) == 3 for a in attacks[1:])
    assert all(a.outputs[1].amount == shiv for a in attacks)


def test_shaco_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Shaco is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Shaco")
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
