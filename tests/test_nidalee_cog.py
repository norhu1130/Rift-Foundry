"""Focused regressions for the locked Nidalee champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import (
    DamageOutput,
    EntityId,
    MissingHealthDamageOutput,
    MissingHealthHealOutput,
)

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *, as_actor: bool = True, item_stats: dict[str, Decimal] | None = None
) -> ParticipantContext:
    """Build a level-13 Nidalee-versus-Garen encounter.

    :param as_actor: Place Nidalee in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Nidalee.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    nidalee = registry.require_cog("Nidalee")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        nidalee.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one named Nidalee event.

    :param plan: Action plan containing the expected event.
    :param event_id: Exact stable identifier.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_nidalee_metadata_human_to_cougar_rotation_is_explicit() -> None:
    """Require evidence, Hunt, heal, transform, cougar skills, and determinism."""
    cog = create_default_registry(ROOT).require_cog("Nidalee")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    assert len(_event(plan, "NIDALEE_Q_JAVELIN_TOSS_MAX_RANGE").outputs) == 2
    assert isinstance(
        _event(plan, "NIDALEE_E_PRIMAL_SURGE_SELF_MINIMUM").outputs[0],
        MissingHealthHealOutput,
    )
    assert isinstance(
        _event(plan, "NIDALEE_Q_TAKEDOWN_BASE_MISSING_HEALTH").outputs[0],
        MissingHealthDamageOutput,
    )
    assert "NIDALEE_HUNTED_TAKEDOWN_EXTRA_MULTIPLIER_NOT_STRUCTURED_IN_LOCKED_BIN" in plan.blockers


def test_nidalee_ap_attack_speed_and_hunted_engagement_are_connected() -> None:
    """Exercise AP, self healing, accelerated attacks, pursuit speed, and Pounce."""
    cog = create_default_registry(ROOT).require_cog("Nidalee")
    base = cog.build_action_plan(_context())
    powered = cog.build_action_plan(
        _context(item_stats={"AP": Decimal(100), "ATTACK_SPEED": Decimal("0.5")})
    )

    assert _event(powered, "NIDALEE_Q_JAVELIN_TOSS_MAX_RANGE").outputs[0].amount - _event(
        base, "NIDALEE_Q_JAVELIN_TOSS_MAX_RANGE"
    ).outputs[0].amount == Decimal("162.5")
    assert _event(powered, "NIDALEE_E_PRIMAL_SURGE_SELF_MINIMUM").outputs[0].base_amount == 185
    assert len([event for event in powered.events if "COUGAR_BASIC_ATTACK" in event.id]) > len(
        [event for event in base.events if "COUGAR_BASIC_ATTACK" in event.id]
    )
    assert cog.engagement_speed_multiplier(_context()) == Decimal("1.30")
    assert cog.engagement_dash_distance(_context()) == 750


def test_nidalee_role_reversal_sustain_and_item_policy_are_honest() -> None:
    """Reverse outputs and retain form, coefficient, and sustain blockers."""
    cog = create_default_registry(ROOT).require_cog("Nidalee")
    plan = cog.build_action_plan(_context(as_actor=False))

    assert all(event.source is EntityId.TARGET for event in plan.events)
    assert any(
        isinstance(output, DamageOutput) and output.recipient is EntityId.ACTOR
        for event in plan.events
        for output in event.outputs
    )
    assert (
        _event(plan, "NIDALEE_E_PRIMAL_SURGE_SELF_MINIMUM").outputs[0].recipient is EntityId.TARGET
    )
    sustain, blockers = cog.lane_sustain_extra_health(
        _context(), duration_ms=30_000, no_damage_delay_ms=8000
    )
    assert sustain == 0
    assert blockers == ("NIDALEE_E_HEAL_REQUIRES_MANA_COOLDOWN_AND_MISSING_HEALTH",)
    assert (
        cog.item_candidate_blocker({"id": 10, "stats": {"MANA": {}, "OMNIVAMP": {}}})
        == "NIDALEE_ITEM_STAT_NOT_MODELED:10:MANA"
    )
