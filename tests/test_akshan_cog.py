"""Focused regression tests for the locked Akshan champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, DamageOutput, EntityId, ShieldOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    item_stats: dict[str, Decimal] | None = None,
    akshan_is_actor: bool = True,
) -> ParticipantContext:
    """Build a level-13 Akshan-versus-Garen direct-call context.

    :param item_stats: Optional permanent Akshan item-stat modifiers.
    :param akshan_is_actor: Put Akshan on the actor side when true.
    :return: Role-bound context accepted by the Akshan Cog.
    """
    registry = create_default_registry(ROOT)
    akshan = registry.require_cog("Akshan")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if akshan_is_actor else EntityId.TARGET,
        EntityId.TARGET if akshan_is_actor else EntityId.ACTOR,
        akshan.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def test_akshan_declares_modeled_capabilities_and_locked_evidence() -> None:
    """Distinguish Akshan from a scaffold and retain all three source forms."""
    akshan = create_default_registry(ROOT).require_cog("Akshan")

    assert akshan.maturity is CogMaturity.MODELED_UNVERIFIED
    assert akshan.capabilities == DUEL_CAPABILITIES
    assert akshan.verification_blockers() == ("COG_MODEL_UNVERIFIED:Akshan",)
    assert akshan.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Akshan.json",
        "data/raw/16.17.1/communitydragon/champions/166.json",
        "data/raw/16.17.1/communitydragon/champions/akshan.bin.json",
    )
    assert all((ROOT / reference).is_file() for reference in akshan.evidence_refs)


def test_akshan_plan_anchors_passive_q_e_r_and_is_deterministic() -> None:
    """Anchor Q5/E5/R2 formulas and the first three-hit passive proc."""
    akshan = create_default_registry(ROOT).require_cog("Akshan")
    context = _context(
        item_stats={
            "AD": Decimal(40),
            "AP": Decimal(100),
            "ATTACK_SPEED": Decimal("0.50"),
            "CRITICAL_STRIKE_CHANCE": Decimal("0.20"),
        }
    )

    first = akshan.build_action_plan(context)
    second = akshan.build_action_plan(context)
    q_out = next(event for event in first.events if event.id == "AKSHAN_Q_OUT_1")
    q_return = next(event for event in first.events if event.id == "AKSHAN_Q_RETURN_2")
    passive = next(event for event in first.events if len(event.outputs) == 3)
    e_shot = next(event for event in first.events if "E_SHOT" in event.id)
    r_bullets = tuple(
        event for event in first.events if event.id.startswith("AKSHAN_R_COMEUPPANCE")
    )

    assert first == second
    assert first.model_id == "akshan_q5_w1_e5_r2_level13_locked_v1"
    assert q_out.outputs[0] == q_return.outputs[0]
    assert q_out.outputs[0].amount == Decimal(165) + Decimal("0.70") * Decimal(40)
    assert passive.outputs[1] == DamageOutput(
        context.opponent_entity,
        Decimal(140),
        DamageType.MAGIC,
    )
    assert isinstance(passive.outputs[2], ShieldOutput)
    assert passive.outputs[2].recipient is context.self_entity
    assert passive.outputs[2].duration_ms == 2000
    assert e_shot.outputs[0].amount > Decimal(40)
    assert len(r_bullets) == 6
    assert all(event.outputs[0].amount == Decimal("41") * Decimal("1.06") for event in r_bullets)
    assert "AKSHAN_E_GRAPPLE_TERRAIN_AND_COLLISION_NOT_MODELED" in first.blockers
    assert "AKSHAN_W_SCOUNDREL_MARK_GOLD_AND_REVIVAL_OUT_OF_MODEL" in first.blockers


def test_akshan_ad_ap_attack_speed_and_crit_affect_represented_outputs() -> None:
    """Prove Akshan's principal marksman stats alter represented channels."""
    akshan = create_default_registry(ROOT).require_cog("Akshan")
    baseline = akshan.build_action_plan(_context())
    more_ad = akshan.build_action_plan(_context(item_stats={"AD": Decimal(50)}))
    more_ap = akshan.build_action_plan(_context(item_stats={"AP": Decimal(100)}))
    more_speed = akshan.build_action_plan(_context(item_stats={"ATTACK_SPEED": Decimal("0.50")}))
    more_crit = akshan.build_action_plan(
        _context(item_stats={"CRITICAL_STRIKE_CHANCE": Decimal("0.25")})
    )

    def event_amount(plan: object, prefix: str) -> Decimal:
        """Return the first damage amount for an event prefix.

        :param plan: Action plan whose ordered events are searched.
        :param prefix: Champion-scoped identifier prefix to locate.
        :return: Raw damage on the matching event's first output.
        """
        event = next(candidate for candidate in plan.events if candidate.id.startswith(prefix))
        return event.outputs[0].amount

    assert event_amount(more_ad, "AKSHAN_Q_OUT") > event_amount(baseline, "AKSHAN_Q_OUT")
    baseline_passive = next(event for event in baseline.events if len(event.outputs) == 3)
    ap_passive = next(event for event in more_ap.events if len(event.outputs) == 3)
    assert ap_passive.outputs[1].amount > baseline_passive.outputs[1].amount
    baseline_attacks = tuple(
        event for event in baseline.events if event.channel is ActionChannel.BASIC_ATTACK
    )
    faster_attacks = tuple(
        event for event in more_speed.events if event.channel is ActionChannel.BASIC_ATTACK
    )
    assert len(faster_attacks) > len(baseline_attacks)
    assert event_amount(more_crit, "AKSHAN_ATTACK") > event_amount(baseline, "AKSHAN_ATTACK")


