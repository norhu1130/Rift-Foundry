"""Focused regressions for the locked Nautilus champion Cog."""

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
    """Build a level-13 Nautilus-versus-Garen encounter.

    :param as_actor: Place Nautilus in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Nautilus.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    nautilus = registry.require_cog("Nautilus")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        nautilus.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one named Nautilus event.

    :param plan: Action plan containing the expected event.
    :param event_id: Exact stable identifier.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_nautilus_metadata_shield_waves_dot_and_passive_are_explicit() -> None:
    """Require evidence, shield, three E waves, four W ticks, and passive root."""
    cog = create_default_registry(ROOT).require_cog("Nautilus")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    assert isinstance(_event(plan, "NAUTILUS_W_TITANS_WRATH_SHIELD").outputs[0], ShieldOutput)
    assert len([event for event in plan.events if "E_RIPTIDE_WAVE" in event.id]) == 3
    assert len([event for event in plan.events if "W_TITANS_WRATH_DOT" in event.id]) == 4
    assert isinstance(_event(plan, "NAUTILUS_PASSIVE_STAGGERING_BLOW").outputs[1], StatusOutput)


def test_nautilus_ap_health_attack_speed_and_control_are_connected() -> None:
    """Exercise AP, maximum health shielding, attack clock, reach, and CC phases."""
    cog = create_default_registry(ROOT).require_cog("Nautilus")
    base = cog.build_action_plan(_context())
    powered = cog.build_action_plan(
        _context(
            item_stats={"AP": Decimal(100), "HP": Decimal(1000), "ATTACK_SPEED": Decimal("0.5")}
        )
    )

    assert (
        _event(powered, "NAUTILUS_Q_DREDGE_LINE").outputs[0].amount
        - _event(base, "NAUTILUS_Q_DREDGE_LINE").outputs[0].amount
        == 90
    )
    assert (
        _event(powered, "NAUTILUS_W_TITANS_WRATH_SHIELD").outputs[0].amount
        - _event(base, "NAUTILUS_W_TITANS_WRATH_SHIELD").outputs[0].amount
        == 120
    )
    assert len([event for event in powered.events if "BASIC_ATTACK" in event.id]) > len(
        [event for event in base.events if "BASIC_ATTACK" in event.id]
    )
    controls = cog.build_reaction_plan(_context()).cast_block_windows
    assert tuple(window.control_type for window in controls) == (
        ControlType.AIRBORNE,
        ControlType.ROOT,
        ControlType.SLOW,
        ControlType.AIRBORNE,
        ControlType.STUN,
    )
    assert cog.engagement_dash_distance(_context()) == 1150


def test_nautilus_role_reversal_and_item_policy_are_honest() -> None:
    """Reverse damage and shield recipients while retaining conditional blockers."""
    cog = create_default_registry(ROOT).require_cog("Nautilus")
    plan = cog.build_action_plan(_context(as_actor=False))

    assert all(event.source is EntityId.TARGET for event in plan.events)
    assert any(
        isinstance(output, DamageOutput) and output.recipient is EntityId.ACTOR
        for event in plan.events
        for output in event.outputs
    )
    assert _event(plan, "NAUTILUS_W_TITANS_WRATH_SHIELD").outputs[0].recipient is EntityId.TARGET
    assert "NAUTILUS_W_REQUIRES_SHIELD_TO_PERSIST_FOR_ATTACK_DOT" in plan.blockers
    assert (
        cog.item_candidate_blocker({"id": 8, "stats": {"MANA": {}, "OMNIVAMP": {}}})
        == "NAUTILUS_ITEM_STAT_NOT_MODELED:8:MANA"
    )
