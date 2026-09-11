from decimal import Decimal
from pathlib import Path

from lol_build.application.cog_preview import (
    _heartsteel_bonus_health,
    _stage_noncombat_metrics,
    generic_cog_build_preview,
)
from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import (
    DariusCog,
    GarenCog,
    ParticipantContext,
    create_default_registry,
)
from lol_build.cogs.manifest import CHAMPION_COG_BY_KEY
from lol_build.core.timeline import DamageOutput, EntityId, MissingHealthDamageOutput
from lol_build.recommendation.selection import BranchId

ROOT = Path(__file__).resolve().parents[1]


def test_registry_resolves_every_champion_by_name_and_numeric_id() -> None:
    registry = create_default_registry(ROOT)
    registered = tuple(registry.walk_cogs())

    assert registry.require_cog("Darius") is registry.require_cog(122)
    assert registry.require_cog("ahri").champion_id == 103
    assert registry.require_cog("Aatrox").champion_id == 266
    assert isinstance(registry.require_cog("Darius"), DariusCog)
    assert isinstance(registry.require_cog("Garen"), GarenCog)
    assert registry.require_cog("Garen").snapshot(level=13).attack_damage > 100
    assert len(registered) == 173
    assert all(
        cog.__class__.__module__.startswith("lol_build.cogs.champions.") for cog in registered
    )
    assert all(cog.detail_root is not None for cog in registered)


def test_roles_are_request_scoped_not_cog_types() -> None:
    engine = MatchupEngine(ROOT)
    garen_attacks = engine.resolve(MatchupRequest("Garen", "Aatrox"))
    garen_defends = engine.resolve(MatchupRequest("Aatrox", "Garen"))

    assert garen_attacks.actor_cog == garen_defends.opponent_cog == "champion:Garen"
    assert garen_attacks.same_cog_contract is True
    assert garen_defends.same_cog_contract is True


def test_arbitrary_matchups_have_deterministic_structural_fallback() -> None:
    engine = MatchupEngine(ROOT)

    darius_ahri = engine.evaluate(
        MatchupRequest("Darius", "Ahri", actor_item_ids=(6631,), opponent_item_ids=(6657,))
    )
    garen_aatrox = engine.evaluate(
        MatchupRequest("Garen", "Aatrox", actor_item_ids=(6631,), opponent_item_ids=(3071,))
    )

    assert darius_ahri.resolved.actor_champion_id == 122
    assert darius_ahri.resolved.opponent_champion_id == 103
    assert garen_aatrox.resolved.actor_champion_id == 86
    assert garen_aatrox.resolved.opponent_champion_id == 266
    assert darius_ahri.actor_hp_lost > 0
    assert garen_aatrox.opponent_hp_lost > 0
    assert "AHRI_FORMULAS_CURATED_UNVERIFIED" in darius_ahri.blockers
    assert "GAREN_R_CAST_TIMING_UNVERIFIED" in garen_aatrox.blockers
    assert garen_aatrox.actor_action_model == "garen_q5_e5_r2_level13_synthetic_v1"
    assert garen_aatrox.actor_reaction_model == "garen_w_rank1_synthetic_v1"
    assert garen_aatrox.opponent_action_model == "aatrox_q5_w1_e5_r2_level13_synthetic_v1"
    assert garen_aatrox.opponent_reaction_model == "aatrox_q_sweetspot_reaction_v1"
    assert any(
        entry.event_id == "AATROX_Q1_SWEETSPOT" and entry.status == "CANCELLED"
        for entry in garen_aatrox.timeline.log
    )
    assert any(
        entry.event_id == "GAREN_E_TICK_1" and entry.status == "APPLIED"
        for entry in garen_aatrox.timeline.log
    )


def test_garen_reaction_follows_garen_to_either_side() -> None:
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Garen", "Aatrox"))
    as_opponent = engine.evaluate(MatchupRequest("Aatrox", "Garen"))

    assert as_actor.timeline.actor_at_end.shield >= 0
    assert as_opponent.timeline.target_at_end.shield >= 0
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    assert "GAREN_W_RANK1_TIMING_UNVERIFIED" in as_actor.blockers
    assert "GAREN_W_RANK1_TIMING_UNVERIFIED" in as_opponent.blockers


