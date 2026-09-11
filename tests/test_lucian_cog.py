"""Focused regressions for the locked Lucian champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    as_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a level-13 Lucian-versus-Garen encounter.

    :param as_actor: Place Lucian in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Lucian.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    lucian = registry.require_cog("Lucian")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        lucian.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def test_lucian_metadata_rotation_and_e_refund_are_complete() -> None:
    """Require locked evidence, passive pairs, and the refunded second dash."""
    cog = create_default_registry(ROOT).require_cog("Lucian")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    assert len([event for event in plan.events if "PASSIVE_LIGHTSLINGER" in event.id]) == 4
    assert any("E_RELENTLESS_PURSUIT_2" in event.id for event in plan.events)


def test_lucian_crit_and_ap_change_culling_and_w_damage() -> None:
    """Exercise Culling bullet-count scaling and Ardent Blaze's AP ratio."""
    cog = create_default_registry(ROOT).require_cog("Lucian")
    base = cog.build_action_plan(_context())
    powered = cog.build_action_plan(
        _context(item_stats={"AP": Decimal(100), "CRITICAL_STRIKE_CHANCE": Decimal("0.5")})
    )

    base_bullets = [event for event in base.events if "THE_CULLING_BULLET" in event.id]
    powered_bullets = [event for event in powered.events if "THE_CULLING_BULLET" in event.id]
    assert len(powered_bullets) > len(base_bullets)
    base_w = next(event for event in base.events if event.id == "LUCIAN_W_ARDENT_BLAZE")
    powered_w = next(event for event in powered.events if event.id == "LUCIAN_W_ARDENT_BLAZE")
    base_damage = next(o.amount for o in base_w.outputs if isinstance(o, DamageOutput))
    powered_damage = next(o.amount for o in powered_w.outputs if isinstance(o, DamageOutput))
    assert powered_damage > base_damage


def test_lucian_role_reversal_and_item_policy_are_honest() -> None:
    """Reverse damage recipients and reject unrepresented sustain channels."""
    cog = create_default_registry(ROOT).require_cog("Lucian")
    plan = cog.build_action_plan(_context(as_actor=False))

    assert all(event.source is EntityId.TARGET for event in plan.events)
    assert any(
        isinstance(output, DamageOutput) and output.recipient is EntityId.ACTOR
        for event in plan.events
        for output in event.outputs
    )
    assert (
        cog.item_candidate_blocker(
            {"id": 1, "stats": {"AD": {}, "AP": {}, "CRITICAL_STRIKE_CHANCE": {}}}
        )
        is None
    )
    assert (
        cog.item_candidate_blocker({"id": 2, "stats": {"MANA": {}, "LIFESTEAL": {}}})
        == "LUCIAN_ITEM_STAT_NOT_MODELED:2:MANA"
    )
