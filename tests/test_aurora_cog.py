"""Focused regressions for the locked Aurora champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.champions.wip.aurora import AuroraCog
from lol_build.cogs.registry import ChampionCogRegistry, create_default_registry
from lol_build.core.timeline import (
    ActionChannel,
    DamageOutput,
    EntityId,
    HealOutput,
    StatModifierOutput,
    StatusOutput,
)

ROOT = Path(__file__).resolve().parents[1]


def _registry_with_aurora() -> ChampionCogRegistry:
    """Install Aurora's modeled implementation into the locked registry.

    :return: Complete registry containing the modeled Aurora Cog.
    """
    registry = create_default_registry(ROOT)
    loaded = registry.require_cog("Aurora")
    registry.add_cog(AuroraCog(loaded.document, loaded.detail_root), override=True)
    return registry


def _context(
    *,
    aurora_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
    opponent_health: Decimal = Decimal(0),
) -> ParticipantContext:
    """Build a level-13 Aurora-versus-Garen direct-Cog context.

    :param aurora_is_actor: Place Aurora on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Aurora.
    :param opponent_health: Additional maximum health applied to Garen.
    :return: Role-bound deterministic benchmark context.
    """
    registry = _registry_with_aurora()
    aurora = registry.require_cog("Aurora")
    garen = registry.require_cog("Garen")
    return ParticipantContext(
        EntityId.ACTOR if aurora_is_actor else EntityId.TARGET,
        EntityId.TARGET if aurora_is_actor else EntityId.ACTOR,
        aurora.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13, item_stats={"HP": opponent_health}),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Resolve one event by its stable Aurora identifier.

    :param plan: Action plan exposing an ``events`` tuple.
    :param event_id: Exact event identifier to locate.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def _damage_outputs(event: object) -> tuple[DamageOutput, ...]:
    """Select damage outputs from one Aurora action.

    :param event: Action event exposing an ``outputs`` tuple.
    :return: Fixed damage outputs in their resolution order.
    """
    return tuple(output for output in event.outputs if isinstance(output, DamageOutput))


def test_aurora_declares_modeled_capabilities_and_locked_evidence() -> None:
    """Distinguish Aurora from a scaffold and retain all source forms."""
    aurora = _registry_with_aurora().require_cog("Aurora")

    assert aurora.maturity is CogMaturity.MODELED_UNVERIFIED
    assert aurora.capabilities == DUEL_CAPABILITIES
    assert aurora.verification_blockers() == ("COG_MODEL_UNVERIFIED:Aurora",)
    assert aurora.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Aurora.json",
        "data/raw/16.17.1/communitydragon/champions/893.json",
        "data/raw/16.17.1/communitydragon/champions/aurora.bin.json",
    )
    assert all((ROOT / reference).is_file() for reference in aurora.evidence_refs)


def test_aurora_rotation_is_deterministic_and_uses_locked_rank_values() -> None:
    """Anchor Q5/E5/W1/R2 values and both halves of Twofold Hex."""
    aurora = _registry_with_aurora().require_cog("Aurora")
    context = _context(item_stats={"AP": Decimal(100)})
    first = aurora.build_action_plan(context)

    assert first == aurora.build_action_plan(context)
    assert first.model_id == "aurora_q5_e5_w1_r2_level13_spirit_fixture_v1"
    assert _damage_outputs(_event(first, "AURORA_Q_TWOFOLD_HEX_OUT_1"))[0].amount == 185
    assert _damage_outputs(_event(first, "AURORA_Q_TWOFOLD_HEX_RETURN_1"))[0].amount == 185
    assert _damage_outputs(_event(first, "AURORA_E_THE_WEIRDING"))[0].amount == 300
    assert _damage_outputs(_event(first, "AURORA_R_BETWEEN_WORLDS_IMPACT"))[0].amount == 345
    assert "AURORA_Q_RETURN_MISSING_HEALTH_AMPLIFICATION_NOT_MODELED" in first.blockers
    assert "AURORA_W_INVISIBILITY_TARGETING_EFFECTS_NOT_MODELED" in first.blockers
    assert "AURORA_R_ZONE_CROSSING_AND_TELEPORT_NOT_MODELED" in first.blockers


def test_aurora_passive_tracks_spirits_damage_healing_and_speed() -> None:
    """Exercise three-hit exorcism and its four-second spirit outputs."""
    aurora = _registry_with_aurora().require_cog("Aurora")
    context = _context(item_stats={"AP": Decimal(100)})
    plan = aurora.build_action_plan(context)
    first_proc = _event(plan, "AURORA_E_THE_WEIRDING")

    passive_damage = _damage_outputs(first_proc)[1]
    assert passive_damage.amount == context.opponent_snapshot.max_hp * Decimal("0.037")
    statuses = [output for output in first_proc.outputs if isinstance(output, StatusOutput)]
    assert any(
        output.status == "AURORA_SPIRIT_STACK_1" and output.duration_ms == 4000
        for output in statuses
    )
    speed = next(output for output in first_proc.outputs if isinstance(output, StatModifierOutput))
    assert speed.amount == context.snapshot.move_speed * Decimal("0.104")
    heals = [
        event.outputs[0]
        for event in plan.events
        if event.id.startswith("AURORA_PASSIVE_SPIRIT_1_HEAL_")
    ]
    assert len(heals) == 4
    assert all(isinstance(output, HealOutput) and output.amount == 17 for output in heals)
    assert any("AURORA_SPIRIT_STACK_2" in str(event.outputs) for event in plan.events)


def test_aurora_ap_attack_speed_haste_and_target_hp_affect_outputs() -> None:
    """Prove AP, cadence, cooldown, and target-health channels are live."""
    aurora = _registry_with_aurora().require_cog("Aurora")
    baseline = aurora.build_action_plan(_context())
    scaled_context = _context(
        item_stats={
            "AP": Decimal(100),
            "ATTACK_SPEED": Decimal("0.50"),
            "ABILITY_HASTE": Decimal(100),
        },
        opponent_health=Decimal(500),
    )
    scaled = aurora.build_action_plan(scaled_context)

    assert (
        _damage_outputs(_event(scaled, "AURORA_E_THE_WEIRDING"))[0].amount
        - _damage_outputs(_event(baseline, "AURORA_E_THE_WEIRDING"))[0].amount
        == 70
    )
    assert len(
        [event for event in scaled.events if event.id.startswith("AURORA_BASIC_ATTACK_")]
    ) > len([event for event in baseline.events if event.id.startswith("AURORA_BASIC_ATTACK_")])
    assert _event(scaled, "AURORA_Q_TWOFOLD_HEX_OUT_2").at_ms == 4000
    assert _event(baseline, "AURORA_Q_TWOFOLD_HEX_OUT_2").at_ms == 7500
    assert _damage_outputs(_event(scaled, "AURORA_E_THE_WEIRDING"))[1].amount > (
        _damage_outputs(_event(baseline, "AURORA_E_THE_WEIRDING"))[1].amount
    )


def test_aurora_control_engagement_and_roles_are_symmetric() -> None:
    """Keep Aurora's slows and mobility attached to either participant role."""
    aurora = _registry_with_aurora().require_cog("Aurora")
    r_slow, e_slow = aurora.build_reaction_plan(_context()).cast_block_windows

    assert (r_slow.control_type.value, r_slow.end_ms - r_slow.start_ms) == (
        "SLOW",
        2000,
    )
    assert (e_slow.control_type.value, e_slow.end_ms - e_slow.start_ms) == (
        "SLOW",
        1000,
    )
    assert r_slow.blocked_channels == e_slow.blocked_channels == (ActionChannel.MOVEMENT,)
    assert r_slow.tenacity_reducible is e_slow.tenacity_reducible is True
    assert aurora.engagement_dash_distance(_context()) == 300
    assert aurora.engagement_speed_multiplier(_context()) == Decimal("1.20")

    actor_q = _event(
        aurora.build_action_plan(_context(aurora_is_actor=True)),
        "AURORA_Q_TWOFOLD_HEX_OUT_1",
    )
    target_q = _event(
        aurora.build_action_plan(_context(aurora_is_actor=False)),
        "AURORA_Q_TWOFOLD_HEX_OUT_1",
    )
    assert actor_q.source is EntityId.ACTOR
    assert target_q.source is EntityId.TARGET
    assert actor_q.outputs[0].recipient is EntityId.TARGET
    assert target_q.outputs[0].recipient is EntityId.ACTOR
    assert actor_q.sequence != target_q.sequence