def test_garen_action_plan_contains_locked_q_e_and_missing_health_r_shapes() -> None:
    registry = create_default_registry(ROOT)
    garen = registry.require_cog("Garen")
    aatrox = registry.require_cog("Aatrox")
    plan = garen.build_action_plan(
        ParticipantContext(
            EntityId.ACTOR,
            EntityId.TARGET,
            garen.snapshot(level=13, item_stats={"ATTACK_SPEED": Decimal("0.25")}),
            aatrox.snapshot(level=13),
            8000,
            3000,
        )
    )

    q = next(event for event in plan.events if event.id == "GAREN_Q_STRIKE")
    r = next(event for event in plan.events if event.id == "GAREN_R_DEMACIAN_JUSTICE")
    assert isinstance(q.outputs[0], DamageOutput)
    assert sum(event.id.startswith("GAREN_E_TICK") for event in plan.events) >= 8
    assert isinstance(r.outputs[0], MissingHealthDamageOutput)

    no_crit = garen.build_action_plan(
        ParticipantContext(
            EntityId.ACTOR,
            EntityId.TARGET,
            garen.snapshot(level=13),
            aatrox.snapshot(level=13),
            8000,
            3000,
        )
    )
    assert sum(
        event.outputs[0].amount for event in plan.events if event.id.startswith("GAREN_E_TICK")
    ) > sum(
        event.outputs[0].amount for event in no_crit.events if event.id.startswith("GAREN_E_TICK")
    )


def test_specialized_recommendation_capability_belongs_to_actor_cog() -> None:
    engine = MatchupEngine(ROOT)

    assert engine.resolve(MatchupRequest("Darius", "Garen")).specialized_recommendation_available
    assert engine.resolve(MatchupRequest("Darius", "Ahri")).specialized_recommendation_available
    assert engine.resolve(MatchupRequest("Garen", "Aatrox")).specialized_recommendation_available
    assert engine.resolve(MatchupRequest("Aatrox", "Garen")).specialized_recommendation_available

    fallback = generic_cog_build_preview(
        engine,
        MatchupRequest("Aatrox", "Garen"),
    )
    assert fallback.actor_cog == "champion:Aatrox"
    assert fallback.release_eligible is False


def test_garen_action_cog_drives_bounded_three_core_preview() -> None:
    engine = MatchupEngine(ROOT)
    progress: list[str] = []
    preview = generic_cog_build_preview(
        engine,
        MatchupRequest("Garen", "Aatrox", opponent_item_ids=(3071, 3053, 6333)),
        progress=progress.append,
    )

    assert preview.actor_cog == "champion:Garen"
    assert preview.opponent_cog == "champion:Aatrox"
    assert {branch.value for branch in preview.branches} == {
        "DEFAULT",
        "OFFENSE",
        "DEFENSE",
    }
    assert all(len(branch.item_ids) == 3 for branch in preview.branches.values())
    assert preview.evaluated_candidate_count > 100
    assert preview.release_eligible is False
    assert preview.state.outcome.value == "FOUND"
    assert preview.state.verification.value == "INSUFFICIENT_VERIFICATION"
    assert preview.state.scope.value == "IN_SCOPE"
    assert preview.assumptions.game_state == "NOT_MODELED"
    assert preview.assumptions.level_assumption == "EQUAL_LEVEL_13"
    assert preview.scope.actor_champion_id == 86
    assert preview.scope.max_core_count == 3
    assert {message.split(" ", 1)[0] for message in progress} >= {
        "2/7",
        "3/7",
        "4/7",
        "5/7",
        "6/7",
    }
    assert all(
        {
            "ENGAGE_COMBAT_UPTIME_FRACTION",
            "LANE_RECOVERED_HP_30S",
            "MIXED_EFFECTIVE_HEALTH",
            "CORE_COMPLETION_GOLD_WEIGHTED",
            "HEARTSTEEL_PROC_COUNT",
        }
        <= branch.metrics.keys()
        for branch in preview.branches.values()
    )
    assert all(
        tuple(contribution.item_id for contribution in branch.explanation.item_contributions)
        == branch.item_ids
        for branch in preview.branches.values()
    )
    assert preview.branches[BranchId.DEFAULT].explanation.reason_codes == (
        "BALANCED_CHASSIS_GATED_DAMAGE_PRIORITY",
    )
    assert "PRIMARY_DAMAGE_FLOOR_PASSED" in (
        preview.branches[BranchId.DEFENSE].explanation.satisfied_constraints
    )
    assert preview.branches[BranchId.OFFENSE].explanation.metric_comparisons


