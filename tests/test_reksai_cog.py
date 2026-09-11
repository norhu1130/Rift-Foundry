"""Focused regressions for the locked Rek'Sai champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.combat import DamageType
from lol_build.core.timeline import DamageOutput, EntityId, MissingHealthDamageOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(*, as_actor: bool = True) -> ParticipantContext:
    """Build a level-13 Rek'Sai-versus-Garen encounter.

    :param as_actor: Place Rek'Sai in the actor role when true.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    cog = registry.require_cog("RekSai")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        cog.snapshot(level=13),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def test_reksai_is_modeled_with_locked_evidence() -> None:
    """Require evidence, the duel capabilities, and a deterministic plan."""
    cog = create_default_registry(ROOT).require_cog("RekSai")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())


def test_reksai_bites_at_max_fury_for_true_damage_and_rushes_missing_health() -> None:
    """Deal true damage on the fourth-hit bite and missing-health damage on Void Rush."""
    plan = create_default_registry(ROOT).require_cog("RekSai").build_action_plan(_context())
    bite = next(e for e in plan.events if e.id == "REKSAI_E_FURIOUS_BITE_MAX_FURY")
    rush = next(e for e in plan.events if e.id == "REKSAI_R_VOID_RUSH")

    assert bite.outputs[0].damage_type is DamageType.TRUE
    assert bite.outputs[0].amount == Decimal("1.2") * Decimal(170)
    assert isinstance(rush.outputs[0], MissingHealthDamageOutput)
    assert rush.outputs[0].missing_health_ratio == Decimal("0.30")
    assert "REKSAI_PASSIVE_BURROWED_HEAL_FURY_SPENT_ON_EMPOWERED_BITE" in plan.blockers


def test_reksai_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Rek'Sai is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("RekSai")
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
