"""Patch-locked inventory of every purchasable Summoner's Rift item effect."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from lol_build.core.canonical import dumps


class ItemClass(StrEnum):
    """Separate build candidates from components, consumables, trinkets, and variants."""

    STANDARD_BUILD = "STANDARD_BUILD"
    COMPONENT = "COMPONENT"
    CONSUMABLE = "CONSUMABLE"
    TRINKET = "TRINKET"
    MODE_OR_VARIANT = "MODE_OR_VARIANT"


class ImplementationStatus(StrEnum):
    """State whether an item's advertised effects are implemented or inapplicable."""

    IMPLEMENTED = "IMPLEMENTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNIMPLEMENTED = "UNIMPLEMENTED"


@dataclass(frozen=True)
class ItemEffectRecord:
    """Record expected tooltip effects and their implementation coverage."""

    item_id: int
    name: str
    item_class: ItemClass
    terminal: bool
    passive_labels: tuple[str, ...]
    active_labels: tuple[str, ...]
    cdragon_active: bool
    implementation_status: ImplementationStatus
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class ItemEffectInventory:
    """Aggregate item-effect coverage counts and per-item audit records."""

    game_patch: str
    map_id: int
    records: tuple[ItemEffectRecord, ...]
    total_items: int
    items_with_passives: int
    items_with_actives: int
    implemented_items: int
    unimplemented_items: int


_TAG_PATTERN = re.compile(r"<(passive|active)>(.*?)</\1>", re.IGNORECASE | re.DOTALL)
_HTML_PATTERN = re.compile(r"<[^>]+>")
_TRINKET_IDS = {3330, 3340, 3363, 3364}
_CONSUMABLE_TAGS = {"Consumable"}


def _labels(description: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Extract passive and active labels from an item tooltip.

    :param description: Raw localized item tooltip whose effect labels are extracted.
    :return: Passive labels followed by active labels, each deduplicated in tooltip order.
    """

    found: dict[str, list[str]] = {"passive": [], "active": []}
    for kind, raw_label in _TAG_PATTERN.findall(description):
        label = _HTML_PATTERN.sub("", raw_label).strip()
        if label and label not in found[kind.lower()]:
            found[kind.lower()].append(label)
    active_labels = found["active"]
    if len(active_labels) > 1:
        active_labels = [
            label for label in active_labels if label.upper() not in {"ACTIVE", "ACTIVE -"}
        ]
    return tuple(found["passive"]), tuple(active_labels)


def _classify(item_id: int, item: Mapping[str, Any]) -> ItemClass:
    """Classify an item by map availability and build role.

    :param item_id: Numeric Riot item identifier.
    :param item: Normalized item document being evaluated.
    :return: The catalog class that determines whether the item belongs in build search.
    """

    tags = set(item.get("tags", ()))
    if item_id >= 100000:
        return ItemClass.MODE_OR_VARIANT
    if item_id in _TRINKET_IDS or "Trinket" in tags:
        return ItemClass.TRINKET
    if tags & _CONSUMABLE_TAGS or item_id in {2003, 2031, 2055, 2138, 2139, 2140, 2141}:
        return ItemClass.CONSUMABLE
    if item.get("into"):
        return ItemClass.COMPONENT
    return ItemClass.STANDARD_BUILD


def build_item_effect_inventory(
    *,
    item_document: Mapping[str, Any],
    cdragon_items: tuple[Mapping[str, Any], ...],
    game_patch: str,
    implemented_effect_labels: Mapping[int, frozenset[str]] | None = None,
) -> ItemEffectInventory:
    """Inventory all map-11 purchasable records without treating absence as support.

    :param item_document: Locked Data Dragon item catalog for the target patch.
    :param cdragon_items: CommunityDragon item records used to cross-check active effects.
    :param game_patch: Game patch shared by every inventory record.
    :param implemented_effect_labels: Curated passive and active labels implemented per item ID.
    :return: Coverage totals and one implementation record per purchasable map-11 item.
    """

    cdragon_by_id = {item["id"]: item for item in cdragon_items}
    implementations = implemented_effect_labels or {}
    records: list[ItemEffectRecord] = []
    for raw_id, item in item_document["data"].items():
        item_id = int(raw_id)
        if not item["maps"].get("11", False) or not item["gold"]["purchasable"]:
            continue
        passives, actives = _labels(item.get("description", ""))
        cdragon_active = bool(cdragon_by_id.get(item_id, {}).get("active", False))
        expected_labels = {
            *(f"PASSIVE:{label}" for label in passives),
            *(f"ACTIVE:{label}" for label in actives),
        }
        if cdragon_active and not actives:
            expected_labels.add("ACTIVE:__CDRAGON_ACTIVE__")
        implemented_labels = set(implementations.get(item_id, ()))
        has_effect = bool(expected_labels)
        if has_effect and implemented_labels == expected_labels:
            status = ImplementationStatus.IMPLEMENTED
            blockers: tuple[str, ...] = ()
        elif has_effect:
            status = ImplementationStatus.UNIMPLEMENTED
            blockers = (f"ITEM_EFFECTS_UNIMPLEMENTED:{item_id}",)
        else:
            status = ImplementationStatus.NOT_APPLICABLE
            blockers = ()
        records.append(
            ItemEffectRecord(
                item_id,
                item["name"],
                _classify(item_id, item),
                not bool(item.get("into")),
                passives,
                actives,
                cdragon_active,
                status,
                blockers,
            )
        )
    ordered = tuple(sorted(records, key=lambda record: record.item_id))
    return ItemEffectInventory(
        game_patch,
        11,
        ordered,
        len(ordered),
        sum(bool(record.passive_labels) for record in ordered),
        sum(bool(record.active_labels) for record in ordered),
        sum(record.implementation_status is ImplementationStatus.IMPLEMENTED for record in ordered),
        sum(
            record.implementation_status is ImplementationStatus.UNIMPLEMENTED for record in ordered
        ),
    )


def inventory_document(root: Path) -> ItemEffectInventory:
    """Build the canonical item-effect inventory document.

    :param root: Project root containing locked data and curated records.
    :return: Inventory derived from the current lock and curated effect programs.
    """

    lock = json.loads((root / "patch.lock.json").read_text(encoding="utf-8"))
    items = json.loads((root / "data/raw/16.17.1/en_US/item.json").read_text(encoding="utf-8"))
    cdragon = tuple(
        json.loads(
            (root / "data/raw/16.17.1/communitydragon/items.json").read_text(encoding="utf-8")
        )
    )
    implementations: dict[int, frozenset[str]] = {}
    for path in sorted((root / "data/curated/item_effects").glob("*.json")):
        program_document = json.loads(path.read_text(encoding="utf-8"))
        implementations[program_document["item_id"]] = frozenset(
            program["source_label"] for program in program_document["programs"]
        )
    return build_item_effect_inventory(
        item_document=items,
        cdragon_items=cdragon,
        game_patch=lock["game_patch"],
        implemented_effect_labels=implementations,
    )


def main() -> None:
    """Run the module command-line interface.

    :return: None.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    print(dumps(asdict(inventory_document(args.root.resolve()))))


if __name__ == "__main__":
    main()