def test_teemo_blind_cancels_aurora_attacks_but_not_abilities() -> None:
    """Keep Aurora's spell damage independent from the blinded attack channel."""
    result = MatchupEngine(ROOT, registry=_registry_with_aurora()).evaluate(
        MatchupRequest("Aurora", "Teemo")
    )

    assert any(
        entry.event_id.startswith("AURORA_BASIC_ATTACK_") and entry.status == "CANCELLED"
        for entry in result.timeline.log
    )
    for event_id in (
        "AURORA_Q_TWOFOLD_HEX_OUT_1",
        "AURORA_E_THE_WEIRDING",
        "AURORA_R_BETWEEN_WORLDS_IMPACT",
    ):
        assert any(
            entry.event_id == event_id and entry.operation == "DAMAGE" and entry.status == "APPLIED"
            for entry in result.timeline.log
        )


def test_aurora_item_policy_accepts_only_represented_channels() -> None:
    """Allow modeled stats while rejecting mana and sustain amplification."""
    aurora = _registry_with_aurora().require_cog("Aurora")

    assert (
        aurora.item_candidate_blocker(
            {
                "id": 1,
                "stats": {
                    "AP": {},
                    "ATTACK_SPEED": {},
                    "ABILITY_HASTE": {},
                    "HP": {},
                },
            }
        )
        is None
    )
    assert (
        aurora.item_candidate_blocker({"id": 2, "stats": {"HEAL_SHIELD_POWER": {}, "MANA": {}}})
        == "AURORA_ITEM_STAT_NOT_MODELED:2:MANA"
    )
