"""Orthogonal recommendation state and explicit pregame assumptions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class OutcomeStatus(StrEnum):
    """State whether selection found at least one feasible recommendation."""

    FOUND = "FOUND"
    NO_FEASIBLE = "NO_FEASIBLE"


class VerificationStatus(StrEnum):
    """State whether every recommendation dependency has verified evidence."""

    VERIFIED = "VERIFIED"
    INSUFFICIENT_VERIFICATION = "INSUFFICIENT_VERIFICATION"


class ScopeStatus(StrEnum):
    """State whether the requested scenario belongs to the implemented model."""

    IN_SCOPE = "IN_SCOPE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


@dataclass(frozen=True)
class RecommendationState:
    """Keep outcome, verification, and model scope independently observable."""

    outcome: OutcomeStatus
    verification: VerificationStatus
    scope: ScopeStatus


@dataclass(frozen=True)
class RecommendationAssumptions:
    """Expose pregame context without claiming an unknown game state is even."""

    recommendation_context: str
    game_state: str
    level_assumption: str
    opponent_build_source: str
    note_code: str


def pregame_assumptions(level: int, opponent_build_source: str) -> RecommendationAssumptions:
    """Create the explicit game-state disclaimer shared by v1 previews.

    :param level: Equal benchmark level enforced for both participants.
    :param opponent_build_source: Origin of the opponent item path.
    :return: Pregame assumptions that make the omitted game-state axis visible.
    """

    return RecommendationAssumptions(
        "PREGAME",
        "NOT_MODELED",
        f"EQUAL_LEVEL_{level}",
        opponent_build_source,
        "GAME_STATE_NOT_MODELED_REVIEW_DEFENSE_BRANCH_IF_CONTEXT_CHANGED",
    )
