"""Focused regressions for the locked Yasuo champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *, as_actor: bool = True, item_stats: dict[str, Decimal] | None = None
) -> ParticipantContext:
    """Build a level-13 Yasuo-versus-Garen encounter.

    :param as_actor: Place Yasuo in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Yasuo.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    yasuo = registry.require_cog("Yasuo")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        yasuo.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def test_yasuo_metadata_triple_thrust_and_airborne_follow_are_explicit() -> None:
    """Require evidence, three Q casts, and R landing on an airborne target."""
    cog = create_default_registry(ROOT).require_cog("Yasuo")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    q_events = sorted(
        (e for e in plan.events if "Q_STEEL_TEMPEST" in e.id), key=lambda e: e.at_ms
    )
    assert len(q_events) == 3
    r_event = next(e for e in plan.events if "R_LAST_BREATH" in e.id)
    # R must resolve while Q3's knock-up is still active, matching the combo
    # the ability text itself requires (teleport to an airborne champion).
    assert q_events[2].at_ms < r_event.at_ms < q_events[2].at_ms + cog._Q3_KNOCKUP_MS


def test_yasuo_reaction_plan_exposes_both_knockups() -> None:
    """Expose the Q3 tornado and R knock-ups as control windows."""
    cog = create_default_registry(ROOT).require_cog("Yasuo")
    reactions = cog.build_reaction_plan(_context())

    assert len(reactions.cast_block_windows) == 2
    assert all(
        window.control_type is ControlType.AIRBORNE for window in reactions.cast_block_windows
    )


def test_yasuo_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Yasuo is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Yasuo")
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
