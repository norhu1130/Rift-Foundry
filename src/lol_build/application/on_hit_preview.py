"""Non-release synthetic end-to-end preview of the recommendation pipeline."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from lol_build.core.canonical import dumps
from lol_build.core.combat import DamageMix, calculate_effective_health
from lol_build.core.expression import EvaluationContext, evaluate
from lol_build.core.timeline import Combatant, EntityId
from lol_build.items.candidates import ResourceType, generate_build_candidates
from lol_build.recommendation.provenance import (
    EvidenceKind,
    ExplanationEvidence,
    MechanicDependency,
    NumericEvidence,
    RecommendationProvenance,
    build_recommendation_provenance,
)
from lol_build.recommendation.readiness import RecommendationStatus, readiness_document
from lol_build.recommendation.selection import (
    BranchId,
    EvaluatedCandidate,
    SelectionPolicy,
    select_three_branches,
)
from lol_build.simulation.on_hit import (
    BlindWindow,
    MissStackPolicy,
    SustainedOnHitSpec,
    simulate_sustained_on_hit_rotation,
)


class SyntheticPreviewError(ValueError):
    """Raised when synthetic assumptions cannot produce a safe preview."""


@dataclass(frozen=True)
class PreviewBranch:
    """Expose one selected branch with metrics and ordered item IDs."""

    branch: BranchId
    candidate_id: str
    item_ids: tuple[int, ...]
    metrics: Mapping[str, Decimal]
    kill_threshold_met: bool
    provenance: RecommendationProvenance


@dataclass(frozen=True)
class SyntheticPreview:
    """Contain a synthetic recommendation, provenance, and release status."""

    recommendation_status: RecommendationStatus
    preview_kind: str
    release_eligible: bool
    blockers: tuple[str, ...]
    branches: Mapping[BranchId, PreviewBranch]
    variant_branch_item_ids: Mapping[MissStackPolicy, Mapping[BranchId, tuple[int, ...]]]
    stable_across_miss_stack_policies: bool


_MAXIMIZE = (
    "DAMAGE_TOTAL_8S",
    "DAMAGE_FIRST_3S",
    "PHYSICAL_EHP",
    "MAGICAL_EHP",
    "CC_ADJUSTED_UPTIME",
    "MIXED_DAMAGE_EHP",
)
_MINIMIZE = ("TOTAL_GOLD", "OCCUPIED_SLOTS")


def _decimal_map(document: Mapping[str, Any]) -> dict[str, Decimal]:
    """Convert raw numeric mappings into Decimal mappings.

    :param document: Parsed JSON document to validate or transform.
    :return: Mapping with every numeric value converted to ``Decimal``.
    """

    return {key: Decimal(value) for key, value in document.items()}


def _growth_multiplier(level: int) -> Decimal:
    """Calculate Riot's nonlinear champion growth multiplier.

    :param level: Champion level used for growth and level-scaled mechanics.
    :return: Cumulative level-growth multiplier for the requested level.
    """

    levels = Decimal(level - 1)
    return levels * (Decimal("0.7025") + Decimal("0.0175") * levels)


def _base_value(root_record: Mapping[str, Any], key: str) -> Decimal:
    """Read a champion base stat from the locked detail snapshot.

    :param root_record: Locked CommunityDragon record containing champion spell data.
    :param key: CommunityDragon base-stat field to read.
    :return: Exact base-stat value stored in the field.
    """

    return Decimal(str(root_record[key]["baseValue"]))


def _ability(profile: Mapping[str, Any], ability_id: str) -> Mapping[str, Any]:
    """Resolve one spell record from the locked champion snapshot.

    :param profile: Mechanic-keyed champion profile document.
    :param ability_id: Curated spell ID to locate in the champion profile.
    :return: The spell record whose stable ID equals ``ability_id``.
    """

    return next(ability for ability in profile["abilities"] if ability["id"] == ability_id)


def _rank_value(ability: Mapping[str, Any], field: str, rank: int) -> Decimal:
    """Read one spell value from a rank-indexed array.

    :param ability: Resolved spell record from which rank data is read.
    :param field: Rank-indexed spell field, such as base damage or cooldown.
    :param rank: One-based spell rank whose value is required.
    :return: Exact value at the one-based spell rank.
    """

    return Decimal(ability[field][rank - 1])


def _scaling(ability: Mapping[str, Any], stat: str) -> Decimal:
    """Apply a spell's base value and stat coefficient.

    :param ability: Resolved spell record from which rank data is read.
    :param stat: Normalized stat key referenced by the formula.
    :return: Coefficient attached to the requested scaling stat.
    """

    coefficient = next(
        value["coefficient"] for value in ability["scalings"] if value["stat"] == stat
    )
    return Decimal(coefficient)


def _prefix_metrics(
    items: tuple[Mapping[str, Any], ...],
    assumptions: Mapping[str, Any],
    *,
    miss_stack_policy: MissStackPolicy,
    champion_profile: Mapping[str, Any],
    champion_root: Mapping[str, Any],
    scenario: Mapping[str, Any],
) -> dict[str, Decimal]:
    """Evaluate combat and readiness metrics for each build prefix.

    :param items: Build prefix whose combat metrics are evaluated.
    :param assumptions: Explicit scenario constants used instead of inferred game state.
    :param miss_stack_policy: Rule deciding whether a blinded attack advances on-hit stacks.
    :param champion_profile: Mechanic-keyed champion profile checked for release readiness.
    :param champion_root: Locked detailed champion record used for base and growth stats.
    :param scenario: Validated encounter assumptions governing the calculation.
    :return: Damage, effective-health, uptime, and mixed-defense metrics for the prefix.
    """

    context = EvaluationContext(self_level=13, target_level=13, stats={})
    stats: dict[str, Decimal] = {}
    for item in items:
        for stat, expression in item["stats"].items():
            stats[stat] = stats.get(stat, Decimal(0)) + evaluate(expression, context)

    level = champion_profile["level_profile"]["level"]
    growth = _growth_multiplier(level)
    total_ap = stats.get("AP", Decimal(0))
    total_ad = (
        _base_value(champion_root, "baseDamageModifiable")
        + _base_value(champion_root, "damagePerLevelModifiable") * growth
        + stats.get("AD", Decimal(0))
    )
    actor_hp = (
        _base_value(champion_root, "baseHPModifiable")
        + _base_value(champion_root, "hpPerLevelModifiable") * growth
        + stats.get("HP", Decimal(0))
    )
    actor_armor = (
        _base_value(champion_root, "baseArmorModifiable")
        + _base_value(champion_root, "armorPerLevelModifiable") * growth
        + stats.get("ARMOR", Decimal(0))
    )
    actor_mr = Decimal("32") + Decimal("2.05") * growth + stats.get("MAGIC_RESISTANCE", Decimal(0))

    expression_context = EvaluationContext(
        level,
        13,
        {
            ("SELF", "TOTAL", "AP"): total_ap,
            ("TARGET", "CURRENT", "HP"): Decimal(scenario["target"]["stat_snapshot"]["max_hp"]),
        },
    )
    on_hit_magic = sum(
        (
            evaluate(effect["value_expression"], expression_context)
            for item in items
            for effect in item["effects"]
            if effect["trigger"] == "BASIC_ATTACK_HIT"
            and effect["operation"] == "DEAL_MAGIC_DAMAGE"
        ),
        Decimal(0),
    )

    ranks = champion_profile["level_profile"]["spell_ranks"]
    w = _ability(champion_profile, "W_DAMAGE")
    e = _ability(champion_profile, "E_DAMAGE")
    r = _ability(champion_profile, "R_PASSIVE_DAMAGE")
    passive_spell = champion_root["__passive_spell"]
    passive_calculation = passive_spell["mSpellCalculations"]["AttackSpeedPerStack"]
    passive_part = passive_calculation["mFormulaParts"][0]
    passive_per_stack = Decimal(str(passive_part["mLevel1Value"])) + sum(
        Decimal(str(breakpoint.get("mAdditionalBonusAtThisLevel", 0)))
        for breakpoint in passive_part["mBreakpoints"]
        if breakpoint["mLevel"] <= level
    )

    mix = _decimal_map(assumptions["damage_mix"])
    ehp = calculate_effective_health(
        actor_hp,
        armor=actor_armor,
        magic_resistance=actor_mr,
        damage_mix=DamageMix(mix["physical"], mix["magical"], mix["true"]),
    )

    tenacity_sources = [
        evaluate(item["stats"]["TENACITY"], context)
        for item in items
        if "TENACITY" in item["stats"]
    ]
    if len(tenacity_sources) > 1:
        raise SyntheticPreviewError("synthetic preview supports one tenacity source only")
    tenacity = tenacity_sources[0] if tenacity_sources else Decimal(0)
    cc_document = assumptions["cc_formula"]
    encounter_duration = Decimal(cc_document["encounter_duration_ms"])
    blind_base_duration = Decimal(cc_document["blind_base_duration_ms"])
    adjusted_blind = blind_base_duration * (Decimal(1) - tenacity)
    uptime = (encounter_duration - adjusted_blind) / encounter_duration
    target_snapshot = scenario["target"]["stat_snapshot"]
    target = Combatant(
        EntityId.TARGET,
        Decimal(target_snapshot["max_hp"]),
        Decimal(target_snapshot["max_hp"]),
        Decimal(target_snapshot["armor"]),
        Decimal(target_snapshot["magic_resistance"]),
    )
    actor_combatant = Combatant(
        EntityId.ACTOR,
        actor_hp,
        actor_hp,
        actor_armor,
        actor_mr,
    )
    spec = SustainedOnHitSpec(
        duration_ms=int(encounter_duration),
        horizon_ms=3000,
        base_attack_speed=_base_value(champion_root, "attackSpeedModifiable"),
        attack_speed_ratio=_base_value(champion_root, "attackSpeedRatioModifiable"),
        bonus_attack_speed=(
            _base_value(champion_root, "attackSpeedPerLevelModifiable") * growth / Decimal(100)
            + stats.get("ATTACK_SPEED", Decimal(0))
        ),
        passive_attack_speed_per_stack=passive_per_stack,
        passive_max_stacks=8,
        total_attack_damage=total_ad,
        total_ability_power=total_ap,
        ability_haste=stats.get("ABILITY_HASTE", Decimal(0)),
        reset_first_at_ms=assumptions["rotation_timing"]["reset_first_at_ms"],
        reset_base_cooldown_seconds=_rank_value(w, "cooldown_seconds_by_rank", ranks["W"]),
        reset_magic_base_damage=_rank_value(w, "base_damage_by_rank", ranks["W"]),
        reset_ap_ratio=_scaling(w, "AP"),
        once_at_ms=assumptions["rotation_timing"]["once_at_ms"],
        once_magic_base_damage=_rank_value(e, "base_damage_by_rank", ranks["E"]),
        once_ap_ratio=_scaling(e, "AP"),
        once_target_max_hp_ratio=_scaling(e, "TARGET_MAX_HP"),
        nth_hit=3,
        nth_magic_base_damage=_rank_value(r, "base_damage_by_rank", ranks["R"]),
        nth_ap_ratio=_scaling(r, "AP"),
        on_hit_magic_base_damage=on_hit_magic,
    )
    rotation = simulate_sustained_on_hit_rotation(
        spec=spec,
        blind=BlindWindow(1000, 1000 + int(adjusted_blind)),
        miss_stack_policy=miss_stack_policy,
        actor=actor_combatant,
        target=target,
    )
    return {
        "DAMAGE_TOTAL_8S": rotation.timeline.damage_to_target_total,
        "DAMAGE_FIRST_3S": rotation.timeline.damage_to_target_first_horizon,
        "PHYSICAL_EHP": ehp.physical_ehp,
        "MAGICAL_EHP": ehp.magical_ehp,
        "CC_ADJUSTED_UPTIME": uptime,
        "MIXED_DAMAGE_EHP": ehp.mixed_ehp,
    }


def _evaluate_paths(
    items_by_id: Mapping[int, Mapping[str, Any]],
    paths: tuple[tuple[int, ...], ...],
    assumptions: Mapping[str, Any],
    *,
    miss_stack_policy: MissStackPolicy,
    champion_profile: Mapping[str, Any],
    champion_root: Mapping[str, Any],
    scenario: Mapping[str, Any],
) -> tuple[EvaluatedCandidate, ...]:
    """Evaluate paths.

    :param items_by_id: Curated item records indexed by Riot item ID.
    :param paths: Validated source paths whose evidence state must be combined.
    :param assumptions: Explicit scenario constants used instead of inferred game state.
    :param miss_stack_policy: Rule deciding whether a blinded attack advances on-hit stacks.
    :param champion_profile: Mechanic-keyed champion profile checked for release readiness.
    :param champion_root: Locked detailed champion record used for base and growth stats.
    :param scenario: Validated encounter assumptions governing the calculation.
    :return: Candidate records containing averaged prefix metrics and threshold status.
    """

    evaluated = []
    threshold = Decimal(assumptions["target"]["kill_threshold_hp"])
    for item_ids in paths:
        aggregate = {metric: Decimal(0) for metric in _MAXIMIZE}
        final_prefix: dict[str, Decimal] | None = None
        for core in range(1, len(item_ids) + 1):
            prefix = tuple(items_by_id[item_id] for item_id in item_ids[:core])
            final_prefix = _prefix_metrics(
                prefix,
                assumptions,
                miss_stack_policy=miss_stack_policy,
                champion_profile=champion_profile,
                champion_root=champion_root,
                scenario=scenario,
            )
            for metric in _MAXIMIZE:
                aggregate[metric] += final_prefix[metric]
        assert final_prefix is not None
        for metric in _MAXIMIZE:
            aggregate[metric] /= Decimal(len(item_ids))
        total_gold = sum(items_by_id[item_id]["cost"]["total"] for item_id in item_ids)
        aggregate["TOTAL_GOLD"] = Decimal(total_gold)
        aggregate["OCCUPIED_SLOTS"] = Decimal(len(item_ids))
        evaluated.append(
            EvaluatedCandidate(
                id="-".join(map(str, item_ids)),
                item_ids=item_ids,
                metrics=aggregate,
                kill_threshold_met=final_prefix["DAMAGE_FIRST_3S"] >= threshold,
                total_gold=total_gold,
                occupied_slots=len(item_ids),
            )
        )
    return tuple(evaluated)


def _provenance(
    branch: BranchId,
    candidate: EvaluatedCandidate,
    assumptions: Mapping[str, Any],
) -> RecommendationProvenance:
    """Assemble evidence provenance for a generated recommendation.

    :param branch: Recommendation branch being constructed or labeled.
    :param candidate: Evaluated build candidate under comparison.
    :param assumptions: Explicit scenario constants used instead of inferred game state.
    :return: Evidence record linking branch metrics to locked and synthetic inputs.
    """

    input_refs = (
        f"synthetic:{assumptions['id']}",
        f"candidate:{candidate.id}",
    )
    numbers = tuple(
        NumericEvidence(
            metric,
            value,
            EvidenceKind.CALCULATED,
            formula_ref=f"calculated.rotation_path_prefix_mean.{metric.lower()}.v1",
            input_refs=input_refs,
        )
        for metric, value in candidate.metrics.items()
    )
    return build_recommendation_provenance(
        recommendation_id=f"{branch.value}:{candidate.id}",
        game_patch=assumptions["game_patch"],
        patch_lock_ref="patch.lock.json",
        scenario_ref=assumptions["scenario_ref"],
        candidate_ref=candidate.id,
        item_ids=candidate.item_ids,
        source_file_refs=tuple(
            f"data/curated/items/{item_id}.json" for item_id in candidate.item_ids
        )
        + (
            "data/curated/champions/24.json",
            "data/raw/16.17.1/en_US/champion/Jax.json",
            "data/raw/16.17.1/communitydragon/champions/jax.bin.json",
            "fixtures/scenarios/duel_jax_l13_8s_vs_teemo_blind_v1.json",
            "fixtures/synthetic/duel_jax_l13_8s_preview_v1.json",
        ),
        numeric_evidence=numbers,
        explanation_evidence=(
            ExplanationEvidence(
                "synthetic-preview-warning",
                "합성 가정으로 선택한 구조 검증용 분기이며 실제 추천이 아니다.",
                EvidenceKind.UNVERIFIED,
                blockers=tuple(assumptions["blockers"]),
            ),
        ),
        mechanic_dependencies=(MechanicDependency("cc_blind_v1", "UNVERIFIED", ()),),
    )


def synthetic_preview_document(root: Path) -> SyntheticPreview:
    """Build the canonical generic preview document.

    :param root: Project root containing locked data and curated records.
    :return: Non-release preview with selected branches, evidence, and readiness blockers.
    """

    assumptions = json.loads(
        (root / "fixtures/synthetic/duel_jax_l13_8s_preview_v1.json").read_text()
    )
    items = tuple(
        json.loads((root / f"data/curated/items/{item_id}.json").read_text())
        for item_id in assumptions["item_ids"]
    )
    items_by_id = {item["id"]: item for item in items}
    champion_profile = json.loads((root / "data/curated/champions/24.json").read_text())
    raw_champion = json.loads(
        (root / "data/raw/16.17.1/communitydragon/champions/jax.bin.json").read_text()
    )
    champion_root = dict(raw_champion["Characters/Jax/CharacterRecords/Root"])
    champion_root["__passive_spell"] = raw_champion[
        "Characters/Jax/Spells/JaxPassiveAbility/JaxPassive"
    ]["mSpell"]
    scenario = json.loads(
        (root / "fixtures/scenarios/duel_jax_l13_8s_vs_teemo_blind_v1.json").read_text()
    )
    generated = generate_build_candidates(
        items=items,
        allowed_item_ids=set(assumptions["item_ids"]),
        expected_patch=assumptions["game_patch"],
        budgets_by_core={
            int(core): budget for core, budget in assumptions["budgets_by_core"].items()
        },
        resource=ResourceType.MANA,
        evaluation_context=EvaluationContext(13, 13, {}),
        range_class="MELEE",
    )
    paths = tuple(candidate.item_ids for candidate in generated.candidates_by_core[3])
    metrics = _MAXIMIZE + _MINIMIZE
    policy = SelectionPolicy(
        maximize=_MAXIMIZE,
        minimize=_MINIMIZE,
        epsilons={metric: Decimal(0) for metric in metrics},
        primary_metric="DAMAGE_TOTAL_8S",
        offense_metric="DAMAGE_TOTAL_8S",
        defense_metric="MIXED_DAMAGE_EHP",
        kill_fallback_metric="DAMAGE_FIRST_3S",
        defense_max_primary_loss_fraction=Decimal(
            assumptions["selection"]["defense_max_primary_loss_fraction"]
        ),
    )
    selections = {}
    for miss_policy in MissStackPolicy:
        evaluated = _evaluate_paths(
            items_by_id,
            paths,
            assumptions,
            miss_stack_policy=miss_policy,
            champion_profile=champion_profile,
            champion_root=champion_root,
            scenario=scenario,
        )
        selections[miss_policy] = select_three_branches(evaluated, policy)
    selected = selections[MissStackPolicy.DOES_NOT_GRANT_STACK]
    branches = {}
    for branch, selection in selected.branches.items():
        candidate = selection.selected
        branches[branch] = PreviewBranch(
            branch,
            candidate.id,
            candidate.item_ids,
            candidate.metrics,
            candidate.kill_threshold_met,
            _provenance(branch, candidate, assumptions),
        )

    readiness = readiness_document(root, item_ids=set(assumptions["item_ids"]))
    blockers = tuple(
        sorted(
            set(assumptions["blockers"])
            | {f"{blocker.code}:{blocker.ref}" for blocker in readiness.blockers}
        )
    )
    variant_branch_item_ids = {
        miss_policy: {
            branch: selection.selected.item_ids for branch, selection in result.branches.items()
        }
        for miss_policy, result in selections.items()
    }
    stable = (
        len(
            {
                tuple(variant_branch_item_ids[miss_policy][branch] for branch in BranchId)
                for miss_policy in MissStackPolicy
            }
        )
        == 1
    )
    return SyntheticPreview(
        RecommendationStatus.INSUFFICIENT_EVIDENCE,
        "SYNTHETIC_NON_RELEASE",
        False,
        blockers,
        branches,
        variant_branch_item_ids,
        stable,
    )


def main() -> None:
    """Run the module command-line interface.

    :return: None.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    print(dumps(asdict(synthetic_preview_document(args.root.resolve()))))


if __name__ == "__main__":
    main()
