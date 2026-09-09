"""Focused regressions for the locked Yone champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId, ShieldOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *, as_actor: bool = True, item_stats: dict[str, Decimal] | None = None
) -> ParticipantContext:
    """Build a level-13 Yone-versus-Garen encounter.

    :param as_actor: Place Yone in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Yone.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    yone = registry.require_cog("Yone")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        yone.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one named Yone event.

    :param plan: Action plan containing the expected event.
    :param event_id: Exact stable identifier.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_yone_metadata_split_cleave_triple_thrust_and_hybrid_r() -> None:
    """Require evidence, W's split damage types, three Qs, and R's hybrid hit."""
    cog = create_default_registry(ROOT).require_cog("Yone")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    w_outputs = _event(plan, "YONE_W_SPIRIT_CLEAVE").outputs
    types = {output.damage_type.value for output in w_outputs if isinstance(output, DamageOutput)}
    assert types == {"PHYSICAL", "MAGIC"}
    assert any(isinstance(output, ShieldOutput) for output in w_outputs)
    assert len([e for e in plan.events if "Q_MORTAL_STEEL" in e.id]) == 3
    r_outputs = _event(plan, "YONE_R_FATE_SEALED").outputs
    r_damages = [output for output in r_outputs if isinstance(output, DamageOutput)]
    assert len(r_damages) == 2
    assert r_damages[0].amount == r_damages[1].amount


def test_yone_reaction_plan_exposes_both_knockups() -> None:
    """Expose the Q3 wind wave and R knock-ups as control windows."""
    cog = create_default_registry(ROOT).require_cog("Yone")
    reactions = cog.build_reaction_plan(_context())

    assert len(reactions.cast_block_windows) == 2
    assert all(
        window.control_type is ControlType.AIRBORNE for window in reactions.cast_block_windows
    )


def test_yone_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Yone is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Yone")
    actor_plan = cog.build_action_plan(_context(as_actor=True))
    target_plan = cog.build_action_plan(_context(as_actor=False))

    actor_ids = {event.id.split("_", 1)[1] for event in actor_plan.events}
    target_ids = {event.id.split("_", 1)[1] for event in target_plan.events}
    assert actor_ids == target_ids
    for event in target_plan.events:
        assert event.source is EntityId.TARGET
        for output in event.outputs:
            if isinstance(output, DamageOutput):
                assert output.recipient is EntityId.ACTOR
