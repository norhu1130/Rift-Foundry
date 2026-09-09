"""Focused regression coverage for the locked Braum champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES, ActionPlan
from lol_build.cogs.registry import create_default_registry
from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    EntityId,
    StatModifierOutput,
)

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    braum_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a role-neutral level-13 Braum-versus-Garen context.

    :param braum_is_actor: Place Braum on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Braum.
    :return: Role-bound context for deterministic Braum tests.
    """
    registry = create_default_registry(ROOT)
    braum = registry.require_cog("Braum")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if braum_is_actor else EntityId.TARGET,
        EntityId.TARGET if braum_is_actor else EntityId.ACTOR,
        braum.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan: ActionPlan, event_id: str) -> ActionEvent:
    """Resolve one named event from a Braum action plan.

    :param plan: Braum action plan containing the requested event.
    :param event_id: Stable identifier of the requested event.
    :return: Matching immutable action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def _attacks(plan: ActionPlan) -> tuple[ActionEvent, ...]:
    """Collect ordinary Braum attacks from an action plan.

    :param plan: Braum action plan containing ordinary attacks.
    :return: Chronological ordinary attack events.
    """
    return tuple(
        event for event in plan.events if event.id.startswith("BRAUM_BASIC_ATTACK_")
    )


def test_braum_declares_modeled_capabilities_and_locked_evidence() -> None:
    """Distinguish Braum's implemented model from its former scaffold."""
    braum = create_default_registry(ROOT).require_cog("Braum")

    assert braum.maturity is CogMaturity.MODELED_UNVERIFIED
    assert braum.capabilities == DUEL_CAPABILITIES
    assert braum.verification_blockers() == ("COG_MODEL_UNVERIFIED:Braum",)
    assert braum.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Braum.json",
        "data/raw/16.17.1/communitydragon/champions/201.json",
        "data/raw/16.17.1/communitydragon/champions/braum.bin.json",
    )
    assert all((ROOT / path).is_file() for path in braum.evidence_refs)


def test_braum_rotation_is_deterministic_and_anchors_locked_values() -> None:
    """Anchor Q5, W1, E5, R2, and level-13 passive outputs."""
    braum = create_default_registry(ROOT).require_cog("Braum")
    context = _context(item_stats={"AP": Decimal(100), "HP": Decimal(200)})

    first = braum.build_action_plan(context)
    repeated = braum.build_action_plan(context)
    q = _event(first, "BRAUM_Q_WINTERS_BITE_1")
    ultimate = _event(first, "BRAUM_R_GLACIAL_FISSURE")
    proc = _event(first, "BRAUM_PASSIVE_CONCUSSIVE_PROC_1")

    assert first == repeated
    assert first.model_id == "braum_q5_e5_w1_r2_level13_self_stack_v1"
    assert q.outputs[0].amount == Decimal(255) + Decimal("0.025") * context.snapshot.max_hp
    assert (q.outputs[1].status, q.outputs[1].duration_ms, q.outputs[1].magnitude) == (
        "CC_SLOW",
        2000,
        Decimal("0.70"),
    )
    assert ultimate.outputs[0].amount == Decimal(310)
    assert (ultimate.outputs[1].status, ultimate.outputs[1].duration_ms) == (
        "CC_AIRBORNE",
        1500,
    )
    assert proc.outputs[0].amount == Decimal(136)
    assert (proc.outputs[1].status, proc.outputs[1].duration_ms) == (
        "CC_STUN",
        1750,
    )
    assert "BRAUM_PASSIVE_ALLIED_STACK_SOURCES_NOT_MODELED" in first.blockers
    assert "BRAUM_E_FIRST_PROJECTILE_NULLIFICATION_NOT_MODELED" in first.blockers