def test_generic_preview_is_deterministic_for_arbitrary_role_order() -> None:
    """Keep repeated searches stable and allow the former opponent to be actor."""
    engine = MatchupEngine(ROOT)
    request = MatchupRequest(
        "Aatrox",
        "Garen",
        actor_item_ids=(),
        opponent_item_ids=(6631, 3046, 3742),
    )

    first = generic_cog_build_preview(engine, request)
    second = generic_cog_build_preview(engine, request)

    assert first == second
    assert first.actor_cog == "champion:Aatrox"
    assert first.opponent_cog == "champion:Garen"


def test_generic_preview_falls_back_instead_of_dropping_an_infeasible_defense_branch() -> None:
    """DEFENSE degrades like DEFAULT rather than vanishing when no candidate clears its floor.

    Dropping the branch outright is a worse failure than ranking without a
    gate the search proved unreachable — the same reasoning DEFAULT already
    applies when no candidate meets its own chassis gate. The two gates
    (chassis readiness, then the damage-loss floor) fall back independently,
    so this covers both: Aatrox-versus-Ahri fails chassis readiness outright
    (a melee actor cannot reliably reach a kiting target under the default
    ``uncorrelated`` active-duty policy), while Darius-versus-Garen clears
    chassis but, forced to a zero-loss damage floor, clears no candidate on
    that second gate.
    """
    engine = MatchupEngine(ROOT)

    no_chassis = generic_cog_build_preview(
        engine,
        MatchupRequest("Aatrox", "Ahri"),
        defense_max_primary_loss_fraction=Decimal(0),
    )
    assert BranchId.DEFENSE in no_chassis.branches
    assert no_chassis.branches[BranchId.DEFENSE].explanation.reason_codes == (
        "DEFENSE_FALLBACK_NO_FULL_CHASSIS",
    )
    assert "PRIMARY_DAMAGE_FLOOR_PASSED" not in (
        no_chassis.branches[BranchId.DEFENSE].explanation.satisfied_constraints
    )
    assert "NO_CANDIDATE_MEETS_ALL_CORE_CHASSIS_FLOORS" in no_chassis.blockers

    no_damage_floor = generic_cog_build_preview(
        engine,
        MatchupRequest("Darius", "Garen"),
        defense_max_primary_loss_fraction=Decimal(0),
    )
    assert BranchId.DEFENSE in no_damage_floor.branches
    assert no_damage_floor.branches[BranchId.DEFENSE].explanation.reason_codes == (
        "DEFENSE_FALLBACK_NO_DAMAGE_FLOOR_MET",
    )
    assert "PRIMARY_DAMAGE_FLOOR_PASSED" not in (
        no_damage_floor.branches[BranchId.DEFENSE].explanation.satisfied_constraints
    )
    assert "NO_CANDIDATE_MEETS_DEFENSE_DAMAGE_FLOOR" in no_damage_floor.blockers


def test_slot_runner_up_names_the_best_gate_failing_alternative_and_why() -> None:
    """A slot with no gate-passing runner-up still names its closest miss.

    Dead Man's Plate's DEFENSE slot in the Darius-versus-Garen matchup has no
    legal, gate-passing alternative (``alternative_count == 0``), but Warmog's
    Armor is the single best legal item that failed the gate — its passive
    never activates within the fixed-length duel, which the reason code names
    explicitly instead of leaving the UI with a bare "no alternative".
    """
    engine = MatchupEngine(ROOT)
    preview = generic_cog_build_preview(engine, MatchupRequest("Darius", "Garen"))

    defense = preview.branches[BranchId.DEFENSE]
    dead_mans_plate = next(
        contribution
        for contribution in defense.explanation.item_contributions
        if contribution.item_id == 3742
    )
    runner_up = dead_mans_plate.slot_runner_up
    assert runner_up.item_id is None
    assert runner_up.alternative_count == 0
    assert runner_up.legal_alternative_count > 0
    assert runner_up.excluded_item_id == 3083  # Warmog's Armor
    assert runner_up.excluded_reason_codes == ("ALL_CORE_ITEM_PASSIVES_READY_NOT_MET",)
    assert runner_up.excluded_metric_comparisons


