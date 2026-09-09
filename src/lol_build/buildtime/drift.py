"""Report item and champion record drift between two verified patch locks."""

from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from lol_build.buildtime.patch_lock import verify_patch_lock
from lol_build.core.canonical import dumps


class DriftError(RuntimeError):
    """Raised when comparable summary data cannot be found."""


def diff_records(old: dict[str, Any], new: dict[str, Any]) -> dict[str, list[str]]:
    """Return stable ID lists for added, removed, and structurally changed records.

    :param old: Records from the earlier locked snapshot.
    :param new: Records from the later locked snapshot.
    :return: Stable ``added``, ``removed``, and ``changed`` identifier lists.
    """

    old_ids = set(old)
    new_ids = set(new)
    return {
        "added": sorted(new_ids - old_ids, key=_id_sort_key),
        "removed": sorted(old_ids - new_ids, key=_id_sort_key),
        "changed": sorted(
            (
                record_id
                for record_id in old_ids & new_ids
                if dumps(old[record_id]) != dumps(new[record_id])
            ),
            key=_id_sort_key,
        ),
    }


def _id_sort_key(value: str) -> tuple[int, int | str]:
    """Create a stable numeric-first identifier sort key.

    :param value: Raw record identifier, numeric or textual.
    :return: Key that orders numeric identifiers before textual identifiers.
    """

    return (0, int(value)) if value.isdecimal() else (1, value)


def _summary_path(lock_path: Path, lock: dict[str, Any], role: str, filename: str) -> Path:
    """Resolve the drift-summary path for a locked source file.

    :param lock_path: Path to the patch lock being verified or compared.
    :param lock: Parsed patch-lock document that declares source files.
    :param role: Source role, such as Data Dragon or CommunityDragon.
    :param filename: Lock-declared source filename being resolved.
    :return: The sole locked file matching ``role`` and ``filename``.
    """

    matches = [
        lock_path.parent / entry["path"]
        for entry in lock["files"]
        if entry["role"] == role
        and Path(entry["path"]).name == filename
        and entry.get("locale") == lock["locale"]
    ]
    if len(matches) != 1:
        raise DriftError(f"expected one locked {role} summary named {filename}, got {len(matches)}")
    return matches[0]


def _data_records(path: Path) -> dict[str, Any]:
    """Extract comparable records from a locked JSON document.

    :param path: Locked Data Dragon summary to normalize for comparison.
    :return: Record mapping stored in the document's top-level ``data`` field.
    """

    document = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
    records = document.get("data")
    if not isinstance(records, dict):
        raise DriftError(f"summary has no object-valued data field: {path}")
    return records


def compare_locks(old_lock_path: Path, new_lock_path: Path) -> dict[str, Any]:
    """Verify two locks, then compare their canonical Data Dragon summaries.

    :param old_lock_path: Path to the baseline patch lock.
    :param new_lock_path: Path to the patch lock being compared with the baseline.
    :return: Patch metadata and item/champion drift between the two verified locks.
    """

    old_lock_path = old_lock_path.resolve()
    new_lock_path = new_lock_path.resolve()
    old_lock = verify_patch_lock(old_lock_path)
    new_lock = verify_patch_lock(new_lock_path)

    if old_lock["region"] != new_lock["region"]:
        raise DriftError(
            f"cannot compare different regions: {old_lock['region']} vs {new_lock['region']}"
        )

    old_items = _data_records(_summary_path(old_lock_path, old_lock, "ITEMS", "item.json"))
    new_items = _data_records(_summary_path(new_lock_path, new_lock, "ITEMS", "item.json"))
    old_champions = _data_records(
        _summary_path(old_lock_path, old_lock, "CHAMPIONS", "champion.json")
    )
    new_champions = _data_records(
        _summary_path(new_lock_path, new_lock, "CHAMPIONS", "champion.json")
    )

    return {
        "region": old_lock["region"],
        "old_patch": old_lock["game_patch"],
        "new_patch": new_lock["game_patch"],
        "items": diff_records(old_items, new_items),
        "champions": diff_records(old_champions, new_champions),
    }


def main() -> None:
    """Run the module command-line interface.

    :return: None.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old_lock", type=Path)
    parser.add_argument("new_lock", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare_locks(args.old_lock, args.new_lock), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
