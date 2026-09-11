from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from lol_build.buildtime.champion_snapshots import (
    ChampionSnapshotError,
    audit_champion_snapshot_coverage,
    build_champion_snapshot_plan,
    sync_champion_snapshots,
)


def _write_fixture_lock(root: Path) -> Path:
    roster = {
        "data": {
            "Alpha": {"id": "Alpha", "key": "1"},
            "Bravo": {"id": "Bravo", "key": "22"},
        }
    }
    roster_path = root / "data/raw/99.1.1/en_US/champion.json"
    roster_path.parent.mkdir(parents=True)
    roster_payload = json.dumps(roster).encode()
    roster_path.write_bytes(roster_payload)
    lock = {
        "game_patch": "99.1.1",
        "upstreams": {
            "data_dragon": {"build": "99.1.1"},
            "community_dragon": {
                "status": "LOCKED",
                "base_url": "https://raw.communitydragon.example/99.1/",
            },
        },
        "files": [
            {
                "source": "DATA_DRAGON",
                "role": "CHAMPIONS",
                "url": "https://ddragon.example/champion.json",
                "path": "data/raw/99.1.1/en_US/champion.json",
                "locale": "en_US",
                "sha256": hashlib.sha256(roster_payload).hexdigest(),
                "retrieved_at": "2026-01-01T00:00:00Z",
            }
        ],
    }
    lock_path = root / "patch.lock.json"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    return lock_path


def _source_payload(url: str) -> bytes:
    if url.endswith(".bin.json"):
        key = Path(url).name.removesuffix(".bin.json")
        display_key = {"alpha": "Alpha", "bravo": "Bravo"}[key]
        return json.dumps(
            {
                "{01234567}": {"mType": "HashOnlyRecord"},
                f"Characters/{display_key}/Spells/{display_key}QAbility": {},
            }
        ).encode()
    if "/champion/" in url:
        key = Path(url).stem
        numeric_id = {"Alpha": "1", "Bravo": "22"}[key]
        return json.dumps({"data": {key: {"id": key, "key": numeric_id, "spells": []}}}).encode()
    numeric_id = int(Path(url).stem)
    return json.dumps({"id": numeric_id, "spells": []}).encode()


class MappingFetcher:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        return _source_payload(url)


def test_plan_contains_three_artifacts_for_every_roster_champion(tmp_path: Path) -> None:
    lock_path = _write_fixture_lock(tmp_path)

    plan = build_champion_snapshot_plan(lock_path)

    assert len(plan) == 6
    assert [(spec.champion.key, spec.kind) for spec in plan] == [
        ("Alpha", "DATA_DRAGON_DETAIL"),
        ("Alpha", "COMMUNITY_PROFILE"),
        ("Alpha", "COMMUNITY_BIN"),
        ("Bravo", "DATA_DRAGON_DETAIL"),
        ("Bravo", "COMMUNITY_PROFILE"),
        ("Bravo", "COMMUNITY_BIN"),
    ]
    assert plan[1].url.endswith("/champions/1.json")
    assert plan[2].url.endswith("/game/data/characters/alpha/alpha.bin.json")


def test_sync_validates_writes_and_locks_every_detail_snapshot(tmp_path: Path) -> None:
    lock_path = _write_fixture_lock(tmp_path)
    fetcher = MappingFetcher()

    result = sync_champion_snapshots(
        lock_path,
        repository=tmp_path,
        fetcher=fetcher,
        retrieved_at="2026-09-08T00:00:00Z",
    )

    assert result == {"roster": 2, "fetched": 6, "reused": 0, "snapshots": 6}
    assert len(fetcher.urls) == 6
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    detail_entries = [entry for entry in lock["files"] if entry["path"] != lock["files"][0]["path"]]
    assert len(detail_entries) == 6
    for entry in detail_entries:
        payload = (tmp_path / entry["path"]).read_bytes()
        assert entry["sha256"] == hashlib.sha256(payload).hexdigest()
        assert entry["retrieved_at"] == "2026-09-08T00:00:00Z"
    assert audit_champion_snapshot_coverage(lock_path).complete


def test_second_sync_reuses_authenticated_files_without_fetching(tmp_path: Path) -> None:
    lock_path = _write_fixture_lock(tmp_path)
    sync_champion_snapshots(lock_path, repository=tmp_path, fetcher=_source_payload)

    def reject_network(_url: str) -> bytes:
        raise AssertionError("authenticated snapshots must be reused")

    result = sync_champion_snapshots(
        lock_path,
        repository=tmp_path,
        fetcher=reject_network,
    )

    assert result["fetched"] == 0
    assert result["reused"] == 6


def test_invalid_response_does_not_change_lock_or_install_files(tmp_path: Path) -> None:
    lock_path = _write_fixture_lock(tmp_path)
    original_lock = lock_path.read_bytes()

    def malformed_fetcher(url: str) -> bytes:
        if url.endswith("Alpha.json"):
            return b'{"data":{"Wrong":{"key":"1","spells":[]}}}'
        return _source_payload(url)

    with pytest.raises(ChampionSnapshotError, match="does not match Alpha"):
        sync_champion_snapshots(
            lock_path,
            repository=tmp_path,
            fetcher=malformed_fetcher,
        )

    assert lock_path.read_bytes() == original_lock
    assert not (tmp_path / "data/raw/99.1.1/en_US/champion/Alpha.json").exists()


def test_bin_validation_requires_a_case_insensitive_champion_root(tmp_path: Path) -> None:
    lock_path = _write_fixture_lock(tmp_path)

    def wrong_bin_fetcher(url: str) -> bytes:
        if url.endswith("alpha.bin.json"):
            return b'{"{01234567}":{},"Characters/Bravo/Spells/AlphaQAbility":{}}'
        return _source_payload(url)

    with pytest.raises(ChampionSnapshotError, match="BIN does not match Alpha"):
        sync_champion_snapshots(
            lock_path,
            repository=tmp_path,
            fetcher=wrong_bin_fetcher,
        )

    assert not (tmp_path / "data/raw/99.1.1/communitydragon/champions/alpha.bin.json").exists()


def test_audit_does_not_count_a_missing_or_corrupted_locked_file(tmp_path: Path) -> None:
    lock_path = _write_fixture_lock(tmp_path)
    sync_champion_snapshots(lock_path, repository=tmp_path, fetcher=_source_payload)
    corrupted = tmp_path / "data/raw/99.1.1/en_US/champion/Alpha.json"
    corrupted.write_bytes(b"corrupted")

    coverage = audit_champion_snapshot_coverage(lock_path)

    assert coverage.data_dragon_detail_count == 1
    assert coverage.missing_data_dragon_detail == ("Alpha",)
    assert coverage.community_profile_count == 2
    assert coverage.community_bin_count == 2


def test_repository_audit_reports_complete_locked_coverage() -> None:
    root = Path(__file__).resolve().parents[1]

    coverage = audit_champion_snapshot_coverage(root / "patch.lock.json")

    assert coverage.roster_count == 173
    assert coverage.data_dragon_detail_count == 173
    assert coverage.community_profile_count == 173
    assert coverage.community_bin_count == 173
    assert coverage.complete
    assert coverage.missing_data_dragon_detail == ()
    assert coverage.missing_community_profile == ()
    assert coverage.missing_community_bin == ()
