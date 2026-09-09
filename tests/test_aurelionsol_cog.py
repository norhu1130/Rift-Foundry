"""Focused regressions for the locked Aurelion Sol champion Cog."""

import json
from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.champions.modeled_unverified.garen import GarenCog
from lol_build.cogs.champions.wip.aurelionsol import AurelionSolCog
from lol_build.cogs.champions.wip.teemo import TeemoCog
from lol_build.cogs.registry import ChampionCogRegistry
from lol_build.core.timeline import ActionChannel, EntityId, StatusOutput

ROOT = Path(__file__).resolve().parents[1]


def _registry_with_aurelionsol() -> ChampionCogRegistry:
    """Build an isolated registry for the focused matchup fixtures.

    :return: Registry containing Aurelion Sol, Garen, and Teemo.
    """
    catalog = json.loads(
        (ROOT / "data/raw/16.17.1/en_US/champion.json").read_text(encoding="utf-8")
    )["data"]
    registry = ChampionCogRegistry()
    registry.add_cog(AurelionSolCog(catalog["AurelionSol"]))
    registry.add_cog(GarenCog(catalog["Garen"]))
    registry.add_cog(TeemoCog(catalog["Teemo"]))
    return registry


def _context(
    *,
    aurelionsol_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
    opponent_item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a level-13 Aurelion Sol-versus-Garen direct context.

    :param aurelionsol_is_actor: Place Aurelion Sol on the actor side when true.
    :param item_stats: Optional item modifiers applied to Aurelion Sol.
    :param opponent_item_stats: Optional item modifiers applied to Garen.
    :return: Role-bound deterministic benchmark context.
    """
    registry = _registry_with_aurelionsol()
    aurelionsol = registry.require_cog("AurelionSol")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if aurelionsol_is_actor else EntityId.TARGET,
        EntityId.TARGET if aurelionsol_is_actor else EntityId.ACTOR,
        aurelionsol.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13, item_stats=opponent_item_stats),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Resolve one action by its stable Aurelion Sol identifier.

    :param plan: Action plan exposing an ``events`` collection.
    :param event_id: Exact event identifier to locate.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_aurelionsol_declares_modeled_capabilities_and_locked_evidence() -> None:
    """Distinguish modeled behavior and retain all three evidence forms."""
    aurelionsol = _registry_with_aurelionsol().require_cog("AurelionSol")

    assert aurelionsol.maturity is CogMaturity.MODELED_UNVERIFIED
    assert aurelionsol.capabilities == DUEL_CAPABILITIES
    assert aurelionsol.verification_blockers() == (
        "COG_MODEL_UNVERIFIED:AurelionSol",
    )
    assert aurelionsol.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/AurelionSol.json",
        "data/raw/16.17.1/communitydragon/champions/136.json",
        "data/raw/16.17.1/communitydragon/champions/aurelionsol.bin.json",
    )
    assert all((ROOT / reference).is_file() for reference in aurelionsol.evidence_refs)


def test_aurelionsol_rotation_is_deterministic_and_anchors_locked_formulas() -> None:
    """Anchor E5, R2, W1, and Q5 formulas at fifty fixture stacks."""
    aurelionsol = _registry_with_aurelionsol().require_cog("AurelionSol")
    context = _context(item_stats={"AP": Decimal(100)})
    first = aurelionsol.build_action_plan(context)

    assert first == aurelionsol.build_action_plan(context)
    assert first.model_id == "aurelionsol_q5_e5_w1_r2_level13_stardust50_v1"
    assert _event(first, "AURELIONSOL_E_SINGULARITY_1_TICK_1").outputs[0].amount == 42
    ultimate = _event(first, "AURELIONSOL_R_FALLING_STAR")
    assert ultimate.outputs[0].amount == 325
    assert isinstance(ultimate.outputs[1], StatusOutput)
    assert (ultimate.outputs[1].status, ultimate.outputs[1].duration_ms) == (
        "CC_STUN",
        1000,
    )
    q = _event(first, "AURELIONSOL_Q_BREATH_PERIOD_1_FLIGHT")
    assert tuple(output.amount for output in q.outputs[:2]) == (
        Decimal("172.80"),
        Decimal("140.40"),
    )
    assert q.outputs[2].amount == (
        context.opponent_snapshot.max_hp * Decimal("0.0167400")
    )
    assert "AURELIONSOL_STARDUST_FIXED_50_FIXTURE" in first.blockers
    assert "AURELIONSOL_E_CURRENT_HP_EXECUTE_NOT_MODELED" in first.blockers
    assert "AURELIONSOL_MULTI_TARGET_EFFECTS_NOT_MODELED" in first.blockers


def test_aurelionsol_ap_haste_and_target_hp_reach_distinct_outputs() -> None:
    """Prove AP, haste, and target health affect only supported channels."""
    aurelionsol = _registry_with_aurelionsol().require_cog("AurelionSol")
    baseline = aurelionsol.build_action_plan(_context())
    powered = aurelionsol.build_action_plan(_context(item_stats={"AP": Decimal(100)}))
    hasted = aurelionsol.build_action_plan(
        _context(item_stats={"ABILITY_HASTE": Decimal(100)})
    )
    healthy_target = aurelionsol.build_action_plan(
        _context(opponent_item_stats={"HP": Decimal(1000)})
    )

    assert (
        _event(powered, "AURELIONSOL_R_FALLING_STAR").outputs[0].amount
        - _event(baseline, "AURELIONSOL_R_FALLING_STAR").outputs[0].amount
        == 75
    )
    assert _event(hasted, "AURELIONSOL_E_SINGULARITY_2_TICK_1").at_ms == 6100
    assert not any("SINGULARITY_2" in event.id for event in baseline.events)
    baseline_q = _event(baseline, "AURELIONSOL_Q_BREATH_PERIOD_1_FLIGHT")
    healthy_q = _event(healthy_target, "AURELIONSOL_Q_BREATH_PERIOD_1_FLIGHT")
    assert healthy_q.outputs[2].amount - baseline_q.outputs[2].amount == Decimal(
        "16.74000"
    )


def test_aurelionsol_engagement_sustain_and_item_policy_are_state_honest() -> None:
    """Expose W approach while rejecting unrepresented resource and sustain stats."""
    aurelionsol = _registry_with_aurelionsol().require_cog("AurelionSol")
    context = _context()

    assert aurelionsol.engagement_dash_distance(context) == Decimal("1875.0")
    assert aurelionsol.engagement_speed_multiplier(context) > Decimal(1)
    amount, blockers = aurelionsol.lane_sustain_extra_health(
        context,
        duration_ms=8000,
        no_damage_delay_ms=4000,
    )
    assert amount == 0
    assert blockers == ("AURELIONSOL_MANA_GATED_LANE_SUSTAIN_NOT_MODELED",)
    assert aurelionsol.item_candidate_blocker(
        {
            "id": 1,
            "stats": {
                "AP": {},
                "ABILITY_HASTE": {},
                "HP": {},
                "ATTACK_SPEED": {},
            },
        }
    ) is None
    assert aurelionsol.item_candidate_blocker(
        {"id": 2, "stats": {"MANA": {}, "OMNIVAMP": {}}}
    ) == "AURELIONSOL_ITEM_STAT_NOT_MODELED:2:MANA,OMNIVAMP"


def test_aurelionsol_control_and_matchup_models_follow_role_reversal() -> None:
    """Keep outgoing damage, pull, stun, and models attached to either role."""
    aurelionsol = _registry_with_aurelionsol().require_cog("AurelionSol")
    reaction = aurelionsol.build_reaction_plan(_context())
    pull, stun = reaction.cast_block_windows

    assert pull.blocked_channels == (ActionChannel.MOVEMENT,)
    assert pull.tenacity_reducible is False
    assert stun.control_type.value == "STUN"
    assert stun.tenacity_reducible is True
    assert stun.blocked_channels == (
        ActionChannel.BASIC_ATTACK,
        ActionChannel.ABILITY,
        ActionChannel.MOVEMENT,
    )

    engine = MatchupEngine(ROOT, registry=_registry_with_aurelionsol())
    as_actor = engine.evaluate(MatchupRequest("AurelionSol", "Garen"))
    as_target = engine.evaluate(MatchupRequest("Garen", "AurelionSol"))
    assert as_actor.actor_action_model == as_target.opponent_action_model
    assert as_actor.actor_reaction_model == as_target.opponent_reaction_model
    actor_q = next(
        entry
        for entry in as_actor.timeline.log
        if entry.event_id == "AURELIONSOL_Q_BREATH_PERIOD_1_FLIGHT"
        and entry.operation == "DAMAGE"
    )
    target_q = next(
        entry
        for entry in as_target.timeline.log
        if entry.event_id == "AURELIONSOL_Q_BREATH_PERIOD_1_FLIGHT"
        and entry.operation == "DAMAGE"
    )
    assert actor_q.recipient is EntityId.TARGET
    assert target_q.recipient is EntityId.ACTOR


def test_teemo_blind_cancels_aurelionsol_attack_but_not_spells() -> None:
    """Keep Breath of Light and other abilities independent from blind."""
    result = MatchupEngine(ROOT, registry=_registry_with_aurelionsol()).evaluate(
        MatchupRequest("AurelionSol", "Teemo")
    )

    assert any(
        entry.event_id.startswith("AURELIONSOL_BASIC_ATTACK_")
        and entry.status == "CANCELLED"
        for entry in result.timeline.log
    )
    for event_id in (
        "AURELIONSOL_E_SINGULARITY_1_TICK_1",
        "AURELIONSOL_R_FALLING_STAR",
        "AURELIONSOL_Q_BREATH_PERIOD_1_FLIGHT",
    ):
        assert any(
            entry.event_id == event_id
            and entry.operation == "DAMAGE"
            and entry.status == "APPLIED"
            for entry in result.timeline.log
        )
