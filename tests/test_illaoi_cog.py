"""Focused regressions for the locked Illaoi champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.champions.wip.illaoi import IllaoiCog
from lol_build.cogs.registry import create_default_registry
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, EntityId

ROOT = Path(__file__).resolve().parents[1]


def _illaoi() -> IllaoiCog:
    """Construct Illaoi from the locked registry documents.

    :return: Dedicated Illaoi Cog with locked summary and detail data.
    """
    registered = create_default_registry(ROOT).require_cog("Illaoi")
    return IllaoiCog(registered.document, registered.detail_root)


def _context(
    *,
    illaoi_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
    opponent_health: Decimal = Decimal(0),
) -> ParticipantContext:
    """Build a fixed level-13 Illaoi-versus-Garen direct-Cog context.

    :param illaoi_is_actor: Place Illaoi on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Illaoi.
    :param opponent_health: Additional maximum health applied to Garen.
    :return: Role-bound deterministic benchmark context.
    """
    registry = create_default_registry(ROOT)
    illaoi = _illaoi()
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if illaoi_is_actor else EntityId.TARGET,
        EntityId.TARGET if illaoi_is_actor else EntityId.ACTOR,
        illaoi.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13, item_stats={"HP": opponent_health}),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Resolve one event by its stable Illaoi identifier.

    :param plan: Action plan exposing an ``events`` tuple.
    :param event_id: Exact event identifier to locate.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_illaoi_declares_modeled_capabilities_and_three_locked_sources() -> None:
    """Distinguish Illaoi from a scaffold and retain all source forms."""
    illaoi = _illaoi()

    assert illaoi.maturity is CogMaturity.MODELED_UNVERIFIED
    assert illaoi.capabilities == DUEL_CAPABILITIES
    assert illaoi.verification_blockers() == ("COG_MODEL_UNVERIFIED:Illaoi",)
    assert illaoi.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Illaoi.json",
        "data/raw/16.17.1/communitydragon/champions/420.json",
        "data/raw/16.17.1/communitydragon/champions/illaoi.bin.json",
    )
    assert all((ROOT / reference).is_file() for reference in illaoi.evidence_refs)


def test_illaoi_rotation_is_deterministic_and_uses_r_reduced_w_cooldown() -> None:
    """Anchor the fixed direct-damage schedule and W's ultimate cooldown."""
    illaoi = _illaoi()
    context = _context()

    first = illaoi.build_action_plan(context)
    repeated = illaoi.build_action_plan(context)
    harsh_lessons = tuple(
        event for event in first.events if event.id.startswith("ILLAOI_W_HARSH_LESSON")
    )

    assert first == repeated
    assert first.model_id == "illaoi_q5_w1_e5_r2_level13_synthetic_v1"
    assert tuple(event.at_ms for event in harsh_lessons) == (2200, 4200, 6200)
    assert all(event.channel is ActionChannel.BASIC_ATTACK for event in harsh_lessons)
    assert all(len(event.outputs) == 2 for event in harsh_lessons)
    assert "ILLAOI_W_DURING_R_COOLDOWN_FIXTURE_ASSUMED" in first.blockers


def test_illaoi_q_w_and_r_use_locked_ad_ap_and_health_formulas() -> None:
    """Prove every direct spell-damage input reaches a modeled output."""
    illaoi = _illaoi()
    context = _context(
        item_stats={"AD": Decimal(100), "AP": Decimal(50)},
        opponent_health=Decimal(500),
    )
    plan = illaoi.build_action_plan(context)
    q = _event(plan, "ILLAOI_Q_TENTACLE_SMASH")
    w = _event(plan, "ILLAOI_W_HARSH_LESSON_1")
    r = _event(plan, "ILLAOI_R_LEAP_OF_FAITH")

    level_base = Decimal(9) + Decimal(171 * 12) / Decimal(17)
    assert q.outputs[0].amount == Decimal("1.30") * (
        level_base + Decimal("1.10") * context.snapshot.attack_damage + Decimal(20)
    )
    assert q.outputs[0].damage_type is DamageType.PHYSICAL
    assert w.outputs[0].amount == context.snapshot.attack_damage
    assert w.outputs[1].amount == context.opponent_snapshot.max_hp * (
        Decimal("0.03") + Decimal("0.00035") * context.snapshot.attack_damage
    )
    assert r.outputs[0].amount == Decimal(300)


