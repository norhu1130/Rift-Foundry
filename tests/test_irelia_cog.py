"""Focused regressions for the locked Irelia champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.combat import DamageType
from lol_build.core.timeline import DamageOutput, EntityId, HealOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    as_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a level-13 Irelia-versus-Garen encounter.

    :param as_actor: Place Irelia in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Irelia.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    irelia = registry.require_cog("Irelia")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        irelia.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Locate an event by stable identifier.

    :param plan: Action plan exposing an events tuple.
    :param event_id: Exact event identifier to locate.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_irelia_metadata_and_evidence_are_complete() -> None:
    """Require complete recommendation routing and three locked sources."""
    cog = create_default_registry(ROOT).require_cog("Irelia")

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)


def test_irelia_rotation_contains_mark_resets_heals_and_max_fervor() -> None:
    """Anchor marked Q casts, W charge, and empowered follow-up attacks."""
    cog = create_default_registry(ROOT).require_cog("Irelia")
    plan = cog.build_action_plan(_context())

    assert plan == cog.build_action_plan(_context())
    q_events = [event for event in plan.events if event.id.startswith("IRELIA_Q_")]
    attacks = [event for event in plan.events if "MAX_FERVOR_ATTACK" in event.id]
    assert len(q_events) == 3
    assert attacks
    assert all(
        any(isinstance(output, HealOutput) for output in event.outputs) for event in q_events
    )
    assert any(
        isinstance(output, DamageOutput) and output.damage_type is DamageType.MAGIC
        for output in attacks[0].outputs
    )
    assert _event(plan, "IRELIA_W_DEFIANT_DANCE_FULL_CHARGE")


def test_irelia_haste_ad_ap_and_attack_speed_reach_their_mechanics() -> None:
    """Exercise Q cadence, mixed spell scaling, and passive attack cadence."""
    cog = create_default_registry(ROOT).require_cog("Irelia")
    base = cog.build_action_plan(_context())
    powered = cog.build_action_plan(
        _context(
            item_stats={
                "AD": Decimal(50),
                "AP": Decimal(100),
                "ABILITY_HASTE": Decimal(100),
                "ATTACK_SPEED": Decimal("0.50"),
            }
        )
    )

    base_q = [event for event in base.events if event.id.startswith("IRELIA_Q_")]
    powered_q = [event for event in powered.events if event.id.startswith("IRELIA_Q_")]
    base_attacks = [event for event in base.events if "MAX_FERVOR_ATTACK" in event.id]
    powered_attacks = [event for event in powered.events if "MAX_FERVOR_ATTACK" in event.id]
    assert powered_q[-1].at_ms < base_q[-1].at_ms
    assert len(powered_attacks) > len(base_attacks)
    base_r = next(
        output.amount
        for output in _event(base, "IRELIA_R_VANGUARDS_EDGE_MISSILE").outputs
        if isinstance(output, DamageOutput)
    )
    powered_r = next(
        output.amount
        for output in _event(powered, "IRELIA_R_VANGUARDS_EDGE_MISSILE").outputs
        if isinstance(output, DamageOutput)
    )
    assert powered_r > base_r


def test_irelia_reaction_distinguishes_damage_types_and_control() -> None:
    """Preserve W's asymmetric mitigation and E/R control categories."""
    cog = create_default_registry(ROOT).require_cog("Irelia")
    reaction = cog.build_reaction_plan(_context())

    assert reaction.damage_windows[0].damage_types == (DamageType.PHYSICAL,)
    assert reaction.damage_windows[1].damage_types == (DamageType.MAGIC,)
    assert reaction.damage_windows[0].multiplier < reaction.damage_windows[1].multiplier
    assert tuple(window.control_type for window in reaction.cast_block_windows) == (
        ControlType.STUN,
        ControlType.SLOW,
    )


def test_irelia_role_reversal_and_item_policy_remain_honest() -> None:
    """Reverse hostile recipients and reject unrepresented item channels."""
    cog = create_default_registry(ROOT).require_cog("Irelia")
    plan = cog.build_action_plan(_context(as_actor=False))

    assert all(event.source is EntityId.TARGET for event in plan.events)
    assert any(
        isinstance(output, DamageOutput) and output.recipient is EntityId.ACTOR
        for event in plan.events
        for output in event.outputs
    )
    assert (
        cog.item_candidate_blocker(
            {"id": 1, "stats": {"AD": {}, "AP": {}, "ATTACK_SPEED": {}, "HP": {}}}
        )
        is None
    )
    assert (
        cog.item_candidate_blocker({"id": 2, "stats": {"MANA": {}, "LIFESTEAL": {}}})
        == "IRELIA_ITEM_STAT_NOT_MODELED:2:MANA"
    )
