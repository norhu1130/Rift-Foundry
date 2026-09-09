import json
from copy import deepcopy
from pathlib import Path

from lol_build.core.expression import EvaluationContext
from lol_build.items.candidates import (
    RejectionReason,
    ResourceType,
    generate_build_candidates,
)

REPOSITORY = Path(__file__).resolve().parents[1]


def _item(item_id: int) -> dict:
    return json.loads((REPOSITORY / f"data/curated/items/{item_id}.json").read_text())


def _context() -> EvaluationContext:
    return EvaluationContext(self_level=13, target_level=13, stats={})


def test_generates_deterministic_ordered_candidates_for_each_core_milestone() -> None:
    items = (_item(3053), _item(3115), _item(6665))
    result = generate_build_candidates(
        items=items,
        allowed_item_ids={3053, 3115, 6665},
        expected_patch="16.17.1",
        budgets_by_core={1: 4000, 2: 7000, 3: 10000},
        resource=ResourceType.MANA,
        evaluation_context=_context(),
        range_class="MELEE",
    )

    assert [candidate.item_ids for candidate in result.candidates_by_core[1]] == [
        (3053,),
        (3115,),
        (6665,),
    ]
    assert len(result.candidates_by_core[2]) == 6
    assert len(result.candidates_by_core[3]) == 6
    assert result.candidates_by_core[2][0].item_ids == (3053, 3115)
    assert result.candidates_by_core[2][0].component_paths == (
        tuple(items[0]["build_path"]),
        tuple(items[1]["build_path"]),
    )


def test_purchase_limit_is_hard_but_passive_and_cooldown_groups_are_annotations() -> None:
    first = _item(3053)
    second = _item(3115)
    second["groups"] = {
        "purchase_limit": None,
        "same_passive": "lifeline",
        "shared_cooldown": "lifeline",
    }
    first["groups"]["purchase_limit"] = None
    result = generate_build_candidates(
        items=(first, second),
        allowed_item_ids={3053, 3115},
        expected_patch="16.17.1",
        budgets_by_core={1: 4000, 2: 7000},
        resource=ResourceType.MANA,
        evaluation_context=_context(),
        range_class="MELEE",
        max_core_count=2,
    )

    build = next(
        candidate
        for candidate in result.candidates_by_core[2]
        if candidate.item_ids == (3053, 3115)
    )
    assert build.nonstacking_passive_groups == ("lifeline",)
    assert build.shared_cooldown_groups == ("lifeline",)

    first["groups"]["purchase_limit"] = "lifeline_items"
    second["groups"]["purchase_limit"] = "lifeline_items"
    hard_result = generate_build_candidates(
        items=(first, second),
        allowed_item_ids={3053, 3115},
        expected_patch="16.17.1",
        budgets_by_core={1: 4000, 2: 7000},
        resource=ResourceType.MANA,
        evaluation_context=_context(),
        range_class="MELEE",
        max_core_count=2,
    )
    assert hard_result.candidates_by_core[2] == ()
    assert {rejection.reason for rejection in hard_result.rejections} >= {
        RejectionReason.PURCHASE_LIMIT_DUPLICATE
    }


def test_mana_crit_budget_and_slot_constraints_are_audited() -> None:
    mana_item = _item(3115)
    mana_item["stats"]["MANA"] = {"type": "CONSTANT", "value": "100"}
    crit_item = deepcopy(_item(6665))
    crit_item["stats"]["CRITICAL_STRIKE_CHANCE"] = {
        "type": "CONSTANT",
        "value": "1.10",
    }
    result = generate_build_candidates(
        items=(mana_item, crit_item),
        allowed_item_ids={3115, 6665},
        expected_patch="16.17.1",
        budgets_by_core={1: 3100},
        resource=ResourceType.NONE,
        evaluation_context=_context(),
        range_class="MELEE",
        max_core_count=1,
        max_slots=1,
    )

    reasons = {rejection.reason for rejection in result.rejections}
    assert RejectionReason.MANA_ON_MANALESS_CHAMPION in reasons
    assert RejectionReason.BUDGET_EXCEEDED in reasons

    crit_only = generate_build_candidates(
        items=(crit_item,),
        allowed_item_ids={6665},
        expected_patch="16.17.1",
        budgets_by_core={1: 4000},
        resource=ResourceType.NONE,
        evaluation_context=_context(),
        range_class="MELEE",
        max_core_count=1,
    )
    assert crit_only.rejections[0].reason is RejectionReason.CRITICAL_STRIKE_CAP_EXCEEDED

    no_slots = generate_build_candidates(
        items=(_item(3115),),
        allowed_item_ids={3115},
        expected_patch="16.17.1",
        budgets_by_core={1: 4000},
        resource=ResourceType.MANA,
        evaluation_context=_context(),
        range_class="MELEE",
        max_core_count=1,
        max_slots=0,
    )
    assert no_slots.rejections[0].reason is RejectionReason.SLOT_LIMIT_EXCEEDED


def test_item_missing_from_locked_patch_is_rejected_before_scoring() -> None:
    fabricated = _item(3115)
    fabricated["id"] = 999999

    result = generate_build_candidates(
        items=(fabricated,),
        allowed_item_ids={3115},
        expected_patch="16.17.1",
        budgets_by_core={1: 4000},
        resource=ResourceType.MANA,
        evaluation_context=_context(),
        range_class="MELEE",
        max_core_count=1,
    )

    assert result.candidates_by_core[1] == ()
    assert result.rejections[0].reason is RejectionReason.ITEM_NOT_IN_LOCKED_PATCH
