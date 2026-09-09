import json
from pathlib import Path

from lol_build.items.inventory import (
    ImplementationStatus,
    ItemClass,
    build_item_effect_inventory,
    inventory_document,
)

ROOT = Path(__file__).resolve().parents[1]


def test_locked_patch_inventory_covers_every_map_11_purchasable_item() -> None:
    inventory = inventory_document(ROOT)
    raw = json.loads((ROOT / "data/raw/16.17.1/en_US/item.json").read_text(encoding="utf-8"))
    expected = {
        int(item_id)
        for item_id, item in raw["data"].items()
        if item["maps"].get("11", False) and item["gold"]["purchasable"]
    }

    assert {record.item_id for record in inventory.records} == expected
    assert inventory.total_items == 254
    assert inventory.items_with_passives == 171
    assert inventory.items_with_actives == 44
    assert inventory.implemented_items == 201
    assert inventory.unimplemented_items == 0


def test_inventory_classifies_garen_build_and_active_stridebreaker() -> None:
    records = {record.item_id: record for record in inventory_document(ROOT).records}

    assert records[6631].item_class is ItemClass.STANDARD_BUILD
    assert records[6631].passive_labels == ("Cleave",)
    assert records[6631].active_labels == ("Breaking Shockwave",)
    assert records[6631].cdragon_active is True
    assert records[6631].implementation_status is ImplementationStatus.IMPLEMENTED
    assert records[3046].passive_labels == ("Spectral Waltz",)
    assert records[3742].passive_labels == ("Shipwrecker", "Unsinkable")
    assert records[3046].implementation_status is ImplementationStatus.IMPLEMENTED
    assert records[3742].implementation_status is ImplementationStatus.IMPLEMENTED
    assert records[3139].active_labels == ("Quicksilver",)
    assert records[3139].implementation_status is ImplementationStatus.IMPLEMENTED
    assert records[3146].active_labels == ("Lightning Bolt",)
    assert records[663193].active_labels == ("Unbreakable:",)
    assert records[663193].implementation_status is ImplementationStatus.IMPLEMENTED


def test_explicit_implementation_is_required_to_remove_blocker() -> None:
    item_document = {
        "data": {
            "1": {
                "name": "Example",
                "description": "<passive>Effect</passive>",
                "maps": {"11": True},
                "gold": {"purchasable": True},
                "tags": [],
            }
        }
    }
    inventory = build_item_effect_inventory(
        item_document=item_document,
        cdragon_items=(),
        game_patch="16.17.1",
        implemented_effect_labels={1: frozenset({"PASSIVE:Effect"})},
    )

    assert inventory.records[0].implementation_status is ImplementationStatus.IMPLEMENTED
    assert inventory.records[0].blockers == ()
