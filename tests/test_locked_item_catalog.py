from pathlib import Path

from lol_build.items.catalog import load_complete_item_pool

ROOT = Path(__file__).resolve().parents[1]


def test_locked_complete_pool_contains_both_champions_core_options() -> None:
    items = {item["id"]: item for item in load_complete_item_pool(ROOT)}

    assert {2501, 3046, 3053, 3071, 3078, 3153, 3742, 6333, 6610, 6631} <= set(items)
    assert items[6631]["stats"]["AD"]["value"] == "40.0"
    assert items[3053]["stats"]["TENACITY"]["value"].startswith("0.20")
    assert items[3047]["groups"]["purchase_limit"] == "boots"
    assert items[3083]["stats"]["BASE_HEALTH_REGEN_PERCENT"]["value"] == "1.0"
    assert items[3084]["stats"]["BASE_HEALTH_REGEN_PERCENT"]["value"] == "1.0"
    assert items[2517]["stats"]["OMNIVAMP"]["value"].startswith("0.05")
    assert all(item["patch_version"] == "16.17.1" for item in items.values())
