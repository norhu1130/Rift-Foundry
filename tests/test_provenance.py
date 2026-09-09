from dataclasses import asdict
from decimal import Decimal

import pytest

from lol_build.core.canonical import dumps
from lol_build.recommendation.provenance import (
    EvidenceKind,
    ExplanationEvidence,
    MechanicDependency,
    NumericEvidence,
    ProvenanceError,
    build_recommendation_provenance,
)


def _calculated(metric_id: str = "damage_8s") -> NumericEvidence:
    return NumericEvidence(
        metric_id,
        Decimal("123.40"),
        EvidenceKind.CALCULATED,
        formula_ref="combat.damage_after_resistance.v1",
        input_refs=("scenario:duel-v1", "item:3115"),
    )


def test_calculated_number_requires_formula_and_inputs() -> None:
    with pytest.raises(ProvenanceError, match="formula_ref"):
        NumericEvidence("damage_8s", Decimal(10), EvidenceKind.CALCULATED)


def test_measured_number_requires_observation_reference() -> None:
    with pytest.raises(ProvenanceError, match="measurement_refs"):
        NumericEvidence("blind_duration_ms", Decimal(1500), EvidenceKind.MEASURED)


def test_unverified_number_cannot_smuggle_a_score() -> None:
    with pytest.raises(ProvenanceError, match="must not contain a score"):
        NumericEvidence(
            "cc_adjusted_uptime",
            Decimal("0.75"),
            EvidenceKind.UNVERIFIED,
            blockers=("BLIND_FACT_UNVERIFIED",),
        )


def test_unverified_dependency_derives_non_release_output() -> None:
    result = build_recommendation_provenance(
        recommendation_id="default:candidate-1",
        game_patch="16.17.1",
        patch_lock_ref="patch.lock.json",
        scenario_ref="scenario:duel-v1",
        candidate_ref="candidate-1",
        item_ids=(3115,),
        source_file_refs=("data/raw/16.17.1/item.json",),
        numeric_evidence=(
            _calculated(),
            NumericEvidence(
                "cc_adjusted_uptime",
                None,
                EvidenceKind.UNVERIFIED,
                input_refs=("mechanic:cc.blind",),
                blockers=("BLIND_FACT_UNVERIFIED",),
            ),
        ),
        explanation_evidence=(
            ExplanationEvidence(
                "why-blind",
                "실명 보정 결과는 아직 추천 점수에 포함하지 않는다.",
                EvidenceKind.UNVERIFIED,
                blockers=("BLIND_FACT_UNVERIFIED",),
            ),
        ),
        mechanic_dependencies=(MechanicDependency("cc.blind", "UNVERIFIED", ()),),
    )

    assert result.release_eligible is False
    assert result.blockers == (
        "BLIND_FACT_UNVERIFIED",
        "MECHANIC_NOT_VERIFIED:cc.blind:UNVERIFIED",
    )


def test_fully_supported_provenance_is_canonical_and_release_eligible() -> None:
    kwargs = {
        "recommendation_id": "default:candidate-1",
        "game_patch": "16.17.1",
        "patch_lock_ref": "patch.lock.json",
        "scenario_ref": "scenario:duel-v1",
        "candidate_ref": "candidate-1",
        "item_ids": (3115,),
        "source_file_refs": (
            "data/raw/16.17.1/item.json",
            "data/raw/16.17.1/item.json",
        ),
        "numeric_evidence": (
            NumericEvidence(
                "blind_duration_ms",
                Decimal(1500),
                EvidenceKind.MEASURED,
                measurement_refs=("measurement:blind:B0",),
            ),
            _calculated(),
        ),
        "explanation_evidence": (
            ExplanationEvidence(
                "why-selected",
                "8초 피해 계산에서 기본 분기로 선택됐다.",
                EvidenceKind.CALCULATED,
                input_refs=("metric:damage_8s", "selection:default"),
            ),
        ),
        "mechanic_dependencies": (
            MechanicDependency("cc.blind", "VERIFIED", ("measurement:blind:B0-B6",)),
        ),
    }

    first = build_recommendation_provenance(**kwargs)
    second = build_recommendation_provenance(**kwargs)

    assert first.release_eligible is True
    assert first.blockers == ()
    assert first.source_file_refs == ("data/raw/16.17.1/item.json",)
    assert dumps(asdict(first)) == dumps(asdict(second))
