"""Focused regressions for the locked Nami champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import DamageOutput, EntityId, HealOutput, StatusOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *, as_actor: bool = True, item_stats: dict[str, Decimal] | None = None
) -> ParticipantContext:
    """Build a level-13 Nami-versus-Garen encounter.

    :param as_actor: Place Nami in the actor role when true.
    :param item_stats: Optional permanent modifiers applied to Nami.
    :return: Deterministic eight-second participant context.
    """
    registry = create_default_registry(ROOT)
    nami = registry.require_cog("Nami")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if as_actor else EntityId.TARGET,
        EntityId.TARGET if as_actor else EntityId.ACTOR,
        nami.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan, event_id: str):
    """Resolve one named Nami event.

    :param plan: Action plan containing the expected event.
    :param event_id: Exact stable identifier.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_nami_metadata_self_buff_bounce_and_three_procs_are_explicit() -> None:
    """Require evidence, self E, self-heal bounce, three procs, and determinism."""
    cog = create_default_registry(ROOT).require_cog("Nami")
    plan = cog.build_action_plan(_context())

    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert all((ROOT / ref).is_file() for ref in cog.evidence_refs)
    assert plan == cog.build_action_plan(_context())
    assert isinstance(_event(plan, "NAMI_E_TIDECALLERS_BLESSING_SELF").outputs[0], StatusOutput)
    assert isinstance(_event(plan, "NAMI_W_EBB_AND_FLOW_SELF_HEAL").outputs[0], HealOutput)
    assert all(
        len(_event(plan, event_id).outputs) >= 2
        for event_id in (
            "NAMI_Q_AQUA_PRISON_E_PROC",
            "NAMI_W_EBB_AND_FLOW_ENEMY_BOUNCE_E_PROC",
            "NAMI_R_TIDAL_WAVE_E_PROC",
        )
    )


def test_nami_ap_bounce_speed_and_control_are_connected() -> None:
    """Exercise AP across damage, heal, bounce scaling, movement, and CC windows."""
    cog = create_default_registry(ROOT).require_cog("Nami")
    base = cog.build_action_plan(_context())
    powered = cog.build_action_plan(_context(item_stats={"AP": Decimal(100)}))

    for event_id in (
        "NAMI_Q_AQUA_PRISON_E_PROC",
        "NAMI_W_EBB_AND_FLOW_ENEMY_BOUNCE_E_PROC",
        "NAMI_R_TIDAL_WAVE_E_PROC",
    ):
        assert (
            _event(powered, event_id).outputs[0].amount > _event(base, event_id).outputs[0].amount
        )
    assert _event(powered, "NAMI_W_EBB_AND_FLOW_SELF_HEAL").outputs[0].amount == 195
    assert cog.engagement_speed_multiplier(
        _context(item_stats={"AP": Decimal(100)})
    ) > cog.engagement_speed_multiplier(_context())
    controls = cog.build_reaction_plan(_context()).cast_block_windows
    assert tuple(window.control_type for window in controls) == (
        ControlType.STUN,
        ControlType.AIRBORNE,
        ControlType.SLOW,
    )


def test_nami_role_reversal_sustain_and_item_policy_are_honest() -> None:
    """Reverse outputs and retain bounce, distance, and resource blockers."""
    cog = create_default_registry(ROOT).require_cog("Nami")
    plan = cog.build_action_plan(_context(as_actor=False))

    assert all(event.source is EntityId.TARGET for event in plan.events)
    assert any(
        isinstance(output, DamageOutput) and output.recipient is EntityId.ACTOR
        for event in plan.events
        for output in event.outputs
    )
    assert any(
        isinstance(output, HealOutput) and output.recipient is EntityId.TARGET
        for event in plan.events
        for output in event.outputs
    )
    assert "NAMI_W_NO_THIRD_VALID_ALLY_TARGET_IN_DUEL" in plan.blockers
    sustain, blockers = cog.lane_sustain_extra_health(
        _context(), duration_ms=30_000, no_damage_delay_ms=8000
    )
    assert sustain == 0
    assert blockers == ("NAMI_W_SELF_HEAL_REQUIRES_MANA_AND_COOLDOWN_STATE",)
    assert (
        cog.item_candidate_blocker({"id": 7, "stats": {"MANA": {}, "OMNIVAMP": {}}})
        == "NAMI_ITEM_STAT_NOT_MODELED:7:MANA,OMNIVAMP"
    )
