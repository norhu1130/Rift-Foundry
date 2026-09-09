"""Typed evidence provenance for recommendation output."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class ProvenanceError(ValueError):
    """Raised when an evidence record could overstate its support."""


class EvidenceKind(StrEnum):
    """Distinguish measured, calculated, and unresolved recommendation evidence."""

    MEASURED = "MEASURED"
    CALCULATED = "CALCULATED"
    UNVERIFIED = "UNVERIFIED"


@dataclass(frozen=True)
class NumericEvidence:
    """Record auditable numeric evidence metadata."""

    metric_id: str
    value: Decimal | None
    evidence_kind: EvidenceKind
    formula_ref: str | None = None
    input_refs: tuple[str, ...] = ()
    measurement_refs: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate dataclass invariants after initialization.

        :return: None.
        """

        if not self.metric_id:
            raise ProvenanceError("metric_id must not be empty")
        if self.value is not None and not self.value.is_finite():
            raise ProvenanceError(f"metric {self.metric_id!r} has a non-finite value")
        if self.evidence_kind is EvidenceKind.MEASURED:
            if self.value is None or not self.measurement_refs:
                raise ProvenanceError(
                    "MEASURED numeric evidence requires value and measurement_refs"
                )
            if self.formula_ref is not None or self.input_refs or self.blockers:
                raise ProvenanceError(
                    "MEASURED numeric evidence cannot claim calculation inputs or blockers"
                )
        elif self.evidence_kind is EvidenceKind.CALCULATED:
            if self.value is None or self.formula_ref is None or not self.input_refs:
                raise ProvenanceError(
                    "CALCULATED numeric evidence requires value, formula_ref, and input_refs"
                )
            if self.measurement_refs or self.blockers:
                raise ProvenanceError(
                    "CALCULATED numeric evidence cannot claim measurements or blockers"
                )
        elif self.evidence_kind is EvidenceKind.UNVERIFIED:
            if self.value is not None:
                raise ProvenanceError("UNVERIFIED numeric evidence must not contain a score")
            if not self.blockers:
                raise ProvenanceError("UNVERIFIED numeric evidence requires blockers")
            if self.formula_ref is not None or self.measurement_refs:
                raise ProvenanceError("UNVERIFIED numeric evidence cannot claim completed evidence")


