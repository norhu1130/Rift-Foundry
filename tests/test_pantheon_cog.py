"""Focused regressions for the locked Pantheon champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId, ShieldOutput, StatusOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *, as_actor: bool = True, item_stats: dict[str, Decimal] | None = None
) -> ParticipantContext:
    """Build a level-13 Pantheon-versus-Garen encounter.

    :param as_actor: Place Pantheon in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Pantheon.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    pantheon = registry.require_cog("Pantheon")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        pantheon.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one named Pantheon event.

    :param plan: Action plan containing the expected event.
    :param event_id: Exact stable identifier.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_pantheon_metadata_stun_shield_and_strikes_are_explicit() -> None:
    """Require evidence, the W stun, the E shield, and its six held strikes."""
    cog = create_default_registry(ROOT).require_cog("Pantheon")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    assert isinstance(_event(plan, "PANTHEON_E_AEGIS_ASSAULT_SHIELD").outputs[0], ShieldOutput)
    assert len([event for event in plan.events if "E_AEGIS_ASSAULT_STRIKE" in event.id]) == 6
    w_outputs = _event(plan, "PANTHEON_W_SHIELD_VAULT").outputs
    assert isinstance(w_outputs[0], DamageOutput)
    assert isinstance(w_outputs[2], StatusOutput)


def test_pantheon_reaction_plan_exposes_the_w_stun() -> None:
    """Expose the Shield Vault stun as a control window on the reaction plan."""
    cog = create_default_registry(ROOT).require_cog("Pantheon")
    reactions = cog.build_reaction_plan(_context())

    assert len(reactions.cast_block_windows) == 1
    window = reactions.cast_block_windows[0]
    assert window.control_type is ControlType.STUN
    assert window.start_ms == 0
    assert window.end_ms == 1000


def test_pantheon_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Pantheon is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Pantheon")
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


def test_pantheon_second_q_waits_for_locked_haste_reduced_cooldown() -> None:
    """Delay the tap-cast Q recast by its own cooldown, adjusted for haste."""
    cog = create_default_registry(ROOT).require_cog("Pantheon")
    plan = cog.build_action_plan(_context(item_stats={"ABILITY_HASTE": Decimal(50)}))

    taps = sorted(
        (event for event in plan.events if "Q_COMET_SPEAR_TAP" in event.id),
        key=lambda event: event.at_ms,
    )
    assert len(taps) == 2
    # 8000ms * (1 - 0.60) = 3200ms base refund cooldown, halved by 50 haste.
    assert taps[1].at_ms - taps[0].at_ms >= 2100
