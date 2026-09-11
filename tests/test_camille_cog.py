"""Focused regressions for the locked Camille champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ControlType, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    CurrentHealthDamageOutput,
    EntityId,
    HealOutput,
)

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    camille_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
    opponent_health: Decimal = Decimal(0),
) -> ParticipantContext:
    """Build a level-13 Camille-versus-Teemo direct-Cog context.

    :param camille_is_actor: Place Camille on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Camille.
    :param opponent_health: Additional maximum health applied to Teemo.
    :return: Role-bound deterministic benchmark context.
    """
    registry = create_default_registry(ROOT)
    camille = registry.require_cog("Camille")
    teemo = registry.require_cog("Teemo")
    return ParticipantContext(
        EntityId.ACTOR if camille_is_actor else EntityId.TARGET,
        EntityId.TARGET if camille_is_actor else EntityId.ACTOR,
        camille.snapshot(level=13, item_stats=item_stats),
        teemo.snapshot(level=13, item_stats={"HP": opponent_health}),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Resolve one event by its stable Camille identifier.

    :param plan: Action plan exposing an ``events`` tuple.
    :param event_id: Exact event identifier to locate.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_camille_declares_modeled_capabilities_and_locked_evidence() -> None:
    """Distinguish Camille from a scaffold and retain all source forms."""
    camille = create_default_registry(ROOT).require_cog("Camille")

    assert camille.maturity is CogMaturity.MODELED_UNVERIFIED
    assert camille.capabilities == DUEL_CAPABILITIES
    assert camille.verification_blockers() == ("COG_MODEL_UNVERIFIED:Camille",)
    assert camille.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Camille.json",
        "data/raw/16.17.1/communitydragon/champions/164.json",
        "data/raw/16.17.1/communitydragon/champions/camille.bin.json",
    )
    assert all((ROOT / reference).is_file() for reference in camille.evidence_refs)


def test_camille_rotation_is_deterministic_and_uses_locked_formulas() -> None:
    """Anchor Q5/W1/E5/R2 damage, healing, control, and true conversion."""
    camille = create_default_registry(ROOT).require_cog("Camille")
    context = _context(item_stats={"AD": Decimal(100)})

    first = camille.build_action_plan(context)
    repeated = camille.build_action_plan(context)
    q1 = _event(first, "CAMILLE_Q1_PRECISION_PROTOCOL_ATTACK")
    q2 = _event(first, "CAMILLE_Q2_PRECISION_PROTOCOL_EMPOWERED")
    sweep = _event(first, "CAMILLE_W_TACTICAL_SWEEP_OUTER")
    hookshot = _event(first, "CAMILLE_E_HOOKSHOT_CHAMPION_HIT")

    assert first == repeated
    assert first.model_id == "camille_q5_w1_e5_r2_level13_locked_v1"
    assert camille.engagement_dash_distance(context) == Decimal(800)
    assert q1.outputs[0].amount == Decimal("1.40") * context.snapshot.attack_damage
    q2_total = Decimal("1.80") * context.snapshot.attack_damage
    assert q2.outputs[0].amount == q2_total * Decimal("0.12")
    assert q2.outputs[1].amount == q2_total * Decimal("0.88")
    assert q2.outputs[1].damage_type is DamageType.TRUE
    assert isinstance(q2.outputs[2], CurrentHealthDamageOutput)
    assert q2.outputs[2].ratio == Decimal("0.06")
    assert hookshot.outputs[0].amount == Decimal(255)
    assert isinstance(sweep.outputs[1], HealOutput)
    assert "CAMILLE_PASSIVE_ADAPTIVE_DAMAGE_TYPE_NOT_MODELED" in first.blockers


def test_camille_ad_as_and_target_hp_change_represented_outputs() -> None:
    """Prove AD, attack speed, and opposing health alter the model."""
    camille = create_default_registry(ROOT).require_cog("Camille")
    baseline = camille.build_action_plan(_context())
    scaled = camille.build_action_plan(
        _context(
            item_stats={"AD": Decimal(80), "ATTACK_SPEED": Decimal("0.50")},
            opponent_health=Decimal(500),
        )
    )

    baseline_q2 = _event(baseline, "CAMILLE_Q2_PRECISION_PROTOCOL_EMPOWERED")
    scaled_q2 = _event(scaled, "CAMILLE_Q2_PRECISION_PROTOCOL_EMPOWERED")
    baseline_w = _event(baseline, "CAMILLE_W_TACTICAL_SWEEP_OUTER")
    scaled_w = _event(scaled, "CAMILLE_W_TACTICAL_SWEEP_OUTER")
    baseline_attacks = tuple(
        event for event in baseline.events if event.id.startswith("CAMILLE_BASIC_ATTACK_")
    )
    scaled_attacks = tuple(
        event for event in scaled.events if event.id.startswith("CAMILLE_BASIC_ATTACK_")
    )

    assert scaled_q2.outputs[1].amount > baseline_q2.outputs[1].amount
    assert scaled_w.outputs[0].amount > baseline_w.outputs[0].amount
    assert scaled_w.outputs[1].amount > baseline_w.outputs[1].amount
    assert len(scaled_attacks) > len(baseline_attacks)


def test_camille_reaction_models_tenacity_reducible_hookshot_stun() -> None:
    """Expose Hookshot control without inventing R boundary semantics."""
    camille = create_default_registry(ROOT).require_cog("Camille")
    reaction = camille.build_reaction_plan(_context())

    stun = reaction.cast_block_windows[0]
    assert stun.start_ms == 200
    assert stun.end_ms == 950
    assert stun.control_type is ControlType.STUN
    assert stun.tenacity_reducible is True
    assert stun.source_event_id == "CAMILLE_E_HOOKSHOT_CHAMPION_HIT"
    assert "CAMILLE_R_UNTARGETABILITY_REACTION_NOT_MODELED" in reaction.blockers


def test_camille_role_reversal_and_teemo_blind_preserve_channels() -> None:
    """Keep Camille role-neutral while blind cancels Q attacks, not W or E."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Camille", "Teemo"))
    as_opponent = engine.evaluate(MatchupRequest("Teemo", "Camille"))

    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    assert any(
        entry.event_id.startswith("CAMILLE_Q")
        and entry.action_channel is ActionChannel.BASIC_ATTACK
        and entry.status == "CANCELLED"
        for entry in as_opponent.timeline.log
    )
    assert any(
        entry.event_id == "CAMILLE_W_TACTICAL_SWEEP_OUTER"
        and entry.operation == "DAMAGE"
        and entry.status == "APPLIED"
        and entry.recipient is EntityId.ACTOR
        for entry in as_opponent.timeline.log
    )
    assert any(
        entry.event_id == "CAMILLE_E_HOOKSHOT_CHAMPION_HIT"
        and entry.operation == "DAMAGE"
        and entry.status == "APPLIED"
        for entry in as_opponent.timeline.log
    )


def test_camille_item_policy_rejects_only_unrepresented_channels() -> None:
    """Accept consumed stats and reject unsupported scheduling or sustain."""
    camille = create_default_registry(ROOT).require_cog("Camille")

    assert (
        camille.item_candidate_blocker(
            {
                "id": 1,
                "stats": {
                    "AD": {},
                    "ATTACK_SPEED": {},
                    "HP": {},
                    "ARMOR": {},
                    "MAGIC_RESISTANCE": {},
                },
            }
        )
        is None
    )
    assert (
        camille.item_candidate_blocker(
            {"id": 2, "stats": {"ABILITY_HASTE": {}, "LIFESTEAL": {}, "MANA": {}}}
        )
        == "CAMILLE_ITEM_STAT_NOT_MODELED:2:ABILITY_HASTE,MANA"
    )
