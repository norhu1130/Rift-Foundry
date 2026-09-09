"""Focused regressions for the locked Akali champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    as_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a level-13 Akali-versus-Garen context.

    :param as_actor: Place Akali in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Akali.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    akali = registry.require_cog("Akali")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        akali.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Locate one action by stable identifier.

    :param plan: Action plan exposing an events tuple.
    :param event_id: Exact event identifier to find.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def _damage_amount(plan: object, event_id: str) -> Decimal:
    """Return the first damage output from a named event.

    :param plan: Action plan exposing an events tuple.
    :param event_id: Exact damaging event identifier.
    :return: Raw amount of the first damage output.
    """
    event = _event(plan, event_id)
    return next(output.amount for output in event.outputs if isinstance(output, DamageOutput))


def test_akali_declares_modeled_metadata_and_locked_evidence() -> None:
    """Require complete recommendation capabilities and three evidence forms."""
    akali = create_default_registry(ROOT).require_cog("Akali")

    assert akali.maturity is CogMaturity.MODELED_UNVERIFIED
    assert akali.capabilities == DUEL_CAPABILITIES
    assert len(akali.evidence_refs) == 3
    assert all((ROOT / ref).is_file() for ref in akali.evidence_refs)


def test_akali_rotation_is_deterministic_and_contains_both_recasts() -> None:
    """Anchor the fixed Q/E/R sequence and blocker honesty."""
    akali = create_default_registry(ROOT).require_cog("Akali")
    first = akali.build_action_plan(_context())

    assert first == akali.build_action_plan(_context())
    assert first.model_id == "akali_q5_e5_w1_r2_level13_confirmed_mark_v1"
    assert _event(first, "AKALI_E1_SHURIKEN_FLIP")
    assert _event(first, "AKALI_E2_SHURIKEN_FLIP_RECAST")
    assert _event(first, "AKALI_R1_PERFECT_EXECUTION")
    assert _event(first, "AKALI_R2_PERFECT_EXECUTION_MINIMUM")
    assert "AKALI_R2_MISSING_HEALTH_AMPLIFICATION_NOT_MODELED" in first.blockers


def test_akali_damage_uses_total_ad_bonus_ad_and_ap_channels() -> None:
    """Differentiate Q/E total AD from R1 bonus AD and all AP ratios."""
    base = create_default_registry(ROOT).require_cog("Akali").build_action_plan(_context())
    powered = (
        create_default_registry(ROOT)
        .require_cog("Akali")
        .build_action_plan(_context(item_stats={"AD": Decimal(40), "AP": Decimal(100)}))
    )

    assert _damage_amount(powered, "AKALI_Q_FIVE_POINT_STRIKE_1") > _damage_amount(
        base, "AKALI_Q_FIVE_POINT_STRIKE_1"
    )
    assert _damage_amount(powered, "AKALI_E1_SHURIKEN_FLIP") > _damage_amount(
        base, "AKALI_E1_SHURIKEN_FLIP"
    )
    assert _damage_amount(powered, "AKALI_R1_PERFECT_EXECUTION") > _damage_amount(
        base, "AKALI_R1_PERFECT_EXECUTION"
    )


def test_akali_attack_speed_changes_only_follow_up_attack_count() -> None:
    """Keep spell fixtures fixed while allowing attack-speed item value."""
    akali = create_default_registry(ROOT).require_cog("Akali")
    normal = akali.build_action_plan(_context())
    fast = akali.build_action_plan(_context(item_stats={"ATTACK_SPEED": Decimal("0.80")}))

    normal_attacks = [
        event for event in normal.events if event.id.startswith("AKALI_BASIC_ATTACK_")
    ]
    fast_attacks = [event for event in fast.events if event.id.startswith("AKALI_BASIC_ATTACK_")]
    assert len(fast_attacks) > len(normal_attacks)
    assert len([event for event in fast.events if "FIVE_POINT_STRIKE" in event.id]) == 3


def test_akali_reaction_and_role_reversal_are_causal() -> None:
    """Preserve movement-only slows and reverse all hostile recipients."""
    akali = create_default_registry(ROOT).require_cog("Akali")
    reaction = akali.build_reaction_plan(_context())
    reversed_plan = akali.build_action_plan(_context(as_actor=False))

    assert all(window.control_type is ControlType.SLOW for window in reaction.cast_block_windows)
    assert all(
        window.blocked_channels == (window.blocked_channels[0],)
        for window in reaction.cast_block_windows
    )
    assert all(event.source is EntityId.TARGET for event in reversed_plan.events)
    assert any(
        isinstance(output, DamageOutput) and output.recipient is EntityId.ACTOR
        for event in reversed_plan.events
        for output in event.outputs
    )


def test_akali_item_policy_accepts_damage_and_rejects_unmodeled_haste() -> None:
    """Keep supported offensive stats while blocking fixed-schedule haste."""
    akali = create_default_registry(ROOT).require_cog("Akali")

    assert (
        akali.item_candidate_blocker(
            {"id": 1, "stats": {"AD": {}, "AP": {}, "ATTACK_SPEED": {}, "HP": {}}}
        )
        is None
    )
    assert (
        akali.item_candidate_blocker({"id": 2, "stats": {"ABILITY_HASTE": {}, "MANA": {}}})
        == "AKALI_ITEM_STAT_NOT_MODELED:2:ABILITY_HASTE,MANA"
    )
