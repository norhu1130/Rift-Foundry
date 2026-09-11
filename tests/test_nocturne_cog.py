"""Focused regressions for the locked Nocturne champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId, HealOutput, StatusOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *, as_actor: bool = True, item_stats: dict[str, Decimal] | None = None
) -> ParticipantContext:
    """Build a level-13 Nocturne-versus-Garen encounter.

    :param as_actor: Place Nocturne in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Nocturne.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    nocturne = registry.require_cog("Nocturne")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        nocturne.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one named Nocturne event.

    :param plan: Action plan containing the expected event.
    :param event_id: Exact stable identifier.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_nocturne_metadata_rotation_and_evidence_are_explicit() -> None:
    """Require evidence, four tether ticks, spell shield, passive, and determinism."""
    cog = create_default_registry(ROOT).require_cog("Nocturne")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    assert len([event for event in plan.events if "UNSPEAKABLE_HORROR_TICK" in event.id]) == 4
    shield = _event(plan, "NOCTURNE_W_SHROUD_OF_DARKNESS").outputs[0]
    assert isinstance(shield, StatusOutput)
    assert shield.status == "SPELL_SHIELD"
    passive = _event(plan, "NOCTURNE_UMBRA_BLADES_ATTACK_1")
    assert any(isinstance(output, HealOutput) for output in passive.outputs)


def test_nocturne_stats_engagement_and_delayed_fear_are_connected() -> None:
    """Exercise AD, AP, attack speed, crit, Paranoia range, trail speed, and fear."""
    cog = create_default_registry(ROOT).require_cog("Nocturne")
    base = cog.build_action_plan(_context())
    powered_context = _context(
        item_stats={
            "AD": Decimal(100),
            "AP": Decimal(100),
            "ATTACK_SPEED": Decimal("0.5"),
            "CRITICAL_STRIKE_CHANCE": Decimal("0.5"),
        }
    )
    powered = cog.build_action_plan(powered_context)

    assert (
        _event(powered, "NOCTURNE_R_PARANOIA_DASH").outputs[0].amount
        - _event(base, "NOCTURNE_R_PARANOIA_DASH").outputs[0].amount
        == 120
    )
    assert _event(powered, "NOCTURNE_E_UNSPEAKABLE_HORROR_TICK_1").outputs[0].amount == 90
    assert len([event for event in powered.events if "ATTACK" in event.id]) > len(
        [event for event in base.events if "ATTACK" in event.id]
    )
    assert cog.engagement_speed_multiplier(powered_context) == Decimal("1.35")
    assert cog.engagement_dash_distance(powered_context) == 4250
    fear = cog.build_reaction_plan(powered_context).cast_block_windows[0]
    assert fear.start_ms == 2300
    assert fear.end_ms == 4550
    assert fear.tenacity_reducible is True


def test_nocturne_role_reversal_sustain_and_item_policy_are_honest() -> None:
    """Reverse outputs and retain lane-state, resource, and W blockers."""
    cog = create_default_registry(ROOT).require_cog("Nocturne")
    context = _context(as_actor=False)
    plan = cog.build_action_plan(context)

    assert all(event.source is EntityId.TARGET for event in plan.events)
    assert all(
        output.recipient is EntityId.ACTOR
        for event in plan.events
        for output in event.outputs
        if isinstance(output, DamageOutput)
    )
    passive = _event(plan, "NOCTURNE_UMBRA_BLADES_ATTACK_1")
    assert any(
        isinstance(output, HealOutput) and output.recipient is EntityId.TARGET
        for output in passive.outputs
    )
    sustain, blockers = cog.lane_sustain_extra_health(
        context, duration_ms=30_000, no_damage_delay_ms=8000
    )
    assert sustain == 0
    assert blockers == ("NOCTURNE_PASSIVE_LANE_HEAL_REQUIRES_ATTACK_TARGET_TIMELINE",)
    assert (
        cog.item_candidate_blocker({"id": 10, "stats": {"MANA": {}, "OMNIVAMP": {}}})
        == "NOCTURNE_ITEM_STAT_NOT_MODELED:10:MANA"
    )
