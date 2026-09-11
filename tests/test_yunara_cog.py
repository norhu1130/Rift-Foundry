"""Focused regressions for the locked Yunara champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId

ROOT = Path(__file__).resolve().parents[1]


def _context(*, as_actor: bool = True) -> ParticipantContext:
    """Build a level-13 Yunara-versus-Garen encounter.

    :param as_actor: Place Yunara in the actor role when true.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    cog = registry.require_cog("Yunara")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        cog.snapshot(level=13),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def test_yunara_is_modeled_with_locked_evidence() -> None:
    """Require evidence, the duel capabilities, and a deterministic plan."""
    cog = create_default_registry(ROOT).require_cog("Yunara")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())


def test_yunara_fires_arc_of_ruin_every_two_seconds() -> None:
    """Cast the transcendent laser on its 80%-reduced cooldown."""
    plan = create_default_registry(ROOT).require_cog("Yunara").build_action_plan(_context())
    lasers = [e for e in plan.events if e.id.startswith("YUNARA_RW_ARC_OF_RUIN")]

    assert [e.at_ms for e in lasers] == [300, 2300, 4300, 6300]
    assert lasers[0].outputs[0].amount == Decimal(320)


def test_yunara_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Yunara is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Yunara")
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
