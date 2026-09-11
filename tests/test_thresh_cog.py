"""Focused regressions for the locked Thresh champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId

ROOT = Path(__file__).resolve().parents[1]


def _context(*, as_actor: bool = True) -> ParticipantContext:
    """Build a level-13 Thresh-versus-Garen encounter.

    :param as_actor: Place Thresh in the actor role when true.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    cog = registry.require_cog("Thresh")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        cog.snapshot(level=13),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def test_thresh_is_modeled_with_locked_evidence() -> None:
    """Require evidence, the duel capabilities, and a deterministic plan."""
    cog = create_default_registry(ROOT).require_cog("Thresh")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())


def test_thresh_flay_passive_charge_scales_with_time_since_last_attack() -> None:
    """Fully charge the opening attack and partly charge every later one."""
    context = _context()
    plan = create_default_registry(ROOT).require_cog("Thresh").build_action_plan(context)
    attacks = [e for e in plan.events if e.id.startswith("THRESH_BASIC_ATTACK")]
    full = Decimal("2.10") * context.snapshot.attack_damage

    assert attacks[0].outputs[1].amount == full
    assert all(Decimal(0) < a.outputs[1].amount < full for a in attacks[1:])


def test_thresh_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Thresh is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Thresh")
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