def test_illaoi_attack_speed_changes_attacks_without_inventing_tentacles() -> None:
    """Keep attack cadence responsive and all spatial tentacle hits excluded."""
    illaoi = _illaoi()
    baseline = illaoi.build_action_plan(_context())
    faster = illaoi.build_action_plan(_context(item_stats={"ATTACK_SPEED": Decimal("0.50")}))

    baseline_attacks = tuple(
        event for event in baseline.events if event.id.startswith("ILLAOI_BASIC_ATTACK")
    )
    faster_attacks = tuple(
        event for event in faster.events if event.id.startswith("ILLAOI_BASIC_ATTACK")
    )
    assert len(faster_attacks) > len(baseline_attacks)
    assert not any("PASSIVE_TENTACLE" in event.id for event in faster.events)
    assert "ILLAOI_E_SPIRIT_ENTITY_AND_DAMAGE_ECHO_NOT_MODELED" in faster.blockers
    assert "ILLAOI_TENTACLE_PLACEMENT_AND_HIT_GEOMETRY_NOT_MODELED" in faster.blockers


def test_illaoi_engagement_and_reaction_are_explicit_about_state_gaps() -> None:
    """Expose W reach without turning E's conditional slow into direct CC."""
    illaoi = _illaoi()
    context = _context()
    reaction = illaoi.build_reaction_plan(context)

    assert illaoi.engagement_dash_distance(context) == Decimal(400)
    assert reaction.model_id == "illaoi_e_spirit_reaction_blocked_v1"
    assert reaction.events == ()
    assert reaction.cast_block_windows == ()
    assert "ILLAOI_E_VESSEL_STATE_AND_SLOW_NOT_MODELED" in reaction.blockers


def test_illaoi_role_reversal_preserves_action_ownership() -> None:
    """Keep Illaoi's direct damage attached to her in either request role."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Illaoi", "Garen"))
    as_opponent = engine.evaluate(MatchupRequest("Garen", "Illaoi"))

    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    actor_r = next(
        entry
        for entry in as_actor.timeline.log
        if entry.event_id == "ILLAOI_R_LEAP_OF_FAITH" and entry.operation == "DAMAGE"
    )
    opponent_r = next(
        entry
        for entry in as_opponent.timeline.log
        if entry.event_id == "ILLAOI_R_LEAP_OF_FAITH" and entry.operation == "DAMAGE"
    )
    assert actor_r.recipient is EntityId.TARGET
    assert opponent_r.recipient is EntityId.ACTOR


def test_illaoi_item_and_lane_policies_reject_unmodeled_channels() -> None:
    """Allow represented stats while rejecting haste, mana, and sustain."""
    illaoi = _illaoi()

    assert (
        illaoi.item_candidate_blocker(
            {"id": 1, "stats": {"AD": {}, "AP": {}, "HP": {}, "ATTACK_SPEED": {}}}
        )
        is None
    )
    assert (
        illaoi.item_candidate_blocker(
            {"id": 2, "stats": {"ABILITY_HASTE": {}, "MANA": {}, "OMNIVAMP": {}}}
        )
        == "ILLAOI_ITEM_STAT_NOT_MODELED:2:ABILITY_HASTE,MANA"
    )
    sustain, blockers = illaoi.lane_sustain_extra_health(
        _context(), duration_ms=30_000, no_damage_delay_ms=5_000
    )
    assert sustain == 0
    assert blockers == ("ILLAOI_LANE_TENTACLE_HITS_AND_MISSING_HEALTH_NOT_MODELED",)
