"""Focused regressions for the locked Fiora champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.champions.wip.fiora import FioraCog
from lol_build.cogs.registry import create_default_registry
from lol_build.core.combat import DamageType
from lol_build.core.timeline import EntityId, HealOutput

ROOT = Path(__file__).resolve().parents[1]


def _fiora() -> FioraCog:
    """Construct Fiora independently of the root-owned manifest integration.

    :return: Fiora Cog backed by locked registry documents.
    """
    scaffold = create_default_registry(ROOT).require_cog("Fiora")
    return FioraCog(scaffold.document, scaffold.detail_root)


def _context(
    *,
    fiora_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
    opponent_health: Decimal = Decimal(0),
) -> ParticipantContext:
    """Build a level-13 Fiora-versus-Teemo direct-Cog context.

    :param fiora_is_actor: Place Fiora on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Fiora.
    :param opponent_health: Additional maximum health applied to Teemo.
    :return: Role-bound deterministic benchmark context.
    """
    registry = create_default_registry(ROOT)
    fiora = _fiora()
    teemo = registry.require_cog("Teemo")
    return ParticipantContext(
        EntityId.ACTOR if fiora_is_actor else EntityId.TARGET,
        EntityId.TARGET if fiora_is_actor else EntityId.ACTOR,
        fiora.snapshot(level=13, item_stats=item_stats),
        teemo.snapshot(level=13, item_stats={"HP": opponent_health}),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Resolve one event by its stable Fiora identifier.

    :param plan: Action plan exposing an ``events`` tuple.
    :param event_id: Exact event identifier to locate.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_fiora_declares_modeled_capabilities_and_locked_evidence() -> None:
    """Distinguish Fiora from a scaffold and retain all source forms."""
    fiora = _fiora()

    assert fiora.maturity is CogMaturity.MODELED_UNVERIFIED
    assert fiora.capabilities == DUEL_CAPABILITIES
    assert fiora.verification_blockers() == ("COG_MODEL_UNVERIFIED:Fiora",)
    assert all((ROOT / reference).is_file() for reference in fiora.evidence_refs)


def test_fiora_rotation_is_deterministic_and_uses_locked_formulas() -> None:
    """Anchor Q5, W1, E5, R2, vital damage, and healing values."""
    fiora = _fiora()
    context = _context(item_stats={"AD": Decimal(100), "AP": Decimal(50)})

    first = fiora.build_action_plan(context)
    repeated = fiora.build_action_plan(context)
    q = _event(first, "FIORA_Q_LUNGE_1")
    w = _event(first, "FIORA_W_RIPOSTE_STAB")
    e2 = _event(first, "FIORA_E_BLADEWORK_ATTACK_2")

    assert first == repeated
    assert first.model_id == "fiora_q5_w1_e5_r2_level13_locked_v1"
    assert fiora.engagement_dash_distance(context) == Decimal(400)
    assert fiora.engagement_speed_multiplier(context) == Decimal("1.40")
    assert q.outputs[0].amount == Decimal(220)
    assert q.outputs[1].damage_type is DamageType.TRUE
    assert q.outputs[1].amount == context.opponent_snapshot.max_hp * Decimal("0.07")
    assert isinstance(q.outputs[2], HealOutput)
    assert w.outputs[0].amount == Decimal(160)
    assert e2.outputs[0].amount == Decimal(2) * context.snapshot.attack_damage
    assert any("GRAND_CHALLENGE_HEAL" in event.id for event in first.events)


def test_fiora_ad_as_haste_and_target_hp_change_represented_outputs() -> None:
    """Prove all offensive schedule inputs alter Fiora's model outputs."""
    fiora = _fiora()
    baseline = fiora.build_action_plan(_context())
    scaled = fiora.build_action_plan(
        _context(
            item_stats={
                "AD": Decimal(80),
                "ATTACK_SPEED": Decimal("0.50"),
                "ABILITY_HASTE": Decimal(100),
            },
            opponent_health=Decimal(500),
        )
    )

    baseline_q = _event(baseline, "FIORA_Q_LUNGE_1")
    scaled_q = _event(scaled, "FIORA_Q_LUNGE_1")
    baseline_attacks = [
        event for event in baseline.events if event.id.startswith("FIORA_BASIC_ATTACK_")
    ]
    scaled_attacks = [
        event for event in scaled.events if event.id.startswith("FIORA_BASIC_ATTACK_")
    ]
    baseline_lunges = [event for event in baseline.events if event.id.startswith("FIORA_Q_LUNGE_")]
    scaled_lunges = [event for event in scaled.events if event.id.startswith("FIORA_Q_LUNGE_")]

    assert scaled_q.outputs[0].amount > baseline_q.outputs[0].amount
    assert scaled_q.outputs[1].amount > baseline_q.outputs[1].amount
    assert len(scaled_attacks) > len(baseline_attacks)
    assert len(scaled_lunges) > len(baseline_lunges)


def test_fiora_reaction_models_riposte_and_slow_without_claiming_stun() -> None:
    """Expose fixed parry immunity and only the non-stun Riposte result."""
    reaction = _fiora().build_reaction_plan(_context())

    immunity = reaction.control_immunity_windows[0]
    riposte = reaction.damage_windows[0]
    stab_slow = reaction.cast_block_windows[1]
    assert immunity.control_types == (ControlType.ALL,)
    assert immunity.start_ms == riposte.start_ms == 2500
    assert immunity.end_ms == riposte.end_ms == 3250
    assert riposte.multiplier == 0
    assert stab_slow.control_type is ControlType.SLOW
    assert "FIORA_W_STUN_VARIANT_NOT_MODELED" in reaction.blockers


def test_fiora_role_reversal_keeps_recipients_symmetric() -> None:
    """Bind every outgoing event to Fiora's actual participant side."""
    fiora = _fiora()
    actor_plan = fiora.build_action_plan(_context(fiora_is_actor=True))
    target_plan = fiora.build_action_plan(_context(fiora_is_actor=False))

    actor_q = _event(actor_plan, "FIORA_Q_LUNGE_1")
    target_q = _event(target_plan, "FIORA_Q_LUNGE_1")
    assert actor_q.source is EntityId.ACTOR
    assert target_q.source is EntityId.TARGET
    assert actor_q.outputs[0].recipient is EntityId.TARGET
    assert target_q.outputs[0].recipient is EntityId.ACTOR
    assert actor_q.sequence != target_q.sequence


def test_fiora_against_teemo_blind_preserves_ability_damage() -> None:
    """Cancel Fiora attacks during blind without suppressing her Lunge cast."""
    result = MatchupEngine(ROOT).evaluate(MatchupRequest("Fiora", "Teemo"))

    q_entry = next(
        entry
        for entry in result.timeline.log
        if entry.event_id == "FIORA_Q_LUNGE_1" and entry.operation == "DAMAGE"
    )
    assert q_entry.status == "APPLIED"
    assert any(
        entry.event_id.startswith("FIORA_BASIC_ATTACK_") and entry.status == "CANCELLED"
        for entry in result.timeline.log
    )


def test_fiora_item_policy_tracks_only_modeled_channels() -> None:
    """Allow haste, damage, and crit while rejecting unmodeled mana."""
    fiora = _fiora()

    assert fiora.item_candidate_blocker({"id": 1, "stats": {"AD": {}, "ABILITY_HASTE": {}}}) is None
    assert (
        fiora.item_candidate_blocker({"id": 2, "stats": {"CRITICAL_STRIKE_CHANCE": {}, "MANA": {}}})
        == "FIORA_ITEM_STAT_NOT_MODELED:2:MANA"
    )
