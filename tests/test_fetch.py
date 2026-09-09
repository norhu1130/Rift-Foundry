import hashlib
import io
import json
from pathlib import Path

import pytest

from lol_build.buildtime.fetch import SnapshotFetchError, sync_snapshot


class CountingOpener:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.calls = 0

    def __call__(self, _url: str) -> io.BytesIO:
        self.calls += 1
        return io.BytesIO(self.payload)


def _lock(tmp_path: Path, payload: bytes) -> Path:
    document = {
        "files": [
            {
                "url": "https://example.invalid/data.json",
                "path": "data/raw/test/data.json",
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        ]
    }
    path = tmp_path / "source-lock.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_clean_destination_is_reproduced_and_second_run_is_offline(tmp_path: Path) -> None:
    payload = b'{"locked":true}\n'
    lock_path = _lock(tmp_path, payload)
    destination = tmp_path / "destination"
    opener = CountingOpener(payload)

    assert sync_snapshot(lock_path, destination=destination, opener=opener) == {
        "fetched": 1,
        "skipped": 0,
    }
    assert (destination / "data/raw/test/data.json").read_bytes() == payload
    assert sync_snapshot(lock_path, destination=destination, opener=opener) == {
        "fetched": 0,
        "skipped": 1,
    }
    assert opener.calls == 1


def test_existing_mismatch_is_not_overwritten_without_replace(tmp_path: Path) -> None:
    payload = b"correct"
    lock_path = _lock(tmp_path, payload)
    destination = tmp_path / "destination"
    target = destination / "data/raw/test/data.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"user data")

    with pytest.raises(SnapshotFetchError, match="use --replace"):
        sync_snapshot(lock_path, destination=destination, opener=CountingOpener(payload))
    assert target.read_bytes() == b"user data"


def test_bad_download_is_rejected_before_install(tmp_path: Path) -> None:
    lock_path = _lock(tmp_path, b"expected")
    destination = tmp_path / "destination"

    with pytest.raises(SnapshotFetchError, match="download hash mismatch"):
        sync_snapshot(lock_path, destination=destination, opener=CountingOpener(b"wrong"))
    assert not (destination / "data/raw/test/data.json").exists()


def test_path_escape_is_rejected(tmp_path: Path) -> None:
    payload = b"data"
    lock_path = _lock(tmp_path, payload)
    document = json.loads(lock_path.read_text(encoding="utf-8"))
    document["files"][0]["path"] = "../escaped.json"
    lock_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(SnapshotFetchError, match="escapes destination"):
        sync_snapshot(
            lock_path, destination=tmp_path / "destination", opener=CountingOpener(payload)
        )
