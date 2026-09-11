"""Focused regressions for the locked Neeko champion Cog."""

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
    """Build a level-13 Neeko-versus-Garen encounter.

    :param as_actor: Place Neeko in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Neeko.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    neeko = registry.require_cog("Neeko")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        neeko.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one named Neeko event.

    :param plan: Action plan containing the expected event.
    :param event_id: Exact stable identifier.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_neeko_metadata_blooms_basic_root_and_r_phases_are_explicit() -> None:
    """Require evidence, three Q blooms, basic E root, R phases, and determinism."""
    cog = create_default_registry(ROOT).require_cog("Neeko")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    assert len([event for event in plan.events if "NEEKO_Q_BLOOMING_BURST" in event.id]) == 3
    assert _event(plan, "NEEKO_E_TANGLE_BARBS_UNEMPOWERED").outputs[1].duration_ms == 1500
    assert _event(plan, "NEEKO_R_POP_BLOSSOM_AIRBORNE").at_ms == 2250
    assert "NEEKO_E_NO_INTERVENING_UNIT_SO_BASIC_ROOT_USED" in plan.blockers


def test_neeko_ap_attack_speed_third_hit_and_control_are_connected() -> None:
    """Exercise AP, attack cadence, W third hit, movement, and R control phases."""
    cog = create_default_registry(ROOT).require_cog("Neeko")
    base = cog.build_action_plan(_context())
    powered = cog.build_action_plan(
        _context(item_stats={"AP": Decimal(100), "ATTACK_SPEED": Decimal("0.5")})
    )

    assert (
        _event(powered, "NEEKO_Q_BLOOMING_BURST_1").outputs[0].amount
        - _event(base, "NEEKO_Q_BLOOMING_BURST_1").outputs[0].amount
        == 60
    )
    assert (
        _event(powered, "NEEKO_R_POP_BLOSSOM_LAND").outputs[0].amount
        - _event(base, "NEEKO_R_POP_BLOSSOM_LAND").outputs[0].amount
        == 120
    )
    powered_attacks = [event for event in powered.events if "NEEKO_BASIC_ATTACK" in event.id]
    assert len(powered_attacks) > len(
        [event for event in base.events if "NEEKO_BASIC_ATTACK" in event.id]
    )
    assert len(powered_attacks[2].outputs) == 2
    assert cog.engagement_speed_multiplier(_context()) == Decimal("1.20")
    assert tuple(
        window.control_type for window in cog.build_reaction_plan(_context()).cast_block_windows
    ) == (ControlType.ROOT, ControlType.AIRBORNE, ControlType.STUN)


def test_neeko_role_reversal_and_item_policy_are_honest() -> None:
    """Reverse damage and retain disguise, clone, and stale-shield blockers."""
    cog = create_default_registry(ROOT).require_cog("Neeko")
    plan = cog.build_action_plan(_context(as_actor=False))

    assert all(event.source is EntityId.TARGET for event in plan.events)
    assert any(
        isinstance(output, DamageOutput) and output.recipient is EntityId.ACTOR
        for event in plan.events
        for output in event.outputs
    )
    assert (
        "NEEKO_R_LOCKED_TOOLTIP_DOES_NOT_DECLARE_SHIELD_SO_STALE_BIN_VALUES_IGNORED"
        in plan.blockers
    )
    assert "NEEKO_W_STEALTH_AND_CLONE_TARGET_DECEPTION_NOT_MODELED" in plan.blockers
    assert (
        cog.item_candidate_blocker({"id": 9, "stats": {"MANA": {}, "OMNIVAMP": {}}})
        == "NEEKO_ITEM_STAT_NOT_MODELED:9:MANA"
    )
