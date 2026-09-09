"""Focused regressions for the locked Cho'Gath champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES, ActionPlan
from lol_build.cogs.registry import create_default_registry
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, EntityId

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    chogath_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a role-neutral level-13 Cho'Gath-versus-Teemo context.

    :param chogath_is_actor: Place Cho'Gath on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Cho'Gath.
    :return: Role-bound deterministic benchmark context.
    """
    registry = create_default_registry(ROOT)
    chogath = registry.require_cog("Chogath")
    teemo = registry.require_cog("Teemo")
    return ParticipantContext(
        EntityId.ACTOR if chogath_is_actor else EntityId.TARGET,
        EntityId.TARGET if chogath_is_actor else EntityId.ACTOR,
        chogath.snapshot(level=13, item_stats=item_stats),
        teemo.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan: ActionPlan, event_id: str) -> ActionEvent:
    """Resolve one named event from a Cho'Gath action plan.

    :param plan: Action plan containing the expected event.
    :param event_id: Stable identifier of the requested action.
    :return: Matching immutable action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def _attacks(plan: ActionPlan) -> tuple[ActionEvent, ...]:
    """Select all ordinary and empowered Cho'Gath attacks.

    :param plan: Cho'Gath action plan containing attack events.
    :return: Chronological basic-attack-channel events.
    """
    return tuple(event for event in plan.events if event.channel is ActionChannel.BASIC_ATTACK)


def test_chogath_declares_modeled_capabilities_and_three_sources() -> None:
    """Distinguish Cho'Gath's implemented Cog from its former scaffold."""
    chogath = create_default_registry(ROOT).require_cog("Chogath")

    assert chogath.maturity is CogMaturity.MODELED_UNVERIFIED
    assert chogath.capabilities == DUEL_CAPABILITIES
    assert chogath.verification_blockers() == ("COG_MODEL_UNVERIFIED:Chogath",)
    assert chogath.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Chogath.json",
        "data/raw/16.17.1/communitydragon/champions/31.json",
        "data/raw/16.17.1/communitydragon/champions/chogath.bin.json",
    )
    assert all((ROOT / path).is_file() for path in chogath.evidence_refs)


def test_chogath_fixed_feast_stacks_change_health_and_spell_formulas() -> None:
    """Anchor six rank-two Feast stacks in health, E, and R calculations."""
    chogath = create_default_registry(ROOT).require_cog("Chogath")
    context = _context()
    unstacked_native = ChampionNativeHealth.for_level(chogath, 13)
    plan = chogath.build_action_plan(context)
    empowered = _event(plan, "CHOGATH_E_VORPAL_SPIKES_ATTACK_1")
    feast = _event(plan, "CHOGATH_R_FEAST")

    assert context.snapshot.max_hp - unstacked_native == 720
    assert context.snapshot.bonus_health == 720
    assert empowered.outputs[1].amount == (
        Decimal(110) + Decimal("0.069") * context.opponent_snapshot.max_hp
    )
    assert feast.outputs[0].amount == 547
    assert feast.outputs[0].damage_type is DamageType.TRUE
    assert "CHOGATH_FEAST_DYNAMIC_STACK_ACQUISITION_NOT_MODELED" in plan.blockers
    assert "CHOGATH_FEAST_EXECUTE_INDICATOR_NOT_MODELED" in plan.blockers


class ChampionNativeHealth:
    """Calculate native health without duplicating snapshot internals in tests."""

    @staticmethod
    def for_level(chogath, level: int) -> Decimal:
        """Return Cho'Gath's locked native maximum health at one level.

        :param chogath: Cho'Gath Cog supplying locked summary stats and growth.
        :param level: Champion level for nonlinear stat growth.
        :return: Native maximum health before Feast or item bonuses.
        """
        stats = chogath.document["stats"]
        return Decimal(str(stats["hp"])) + Decimal(str(stats["hpperlevel"])) * (
            chogath.growth_multiplier(level)
        )


def test_chogath_rotation_is_deterministic_and_uses_locked_spell_values() -> None:
    """Anchor Q5/W1/E5/R2 base values, coefficients, and timing policy."""
    chogath = create_default_registry(ROOT).require_cog("Chogath")
    context = _context(item_stats={"AP": Decimal(100)})

    first = chogath.build_action_plan(context)
    repeated = chogath.build_action_plan(context)
    rupture = _event(first, "CHOGATH_Q_RUPTURE_1")
    scream = _event(first, "CHOGATH_W_FERAL_SCREAM_1")
    feast = _event(first, "CHOGATH_R_FEAST")

    assert first == repeated
    assert first.model_id == "chogath_q5_w1_e5_r2_six_feast_stacks_level13_locked_v1"
    assert rupture.outputs[0].amount == 400
    assert scream.outputs[0].amount == 150
    assert feast.outputs[0].amount == 597
    assert tuple(
        event.at_ms for event in first.events if event.id.startswith("CHOGATH_Q_RUPTURE_")
    ) == (800, 6800)
    assert len(
        [event for event in first.events if event.id.startswith("CHOGATH_E_VORPAL_SPIKES_ATTACK_")]
    ) == 3


def test_chogath_ap_attack_speed_haste_and_health_are_causally_visible() -> None:
    """Prove all four requested item sensitivities reach distinct outputs."""
    chogath = create_default_registry(ROOT).require_cog("Chogath")
    baseline_context = _context()
    power_context = _context(item_stats={"AP": Decimal(100)})
    speed_context = _context(item_stats={"ATTACK_SPEED": Decimal("0.50")})
    haste_context = _context(item_stats={"ABILITY_HASTE": Decimal(50)})
    health_context = _context(item_stats={"HP": Decimal(500)})
    baseline = chogath.build_action_plan(baseline_context)
    power = chogath.build_action_plan(power_context)
    speed = chogath.build_action_plan(speed_context)
    haste = chogath.build_action_plan(haste_context)
    health = chogath.build_action_plan(health_context)

    assert (
        _event(power, "CHOGATH_Q_RUPTURE_1").outputs[0].amount
        - _event(baseline, "CHOGATH_Q_RUPTURE_1").outputs[0].amount
        == 100
    )
    assert len(_attacks(speed)) > len(_attacks(baseline))
    assert _event(haste, "CHOGATH_Q_RUPTURE_2").at_ms == 4800
    assert health_context.snapshot.max_hp - baseline_context.snapshot.max_hp == 500
    assert (
        _event(health, "CHOGATH_R_FEAST").outputs[0].amount
        - _event(baseline, "CHOGATH_R_FEAST").outputs[0].amount
        == 50
    )


def test_chogath_control_and_engagement_keep_cc_semantics_distinct() -> None:
    """Keep airborne non-reducible while silence and slows use tenacity."""
    chogath = create_default_registry(ROOT).require_cog("Chogath")
    context = _context()
    reaction = chogath.build_reaction_plan(context)
    knockup = next(window for window in reaction.cast_block_windows if "knockup" in window.id)
    silence = next(window for window in reaction.cast_block_windows if "silence" in window.id)
    slow = next(window for window in reaction.cast_block_windows if window.id.endswith("_slow"))

    assert knockup.control_type.value == "AIRBORNE"
    assert knockup.tenacity_reducible is False
    assert silence.control_type.value == "SILENCE"
    assert silence.blocked_channels == (ActionChannel.ABILITY,)
    assert silence.tenacity_reducible is True
    assert slow.control_type.value == "SLOW"
    assert slow.tenacity_reducible is True
    assert chogath.engagement_speed_multiplier(context) == 1
    assert chogath.engagement_dash_distance(context) == 950


def test_chogath_role_reversal_and_teemo_blind_preserve_channels() -> None:
    """Keep roles symmetric while blind cancels E attacks but not Feast."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Chogath", "Teemo"))
    as_opponent = engine.evaluate(MatchupRequest("Teemo", "Chogath"))

    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    assert any(
        entry.event_id.startswith("CHOGATH_E_VORPAL_SPIKES_ATTACK_")
        and entry.action_channel is ActionChannel.BASIC_ATTACK
        and entry.status == "CANCELLED"
        for entry in as_actor.timeline.log
    )
    assert any(
        entry.event_id == "CHOGATH_R_FEAST"
        and entry.operation == "DAMAGE"
        and entry.status == "APPLIED"
        for entry in as_actor.timeline.log
    )
    opponent_feast = next(
        entry
        for entry in as_opponent.timeline.log
        if entry.event_id == "CHOGATH_R_FEAST" and entry.operation == "DAMAGE"
    )
    assert opponent_feast.recipient is EntityId.ACTOR


def test_chogath_item_and_lane_sustain_policies_are_scope_honest() -> None:
    """Accept represented combat stats without inventing passive last hits."""
    chogath = create_default_registry(ROOT).require_cog("Chogath")
    context = _context()

    assert chogath.item_candidate_blocker(
        {
            "id": 1,
            "stats": {
                "AD": {},
                "AP": {},
                "ATTACK_SPEED": {},
                "ABILITY_HASTE": {},
                "HP": {},
            },
        }
    ) is None
    assert chogath.item_candidate_blocker(
        {"id": 2, "stats": {"HEAL_SHIELD_POWER": {}, "MANA": {}, "OMNIVAMP": {}}}
    ) == "CHOGATH_ITEM_STAT_NOT_MODELED:2:HEAL_SHIELD_POWER,MANA,OMNIVAMP"
    recovered, blockers = chogath.lane_sustain_extra_health(
        context,
        duration_ms=30000,
        no_damage_delay_ms=5000,
    )
    assert recovered == 0
    assert blockers == ("CHOGATH_LANE_PASSIVE_MINION_KILL_SCHEDULE_NOT_MODELED",)
