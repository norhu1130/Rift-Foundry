"""Focused regressions for the locked Pyke champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId, StatModifierOutput, StatusOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *, as_actor: bool = True, item_stats: dict[str, Decimal] | None = None
) -> ParticipantContext:
    """Build a level-13 Pyke-versus-Garen encounter.

    :param as_actor: Place Pyke in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Pyke.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    pyke = registry.require_cog("Pyke")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        pyke.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one named Pyke event.

    :param plan: Action plan containing the expected event.
    :param event_id: Exact stable identifier.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_pyke_metadata_stealth_dash_stun_and_slow_are_explicit() -> None:
    """Require evidence, the W buff, the E stun, and the Q slow."""
    cog = create_default_registry(ROOT).require_cog("Pyke")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    w_outputs = _event(plan, "PYKE_W_GHOSTWATER_DIVE").outputs
    assert isinstance(w_outputs[0], StatModifierOutput)
    assert isinstance(w_outputs[1], StatusOutput)
    e_outputs = _event(plan, "PYKE_E_PHANTOM_UNDERTOW").outputs
    assert isinstance(e_outputs[0], DamageOutput)
    q_outputs = _event(plan, "PYKE_Q_BONE_SKEWER_TAP_1").outputs
    assert isinstance(q_outputs[0], DamageOutput)
    assert isinstance(q_outputs[1], StatModifierOutput)


def test_pyke_reaction_plan_exposes_the_e_stun() -> None:
    """Expose the Phantom Undertow stun as a control window."""
    cog = create_default_registry(ROOT).require_cog("Pyke")
    reactions = cog.build_reaction_plan(_context())

    assert len(reactions.cast_block_windows) == 1
    window = reactions.cast_block_windows[0]
    assert window.control_type is ControlType.STUN
    assert window.start_ms == cog._E_AT_MS
    assert window.end_ms == cog._E_AT_MS + cog._E_STUN_MS


def test_pyke_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Pyke is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Pyke")
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


def test_pyke_second_q_waits_for_locked_haste_reduced_cooldown() -> None:
    """Delay the tap-cast Q recast by its own cooldown, adjusted for haste."""
    cog = create_default_registry(ROOT).require_cog("Pyke")
    plan = cog.build_action_plan(_context(item_stats={"ABILITY_HASTE": Decimal(100)}))

    taps = sorted(
        (event for event in plan.events if "Q_BONE_SKEWER_TAP" in event.id),
        key=lambda event: event.at_ms,
    )
    assert len(taps) == 2
    # 8000ms base cooldown halved by 100 ability haste.
    assert taps[1].at_ms - taps[0].at_ms == 4000
