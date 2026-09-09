"""Focused regressions for the locked Brand champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.champions.wip.brand import BrandCog
from lol_build.cogs.registry import ChampionCogRegistry, create_default_registry
from lol_build.core.timeline import ActionChannel, EntityId, StatusOutput

ROOT = Path(__file__).resolve().parents[1]


def _registry_with_brand() -> ChampionCogRegistry:
    """Build a registry whose Brand scaffold is replaced by the modeled Cog.

    This injection keeps the focused test independent from the root agent's
    separate manifest integration step.

    :return: Fully populated registry containing the modeled Brand Cog.
    """
    registry = create_default_registry(ROOT)
    scaffold = registry.require_cog("Brand")
    registry.add_cog(BrandCog(scaffold.document, scaffold.detail_root), override=True)
    return registry


def _context(
    *,
    brand_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a level-13 Brand-versus-Garen direct-Cog context.

    :param brand_is_actor: Place Brand on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Brand.
    :return: Role-bound deterministic benchmark context.
    """
    registry = _registry_with_brand()
    brand = registry.require_cog("Brand")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if brand_is_actor else EntityId.TARGET,
        EntityId.TARGET if brand_is_actor else EntityId.ACTOR,
        brand.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Resolve one event by its stable Brand identifier.

    :param plan: Action plan exposing an ``events`` tuple.
    :param event_id: Exact event identifier to locate.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_brand_declares_modeled_capabilities_and_locked_evidence() -> None:
    """Distinguish Brand from a scaffold and retain all source forms."""
    brand = _registry_with_brand().require_cog("Brand")

    assert brand.maturity is CogMaturity.MODELED_UNVERIFIED
    assert brand.capabilities == DUEL_CAPABILITIES
    assert brand.verification_blockers() == ("COG_MODEL_UNVERIFIED:Brand",)
    assert brand.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Brand.json",
        "data/raw/16.17.1/communitydragon/champions/63.json",
        "data/raw/16.17.1/communitydragon/champions/brand.bin.json",
    )
    assert all((ROOT / reference).is_file() for reference in brand.evidence_refs)


def test_brand_rotation_is_deterministic_and_models_three_blaze_stacks() -> None:
    """Anchor E1/Q5/W5/R2 and Blaze outputs to locked formulas."""
    brand = _registry_with_brand().require_cog("Brand")
    context = _context(item_stats={"AP": Decimal(100)})
    first = brand.build_action_plan(context)

    assert first == brand.build_action_plan(context)
    assert first.model_id == "brand_w5_q5_e1_r2_level13_three_stack_v1"
    assert _event(first, "BRAND_E_CONFLAGRATION_APPLY_BLAZE_1").outputs[0].amount == 115
    q = _event(first, "BRAND_Q_SEAR_ABLAZE_STUN_APPLY_BLAZE_2")
    assert q.outputs[0].amount == 255
    assert isinstance(q.outputs[1], StatusOutput)
    assert (q.outputs[1].status, q.outputs[1].duration_ms) == ("CC_STUN", 1750)
    assert (
        _event(first, "BRAND_W_PILLAR_EMPOWERED_APPLY_BLAZE_3").outputs[0].amount
        == Decimal("406.25")
    )
    ultimate = _event(first, "BRAND_R_PYROCLASM_INITIAL_ABLAZE_HIT")
    assert ultimate.outputs[0].amount == 205
    assert isinstance(ultimate.outputs[1], StatusOutput)
    assert ultimate.outputs[1].magnitude == Decimal("0.45")

    tick = _event(first, "BRAND_PASSIVE_BLAZE_THREE_STACK_TICK_1")
    assert tick.outputs[0].amount == context.opponent_snapshot.max_hp * Decimal("0.015")
    explosion = _event(first, "BRAND_PASSIVE_BLAZE_THREE_STACK_EXPLOSION")
    expected_ratio = (
        Decimal(6) / Decimal(100)
        + Decimal(6 * 12) / Decimal(1700)
        + Decimal("0.02")
    )
    assert explosion.outputs[0].amount == context.opponent_snapshot.max_hp * expected_ratio
    assert "BRAND_R_REPEAT_BOUNCES_REQUIRE_UNIT_GEOMETRY" in first.blockers
    assert "BRAND_PASSIVE_TICK_PHASE_AND_REFRESH_UNVERIFIED" in first.blockers


