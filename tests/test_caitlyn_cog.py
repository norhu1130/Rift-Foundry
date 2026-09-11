"""Focused regression tests for the locked Caitlyn champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry
from lol_build.core.timeline import ActionChannel, DamageOutput, EntityId

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    item_stats: dict[str, Decimal] | None = None,
    caitlyn_is_actor: bool = True,
) -> ParticipantContext:
    """Build a level-13 Caitlyn-versus-Garen direct-call context.

    :param item_stats: Optional permanent Caitlyn item-stat modifiers.
    :param caitlyn_is_actor: Put Caitlyn on the actor side when true.
    :return: Role-bound context accepted by the Caitlyn Cog.
    """
    registry = create_default_registry(ROOT)
    caitlyn = registry.require_cog("Caitlyn")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if caitlyn_is_actor else EntityId.TARGET,
        EntityId.TARGET if caitlyn_is_actor else EntityId.ACTOR,
        caitlyn.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def test_caitlyn_declares_modeled_capabilities_and_locked_evidence() -> None:
    """Distinguish Caitlyn from a scaffold and retain all three source forms."""
    caitlyn = create_default_registry(ROOT).require_cog("Caitlyn")

    assert caitlyn.maturity is CogMaturity.MODELED_UNVERIFIED
    assert caitlyn.capabilities == DUEL_CAPABILITIES
    assert caitlyn.verification_blockers() == ("COG_MODEL_UNVERIFIED:Caitlyn",)
    assert caitlyn.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Caitlyn.json",
        "data/raw/16.17.1/communitydragon/champions/51.json",
        "data/raw/16.17.1/communitydragon/champions/caitlyn.bin.json",
    )
    assert all((ROOT / reference).is_file() for reference in caitlyn.evidence_refs)


def test_caitlyn_plan_is_deterministic_and_uses_locked_rank_values() -> None:
    """Anchor Q5, W5, E1, R2, and level-13 Headshot formulas."""
    caitlyn = create_default_registry(ROOT).require_cog("Caitlyn")
    context = _context(
        item_stats={
            "AD": Decimal(40),
            "AP": Decimal(100),
            "CRITICAL_STRIKE_CHANCE": Decimal("0.25"),
        }
    )

    first = caitlyn.build_action_plan(context)
    second = caitlyn.build_action_plan(context)
    net = next(event for event in first.events if event.id == "CAITLYN_E_90_CALIBER_NET")
    q = next(event for event in first.events if event.id == "CAITLYN_Q_PILTOVER_PEACEMAKER")
    trap_headshot = next(
        event for event in first.events if event.id == "CAITLYN_W_EMPOWERED_HEADSHOT"
    )
    ultimate = next(event for event in first.events if event.id == "CAITLYN_R_ACE_IN_THE_HOLE")

    assert first == second
    assert first.model_id == "caitlyn_q5_w5_e1_r2_level13_locked_v1"
    assert isinstance(net.outputs[0], DamageOutput)
    assert net.outputs[0].amount == Decimal(160)
    assert q.outputs[0].amount == Decimal(210) + Decimal("2.05") * context.snapshot.attack_damage
    expected_attack = context.snapshot.attack_damage * Decimal("1.25")
    expected_headshot = context.snapshot.attack_damage * Decimal("1.25")
    assert trap_headshot.outputs[0].amount == (
        expected_attack
        + expected_headshot
        + Decimal(215)
        + Decimal("0.30") * context.snapshot.bonus_attack_damage
    )
    assert ultimate.outputs[0].amount == (
        Decimal(475) + context.snapshot.bonus_attack_damage
    ) * Decimal("1.075")
    assert "CAITLYN_W_PREARMED_TRAP_TRIGGER_ASSUMED" in first.blockers
    assert "CAITLYN_R_CHANNEL_INTERRUPTION_NOT_CAUSALLY_MODELED" in first.blockers


def test_caitlyn_ad_attack_speed_and_crit_affect_represented_outputs() -> None:
    """Prove Caitlyn's principal marksman item stats change the fixed model."""
    caitlyn = create_default_registry(ROOT).require_cog("Caitlyn")
    baseline = caitlyn.build_action_plan(_context())
    more_ad = caitlyn.build_action_plan(_context(item_stats={"AD": Decimal(50)}))
    more_speed = caitlyn.build_action_plan(_context(item_stats={"ATTACK_SPEED": Decimal("0.50")}))
    more_crit = caitlyn.build_action_plan(
        _context(item_stats={"CRITICAL_STRIKE_CHANCE": Decimal("0.25")})
    )

    baseline_q = next(
        event for event in baseline.events if event.id == "CAITLYN_Q_PILTOVER_PEACEMAKER"
    )
    more_ad_q = next(
        event for event in more_ad.events if event.id == "CAITLYN_Q_PILTOVER_PEACEMAKER"
    )
    baseline_attacks = tuple(
        event for event in baseline.events if event.id.startswith("CAITLYN_ATTACK_")
    )
    faster_attacks = tuple(
        event for event in more_speed.events if event.id.startswith("CAITLYN_ATTACK_")
    )
    baseline_e_headshot = next(
        event for event in baseline.events if event.id == "CAITLYN_E_EMPOWERED_HEADSHOT"
    )
    crit_e_headshot = next(
        event for event in more_crit.events if event.id == "CAITLYN_E_EMPOWERED_HEADSHOT"
    )

    assert more_ad_q.outputs[0].amount - baseline_q.outputs[0].amount == Decimal("102.50")
    assert len(faster_attacks) > len(baseline_attacks)
    assert crit_e_headshot.outputs[0].amount > baseline_e_headshot.outputs[0].amount


