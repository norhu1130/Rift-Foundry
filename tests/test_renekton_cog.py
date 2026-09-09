"""Focused regressions for the locked Renekton champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId, HealOutput, MaxHealthModifierOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *, as_actor: bool = True, item_stats: dict[str, Decimal] | None = None
) -> ParticipantContext:
    """Build a level-13 Renekton-versus-Garen encounter.

    :param as_actor: Place Renekton in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Renekton.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    renekton = registry.require_cog("Renekton")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        renekton.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one named Renekton event.

    :param plan: Action plan containing the expected event.
    :param event_id: Exact stable identifier.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_renekton_metadata_cleave_heal_stun_and_aura_ticks_are_explicit() -> None:
    """Require evidence, the Q heal, the W stun, and the R aura ticks."""
    cog = create_default_registry(ROOT).require_cog("Renekton")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    q_outputs = _event(plan, "RENEKTON_Q_CLEAVE").outputs
    assert isinstance(q_outputs[0], DamageOutput)
    assert isinstance(q_outputs[1], HealOutput)
    assert len([e for e in plan.events if "W_PRE_EXECUTE_HIT" in e.id]) == 2
    assert isinstance(
        _event(plan, "RENEKTON_R_DOMINUS_HEALTH").outputs[0], MaxHealthModifierOutput
    )
    assert len([e for e in plan.events if "R_DOMINUS_AURA_TICK" in e.id]) > 1


def test_renekton_reaction_plan_exposes_the_w_stun() -> None:
    """Expose the Pre-Execute stun as a control window."""
    cog = create_default_registry(ROOT).require_cog("Renekton")
    reactions = cog.build_reaction_plan(_context())

    assert len(reactions.cast_block_windows) == 1
    window = reactions.cast_block_windows[0]
    assert window.control_type is ControlType.STUN
    assert window.start_ms == cog._W_AT_MS
    assert window.end_ms == cog._W_AT_MS + cog._W_STUN_MS


def test_renekton_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Renekton is the actor or target."""
    cog = create_default_registry(ROOT).require_cog("Renekton")
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
