"""Focused regressions for the locked Vi champion Cog."""

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
    """Build a level-13 Vi-versus-Garen encounter.

    :param as_actor: Place Vi in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Vi.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    vi = registry.require_cog("Vi")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        vi.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one named Vi event.

    :param plan: Action plan containing the expected event.
    :param event_id: Exact stable identifier.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_vi_metadata_third_attack_proc_and_r_knockup_are_explicit() -> None:
    """Require evidence, the third-attack Denting Blows bonus, and R's knock-up."""
    cog = create_default_registry(ROOT).require_cog("Vi")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    first_attack = _event(plan, "VI_BASIC_ATTACK_0")
    assert len(first_attack.outputs) == 2  # base attack plus Relentless Force
    third_attack = _event(plan, "VI_BASIC_ATTACK_2")
    assert len(third_attack.outputs) == 2  # base attack plus Denting Blows
    r_outputs = _event(plan, "VI_R_CEASE_AND_DESIST").outputs
    assert isinstance(r_outputs[0], DamageOutput)


def test_vi_reaction_plan_exposes_the_r_knockup() -> None:
    """Expose the Cease and Desist knock-up as a control window."""
    cog = create_default_registry(ROOT).require_cog("Vi")
    reactions = cog.build_reaction_plan(_context())

    assert len(reactions.cast_block_windows) == 1
    assert reactions.cast_block_windows[0].control_type is ControlType.AIRBORNE


def test_vi_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Vi is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Vi")
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