def test_item_actives_and_on_hits_follow_owner_to_either_role() -> None:
    engine = MatchupEngine(ROOT)
    stride_actor = engine.evaluate(MatchupRequest("Garen", "Aatrox", actor_item_ids=(6631,)))
    stride_target = engine.evaluate(MatchupRequest("Aatrox", "Garen", opponent_item_ids=(6631,)))

    actor_proc = next(
        entry
        for entry in stride_actor.timeline.log
        if entry.event_id == "stridebreaker_breaking_shockwave" and entry.operation == "DAMAGE"
    )
    target_proc = next(
        entry
        for entry in stride_target.timeline.log
        if entry.event_id == "stridebreaker_breaking_shockwave" and entry.operation == "DAMAGE"
    )
    assert actor_proc.recipient is EntityId.TARGET
    assert target_proc.recipient is EntityId.ACTOR
    assert "GENERIC_ITEM_PASSIVES_NOT_EVALUATED" not in stride_actor.blockers

    spellblade = engine.evaluate(MatchupRequest("Garen", "Aatrox", actor_item_ids=(3078,)))
    assert any(
        entry.event_id == "trinity_force_spellblade" and entry.operation == "DAMAGE"
        for entry in spellblade.timeline.log
    )


def test_always_item_stat_programs_contribute_to_generic_snapshot() -> None:
    engine = MatchupEngine(ROOT)
    without_sterak = engine.evaluate(MatchupRequest("Garen", "Aatrox"))
    with_sterak = engine.evaluate(MatchupRequest("Garen", "Aatrox", actor_item_ids=(3053,)))

    assert (
        with_sterak.timeline.actor_at_end.current_hp
        > without_sterak.timeline.actor_at_end.current_hp
    )
    q_without = next(
        entry
        for entry in without_sterak.timeline.log
        if entry.event_id == "GAREN_Q_STRIKE" and entry.operation == "DAMAGE"
    )
    q_with = next(
        entry
        for entry in with_sterak.timeline.log
        if entry.event_id == "GAREN_Q_STRIKE" and entry.operation == "DAMAGE"
    )
    assert q_with.raw_amount > q_without.raw_amount

    ahri_plain = engine.evaluate(MatchupRequest("Ahri", "Darius"))
    ahri_deathcap = engine.evaluate(MatchupRequest("Ahri", "Darius", actor_item_ids=(3089,)))
    plain_q = next(
        entry for entry in ahri_plain.timeline.log if entry.event_id == "AHRI_Q_OUTBOUND"
    )
    deathcap_q = next(
        entry for entry in ahri_deathcap.timeline.log if entry.event_id == "AHRI_Q_OUTBOUND"
    )
    assert deathcap_q.raw_amount > plain_q.raw_amount


def test_enemy_attack_speed_aura_changes_opponent_action_schedule() -> None:
    engine = MatchupEngine(ROOT)
    baseline = engine.evaluate(MatchupRequest("Garen", "Jax"))
    frozen_heart = engine.evaluate(MatchupRequest("Garen", "Jax", actor_item_ids=(3110,)))

    def jax_attacks(result):
        return sum(entry.event_id.startswith("JAX_GENERIC_ATTACK") for entry in result.timeline.log)

    assert jax_attacks(frozen_heart) < jax_attacks(baseline)


