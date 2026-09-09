"""Focused regressions for the locked Graves champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import ActionChannel, EntityId, StatModifierOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    graves_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a level-13 Graves-versus-Teemo direct context.

    :param graves_is_actor: Place Graves on the actor side when true.
    :param item_stats: Optional permanent item modifiers for Graves.
    :return: Role-bound deterministic encounter context.
    """
    registry = create_default_registry(ROOT)
    graves = registry.require_cog("Graves")
    teemo = registry.require_cog("Teemo")
    return ParticipantContext(
        EntityId.ACTOR if graves_is_actor else EntityId.TARGET,
        EntityId.TARGET if graves_is_actor else EntityId.ACTOR,
        graves.snapshot(level=13, item_stats=item_stats),
        teemo.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Locate one Graves event by its stable identifier.

    :param plan: Action plan exposing an events tuple.
    :param event_id: Exact event identifier to locate.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_graves_declares_complete_modeled_metadata() -> None:
    """Require full capabilities and three locked evidence forms."""
    graves = create_default_registry(ROOT).require_cog("Graves")

    assert graves.maturity is CogMaturity.MODELED_UNVERIFIED
    assert graves.capabilities == DUEL_CAPABILITIES
    assert len(graves.evidence_refs) == 3
    assert all((ROOT / ref).is_file() for ref in graves.evidence_refs)


def test_graves_rotation_is_deterministic_and_separates_pellets() -> None:
    """Anchor the fixed magazine and pellet-separated basic attacks."""
    graves = create_default_registry(ROOT).require_cog("Graves")
    context = _context()
    first = graves.build_action_plan(context)

    assert first == graves.build_action_plan(context)
    assert first.model_id == "graves_q5_w1_e5_r2_level13_fixed_ammo_v1"
    attack = _event(first, "GRAVES_NEW_DESTINY_ATTACK_1")
    assert attack.channel is ActionChannel.BASIC_ATTACK
    assert len(attack.outputs) == 4
    assert graves.engagement_dash_distance(context) == 375


def test_graves_stats_change_damage_cadence_and_recasts() -> None:
    """Prove AD, critical chance, attack speed, and haste reach outputs."""
    graves = create_default_registry(ROOT).require_cog("Graves")
    baseline = graves.build_action_plan(_context())
    scaled = graves.build_action_plan(
        _context(
            item_stats={
                "AD": Decimal(80),
                "CRITICAL_STRIKE_CHANCE": Decimal("0.5"),
                "ATTACK_SPEED": Decimal("0.5"),
                "ABILITY_HASTE": Decimal(100),
            }
        )
    )

    assert _event(scaled, "GRAVES_NEW_DESTINY_ATTACK_1").outputs[0].amount > (
        _event(baseline, "GRAVES_NEW_DESTINY_ATTACK_1").outputs[0].amount
    )
    assert _event(scaled, "GRAVES_Q_END_OF_THE_LINE_OUTBOUND_1").outputs[0].amount > (
        _event(baseline, "GRAVES_Q_END_OF_THE_LINE_OUTBOUND_1").outputs[0].amount
    )
    assert any(event.id.endswith("OUTBOUND_2") for event in scaled.events)


def test_graves_quickdraw_emits_runtime_resistances() -> None:
    """Keep E's timed armor and magic resistance outputs explicit."""
    graves = create_default_registry(ROOT).require_cog("Graves")
    quickdraw = _event(graves.build_action_plan(_context()), "GRAVES_E_QUICKDRAW_RELOAD")
    modifiers = [output for output in quickdraw.outputs if isinstance(output, StatModifierOutput)]

    assert [(output.stat, output.amount) for output in modifiers] == [
        ("ARMOR", Decimal(38)),
        ("MAGIC_RESISTANCE", Decimal(19)),
    ]


def test_graves_role_reversal_and_item_policy_are_explicit() -> None:
    """Preserve role ownership and reject unsupported sustain channels."""
    graves = create_default_registry(ROOT).require_cog("Graves")
    actor = _event(graves.build_action_plan(_context()), "GRAVES_W_SMOKE_SCREEN_IMPACT")
    target = _event(
        graves.build_action_plan(_context(graves_is_actor=False)),
        "GRAVES_W_SMOKE_SCREEN_IMPACT",
    )

    assert actor.source is EntityId.ACTOR
    assert target.source is EntityId.TARGET
    assert graves.item_candidate_blocker(
        {"id": 1, "stats": {"AD": {}, "CRITICAL_STRIKE_CHANCE": {}, "ABILITY_HASTE": {}}}
    ) is None
    assert graves.item_candidate_blocker(
        {"id": 2, "stats": {"LIFESTEAL": {}, "MANA": {}}}
    ) == "GRAVES_ITEM_STAT_NOT_MODELED:2:LIFESTEAL,MANA"
