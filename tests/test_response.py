from decimal import Decimal

import pytest

from lol_build.recommendation.response import (
    ResponseCandidate,
    ResponseCandidateError,
    ResponseChannel,
    ResponseCost,
    generate_response_candidates,
    order_by_channel_hint,
)


def _candidate(
    id: str,
    channel: ResponseChannel,
    *,
    gold: str = "0",
    slots: int = 0,
    cooldown_ms: int | None = None,
    opportunity_costs: tuple[str, ...] = (),
    selected: bool = False,
) -> ResponseCandidate:
    return ResponseCandidate(
        id,
        channel,
        ("cc_blind_v1",),
        ResponseCost(Decimal(gold), slots, cooldown_ms, opportunity_costs),
        selected,
    )


def test_all_six_channels_are_generated_and_hint_only_changes_order() -> None:
    positioning = _candidate("keep_range", ResponseChannel.POSITIONING)
    ability = _candidate("champion_immunity", ResponseChannel.CHAMPION_ABILITY)
    cleanse = _candidate(
        "summoner_cleanse",
        ResponseChannel.SUMMONER_SPELL,
        cooldown_ms=240000,
        opportunity_costs=("REPLACES_SUMMONER_SLOT",),
    )
    rune = _candidate("tenacity_rune", ResponseChannel.RUNE, opportunity_costs=("RUNE_SLOT",))
    boots = _candidate("mercurys_treads", ResponseChannel.BOOTS, gold="800")
    item = _candidate("tenacity_item", ResponseChannel.ITEM, gold="3000", slots=1)

    generated = generate_response_candidates(
        positioning=(positioning,),
        champion_abilities=(ability,),
        summoner_spells=(cleanse,),
        runes=(rune,),
        boots=(boots,),
        items=(item,),
    )
    ordered = order_by_channel_hint(tuple(reversed(generated)))

    assert len(generated) == 6
    assert [candidate.channel for candidate in ordered] == list(ResponseChannel)
    assert set(ordered) == set(generated)


def test_selected_cleanse_does_not_remove_persistent_tenacity_candidates() -> None:
    cleanse = _candidate(
        "summoner_cleanse",
        ResponseChannel.SUMMONER_SPELL,
        cooldown_ms=240000,
        opportunity_costs=("REPLACES_TELEPORT",),
        selected=True,
    )
    boots = _candidate("mercurys_treads", ResponseChannel.BOOTS, gold="800")
    item = _candidate("steraks_gage", ResponseChannel.ITEM, gold="3200", slots=1)

    candidates = generate_response_candidates(
        summoner_spells=(cleanse,), boots=(boots,), items=(item,)
    )

    assert {candidate.id for candidate in candidates} == {
        "summoner_cleanse",
        "mercurys_treads",
        "steraks_gage",
    }


def test_cost_dimensions_are_not_collapsed_into_one_score() -> None:
    candidate = _candidate(
        "summoner_cleanse",
        ResponseChannel.SUMMONER_SPELL,
        cooldown_ms=240000,
        opportunity_costs=("REPLACES_TELEPORT",),
    )

    assert candidate.cost.incremental_gold == 0
    assert candidate.cost.inventory_slots == 0
    assert candidate.cost.cooldown_ms == 240000
    assert candidate.cost.opportunity_costs == ("REPLACES_TELEPORT",)
    assert not hasattr(candidate.cost, "total_cost")


def test_invalid_group_and_costs_are_rejected() -> None:
    wrong_group = _candidate("cleanse", ResponseChannel.SUMMONER_SPELL)
    with pytest.raises(ResponseCandidateError, match="wrong channel"):
        generate_response_candidates(items=(wrong_group,))

    negative_gold = _candidate("bad", ResponseChannel.ITEM, gold="-1", slots=1)
    with pytest.raises(ResponseCandidateError, match="non-negative"):
        generate_response_candidates(items=(negative_gold,))
