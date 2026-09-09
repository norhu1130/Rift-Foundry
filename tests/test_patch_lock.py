import json
from pathlib import Path

import pytest

from lol_build.buildtime.patch_lock import PatchLockError, verify_patch_lock

ROOT = Path(__file__).resolve().parents[1]


def test_repository_patch_lock_is_valid() -> None:
    lock = verify_patch_lock(ROOT / "patch.lock.json")

    assert lock["region"] == "KR"
    assert lock["game_patch"] == "16.17.1"
    assert lock["locale"] == "ko_KR"
    assert lock["upstreams"]["data_dragon"]["realm_version"] == "16.17.1"
    locked_paths = {entry["path"] for entry in lock["files"]}
    assert "data/raw/16.17.1/ko_KR/item.json" in locked_paths
    assert {f"data/raw/16.17.1/img/sprite/item{index}.png" for index in range(9)} <= locked_paths


def test_modified_locked_file_is_rejected(tmp_path: Path) -> None:
    source = ROOT / "data/raw/16.17.1/meta/versions.json"
    modified = tmp_path / "versions.json"
    modified.write_bytes(source.read_bytes() + b"\n")

    lock = json.loads((ROOT / "patch.lock.json").read_text(encoding="utf-8"))
    lock["files"] = [lock["files"][0]]
    lock["files"][0]["path"] = "versions.json"
    test_lock = tmp_path / "patch.lock.json"
    test_lock.write_text(json.dumps(lock), encoding="utf-8")

    with pytest.raises(PatchLockError, match="SHA-256 mismatch"):
        verify_patch_lock(test_lock)


def test_version_mismatch_is_rejected(tmp_path: Path) -> None:
    lock = json.loads((ROOT / "patch.lock.json").read_text(encoding="utf-8"))
    lock["upstreams"]["data_dragon"]["realm_version"] = "16.16.1"
    test_lock = tmp_path / "patch.lock.json"
    test_lock.write_text(json.dumps(lock), encoding="utf-8")

    with pytest.raises(PatchLockError, match="version mismatch"):
        verify_patch_lock(test_lock)


def test_region_and_realm_url_mismatch_is_rejected(tmp_path: Path) -> None:
    lock = json.loads((ROOT / "patch.lock.json").read_text(encoding="utf-8"))
    lock["region"] = "EUW1"
    test_lock = tmp_path / "patch.lock.json"
    test_lock.write_text(json.dumps(lock), encoding="utf-8")

    with pytest.raises(PatchLockError, match="realm URL does not match region"):
        verify_patch_lock(test_lock)


def test_missing_locked_file_is_rejected(tmp_path: Path) -> None:
    lock = json.loads((ROOT / "patch.lock.json").read_text(encoding="utf-8"))
    lock["files"][0]["path"] = "data/raw/does-not-exist.json"
    test_lock = tmp_path / "patch.lock.json"
    test_lock.write_text(json.dumps(lock), encoding="utf-8")

    with pytest.raises(PatchLockError, match="locked file missing"):
        verify_patch_lock(test_lock)
