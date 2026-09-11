"""Focused regressions for the locked Gragas champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import EntityId, HealOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    gragas_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a level-13 Gragas-versus-Teemo direct context.

    :param gragas_is_actor: Place Gragas on the actor side when true.
    :param item_stats: Optional permanent item modifiers for Gragas.
    :return: Role-bound deterministic encounter context.
    """
    registry = create_default_registry(ROOT)
    gragas = registry.require_cog("Gragas")
    teemo = registry.require_cog("Teemo")
    return ParticipantContext(
        EntityId.ACTOR if gragas_is_actor else EntityId.TARGET,
        EntityId.TARGET if gragas_is_actor else EntityId.ACTOR,
        gragas.snapshot(level=13, item_stats=item_stats),
        teemo.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Locate one Gragas event by its stable identifier.

    :param plan: Action plan exposing an events tuple.
    :param event_id: Exact event identifier to locate.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_gragas_declares_complete_modeled_metadata() -> None:
    """Require full capabilities and three locked evidence forms."""
    gragas = create_default_registry(ROOT).require_cog("Gragas")

    assert gragas.maturity is CogMaturity.MODELED_UNVERIFIED
    assert gragas.capabilities == DUEL_CAPABILITIES
    assert len(gragas.evidence_refs) == 3
    assert all((ROOT / ref).is_file() for ref in gragas.evidence_refs)


def test_gragas_rotation_is_deterministic_and_stat_sensitive() -> None:
    """Anchor charged Q, passive healing, and AP-scaled spell damage."""
    gragas = create_default_registry(ROOT).require_cog("Gragas")
    baseline_context = _context()
    scaled_context = _context(item_stats={"AP": Decimal(100), "HP": Decimal(500)})
    baseline = gragas.build_action_plan(baseline_context)
    scaled = gragas.build_action_plan(scaled_context)

    assert baseline == gragas.build_action_plan(baseline_context)
    assert baseline.model_id == "gragas_q5_e5_w1_r2_level13_max_charge_v1"
    assert _event(scaled, "GRAGAS_Q_BARREL_ROLL_MAX_CHARGE_1").outputs[0].amount > (
        _event(baseline, "GRAGAS_Q_BARREL_ROLL_MAX_CHARGE_1").outputs[0].amount
    )
    assert isinstance(_event(scaled, "GRAGAS_Q_BARREL_ROLL_CAST_1").outputs[1], HealOutput)
    assert gragas.engagement_dash_distance(scaled_context) == 600


def test_gragas_haste_adds_a_second_charged_barrel() -> None:
    """Make ability haste affect the represented Q cadence."""
    gragas = create_default_registry(ROOT).require_cog("Gragas")
    baseline = gragas.build_action_plan(_context())
    hasted = gragas.build_action_plan(_context(item_stats={"ABILITY_HASTE": Decimal(100)}))

    assert not any(event.id.endswith("CHARGE_3") for event in baseline.events)
    assert any(event.id.endswith("CHARGE_3") for event in hasted.events)


def test_gragas_reaction_preserves_slow_stun_and_airborne_semantics() -> None:
    """Keep reducible and non-reducible control windows distinct."""
    gragas = create_default_registry(ROOT).require_cog("Gragas")
    reaction = gragas.build_reaction_plan(_context())
    control_types = tuple(window.control_type for window in reaction.cast_block_windows)

    assert ControlType.SLOW in control_types
    assert ControlType.STUN in control_types
    assert ControlType.AIRBORNE in control_types
    assert reaction.damage_windows[0].multiplier < 1


def test_gragas_role_reversal_and_item_policy_are_explicit() -> None:
    """Preserve role ownership and reject unsupported sustain stats."""
    gragas = create_default_registry(ROOT).require_cog("Gragas")
    actor = _event(gragas.build_action_plan(_context()), "GRAGAS_E_BODY_SLAM")
    target = _event(
        gragas.build_action_plan(_context(gragas_is_actor=False)),
        "GRAGAS_E_BODY_SLAM",
    )

    assert actor.source is EntityId.ACTOR
    assert target.source is EntityId.TARGET
    assert (
        gragas.item_candidate_blocker({"id": 1, "stats": {"AP": {}, "ABILITY_HASTE": {}, "HP": {}}})
        is None
    )
    assert (
        gragas.item_candidate_blocker({"id": 2, "stats": {"MANA": {}, "OMNIVAMP": {}}})
        == "GRAGAS_ITEM_STAT_NOT_MODELED:2:MANA"
    )