def test_brand_ap_and_attack_speed_reach_only_represented_channels() -> None:
    """Prove AP scales spells and Blaze while attack speed adds attacks."""
    brand = _registry_with_brand().require_cog("Brand")
    baseline = brand.build_action_plan(_context())
    powered = brand.build_action_plan(
        _context(item_stats={"AP": Decimal(100), "ATTACK_SPEED": Decimal("0.50")})
    )

    expected_spell_deltas = {
        "BRAND_E_CONFLAGRATION_APPLY_BLAZE_1": Decimal(60),
        "BRAND_Q_SEAR_ABLAZE_STUN_APPLY_BLAZE_2": Decimal(65),
        "BRAND_W_PILLAR_EMPOWERED_APPLY_BLAZE_3": Decimal("87.50"),
        "BRAND_R_PYROCLASM_INITIAL_ABLAZE_HIT": Decimal(30),
    }
    for event_id, expected in expected_spell_deltas.items():
        assert (
            _event(powered, event_id).outputs[0].amount
            - _event(baseline, event_id).outputs[0].amount
            == expected
        )
    baseline_attacks = tuple(
        event for event in baseline.events if "BASIC_ATTACK" in event.id
    )
    powered_attacks = tuple(
        event for event in powered.events if "BASIC_ATTACK" in event.id
    )
    assert len(powered_attacks) > len(baseline_attacks)
    assert (
        _event(powered, "BRAND_PASSIVE_BLAZE_THREE_STACK_EXPLOSION").outputs[0].amount
        > _event(baseline, "BRAND_PASSIVE_BLAZE_THREE_STACK_EXPLOSION").outputs[0].amount
    )


def test_brand_control_and_matchup_models_follow_role_reversal() -> None:
    """Keep Brand's outgoing damage and enhanced control role-neutral."""
    brand = _registry_with_brand().require_cog("Brand")
    stun, slow = brand.build_reaction_plan(_context()).cast_block_windows

    assert (stun.control_type.value, stun.end_ms - stun.start_ms) == ("STUN", 1750)
    assert stun.blocked_channels == (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY)
    assert (slow.control_type.value, slow.end_ms - slow.start_ms) == ("SLOW", 250)
    assert slow.blocked_channels == (ActionChannel.MOVEMENT,)
    assert stun.tenacity_reducible is slow.tenacity_reducible is True

    engine = MatchupEngine(ROOT, registry=_registry_with_brand())
    as_actor = engine.evaluate(MatchupRequest("Brand", "Garen"))
    as_target = engine.evaluate(MatchupRequest("Garen", "Brand"))
    assert as_actor.actor_action_model == as_target.opponent_action_model
    assert as_actor.actor_reaction_model == as_target.opponent_reaction_model
    actor_e = next(
        entry
        for entry in as_actor.timeline.log
        if entry.event_id == "BRAND_E_CONFLAGRATION_APPLY_BLAZE_1"
        and entry.operation == "DAMAGE"
    )
    target_e = next(
        entry
        for entry in as_target.timeline.log
        if entry.event_id == "BRAND_E_CONFLAGRATION_APPLY_BLAZE_1"
        and entry.operation == "DAMAGE"
    )
    assert actor_e.recipient is EntityId.TARGET
    assert target_e.recipient is EntityId.ACTOR


def test_teemo_blind_cancels_brand_attacks_but_not_combo_or_passive() -> None:
    """Keep Brand spells and Blaze independent from the blinded attack channel."""
    evaluation = MatchupEngine(ROOT, registry=_registry_with_brand()).evaluate(
        MatchupRequest("Brand", "Teemo")
    )

    assert any(
        entry.event_id.startswith("BRAND_BASIC_ATTACK_")
        and entry.status == "CANCELLED"
        for entry in evaluation.timeline.log
    )
    for event_id in (
        "BRAND_E_CONFLAGRATION_APPLY_BLAZE_1",
        "BRAND_Q_SEAR_ABLAZE_STUN_APPLY_BLAZE_2",
        "BRAND_W_PILLAR_EMPOWERED_APPLY_BLAZE_3",
        "BRAND_PASSIVE_BLAZE_THREE_STACK_EXPLOSION",
    ):
        assert any(
            entry.event_id == event_id
            and entry.operation == "DAMAGE"
            and entry.status == "APPLIED"
            for entry in evaluation.timeline.log
        )


def test_brand_item_policy_rejects_unrepresented_fixed_rotation_stats() -> None:
    """Allow AP and attack speed while blocking haste and resource stats."""
    brand = _registry_with_brand().require_cog("Brand")

    assert brand.item_candidate_blocker(
        {"id": 1, "stats": {"AP": {}, "HP": {}, "ATTACK_SPEED": {}}}
    ) is None
    assert brand.item_candidate_blocker(
        {"id": 2, "stats": {"ABILITY_HASTE": {}, "MANA": {}}}
    ) == "BRAND_ITEM_STAT_NOT_MODELED:2:ABILITY_HASTE,MANA"
