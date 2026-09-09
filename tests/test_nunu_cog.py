"""Focused regressions for the locked Nunu & Willump champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId, HealOutput, ShieldOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *, as_actor: bool = True, item_stats: dict[str, Decimal] | None = None
) -> ParticipantContext:
    """Build a level-13 Nunu-versus-Garen encounter.

    :param as_actor: Place Nunu in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Nunu.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    nunu = registry.require_cog("Nunu")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        nunu.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one named Nunu event.

    :param plan: Action plan containing the expected event.
    :param event_id: Exact stable identifier.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_nunu_metadata_full_rotation_and_evidence_are_explicit() -> None:
    """Require evidence, nine E projectiles, Q healing, R shield, and determinism."""
    cog = create_default_registry(ROOT).require_cog("Nunu")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    assert len([event for event in plan.events if "SNOWBALL_BARRAGE" in event.id]) == 9
    assert any(isinstance(x, HealOutput) for x in _event(plan, "NUNU_Q_CONSUME_CHAMPION").outputs)
    assert isinstance(_event(plan, "NUNU_R_ABSOLUTE_ZERO_SHIELD").outputs[0], ShieldOutput)


def test_nunu_ap_health_attack_speed_engagement_and_control_are_connected() -> None:
    """Exercise AP, health, attack speed, snowball range, passive speed, and controls."""
    cog = create_default_registry(ROOT).require_cog("Nunu")
    context = _context(
        item_stats={"AP": Decimal(100), "HP": Decimal(500), "ATTACK_SPEED": Decimal("0.5")}
    )
    plan = cog.build_action_plan(context)

    assert _event(plan, "NUNU_Q_CONSUME_CHAMPION").outputs[0].amount == 310
    assert _event(plan, "NUNU_R_ABSOLUTE_ZERO_MAXIMUM_DETONATION").outputs[0].amount == 1225
    assert _event(plan, "NUNU_R_ABSOLUTE_ZERO_SHIELD").outputs[0].amount == 425
    assert cog.engagement_speed_multiplier(context) == Decimal("1.10")
    assert cog.engagement_dash_distance(context) == 1750
    reactions = cog.build_reaction_plan(context)
    assert len(reactions.cast_block_windows) == 7
    assert reactions.cast_block_windows[-2].tenacity_reducible is True


def test_nunu_role_reversal_sustain_and_item_policy_are_honest() -> None:
    """Reverse outputs and retain channel, target-state, and resource blockers."""
    cog = create_default_registry(ROOT).require_cog("Nunu")
    context = _context(as_actor=False)
    plan = cog.build_action_plan(context)

    assert all(event.source is EntityId.TARGET for event in plan.events)
    assert all(
        output.recipient is EntityId.ACTOR
        for event in plan.events
        for output in event.outputs
        if isinstance(output, DamageOutput)
    )
    assert any(
        isinstance(output, HealOutput) and output.recipient is EntityId.TARGET
        for output in _event(plan, "NUNU_Q_CONSUME_CHAMPION").outputs
    )
    sustain, blockers = cog.lane_sustain_extra_health(
        context, duration_ms=30_000, no_damage_delay_ms=8000
    )
    assert sustain == 0
    assert blockers == ("NUNU_Q_LANE_HEAL_REQUIRES_TARGET_AND_CURRENT_HEALTH_TIMELINE",)
    assert (
        cog.item_candidate_blocker({"id": 10, "stats": {"MANA": {}}})
        == "NUNU_ITEM_STAT_NOT_MODELED:10:MANA"
    )
