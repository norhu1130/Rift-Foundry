"""Response-channel candidates with non-collapsed costs."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class ResponseCandidateError(ValueError):
    """Raised when a response candidate violates the cost contract."""


class ResponseChannel(StrEnum):
    """Classify countermeasures by positioning, kit, loadout, or purchased item."""

    POSITIONING = "POSITIONING"
    CHAMPION_ABILITY = "CHAMPION_ABILITY"
    SUMMONER_SPELL = "SUMMONER_SPELL"
    RUNE = "RUNE"
    BOOTS = "BOOTS"
    ITEM = "ITEM"


_CHANNEL_HINT = {
    ResponseChannel.POSITIONING: 1,
    ResponseChannel.CHAMPION_ABILITY: 2,
    ResponseChannel.SUMMONER_SPELL: 3,
    ResponseChannel.RUNE: 4,
    ResponseChannel.BOOTS: 5,
    ResponseChannel.ITEM: 6,
}


@dataclass(frozen=True)
class ResponseCost:
    """Quantify incremental gold and slot cost for a countermeasure."""

    incremental_gold: Decimal
    inventory_slots: int
    cooldown_ms: int | None
    opportunity_costs: tuple[str, ...]


@dataclass(frozen=True)
class ResponseCandidate:
    """Describe one response candidate considered by the recommendation engine."""

    id: str
    channel: ResponseChannel
    mechanic_refs: tuple[str, ...]
    cost: ResponseCost
    currently_selected: bool = False

    @property
    def channel_order_hint(self) -> int:
        """Return a presentation hint, never a legality or exclusion rule.

        :return: Zero-based priority used only as a stable ordering hint.
        """

        return _CHANNEL_HINT[self.channel]


def _validate_candidate(candidate: ResponseCandidate) -> None:
    """Validate candidate.

    :param candidate: Evaluated build candidate under comparison.
    :return: None.
    """

    if not candidate.id:
        raise ResponseCandidateError("candidate id must not be empty")
    if not candidate.mechanic_refs:
        raise ResponseCandidateError(f"candidate {candidate.id!r} needs a mechanic reference")
    cost = candidate.cost
    if not isinstance(cost.incremental_gold, Decimal) or not cost.incremental_gold.is_finite():
        raise ResponseCandidateError("incremental_gold must be a finite Decimal")
    if cost.incremental_gold < 0:
        raise ResponseCandidateError("incremental_gold must be non-negative")
    if isinstance(cost.inventory_slots, bool) or not isinstance(cost.inventory_slots, int):
        raise TypeError("inventory_slots must be int")
    if cost.inventory_slots not in (0, 1):
        raise ResponseCandidateError("inventory_slots must be 0 or 1")
    if cost.cooldown_ms is not None:
        if isinstance(cost.cooldown_ms, bool) or not isinstance(cost.cooldown_ms, int):
            raise TypeError("cooldown_ms must be int or None")
        if cost.cooldown_ms < 0:
            raise ResponseCandidateError("cooldown_ms must be non-negative")
    if len(set(cost.opportunity_costs)) != len(cost.opportunity_costs):
        raise ResponseCandidateError("opportunity costs must be unique")
    if any(not value for value in cost.opportunity_costs):
        raise ResponseCandidateError("opportunity cost must not be empty")


def generate_response_candidates(
    *,
    positioning: tuple[ResponseCandidate, ...] = (),
    champion_abilities: tuple[ResponseCandidate, ...] = (),
    summoner_spells: tuple[ResponseCandidate, ...] = (),
    runes: tuple[ResponseCandidate, ...] = (),
    boots: tuple[ResponseCandidate, ...] = (),
    items: tuple[ResponseCandidate, ...] = (),
) -> tuple[ResponseCandidate, ...]:
    """Combine every supplied response channel without cross-channel filtering.

    :param positioning: Zero-cost positioning responses available in the matchup.
    :param champion_abilities: Champion-native responses available without item purchases.
    :param summoner_spells: Selected summoner-spell responses and their constraints.
    :param runes: Selected rune responses available to the champion.
    :param boots: Boot upgrades considered as low-slot-cost responses.
    :param items: Item-based countermeasures to include without suppressing cheaper channels.
    :return: Validated countermeasure candidates from every response channel.
    """

    groups = (
        (ResponseChannel.POSITIONING, positioning),
        (ResponseChannel.CHAMPION_ABILITY, champion_abilities),
        (ResponseChannel.SUMMONER_SPELL, summoner_spells),
        (ResponseChannel.RUNE, runes),
        (ResponseChannel.BOOTS, boots),
        (ResponseChannel.ITEM, items),
    )
    candidates: list[ResponseCandidate] = []
    seen_ids: set[str] = set()
    for expected_channel, group in groups:
        for candidate in group:
            _validate_candidate(candidate)
            if candidate.channel is not expected_channel:
                raise ResponseCandidateError(
                    f"candidate {candidate.id!r} is in the wrong channel group"
                )
            if candidate.id in seen_ids:
                raise ResponseCandidateError(f"duplicate candidate id {candidate.id!r}")
            seen_ids.add(candidate.id)
            candidates.append(candidate)
    return tuple(candidates)


def order_by_channel_hint(
    candidates: tuple[ResponseCandidate, ...],
) -> tuple[ResponseCandidate, ...]:
    """Order candidates for presentation while preserving the complete set.

    :param candidates: Evaluated build candidates eligible for selection.
    :return: Candidates sorted by channel cost hint and stable identifier.
    """

    for candidate in candidates:
        _validate_candidate(candidate)
    return tuple(sorted(candidates, key=lambda item: (item.channel_order_hint, item.id)))