def test_mercurys_treads_reduce_ahri_charm_duration_on_opponent() -> None:
    engine = MatchupEngine(ROOT)
    plain = engine.evaluate(MatchupRequest("Ahri", "Jax", opponent_item_ids=(3046,)))
    mercs = engine.evaluate(MatchupRequest("Ahri", "Jax", opponent_item_ids=(3046, 3111)))

    def charm_end(result):
        entry = next(
            item
            for item in result.timeline.log
            if item.event_id == "AHRI_E_CHARM" and item.operation == "STATUS"
        )
        return int(entry.detail.split(":")[1])

    assert charm_end(mercs) < charm_end(plain)
    assert (
        next(
            entry for entry in plain.timeline.log if entry.event_id == "JAX_GENERIC_ATTACK_10001"
        ).status
        == "CANCELLED"
    )
    assert (
        next(
            entry for entry in mercs.timeline.log if entry.event_id == "JAX_GENERIC_ATTACK_10001"
        ).operation
        == "DAMAGE"
    )


def test_dead_mans_plate_reduces_slow_magnitude_not_duration() -> None:
    """Connect the normalized slow-resistance stat to role-symmetric item events."""
    engine = MatchupEngine(ROOT)
    result = engine.evaluate(MatchupRequest("Darius", "Garen", opponent_item_ids=(3742,)))
    slow = next(
        entry
        for entry in result.timeline.log
        if entry.event_id == "DARIUS_W_SLOW" and entry.operation == "STATUS"
    )

    assert slow.detail == "CC_SLOW:1450:magnitude=0.7650"


def test_heartsteel_order_and_warmog_readiness_are_core_scoped() -> None:
    engine = MatchupEngine(ROOT)
    request = MatchupRequest("Garen", "Aatrox", opponent_item_ids=(3071, 3053, 6333))
    late_count, late_health = _heartsteel_bonus_health(engine, request, (3083, 3084), 2)
    early_count, early_health = _heartsteel_bonus_health(engine, request, (3084, 3083), 2)
    warmog_first = _stage_noncombat_metrics(engine, request, (3083,), (3071,), Decimal(0), 1)
    heartsteel_then_warmog = _stage_noncombat_metrics(
        engine, request, (3084, 3083), (3071, 3053), early_health, 2
    )

    assert early_count > late_count
    assert early_health > late_health
    assert warmog_first["item_ready"] is False
    assert heartsteel_then_warmog["item_ready"] is True


def test_a_new_capability_is_never_granted_by_declaring_the_whole_enum() -> None:
    """Keep capabilities that need their own evidence out of the duel default.

    Champion Cogs used to declare the whole capability enum, so adding a member
    to it handed that behavior to every Cog at once. A capability like
    MULTI_TARGET must be claimed by the Cogs that implement it.
    """
    from lol_build.cogs.base import DUEL_CAPABILITIES, CogCapability, CogMaturity

    assert CogCapability.MULTI_TARGET not in DUEL_CAPABILITIES
    # The duel set plus the excluded capability must still cover the enum, so a
    # capability added later cannot slip into the default unnoticed.
    assert DUEL_CAPABILITIES | {CogCapability.MULTI_TARGET} == set(CogCapability)

    # Which Cogs legitimately claim MULTI_TARGET is asserted in
    # tests/test_multi_target.py; this guard only fixes how it can be obtained.
    registry = create_default_registry(ROOT)
    scaffolded = [
        key
        for key in CHAMPION_COG_BY_KEY
        if registry.require_cog(key).maturity is CogMaturity.SCAFFOLDED
        and registry.require_cog(key).has_capability(CogCapability.MULTI_TARGET)
    ]
    # A Cog with no modeled rotation cannot have widened one.
    assert scaffolded == []


def test_nothing_declares_or_asserts_the_capability_enum_wholesale() -> None:
    """Fail if declaring the whole capability enum returns, in sources or tests.

    The idiom lived in both places: Cogs claimed every capability, and the tests
    asserted that they should. Guarding only the sources would leave the tests
    demanding behavior the sources are no longer allowed to have.
    """
    # Assembled at runtime so this file does not match its own search.
    needle = "frozenset(" + "CogCapability)"
    searched = [
        *(ROOT / "src/lol_build").rglob("*.py"),
        *(ROOT / "tests").glob("*.py"),
    ]
    offenders = sorted(
        str(path.relative_to(ROOT))
        for path in searched
        # base.py defines the duel set by subtraction and is the one legitimate use.
        if path.name != "base.py" and needle in path.read_text(encoding="utf-8")
    )

    assert offenders == []
