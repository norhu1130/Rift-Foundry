"""Focused regressions for the locked Xin Zhao champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import CurrentHealthDamageOutput, DamageOutput, EntityId

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *, as_actor: bool = True, item_stats: dict[str, Decimal] | None = None
) -> ParticipantContext:
    """Build a level-13 Xin Zhao-versus-Garen encounter.

    :param as_actor: Place Xin Zhao in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Xin Zhao.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    xinzhao = registry.require_cog("XinZhao")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        xinzhao.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one named Xin Zhao event.

    :param plan: Action plan containing the expected event.
    :param event_id: Exact stable identifier.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_xinzhao_metadata_empowered_attacks_and_sweep_are_explicit() -> None:
    """Require evidence, three empowered attacks, and R's health-percent hit."""
    cog = create_default_registry(ROOT).require_cog("XinZhao")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    assert len([e for e in plan.events if "Q_THREE_TALON_STRIKE" in e.id]) == 3
    r_outputs = _event(plan, "XINZHAO_R_CRESCENT_GUARD").outputs
    assert isinstance(r_outputs[0], DamageOutput)
    assert isinstance(r_outputs[1], CurrentHealthDamageOutput)


def test_xinzhao_reaction_plan_exposes_the_q_knockup() -> None:
    """Expose the third Three Talon Strike hit as a knock-up control window."""
    cog = create_default_registry(ROOT).require_cog("XinZhao")
    reactions = cog.build_reaction_plan(_context())

    assert len(reactions.cast_block_windows) == 1
    window = reactions.cast_block_windows[0]
    assert window.control_type is ControlType.AIRBORNE


def test_xinzhao_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Xin Zhao is the actor or target."""
    cog = create_default_registry(ROOT).require_cog("XinZhao")
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
