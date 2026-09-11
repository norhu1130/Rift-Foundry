"""Focused regressions for the locked Lissandra champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.combat import DamageType
from lol_build.core.timeline import DamageOutput, EntityId, MissingHealthHealOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    as_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a level-13 Lissandra-versus-Garen encounter.

    :param as_actor: Place Lissandra in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Lissandra.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    lissandra = registry.require_cog("Lissandra")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        lissandra.snapshot(level=13, item_stats=item_stats),
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


def test_lissandra_metadata_and_evidence_are_complete() -> None:
    """Require complete routing and all three locked evidence forms."""
    cog = create_default_registry(ROOT).require_cog("Lissandra")

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)


def test_lissandra_self_tomb_rotation_is_deterministic_and_haste_sensitive() -> None:
    """Anchor the single self-cast ultimate and haste-dependent shard clock."""
    cog = create_default_registry(ROOT).require_cog("Lissandra")
    base = cog.build_action_plan(_context())
    fast = cog.build_action_plan(_context(item_stats={"ABILITY_HASTE": Decimal(100)}))

    assert base == cog.build_action_plan(_context())
    tomb = _event(base, "LISSANDRA_R_FROZEN_TOMB_SELF_CAST")
    heal = next(o for o in tomb.outputs if isinstance(o, MissingHealthHealOutput))
    assert heal.base_amount == Decimal(150)
    assert heal.missing_health_ratio == Decimal(150) / _context().snapshot.max_hp
    base_q = [event for event in base.events if "Q_ICE_SHARD" in event.id]
    fast_q = [event for event in fast.events if "Q_ICE_SHARD" in event.id]
    assert len(fast_q) > len(base_q)
    assert all(not 2500 <= event.at_ms < 5000 for event in fast_q)


def test_lissandra_reaction_exposes_invulnerability_immunity_and_control() -> None:
    """Preserve self-tomb defenses and hostile root/slow windows."""
    cog = create_default_registry(ROOT).require_cog("Lissandra")
    reaction = cog.build_reaction_plan(_context())

    assert reaction.damage_windows[0].damage_types == (
        DamageType.PHYSICAL,
        DamageType.MAGIC,
        DamageType.TRUE,
    )
    assert reaction.damage_windows[0].multiplier == 0
    assert reaction.control_immunity_windows[0].control_types == (ControlType.ALL,)
    assert reaction.cast_block_windows[0].control_type is ControlType.ROOT


def test_lissandra_ap_role_reversal_sustain_and_item_policy_are_honest() -> None:
    """Exercise AP scaling, role symmetry, and explicit unsupported channels."""
    cog = create_default_registry(ROOT).require_cog("Lissandra")
    base = cog.build_action_plan(_context())
    powered = cog.build_action_plan(_context(item_stats={"AP": Decimal(100)}))
    reversed_plan = cog.build_action_plan(_context(as_actor=False))

    base_e = next(
        output.amount
        for output in _event(base, "LISSANDRA_E_GLACIAL_PATH_HIT_AND_RECAST").outputs
        if isinstance(output, DamageOutput)
    )
    powered_e = next(
        output.amount
        for output in _event(powered, "LISSANDRA_E_GLACIAL_PATH_HIT_AND_RECAST").outputs
        if isinstance(output, DamageOutput)
    )
    assert powered_e > base_e
    assert all(event.source is EntityId.TARGET for event in reversed_plan.events)
    sustain, blockers = cog.lane_sustain_extra_health(
        _context(), duration_ms=30_000, no_damage_delay_ms=8000
    )
    assert sustain == 0
    assert blockers == ("LISSANDRA_R_NOT_REPEATABLE_LANE_SUSTAIN",)
    assert (
        cog.item_candidate_blocker({"id": 2, "stats": {"MANA": {}, "OMNIVAMP": {}}})
        == "LISSANDRA_ITEM_STAT_NOT_MODELED:2:MANA"
    )