def test_akshan_role_reversal_and_teemo_blind_are_channel_correct() -> None:
    """Keep Akshan role-neutral and let blind cancel attacks but not spells."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Akshan", "Teemo"))
    as_opponent = engine.evaluate(MatchupRequest("Teemo", "Akshan"))

    actor_q = next(
        entry
        for entry in as_actor.timeline.log
        if entry.event_id == "AKSHAN_Q_OUT_1" and entry.operation == "DAMAGE"
    )
    opponent_q = next(
        entry
        for entry in as_opponent.timeline.log
        if entry.event_id == "AKSHAN_Q_OUT_1" and entry.operation == "DAMAGE"
    )
    assert actor_q.recipient is EntityId.TARGET
    assert opponent_q.recipient is EntityId.ACTOR
    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    assert any(
        entry.event_id.startswith("AKSHAN_ATTACK")
        and entry.status == "CANCELLED"
        and entry.action_channel is ActionChannel.BASIC_ATTACK
        for entry in as_opponent.timeline.log
    )
    assert opponent_q.status == "APPLIED"
    assert any(
        entry.event_id.startswith("AKSHAN_E_SHOT") and entry.status == "APPLIED"
        for entry in as_opponent.timeline.log
    )


def test_akshan_engagement_reaction_and_item_policy_preserve_boundaries() -> None:
    """Expose Q pursuit while rejecting unsupported terrain and item channels."""
    akshan = create_default_registry(ROOT).require_cog("Akshan")
    context = _context()
    reaction = akshan.build_reaction_plan(context)

    assert akshan.engagement_speed_multiplier(context) == Decimal("1.20")
    assert akshan.engagement_dash_distance(context) == Decimal(0)
    assert reaction.model_id == "akshan_geometry_camouflage_channel_unresolved_v1"
    assert reaction.events == ()
    assert (
        akshan.item_candidate_blocker(
            {
                "id": 1,
                "stats": {
                    "AD": {},
                    "AP": {},
                    "ATTACK_SPEED": {},
                    "CRITICAL_STRIKE_CHANCE": {},
                },
            }
        )
        is None
    )
    assert (
        akshan.item_candidate_blocker({"id": 2, "stats": {"ABILITY_HASTE": {}, "LIFESTEAL": {}}})
        == "AKSHAN_ITEM_STAT_NOT_MODELED:2:ABILITY_HASTE,LIFESTEAL"
    )
