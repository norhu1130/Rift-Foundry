"""Focused regressions for the locked Ziggs champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *, as_actor: bool = True, item_stats: dict[str, Decimal] | None = None
) -> ParticipantContext:
    """Build a level-13 Ziggs-versus-Garen encounter.

    :param as_actor: Place Ziggs in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Ziggs.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    ziggs = registry.require_cog("Ziggs")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        ziggs.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def test_ziggs_metadata_all_four_bombs_deal_magic_damage() -> None:
    """Require evidence and all-magic damage from all four abilities."""
    cog = create_default_registry(ROOT).require_cog("Ziggs")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    ability_ids = {
        "Q_BOUNCING_BOMB",
        "E_HEXPLOSIVE_MINEFIELD",
        "W_SATCHEL_CHARGE",
        "R_MEGA_INFERNO_BOMB",
    }
    found = set()
    for event in plan.events:
        for marker in ability_ids:
            if marker in event.id:
                found.add(marker)
                for output in event.outputs:
                    if isinstance(output, DamageOutput):
                        assert output.damage_type.value == "MAGIC"
    assert found == ability_ids


def test_ziggs_reaction_plan_applies_no_hostile_control() -> None:
    """Report an empty control window set, matching Ziggs's kit."""
    cog = create_default_registry(ROOT).require_cog("Ziggs")
    reactions = cog.build_reaction_plan(_context())

    assert reactions.cast_block_windows == ()


def test_ziggs_is_role_symmetric_between_actor_and_target() -> None:
    """Produce the same event shape whether Ziggs is the actor or the target."""
    cog = create_default_registry(ROOT).require_cog("Ziggs")
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
