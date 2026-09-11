"""Materialize preview item candidates from the patch-locked local snapshots."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

_STAT_FIELDS = {
    "mFlatPhysicalDamageMod": "AD",
    "mFlatMagicDamageMod": "AP",
    "mFlatHPPoolMod": "HP",
    "mFlatArmorMod": "ARMOR",
    "mFlatSpellBlockMod": "MAGIC_RESISTANCE",
    "mPercentAttackSpeedMod": "ATTACK_SPEED",
    "mAbilityHasteMod": "ABILITY_HASTE",
    "mFlatMovementSpeedMod": "MOVE_SPEED_FLAT",
    "mPercentMovementSpeedMod": "MOVE_SPEED_PERCENT",
    "mPercentTenacityItemMod": "TENACITY",
    "mFlatCritChanceMod": "CRITICAL_STRIKE_CHANCE",
    "mFlatCritDamageMod": "CRITICAL_STRIKE_DAMAGE",
    "flatMPPoolMod": "MANA",
    "mPercentLifeStealMod": "LIFESTEAL",
    "PercentOmnivampMod": "OMNIVAMP",
    "mPercentBaseHPRegenMod": "BASE_HEALTH_REGEN_PERCENT",
    "mPercentHealingAmountMod": "HEAL_SHIELD_POWER",
}

_PURCHASE_EXCLUSIVE_GROUPS = {
    "Items/ItemGroups/LifelineItems",
    "Items/ItemGroups/TearItems",
    "Items/ItemGroups/LastWhisper",
    "Items/ItemGroups/VoidPen",
    "Items/ItemGroups/ImmolateItems",
    "Items/ItemGroups/EternityItems",
    "Items/ItemGroups/Quicksilver",
    "Items/ItemGroups/BuildsFromStopwatchGroup",
    "Items/ItemGroups/StopwatchGroup",
}


def _constant(value: int | float) -> dict[str, str]:
    """Encode one numeric source value as a constant expression.

    :param value: Raw numeric item stat read from CommunityDragon.
    :return: Constant expression node preserving the numeric value as decimal text.
    """

    return {"type": "CONSTANT", "value": format(Decimal(str(value)), "f")}


def load_complete_item_pool(
    root: Path, only_ids: frozenset[int] | None = None
) -> tuple[dict[str, Any], ...]:
    """Load ordinary complete items and boots without a network dependency.

    :param root: Project root containing locked Data/CommunityDragon snapshots.
    :param only_ids: When given, load exactly these items instead, bypassing the
        complete-item and minimum-cost filters (for evaluation-only components).
    :return: Stable item documents ready for candidate generation.
    """
    raw = json.loads((root / "data/raw/16.17.1/en_US/item.json").read_text(encoding="utf-8"))[
        "data"
    ]
    compact = {
        item["id"]: item
        for item in json.loads(
            (root / "data/raw/16.17.1/communitydragon/items.json").read_text(encoding="utf-8")
        )
    }
    cdtb = json.loads(
        (root / "data/raw/16.17.1/communitydragon/items.cdtb.bin.json").read_text(encoding="utf-8")
    )
    result: list[dict[str, Any]] = []
    for raw_id, item in raw.items():
        item_id = int(raw_id)
        citem = compact.get(item_id, {})
        detail = cdtb.get(f"Items/{item_id}", {})
        tags = set(item.get("tags", ()))
        is_boot = "Boots" in tags
        terminal_or_boot = not item.get("into") or is_boot
        ordinary_id = item_id < 100000
        available = (
            item["maps"].get("11", False)
            and item["gold"]["purchasable"]
            and item["gold"]["total"] >= 1000
            and "Consumable" not in tags
            and not citem.get("requiredChampion")
            and not citem.get("requiredAlly")
            and not citem.get("specialRecipe")
            and not citem.get("requiredBuffCurrencyName")
        )
        if only_ids is not None:
            if item_id not in only_ids:
                continue
        elif not (ordinary_id and available and terminal_or_boot):
            continue
        stats = {
            target: _constant(value)
            for source, target in _STAT_FIELDS.items()
            if (value := detail.get(source)) not in {None, 0}
        }
        combat_stats = {
            "PERCENT_ARMOR_PENETRATION": detail.get("mPercentArmorPenetrationMod", 0),
            "FLAT_ARMOR_PENETRATION": detail.get("PhysicalLethality", 0),
            "PERCENT_MAGIC_PENETRATION": detail.get("mPercentMagicPenetrationMod", 0),
            "FLAT_MAGIC_PENETRATION": detail.get("mFlatMagicPenetrationMod", 0),
        }
        stats.update(
            {
                stat: _constant(value)
                for stat, value in combat_stats.items()
                if value not in {None, 0}
            }
        )
        result.append(
            {
                "id": item_id,
                "name": item["name"],
                "patch_version": "16.17.1",
                "cost": {
                    "total": item["gold"]["total"],
                    "combine": item["gold"]["base"],
                    "sell_value": item["gold"]["sell"],
                },
                "stats": stats,
                "effects": [],
                "groups": {
                    "purchase_limit": "boots" if is_boot else None,
                    "same_passive": None,
                    "shared_cooldown": None,
                    "purchase_exclusive": tuple(
                        sorted(set(detail.get("mItemGroups", ())) & _PURCHASE_EXCLUSIVE_GROUPS)
                    ),
                },
                "build_path": citem.get("from", ()),
                "slot_cost": 1,
                "__combat_stats": {
                    "PERCENT_ARMOR_PENETRATION": format(
                        Decimal(str(detail.get("mPercentArmorPenetrationMod", 0))), "f"
                    ),
                    "LETHALITY": format(Decimal(str(detail.get("PhysicalLethality", 0))), "f"),
                },
            }
        )
    return tuple(sorted(result, key=lambda value: value["id"]))