@dataclass(frozen=True)
class ExplanationEvidence:
    """Record auditable explanation evidence metadata."""

    claim_id: str
    text: str
    evidence_kind: EvidenceKind
    evidence_refs: tuple[str, ...] = ()
    input_refs: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate dataclass invariants after initialization.

        :return: None.
        """

        if not self.claim_id or not self.text:
            raise ProvenanceError("explanation claim_id and text must not be empty")
        if self.evidence_kind is EvidenceKind.MEASURED:
            if not self.evidence_refs or self.input_refs or self.blockers:
                raise ProvenanceError("MEASURED explanation requires evidence_refs only")
        elif self.evidence_kind is EvidenceKind.CALCULATED:
            if not self.input_refs or self.blockers:
                raise ProvenanceError("CALCULATED explanation requires input_refs and no blockers")
        elif self.evidence_kind is EvidenceKind.UNVERIFIED and not self.blockers:
            raise ProvenanceError("UNVERIFIED explanation requires blockers")


@dataclass(frozen=True)
class MechanicDependency:
    """Link a recommendation claim to one required mechanic fact."""

    fact_id: str
    status: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        """Validate dataclass invariants after initialization.

        :return: None.
        """

        if not self.fact_id or not self.status:
            raise ProvenanceError("mechanic fact_id and status must not be empty")
        if self.status == "VERIFIED" and not self.evidence_refs:
            raise ProvenanceError("VERIFIED mechanic dependency requires evidence_refs")


@dataclass(frozen=True)
class RecommendationProvenance:
    """Record auditable recommendation provenance metadata."""

    recommendation_id: str
    game_patch: str
    patch_lock_ref: str
    scenario_ref: str
    candidate_ref: str
    item_ids: tuple[int, ...]
    source_file_refs: tuple[str, ...]
    numeric_evidence: tuple[NumericEvidence, ...]
    explanation_evidence: tuple[ExplanationEvidence, ...]
    mechanic_dependencies: tuple[MechanicDependency, ...]
    release_eligible: bool
    blockers: tuple[str, ...]


def build_recommendation_provenance(
    *,
    recommendation_id: str,
    game_patch: str,
    patch_lock_ref: str,
    scenario_ref: str,
    candidate_ref: str,
    item_ids: tuple[int, ...],
    source_file_refs: tuple[str, ...],
    numeric_evidence: tuple[NumericEvidence, ...],
    explanation_evidence: tuple[ExplanationEvidence, ...],
    mechanic_dependencies: tuple[MechanicDependency, ...],
) -> RecommendationProvenance:
    """Normalize evidence order and derive, rather than accept, release eligibility.

    :param recommendation_id: Unique identity of the recommendation being justified.
    :param game_patch: Game patch shared by every inventory record.
    :param patch_lock_ref: Stable reference to the patch lock used by the calculation.
    :param scenario_ref: Stable reference to the validated scenario fixture.
    :param candidate_ref: Stable reference to the evaluated build candidate.
    :param item_ids: Ordered Riot item identifiers in the build.
    :param source_file_refs: Locked source files supporting the recommendation.
    :param numeric_evidence: Calculated or measured values cited by the recommendation.
    :param explanation_evidence: Non-numeric claims and their supporting evidence.
    :param mechanic_dependencies: Mechanic facts on which recommendation validity depends.
    :return: Canonically ordered evidence with derived eligibility and blockers.
    """

    identity_values = (
        recommendation_id,
        game_patch,
        patch_lock_ref,
        scenario_ref,
        candidate_ref,
    )
    if any(not value for value in identity_values):
        raise ProvenanceError("recommendation identity and source references must not be empty")
    if not item_ids or not source_file_refs or not numeric_evidence:
        raise ProvenanceError("recommendation requires items, source files, and numeric evidence")
    if len(set(item_ids)) != len(item_ids):
        raise ProvenanceError("recommendation item_ids must be unique")

    numbers = tuple(sorted(numeric_evidence, key=lambda evidence: evidence.metric_id))
    claims = tuple(sorted(explanation_evidence, key=lambda evidence: evidence.claim_id))
    mechanics = tuple(sorted(mechanic_dependencies, key=lambda evidence: evidence.fact_id))
    if len({evidence.metric_id for evidence in numbers}) != len(numbers):
        raise ProvenanceError("numeric metric_ids must be unique")
    if len({evidence.claim_id for evidence in claims}) != len(claims):
        raise ProvenanceError("explanation claim_ids must be unique")
    if len({evidence.fact_id for evidence in mechanics}) != len(mechanics):
        raise ProvenanceError("mechanic fact_ids must be unique")

    blockers = {blocker for evidence in (*numbers, *claims) for blocker in evidence.blockers}
    blockers.update(
        f"MECHANIC_NOT_VERIFIED:{dependency.fact_id}:{dependency.status}"
        for dependency in mechanics
        if dependency.status != "VERIFIED"
    )
    release_eligible = (
        not blockers
        and all(evidence.evidence_kind is not EvidenceKind.UNVERIFIED for evidence in numbers)
        and all(evidence.evidence_kind is not EvidenceKind.UNVERIFIED for evidence in claims)
    )
    return RecommendationProvenance(
        recommendation_id=recommendation_id,
        game_patch=game_patch,
        patch_lock_ref=patch_lock_ref,
        scenario_ref=scenario_ref,
        candidate_ref=candidate_ref,
        item_ids=item_ids,
        source_file_refs=tuple(sorted(set(source_file_refs))),
        numeric_evidence=numbers,
        explanation_evidence=claims,
        mechanic_dependencies=mechanics,
        release_eligible=release_eligible,
        blockers=tuple(sorted(blockers)),
    )
