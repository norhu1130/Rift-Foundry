"""Focused regressions for the locked Cassiopeia champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.champions.wip.cassiopeia import CassiopeiaCog
from lol_build.cogs.registry import ChampionCogRegistry, create_default_registry
from lol_build.core.timeline import ActionChannel, EntityId, HealOutput, StatusOutput

ROOT = Path(__file__).resolve().parents[1]


def _registry_with_cassiopeia() -> ChampionCogRegistry:
    """Replace Cassiopeia's manifest scaffold with the modeled Cog.

    :return: Complete registry containing the modeled Cassiopeia implementation.
    """
    registry = create_default_registry(ROOT)
    scaffold = registry.require_cog("Cassiopeia")
    registry.add_cog(
        CassiopeiaCog(scaffold.document, scaffold.detail_root),
        override=True,
    )
    return registry


def _context(
    *,
    cassiopeia_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a level-13 Cassiopeia-versus-Garen direct-Cog context.

    :param cassiopeia_is_actor: Place Cassiopeia on the actor side when true.
    :param item_stats: Optional permanent modifiers applied to Cassiopeia.
    :return: Role-bound deterministic benchmark context.
    """
    registry = _registry_with_cassiopeia()
    cassiopeia = registry.require_cog("Cassiopeia")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if cassiopeia_is_actor else EntityId.TARGET,
        EntityId.TARGET if cassiopeia_is_actor else EntityId.ACTOR,
        cassiopeia.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Resolve one event by its stable Cassiopeia identifier.

    :param plan: Action plan exposing an ``events`` tuple.
    :param event_id: Exact event identifier to locate.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_cassiopeia_declares_modeled_capabilities_and_locked_evidence() -> None:
    """Distinguish Cassiopeia from a scaffold and retain all source forms."""
    cassiopeia = _registry_with_cassiopeia().require_cog("Cassiopeia")

    assert cassiopeia.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cassiopeia.capabilities == DUEL_CAPABILITIES
    assert cassiopeia.verification_blockers() == ("COG_MODEL_UNVERIFIED:Cassiopeia",)
    assert cassiopeia.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Cassiopeia.json",
        "data/raw/16.17.1/communitydragon/champions/69.json",
        "data/raw/16.17.1/communitydragon/champions/cassiopeia.bin.json",
    )
    assert all((ROOT / reference).is_file() for reference in cassiopeia.evidence_refs)


def test_cassiopeia_rotation_is_deterministic_and_tracks_poisoned_fangs() -> None:
    """Anchor E5/Q5/W1/R2 formulas and both Twin Fang branches."""
    cassiopeia = _registry_with_cassiopeia().require_cog("Cassiopeia")
    context = _context(item_stats={"AP": Decimal(100)})
    first = cassiopeia.build_action_plan(context)

    assert first == cassiopeia.build_action_plan(context)
    assert first.model_id == "cassiopeia_e5_q5_w1_r2_level13_poison_v1"
    assert _event(first, "CASSIOPEIA_R_PETRIFYING_GAZE_FACING_STUN").outputs[0].amount == 300
    assert _event(first, "CASSIOPEIA_Q_NOXIOUS_BLAST_1").outputs[0].amount == 280
    assert _event(first, "CASSIOPEIA_W_MIASMA_ONE_SECOND_CONTACT").outputs[0].amount == 30
    plain = _event(first, "CASSIOPEIA_E_TWIN_FANG_400_UNPOISONED")
    poisoned = _event(first, "CASSIOPEIA_E_TWIN_FANG_1200_POISONED")
    assert plain.outputs[0].amount == 110
    assert len(plain.outputs) == 1
    assert poisoned.outputs[0].amount == 285
    assert isinstance(poisoned.outputs[1], HealOutput)
    assert poisoned.outputs[1].amount == 16
    assert "CASSIOPEIA_R_TARGET_FACING_ASSUMED" in first.blockers
    assert "CASSIOPEIA_MANA_BUDGET_NOT_MODELED" in first.blockers


def test_cassiopeia_ap_attack_speed_and_haste_reach_supported_channels() -> None:
    """Prove AP, attack speed, and haste change represented outputs only."""
    cassiopeia = _registry_with_cassiopeia().require_cog("Cassiopeia")
    baseline = cassiopeia.build_action_plan(_context())
    powered = cassiopeia.build_action_plan(
        _context(
            item_stats={
                "AP": Decimal(100),
                "ATTACK_SPEED": Decimal("0.50"),
                "ABILITY_HASTE": Decimal(50),
            }
        )
    )

    baseline_attacks = [event for event in baseline.events if "BASIC_ATTACK" in event.id]
    powered_attacks = [event for event in powered.events if "BASIC_ATTACK" in event.id]
    baseline_fangs = [event for event in baseline.events if "_E_TWIN_FANG_" in event.id]
    powered_fangs = [event for event in powered.events if "_E_TWIN_FANG_" in event.id]
    baseline_q = [event for event in baseline.events if "_Q_NOXIOUS_BLAST_" in event.id]
    powered_q = [event for event in powered.events if "_Q_NOXIOUS_BLAST_" in event.id]
    assert len(powered_attacks) > len(baseline_attacks)
    assert len(powered_fangs) > len(baseline_fangs)
    assert len(powered_q) > len(baseline_q)
    assert powered_q[0].outputs[0].amount - baseline_q[0].outputs[0].amount == 65
    assert _event(powered, "CASSIOPEIA_E_TWIN_FANG_1200_POISONED").outputs[1].amount == 16


