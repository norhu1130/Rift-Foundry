"""Focused regressions for the locked Ambessa champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.champions.wip.ambessa import AmbessaCog
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import ActionChannel, EntityId, HealOutput, ShieldOutput

ROOT = Path(__file__).resolve().parents[1]


def _ambessa() -> AmbessaCog:
    """Resolve the roster-owned Ambessa implementation.

    :return: Ambessa Cog backed by the locked source documents.
    """
    cog = create_default_registry(ROOT).require_cog("Ambessa")
    assert isinstance(cog, AmbessaCog)
    return cog


def _context(
    *,
    ambessa_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
    opponent_health: Decimal = Decimal(0),
) -> ParticipantContext:
    """Build a level-13 Ambessa-versus-Teemo direct-Cog context.

    :param ambessa_is_actor: Place Ambessa on the actor side when true.
    :param item_stats: Optional permanent modifiers applied to Ambessa.
    :param opponent_health: Additional maximum health applied to Teemo.
    :return: Role-bound deterministic benchmark context.
    """
    registry = create_default_registry(ROOT)
    ambessa = registry.require_cog("Ambessa")
    teemo = registry.require_cog("Teemo")
    return ParticipantContext(
        EntityId.ACTOR if ambessa_is_actor else EntityId.TARGET,
        EntityId.TARGET if ambessa_is_actor else EntityId.ACTOR,
        ambessa.snapshot(level=13, item_stats=item_stats),
        teemo.snapshot(level=13, item_stats={"HP": opponent_health}),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Resolve one event by its stable Ambessa identifier.

    :param plan: Action plan exposing an ``events`` tuple.
    :param event_id: Exact event identifier to locate.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_ambessa_declares_modeled_capabilities_and_locked_evidence() -> None:
    """Distinguish Ambessa from a scaffold and retain all source forms."""
    ambessa = _ambessa()

    assert ambessa.maturity is CogMaturity.MODELED_UNVERIFIED
    assert ambessa.capabilities == DUEL_CAPABILITIES
    assert ambessa.verification_blockers() == ("COG_MODEL_UNVERIFIED:Ambessa",)
    assert ambessa.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Ambessa.json",
        "data/raw/16.17.1/communitydragon/champions/799.json",
        "data/raw/16.17.1/communitydragon/champions/ambessa.bin.json",
    )
    assert all((ROOT / reference).is_file() for reference in ambessa.evidence_refs)


def test_ambessa_rotation_is_deterministic_and_uses_locked_formulas() -> None:
    """Anchor Q5/W1/E5/R2, passive, shielding, and healing values."""
    ambessa = _ambessa()
    context = _context(item_stats={"AD": Decimal(100)})

    first = ambessa.build_action_plan(context)
    repeated = ambessa.build_action_plan(context)
    q1 = _event(first, "AMBESSA_Q1_CUNNING_SWEEP_1")
    q2 = _event(first, "AMBESSA_Q2_SUNDERING_SLAM_1")
    w = _event(first, "AMBESSA_W_REPUDIATION_BRACED")
    e = _event(first, "AMBESSA_E_LACERATE_DOUBLE_1")
    ultimate = _event(first, "AMBESSA_R_PUBLIC_EXECUTION_IMPACT")
    empowered = _event(first, "AMBESSA_PASSIVE_ATTACK_AFTER_Q1_1")

    assert first == repeated
    assert first.model_id == "ambessa_q5_w1_e5_r2_level13_locked_v1"
    assert ambessa.engagement_dash_distance(context) == Decimal(1250)
    assert q1.outputs[0].amount == Decimal(180) + (
        Decimal("0.09") * context.opponent_snapshot.max_hp
    )
    assert q2.outputs[0].amount == Decimal(240) + (
        Decimal("0.10") * context.opponent_snapshot.max_hp
    )
    assert ultimate.outputs[0].amount == Decimal(330)
    # R2's ability healing resolves from each hit's own post-mitigation damage.
    assert ultimate.outputs[0].source_heal_ratio == Decimal("0.175")
    assert not any(isinstance(output, HealOutput) for output in ultimate.outputs)
    assert e.outputs[0].amount == Decimal(340)
    assert w.outputs[0].source_heal_ratio == Decimal("0.175")
    shield = next(output for output in w.outputs if isinstance(output, ShieldOutput))
    assert shield.amount == Decimal(200) + Decimal(270 * 12) / Decimal(17)
    assert empowered.channel is ActionChannel.BASIC_ATTACK
    assert empowered.outputs[1].amount == (Decimal(30) + Decimal(25 * 12) / Decimal(17))
    assert "AMBESSA_ENERGY_LEDGER_NOT_MODELED" in first.blockers
    assert "AMBESSA_R2_NATIVE_ARMOR_PENETRATION_NOT_APPLIED_BY_TIMELINE" in first.blockers


def test_ambessa_ad_as_haste_and_health_change_represented_outputs() -> None:
    """Prove AD, attack speed, haste, and health channels alter the model."""
    ambessa = _ambessa()
    baseline_context = _context()
    baseline = ambessa.build_action_plan(baseline_context)
    scaled_context = _context(
        item_stats={
            "AD": Decimal(80),
            "ATTACK_SPEED": Decimal("0.75"),
            "ABILITY_HASTE": Decimal(100),
            "HP": Decimal(500),
        },
        opponent_health=Decimal(500),
    )
    scaled = ambessa.build_action_plan(scaled_context)

    assert _event(scaled, "AMBESSA_Q1_CUNNING_SWEEP_1").outputs[0].amount > (
        _event(baseline, "AMBESSA_Q1_CUNNING_SWEEP_1").outputs[0].amount
    )
    assert scaled_context.snapshot.max_hp == baseline_context.snapshot.max_hp + Decimal(500)
    assert len(
        [event for event in scaled.events if event.id.startswith("AMBESSA_BASIC_ATTACK_")]
    ) > len([event for event in baseline.events if event.id.startswith("AMBESSA_BASIC_ATTACK_")])
    assert any(event.id == "AMBESSA_Q1_CUNNING_SWEEP_2" for event in scaled.events)
    assert any(event.id == "AMBESSA_E_LACERATE_DOUBLE_2" for event in scaled.events)
    assert not any(event.id == "AMBESSA_Q1_CUNNING_SWEEP_2" for event in baseline.events)


def test_ambessa_reaction_distinguishes_suppression_stun_and_unstoppable() -> None:
    """Preserve R's discrete control semantics and E's reducible slow."""
    reaction = _ambessa().build_reaction_plan(_context())

    suppression, stun, slow = reaction.cast_block_windows
    immunity = reaction.control_immunity_windows[0]
    assert suppression.control_type is ControlType.SUPPRESSION
    assert suppression.tenacity_reducible is False
    assert suppression.start_ms == immunity.start_ms == 200
    assert suppression.end_ms == immunity.end_ms == 950
    assert stun.control_type is ControlType.STUN
    assert stun.tenacity_reducible is True
    assert slow.control_type is ControlType.SLOW
    assert slow.blocked_channels == (ActionChannel.MOVEMENT,)
    assert immunity.control_types == (ControlType.ALL,)
    assert immunity.recipient is EntityId.ACTOR


def test_ambessa_role_reversal_and_teemo_blind_preserve_ability_damage() -> None:
    """Keep role symmetry while blind cancels empowered attacks, not spells."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Ambessa", "Teemo"))
    as_opponent = engine.evaluate(MatchupRequest("Teemo", "Ambessa"))

    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    assert any(
        entry.event_id.startswith("AMBESSA_PASSIVE_ATTACK_")
        and entry.action_channel is ActionChannel.BASIC_ATTACK
        and entry.status == "CANCELLED"
        for entry in as_opponent.timeline.log
    )
    assert any(
        entry.event_id == "AMBESSA_Q1_CUNNING_SWEEP_1"
        and entry.operation == "DAMAGE"
        and entry.status == "APPLIED"
        and entry.recipient is EntityId.ACTOR
        for entry in as_opponent.timeline.log
    )


def test_ambessa_item_and_lane_sustain_policies_are_explicit() -> None:
    """Allow represented fighter stats and reject unsupported item channels."""
    ambessa = _ambessa()

    assert (
        ambessa.item_candidate_blocker(
            {
                "id": 1,
                "stats": {
                    "AD": {},
                    "ATTACK_SPEED": {},
                    "ABILITY_HASTE": {},
                    "HP": {},
                    "ARMOR": {},
                    "MAGIC_RESISTANCE": {},
                },
            }
        )
        is None
    )
    assert (
        ambessa.item_candidate_blocker(
            {"id": 2, "stats": {"AP": {}, "CRITICAL_STRIKE_CHANCE": {}, "MANA": {}}}
        )
        == "AMBESSA_ITEM_STAT_NOT_MODELED:2:AP,MANA"
    )
    recovered, blockers = ambessa.lane_sustain_extra_health(
        _context(),
        duration_ms=30_000,
        no_damage_delay_ms=8_000,
    )
    assert recovered == 0
    assert blockers == ("AMBESSA_R_SUSTAIN_REQUIRES_ABILITY_DAMAGE_TARGET",)
