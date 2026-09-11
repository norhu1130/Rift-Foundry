"""Focused regressions for the locked Morgana champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.combat import DamageType
from lol_build.core.timeline import DamageOutput, EntityId, MissingHealthDamageOutput, ShieldOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *, as_actor: bool = True, item_stats: dict[str, Decimal] | None = None
) -> ParticipantContext:
    """Build a level-13 Morgana-versus-Garen encounter.

    :param as_actor: Place Morgana in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Morgana.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    morgana = registry.require_cog("Morgana")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        morgana.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one named Morgana event.

    :param plan: Action plan containing the expected event.
    :param event_id: Exact stable identifier.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_morgana_metadata_shadow_ticks_and_tether_are_explicit() -> None:
    """Require evidence, ten dynamic W ticks, two R hits, and determinism."""
    cog = create_default_registry(ROOT).require_cog("Morgana")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    shadow = [event for event in plan.events if "W_TORMENTED_SHADOW" in event.id]
    assert len(shadow) == 10
    assert all(isinstance(event.outputs[0], MissingHealthDamageOutput) for event in shadow)
    assert _event(plan, "MORGANA_R_SOUL_SHACKLES_FINISH").at_ms == 3300


def test_morgana_ap_magic_shield_and_control_are_connected() -> None:
    """Exercise AP scaling, typed shielding, Q root, R slow, and R stun."""
    cog = create_default_registry(ROOT).require_cog("Morgana")
    base = cog.build_action_plan(_context())
    powered = cog.build_action_plan(_context(item_stats={"AP": Decimal(100)}))

    assert (
        _event(powered, "MORGANA_Q_DARK_BINDING").outputs[0].amount
        - _event(base, "MORGANA_Q_DARK_BINDING").outputs[0].amount
        == 90
    )
    shield = _event(powered, "MORGANA_E_BLACK_SHIELD_SELF").outputs[0]
    assert isinstance(shield, ShieldOutput)
    assert shield.amount == 390
    assert shield.damage_types == (DamageType.MAGIC,)
    controls = cog.build_reaction_plan(_context()).cast_block_windows
    assert tuple(window.control_type for window in controls) == (
        ControlType.ROOT,
        ControlType.SLOW,
        ControlType.STUN,
    )
    assert not cog.build_reaction_plan(_context()).control_immunity_windows


def test_morgana_role_reversal_sustain_and_item_policy_are_honest() -> None:
    """Reverse recipients and retain shield-coupling and passive blockers."""
    cog = create_default_registry(ROOT).require_cog("Morgana")
    plan = cog.build_action_plan(_context(as_actor=False))

    assert all(event.source is EntityId.TARGET for event in plan.events)
    assert any(
        isinstance(output, DamageOutput) and output.recipient is EntityId.ACTOR
        for event in plan.events
        for output in event.outputs
    )
    assert "MORGANA_E_CONTROL_PROTECTION_DEPENDS_ON_REMAINING_MAGIC_SHIELD" in plan.blockers
    sustain, blockers = cog.lane_sustain_extra_health(
        _context(), duration_ms=30_000, no_damage_delay_ms=8000
    )
    assert sustain == 0
    assert blockers == ("MORGANA_PASSIVE_REQUIRES_POST_MITIGATION_CHAMPION_DAMAGE",)
    assert (
        cog.item_candidate_blocker({"id": 5, "stats": {"MANA": {}, "OMNIVAMP": {}}})
        == "MORGANA_ITEM_STAT_NOT_MODELED:5:MANA"
    )
