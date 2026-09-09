"""Focused regressions for the locked Nilah champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.combat import DamageType
from lol_build.core.timeline import DamageOutput, EntityId

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *, as_actor: bool = True, item_stats: dict[str, Decimal] | None = None
) -> ParticipantContext:
    """Build a level-13 Nilah-versus-Garen encounter.

    :param as_actor: Place Nilah in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Nilah.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    nilah = registry.require_cog("Nilah")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        nilah.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one named Nilah event.

    :param plan: Action plan containing the expected event.
    :param event_id: Exact stable identifier.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_nilah_metadata_rotation_and_evidence_are_explicit() -> None:
    """Require evidence, two E charges, four R ticks, and determinism."""
    cog = create_default_registry(ROOT).require_cog("Nilah")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    assert len([event for event in plan.events if "SLIPSTREAM_CHARGE" in event.id]) == 2
    assert len([event for event in plan.events if "APOTHEOSIS_SPIN" in event.id]) == 4
    assert "NILAH_R_POST_MITIGATION_HEAL_AND_OVERHEAL_SHIELD_NOT_MODELED" in plan.blockers


def test_nilah_critical_scaling_and_output_penetration_are_connected() -> None:
    """Exercise crit-dependent Q, attacks, and output-local armor penetration."""
    cog = create_default_registry(ROOT).require_cog("Nilah")
    base = cog.build_action_plan(_context())
    critical = cog.build_action_plan(
        _context(item_stats={"CRITICAL_STRIKE_CHANCE": Decimal("0.50")})
    )

    base_q = _event(base, "NILAH_Q_FORMLESS_BLADE").outputs[0]
    critical_q = _event(critical, "NILAH_Q_FORMLESS_BLADE").outputs[0]
    assert isinstance(base_q, DamageOutput)
    assert isinstance(critical_q, DamageOutput)
    assert critical_q.amount > base_q.amount
    assert critical_q.percent_resistance_penetration == Decimal("0.1500")
    critical_attack = next(
        event.outputs[0] for event in critical.events if "Q_EMPOWERED_BASIC_ATTACK" in event.id
    )
    base_attack = next(
        event.outputs[0] for event in base.events if "Q_EMPOWERED_BASIC_ATTACK" in event.id
    )
    assert critical_attack.amount == base_attack.amount * Decimal("1.5")


def test_nilah_role_reversal_reactions_engagement_and_policy_are_honest() -> None:
    """Reverse recipients and retain W, pull, engagement, and sustain blockers."""
    cog = create_default_registry(ROOT).require_cog("Nilah")
    context = _context(as_actor=False)
    plan = cog.build_action_plan(context)
    reactions = cog.build_reaction_plan(context)

    assert all(event.source is EntityId.TARGET for event in plan.events)
    assert all(
        output.recipient is EntityId.ACTOR
        for event in plan.events
        for output in event.outputs
        if isinstance(output, DamageOutput)
    )
    assert reactions.damage_windows[0].recipient is EntityId.TARGET
    assert reactions.damage_windows[0].damage_types == (DamageType.MAGIC,)
    assert reactions.damage_windows[0].multiplier == Decimal("0.75")
    assert cog.engagement_speed_multiplier(context) == Decimal("1.15")
    assert cog.engagement_dash_distance(context) == 600
    sustain, blockers = cog.lane_sustain_extra_health(
        context, duration_ms=30_000, no_damage_delay_ms=8000
    )
    assert sustain == 0
    assert blockers == ("NILAH_Q_SUSTAIN_REQUIRES_CHAMPION_DAMAGE_AND_CURRENT_HEALTH",)
    assert (
        cog.item_candidate_blocker({"id": 10, "stats": {"LIFESTEAL": {}, "MANA": {}}})
        == "NILAH_ITEM_STAT_NOT_MODELED:10:LIFESTEAL,MANA"
    )
