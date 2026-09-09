"""Focused regressions for the locked Galio champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import ActionChannel, EntityId, ShieldOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    galio_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a level-13 Galio-versus-Teemo direct context.

    :param galio_is_actor: Place Galio on the actor side when true.
    :param item_stats: Optional permanent item modifiers for Galio.
    :return: Role-bound deterministic encounter context.
    """
    registry = create_default_registry(ROOT)
    galio = registry.require_cog("Galio")
    teemo = registry.require_cog("Teemo")
    return ParticipantContext(
        EntityId.ACTOR if galio_is_actor else EntityId.TARGET,
        EntityId.TARGET if galio_is_actor else EntityId.ACTOR,
        galio.snapshot(level=13, item_stats=item_stats),
        teemo.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Locate one Galio event by its stable identifier.

    :param plan: Action plan exposing an events tuple.
    :param event_id: Exact event identifier to locate.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_galio_declares_complete_modeled_metadata() -> None:
    """Require full capabilities and three locked evidence forms."""
    galio = create_default_registry(ROOT).require_cog("Galio")

    assert galio.maturity is CogMaturity.MODELED_UNVERIFIED
    assert galio.capabilities == DUEL_CAPABILITIES
    assert len(galio.evidence_refs) == 3
    assert all((ROOT / ref).is_file() for ref in galio.evidence_refs)


def test_galio_rotation_is_deterministic_and_has_no_empty_actions() -> None:
    """Anchor the ally-anchor fixture and prevent invalid empty events."""
    galio = create_default_registry(ROOT).require_cog("Galio")
    context = _context(item_stats={"AP": Decimal(100), "MAGIC_RESISTANCE": Decimal(50)})

    first = galio.build_action_plan(context)
    assert first == galio.build_action_plan(context)
    assert first.model_id == "galio_q5_w5_e1_r2_level13_ally_anchor_fixture_v1"
    assert all(event.outputs for event in first.events)
    assert _event(first, "GALIO_R_HEROS_ENTRANCE_LANDING").outputs[0].amount > 250
    assert _event(first, "GALIO_PASSIVE_COLOSSAL_SMASH").channel is ActionChannel.BASIC_ATTACK
    assert galio.engagement_dash_distance(context) == 650


def test_galio_reaction_separates_damage_reduction_and_control_types() -> None:
    """Preserve Galio's magic shield, W mitigation, and discrete controls."""
    galio = create_default_registry(ROOT).require_cog("Galio")
    reaction = galio.build_reaction_plan(_context())

    assert isinstance(reaction.events[0].outputs[0], ShieldOutput)
    assert len(reaction.damage_windows) == 2
    assert tuple(window.control_type for window in reaction.cast_block_windows) == (
        ControlType.AIRBORNE,
        ControlType.AIRBORNE,
        ControlType.TAUNT,
    )
    assert reaction.cast_block_windows[-1].tenacity_reducible is True


def test_galio_role_reversal_preserves_event_ownership() -> None:
    """Attach Galio outputs to Galio after participant reversal."""
    galio = create_default_registry(ROOT).require_cog("Galio")
    actor = _event(galio.build_action_plan(_context()), "GALIO_E_JUSTICE_PUNCH")
    target = _event(
        galio.build_action_plan(_context(galio_is_actor=False)),
        "GALIO_E_JUSTICE_PUNCH",
    )

    assert actor.source is EntityId.ACTOR
    assert target.source is EntityId.TARGET
    assert actor.outputs[0].recipient is EntityId.TARGET
    assert target.outputs[0].recipient is EntityId.ACTOR


def test_galio_item_policy_rejects_unrepresented_resource_stats() -> None:
    """Accept represented tank stats and reject unmodeled resource channels."""
    galio = create_default_registry(ROOT).require_cog("Galio")

    assert galio.item_candidate_blocker(
        {"id": 1, "stats": {"AP": {}, "HP": {}, "MAGIC_RESISTANCE": {}}}
    ) is None
    assert galio.item_candidate_blocker(
        {"id": 2, "stats": {"MANA": {}, "HEAL_SHIELD_POWER": {}}}
    ) == "GALIO_ITEM_STAT_NOT_MODELED:2:HEAL_SHIELD_POWER,MANA"