def test_braum_hp_ap_attack_speed_haste_and_resists_reach_outputs() -> None:
    """Prove each represented item stat changes a distinct modeled channel."""
    braum = create_default_registry(ROOT).require_cog("Braum")
    baseline = braum.build_action_plan(_context())
    durable = braum.build_action_plan(
        _context(
            item_stats={
                "HP": Decimal(400),
                "ARMOR": Decimal(50),
                "MAGIC_RESISTANCE": Decimal(40),
            }
        )
    )
    powered = braum.build_action_plan(_context(item_stats={"AP": Decimal(100)}))
    faster = braum.build_action_plan(
        _context(item_stats={"ATTACK_SPEED": Decimal("0.50")})
    )
    hasted = braum.build_action_plan(
        _context(item_stats={"ABILITY_HASTE": Decimal(100)})
    )

    assert (
        _event(durable, "BRAUM_Q_WINTERS_BITE_1").outputs[0].amount
        - _event(baseline, "BRAUM_Q_WINTERS_BITE_1").outputs[0].amount
        == Decimal(10)
    )
    assert (
        _event(powered, "BRAUM_R_GLACIAL_FISSURE").outputs[0].amount
        - _event(baseline, "BRAUM_R_GLACIAL_FISSURE").outputs[0].amount
        == Decimal(60)
    )
    assert len(_attacks(faster)) > len(_attacks(baseline))
    assert [
        event.at_ms
        for event in hasted.events
        if event.id.startswith("BRAUM_Q_WINTERS_BITE_")
    ] == [100, 3100, 6100]

    base_w = _event(baseline, "BRAUM_W_STAND_BEHIND_ME")
    durable_w = _event(durable, "BRAUM_W_STAND_BEHIND_ME")
    assert isinstance(base_w.outputs[0], StatModifierOutput)
    assert durable_w.outputs[0].amount - base_w.outputs[0].amount == Decimal(18)
    assert durable_w.outputs[1].amount - base_w.outputs[1].amount == Decimal("14.4")


def test_braum_reaction_preserves_stun_knockup_slow_and_e_semantics() -> None:
    """Keep reducible control separate from airborne and directional defense."""
    braum = create_default_registry(ROOT).require_cog("Braum")
    reaction = braum.build_reaction_plan(_context())
    r_knockup, r_slow, passive_stun = reaction.cast_block_windows[:3]

    assert r_knockup.control_type.value == "AIRBORNE"
    assert r_knockup.tenacity_reducible is False
    assert r_knockup.source_event_id == "BRAUM_R_GLACIAL_FISSURE"
    assert r_slow.control_type.value == "SLOW"
    assert r_slow.tenacity_reducible is True
    assert passive_stun.control_type.value == "STUN"
    assert passive_stun.tenacity_reducible is True
    assert passive_stun.source_event_id == "BRAUM_PASSIVE_CONCUSSIVE_PROC_1"
    assert reaction.damage_windows[0].multiplier == Decimal("0.45")
    assert reaction.damage_windows[0].damage_types == (
        DamageType.PHYSICAL,
        DamageType.MAGIC,
    )
    assert "BRAUM_E_DIRECTION_AND_PROJECTILE_CLASSIFICATION_NOT_MODELED" in reaction.blockers


def test_braum_engagement_role_reversal_and_teemo_blind_are_stable() -> None:
    """Keep W/E engagement role-neutral and blind scoped to Braum attacks."""
    braum = create_default_registry(ROOT).require_cog("Braum")
    context = _context()
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Braum", "Teemo"))
    as_opponent = engine.evaluate(MatchupRequest("Teemo", "Braum"))

    assert braum.engagement_speed_multiplier(context) == Decimal("1.10")
    assert braum.engagement_dash_distance(context) == Decimal(650)
    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    assert any(
        entry.event_id.startswith("BRAUM_BASIC_ATTACK_")
        and entry.action_channel is ActionChannel.BASIC_ATTACK
        and entry.status == "CANCELLED"
        for entry in as_actor.timeline.log
    )
    for event_id in ("BRAUM_Q_WINTERS_BITE_1", "BRAUM_R_GLACIAL_FISSURE"):
        assert any(
            entry.event_id == event_id
            and entry.operation == "DAMAGE"
            and entry.status == "APPLIED"
            for entry in as_actor.timeline.log
        )
    opponent_q = next(
        entry
        for entry in as_opponent.timeline.log
        if entry.event_id == "BRAUM_Q_WINTERS_BITE_1"
        and entry.operation == "DAMAGE"
    )
    assert opponent_q.recipient is EntityId.ACTOR


def test_braum_item_policy_accepts_modeled_and_rejects_omitted_stats() -> None:
    """Align candidate eligibility with Braum's represented stat channels."""
    braum = create_default_registry(ROOT).require_cog("Braum")

    assert braum.item_candidate_blocker(
        {
            "id": 1,
            "stats": {
                "AD": {},
                "AP": {},
                "HP": {},
                "ARMOR": {},
                "MAGIC_RESISTANCE": {},
                "ATTACK_SPEED": {},
                "ABILITY_HASTE": {},
                "MOVE_SPEED_FLAT": {},
            },
        }
    ) is None
    assert braum.item_candidate_blocker(
        {"id": 2, "stats": {"HEAL_SHIELD_POWER": {}, "MANA": {}}}
    ) == "BRAUM_ITEM_STAT_NOT_MODELED:2:HEAL_SHIELD_POWER,MANA"