def test_caitlyn_role_reversal_and_teemo_blind_are_channel_correct() -> None:
    """Keep Caitlyn role-neutral and let blind cancel attacks but not Q or E."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Caitlyn", "Teemo"))
    as_opponent = engine.evaluate(MatchupRequest("Teemo", "Caitlyn"))

    actor_q = next(
        entry
        for entry in as_actor.timeline.log
        if entry.event_id == "CAITLYN_Q_PILTOVER_PEACEMAKER" and entry.operation == "DAMAGE"
    )
    opponent_q = next(
        entry
        for entry in as_opponent.timeline.log
        if entry.event_id == "CAITLYN_Q_PILTOVER_PEACEMAKER" and entry.operation == "DAMAGE"
    )
    assert actor_q.recipient is EntityId.TARGET
    assert opponent_q.recipient is EntityId.ACTOR
    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    assert any(
        entry.event_id.startswith("CAITLYN_ATTACK_")
        and entry.status == "CANCELLED"
        and entry.action_channel is ActionChannel.BASIC_ATTACK
        for entry in as_opponent.timeline.log
    )
    assert opponent_q.status == "APPLIED"


def test_caitlyn_reaction_and_item_policy_preserve_model_boundaries() -> None:
    """Expose movement-only trap control and reject unsupported item channels."""
    caitlyn = create_default_registry(ROOT).require_cog("Caitlyn")
    reaction = caitlyn.build_reaction_plan(_context())

    root = reaction.cast_block_windows[0]
    assert root.blocked_channels == (ActionChannel.MOVEMENT,)
    assert root.tenacity_reducible is True
    assert root.control_type.value == "ROOT"
    assert root.source_event_id == "CAITLYN_W_ASSUMED_TRAP_TRIGGER"
    assert (
        caitlyn.item_candidate_blocker(
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
        caitlyn.item_candidate_blocker({"id": 2, "stats": {"ABILITY_HASTE": {}, "LIFESTEAL": {}}})
        == "CAITLYN_ITEM_STAT_NOT_MODELED:2:ABILITY_HASTE,LIFESTEAL"
    )
