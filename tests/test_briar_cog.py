"""Focused regressions for the locked Briar champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.champions.wip.briar import BriarCog
from lol_build.cogs.registry import create_default_registry
from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    EntityId,
    HealOutput,
    MissingHealthDamageOutput,
    ResistanceReductionOutput,
    StatModifierOutput,
)

ROOT = Path(__file__).resolve().parents[1]


def _briar() -> BriarCog:
    """Construct Briar independently of root-owned manifest integration.

    :return: Briar Cog backed by locked registry documents.
    """
    scaffold = create_default_registry(ROOT).require_cog("Briar")
    return BriarCog(scaffold.document, scaffold.detail_root)


def _context(
    *,
    briar_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
    opponent_health: Decimal = Decimal(0),
) -> ParticipantContext:
    """Build a level-13 Briar-versus-Teemo direct-Cog context.

    :param briar_is_actor: Place Briar on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Briar.
    :param opponent_health: Additional maximum health applied to Teemo.
    :return: Role-bound deterministic benchmark context.
    """
    registry = create_default_registry(ROOT)
    briar = _briar()
    teemo = registry.require_cog("Teemo")
    return ParticipantContext(
        EntityId.ACTOR if briar_is_actor else EntityId.TARGET,
        EntityId.TARGET if briar_is_actor else EntityId.ACTOR,
        briar.snapshot(level=13, item_stats=item_stats),
        teemo.snapshot(level=13, item_stats={"HP": opponent_health}),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Resolve one event by its stable Briar identifier.

    :param plan: Action plan exposing an ``events`` tuple.
    :param event_id: Exact event identifier to locate.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_briar_declares_modeled_capabilities_and_locked_evidence() -> None:
    """Distinguish Briar from a scaffold and retain all source forms."""
    briar = _briar()

    assert briar.maturity is CogMaturity.MODELED_UNVERIFIED
    assert briar.capabilities == DUEL_CAPABILITIES
    assert briar.verification_blockers() == ("COG_MODEL_UNVERIFIED:Briar",)
    assert briar.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Briar.json",
        "data/raw/16.17.1/communitydragon/champions/233.json",
        "data/raw/16.17.1/communitydragon/champions/briar.bin.json",
    )
    assert all((ROOT / reference).is_file() for reference in briar.evidence_refs)


def test_briar_rotation_is_deterministic_and_uses_locked_formulas() -> None:
    """Anchor passive, Q5, W5 bite, E1, and R2 outputs to sources."""
    briar = _briar()
    context = _context(item_stats={"AD": Decimal(100), "AP": Decimal(50)})

    first = briar.build_action_plan(context)
    repeated = briar.build_action_plan(context)
    q = _event(first, "BRIAR_Q_HEAD_RUSH_1")
    bite = _event(first, "BRIAR_W_SNACK_ATTACK")
    scream = _event(first, "BRIAR_E_CHILLING_SCREAM_RELEASE")
    ultimate = _event(first, "BRIAR_R_CERTAIN_DEATH_IMPACT")
    bleed = _event(first, "BRIAR_PASSIVE_BLEED_TICK_1")

    assert first == repeated
    assert first.model_id == "briar_w5_q5_e1_r2_level13_locked_v1"
    assert isinstance(q.outputs[0], ResistanceReductionOutput)
    assert q.outputs[0].fraction_per_stack == Decimal("0.20")
    assert q.outputs[1].amount == Decimal(270)
    assert q.outputs[2].duration_ms == 850
    assert isinstance(bite.outputs[0], MissingHealthDamageOutput)
    assert bite.outputs[0].base_amount == (
        Decimal(65) + Decimal("1.05") * context.snapshot.attack_damage
    )
    assert isinstance(bite.outputs[1], HealOutput)
    assert scream.outputs[0].amount == Decimal(230)
    assert scream.outputs[1].amount == Decimal("0.10") * context.snapshot.max_hp
    assert ultimate.outputs[0].amount == Decimal(315)
    assert all(isinstance(output, StatModifierOutput) for output in ultimate.outputs[1:3])
    assert bleed.outputs[0].damage_type is DamageType.PHYSICAL
    assert isinstance(bleed.outputs[1], HealOutput)
    assert "BRIAR_R_AUTOMATIC_PURSUIT_NOT_MODELED" in first.blockers


def test_briar_ad_as_haste_hp_and_target_hp_change_outputs() -> None:
    """Prove item-facing combat stats reach distinct modeled channels."""
    baseline = _briar().build_action_plan(_context())
    scaled = _briar().build_action_plan(
        _context(
            item_stats={
                "AD": Decimal(100),
                "ATTACK_SPEED": Decimal("0.50"),
                "ABILITY_HASTE": Decimal(100),
                "HP": Decimal(500),
            },
            opponent_health=Decimal(500),
        )
    )

    baseline_attacks = [event for event in baseline.events if "FRENZY_ATTACK" in event.id]
    scaled_attacks = [event for event in scaled.events if "FRENZY_ATTACK" in event.id]
    baseline_qs = [event for event in baseline.events if "Q_HEAD_RUSH" in event.id]
    scaled_qs = [event for event in scaled.events if "Q_HEAD_RUSH" in event.id]
    baseline_bite = _event(baseline, "BRIAR_W_SNACK_ATTACK")
    scaled_bite = _event(scaled, "BRIAR_W_SNACK_ATTACK")
    baseline_e = _event(baseline, "BRIAR_E_CHILLING_SCREAM_RELEASE")
    scaled_e = _event(scaled, "BRIAR_E_CHILLING_SCREAM_RELEASE")

    assert len(scaled_attacks) > len(baseline_attacks)
    assert len(scaled_qs) > len(baseline_qs)
    assert scaled_bite.outputs[0].base_amount > baseline_bite.outputs[0].base_amount
    assert (
        scaled_bite.outputs[0].missing_health_ratio > baseline_bite.outputs[0].missing_health_ratio
    )
    assert scaled_e.outputs[1].amount - baseline_e.outputs[1].amount == Decimal(50)


def test_briar_reaction_exposes_q_stun_e_reduction_and_knockback() -> None:
    """Keep reducible stun, discrete displacement, and mitigation separate."""
    reaction = _briar().build_reaction_plan(_context())

    q_stun, e_knockback = reaction.cast_block_windows
    reduction = reaction.damage_windows[0]
    assert q_stun.control_type is ControlType.STUN
    assert q_stun.tenacity_reducible is True
    assert q_stun.source_event_id == "BRIAR_Q_HEAD_RUSH_1"
    assert e_knockback.control_type is ControlType.AIRBORNE
    assert e_knockback.tenacity_reducible is False
    assert reduction.start_ms == 6000
    assert reduction.end_ms == 7000
    assert reduction.multiplier == Decimal("0.65")
    assert "BRIAR_E_WALL_COLLISION_STUN_NOT_MODELED" in reaction.blockers


def test_briar_role_reversal_preserves_sources_and_recipients() -> None:
    """Bind every outgoing Briar event to the selected participant role."""
    briar = _briar()
    actor_plan = briar.build_action_plan(_context(briar_is_actor=True))
    target_plan = briar.build_action_plan(_context(briar_is_actor=False))

    actor_q = _event(actor_plan, "BRIAR_Q_HEAD_RUSH_1")
    target_q = _event(target_plan, "BRIAR_Q_HEAD_RUSH_1")
    assert actor_q.source is EntityId.ACTOR
    assert target_q.source is EntityId.TARGET
    assert actor_q.outputs[1].recipient is EntityId.TARGET
    assert target_q.outputs[1].recipient is EntityId.ACTOR
    assert actor_q.sequence != target_q.sequence


def test_briar_against_teemo_blind_preserves_ability_damage() -> None:
    """Cancel frenzy attacks during blind without suppressing Head Rush."""
    result = MatchupEngine(ROOT).evaluate(MatchupRequest("Teemo", "Briar"))

    q_entry = next(
        entry
        for entry in result.timeline.log
        if entry.event_id == "BRIAR_Q_HEAD_RUSH_1" and entry.operation == "DAMAGE"
    )
    assert q_entry.status == "APPLIED"
    assert any(
        entry.event_id.startswith("BRIAR_W_FRENZY_ATTACK_") and entry.status == "CANCELLED"
        for entry in result.timeline.log
    )


def test_briar_item_policy_and_lane_sustain_keep_state_honest() -> None:
    """Allow represented inputs while retaining dynamic lane blockers."""
    briar = _briar()

    assert (
        briar.item_candidate_blocker(
            {"id": 1, "stats": {"AD": {}, "AP": {}, "ATTACK_SPEED": {}, "HP": {}}}
        )
        is None
    )
    assert (
        briar.item_candidate_blocker({"id": 2, "stats": {"CRITICAL_STRIKE_CHANCE": {}, "MANA": {}}})
        == "BRIAR_ITEM_STAT_NOT_MODELED:2:MANA"
    )
    amount, blockers = briar.lane_sustain_extra_health(
        _context(),
        duration_ms=30_000,
        no_damage_delay_ms=8_000,
    )
    assert amount == 0
    assert blockers == (
        "BRIAR_LANE_TARGET_AND_ATTACK_SCHEDULE_NOT_MODELED",
        "BRIAR_LANE_MISSING_HEALTH_HEAL_SCALING_NOT_MODELED",
        "BRIAR_HAS_NO_INNATE_HEALTH_REGEN",
    )
