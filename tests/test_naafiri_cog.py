"""Focused regressions for the locked current-rework Naafiri Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import (
    DamageOutput,
    EntityId,
    HealOutput,
    MissingHealthDamageOutput,
    StatModifierOutput,
)

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *, as_actor: bool = True, item_stats: dict[str, Decimal] | None = None
) -> ParticipantContext:
    """Build a level-13 Naafiri-versus-Garen encounter.

    :param as_actor: Place Naafiri in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Naafiri.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    naafiri = registry.require_cog("Naafiri")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        naafiri.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one named Naafiri event.

    :param plan: Action plan containing the expected event.
    :param event_id: Exact stable identifier.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_naafiri_metadata_current_spell_layout_and_pack_are_explicit() -> None:
    """Require evidence, current W/R identity, six packmates, and determinism."""
    cog = create_default_registry(ROOT).require_cog("Naafiri")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    assert _event(plan, "NAAFIRI_W_CALL_OF_THE_PACK").at_ms == 0
    pursuit = _event(plan, "NAAFIRI_R_HOUNDS_PURSUIT_SIX_PACKMATES")
    assert isinstance(pursuit.outputs[1], StatModifierOutput)
    assert pursuit.outputs[1].stat == "ARMOR"
    assert pursuit.outputs[1].amount == -30
    assert "NAAFIRI_CURRENT_PATCH_W_IS_CALL_OF_THE_PACK_R_IS_HOUNDS_PURSUIT" in plan.blockers


def test_naafiri_bonus_ad_q2_heal_and_pack_scaling_are_connected() -> None:
    """Exercise W-amplified bonus AD across R, Q2, healing, E, and packmates."""
    cog = create_default_registry(ROOT).require_cog("Naafiri")
    base = cog.build_action_plan(_context())
    powered = cog.build_action_plan(_context(item_stats={"AD": Decimal(100)}))

    for event_id in (
        "NAAFIRI_R_HOUNDS_PURSUIT_SIX_PACKMATES",
        "NAAFIRI_Q_DARKIN_DAGGERS_FIRST",
        "NAAFIRI_E_EVISCERATE_BOTH_SLASHES",
        "NAAFIRI_PASSIVE_SIX_PACKMATES_ATTACK_1",
    ):
        assert (
            _event(powered, event_id).outputs[0].amount > _event(base, event_id).outputs[0].amount
        )
    recast = _event(powered, "NAAFIRI_Q_DARKIN_DAGGERS_RECAST")
    assert isinstance(recast.outputs[1], MissingHealthDamageOutput)
    assert isinstance(recast.outputs[2], HealOutput)
    assert (
        recast.outputs[2].amount > _event(base, "NAAFIRI_Q_DARKIN_DAGGERS_RECAST").outputs[2].amount
    )


def test_naafiri_role_reversal_reaction_and_item_policy_are_honest() -> None:
    """Reverse outputs and retain targetability, takedown, and sustain blockers."""
    cog = create_default_registry(ROOT).require_cog("Naafiri")
    plan = cog.build_action_plan(_context(as_actor=False))

    assert all(event.source is EntityId.TARGET for event in plan.events)
    assert any(
        isinstance(output, DamageOutput) and output.recipient is EntityId.ACTOR
        for event in plan.events
        for output in event.outputs
    )
    reaction = cog.build_reaction_plan(_context())
    assert reaction.cast_block_windows[0].control_type is ControlType.SLOW
    assert not reaction.damage_windows
    assert "NAAFIRI_W_UNTARGETABLE_REQUIRES_TARGETABILITY_METADATA" in reaction.blockers
    sustain, blockers = cog.lane_sustain_extra_health(
        _context(), duration_ms=30_000, no_damage_delay_ms=8000
    )
    assert sustain == 0
    assert blockers == ("NAAFIRI_Q2_HEAL_REQUIRES_BLEEDING_CHAMPION_HIT_AND_MANA",)
    assert (
        cog.item_candidate_blocker({"id": 6, "stats": {"MANA": {}, "OMNIVAMP": {}}})
        == "NAAFIRI_ITEM_STAT_NOT_MODELED:6:MANA"
    )