def test_cassiopeia_control_and_matchup_models_follow_role_reversal() -> None:
    """Keep Cassiopeia's facing assumption, slow, and damage role-neutral."""
    cassiopeia = _registry_with_cassiopeia().require_cog("Cassiopeia")
    stun, slow = cassiopeia.build_reaction_plan(_context()).cast_block_windows

    assert (stun.control_type.value, stun.end_ms - stun.start_ms) == ("STUN", 2000)
    assert stun.blocked_channels == (
        ActionChannel.BASIC_ATTACK,
        ActionChannel.ABILITY,
        ActionChannel.MOVEMENT,
    )
    assert (slow.control_type.value, slow.end_ms - slow.start_ms) == ("SLOW", 1000)
    assert slow.blocked_channels == (ActionChannel.MOVEMENT,)
    assert stun.tenacity_reducible is slow.tenacity_reducible is True

    engine = MatchupEngine(ROOT, registry=_registry_with_cassiopeia())
    as_actor = engine.evaluate(MatchupRequest("Cassiopeia", "Garen"))
    as_target = engine.evaluate(MatchupRequest("Garen", "Cassiopeia"))
    assert as_actor.actor_action_model == as_target.opponent_action_model
    assert as_actor.actor_reaction_model == as_target.opponent_reaction_model
    actor_q = next(
        entry
        for entry in as_actor.timeline.log
        if entry.event_id == "CASSIOPEIA_Q_NOXIOUS_BLAST_1" and entry.operation == "DAMAGE"
    )
    target_q = next(
        entry
        for entry in as_target.timeline.log
        if entry.event_id == "CASSIOPEIA_Q_NOXIOUS_BLAST_1" and entry.operation == "DAMAGE"
    )
    assert actor_q.recipient is EntityId.TARGET
    assert target_q.recipient is EntityId.ACTOR


def test_miasma_exposes_slow_and_grounded_with_scope_blocker() -> None:
    """Retain grounded evidence without pretending it blocks ordinary walking."""
    cassiopeia = _registry_with_cassiopeia().require_cog("Cassiopeia")
    plan = cassiopeia.build_action_plan(_context())
    miasma = _event(plan, "CASSIOPEIA_W_MIASMA_ONE_SECOND_CONTACT")

    statuses = [output for output in miasma.outputs if isinstance(output, StatusOutput)]
    assert [(output.status, output.duration_ms) for output in statuses] == [
        ("CASSIOPEIA_POISON_W", 1000),
        ("CC_SLOW", 1000),
        ("CC_GROUNDED", 1000),
    ]
    reaction = cassiopeia.build_reaction_plan(_context())
    assert "CASSIOPEIA_W_GROUNDED_DASH_CHANNEL_NOT_REPRESENTABLE" in reaction.blockers
    assert "CASSIOPEIA_R_AWAY_FACING_SLOW_BRANCH_NOT_SELECTED" in reaction.blockers


def test_teemo_blind_cancels_cassiopeia_attacks_but_not_spells() -> None:
    """Keep Cassiopeia's poison rotation independent from the blinded channel."""
    evaluation = MatchupEngine(ROOT, registry=_registry_with_cassiopeia()).evaluate(
        MatchupRequest("Teemo", "Cassiopeia")
    )

    assert any(
        entry.event_id.startswith("CASSIOPEIA_BASIC_ATTACK_") and entry.status == "CANCELLED"
        for entry in evaluation.timeline.log
    )
    for event_id in (
        "CASSIOPEIA_R_PETRIFYING_GAZE_FACING_STUN",
        "CASSIOPEIA_Q_NOXIOUS_BLAST_1",
        "CASSIOPEIA_E_TWIN_FANG_1200_POISONED",
    ):
        assert any(
            entry.event_id == event_id and entry.operation == "DAMAGE" and entry.status == "APPLIED"
            for entry in evaluation.timeline.log
        )


def test_cassiopeia_item_policy_forbids_boots_and_unresolved_resources() -> None:
    """Forbid boots while allowing AP, haste, and attack-speed candidates."""
    cassiopeia = _registry_with_cassiopeia().require_cog("Cassiopeia")

    assert (
        cassiopeia.item_candidate_blocker(
            {
                "id": 1,
                "groups": {"purchase_limit": None},
                "stats": {"AP": {}, "ABILITY_HASTE": {}, "ATTACK_SPEED": {}},
            }
        )
        is None
    )
    assert (
        cassiopeia.item_candidate_blocker(
            {
                "id": 3111,
                "groups": {"purchase_limit": "boots"},
                "stats": {"MAGIC_RESISTANCE": {}, "MOVE_SPEED_FLAT": {}},
            }
        )
        == "CASSIOPEIA_BOOTS_FORBIDDEN:3111"
    )
    assert (
        cassiopeia.item_candidate_blocker(
            {
                "id": 2,
                "groups": {"purchase_limit": None},
                "stats": {"MANA": {}, "MANA_REGEN": {}},
            }
        )
        == "CASSIOPEIA_ITEM_STAT_NOT_MODELED:2:MANA,MANA_REGEN"
    )
