"""Reproduce locked raw-data snapshots from their build-time URLs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO, Protocol
from urllib.request import Request, urlopen


class Response(Protocol):
    """Describe the context-manager subset required from an HTTP response."""

    def __enter__(self) -> BinaryIO:
        """Return the readable response stream.

        :return: Binary response stream.
        """
        ...

    def __exit__(self, *args: object) -> None:
        """Close the response context.

        :param args: Exception context supplied by the ``with`` statement.
        :return: None.
        """
        ...


Opener = Callable[[str], Response]


class SnapshotFetchError(RuntimeError):
    """Raised when a locked snapshot cannot be reproduced safely."""


def _open_snapshot(url: str) -> Response:
    """Open a build-time snapshot request with the project user agent.

    :param url: Build-time source URL stored in the patch lock.
    :return: Context-managed binary response for the requested snapshot.
    """

    request = Request(url, headers={"User-Agent": "rift-foundry/0.1 snapshot-fetch"})
    return urlopen(request)


def _sha256(path: Path) -> str:
    """Calculate the SHA-256 digest of a local file.

    :param path: Downloaded or installed snapshot whose bytes are checked.
    :return: Lowercase hexadecimal SHA-256 digest.
    """

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_target(destination: Path, relative_path: str) -> Path:
    """Resolve and validate a snapshot destination under the data root.

    :param destination: Local root under which locked snapshots are written.
    :param relative_path: Lock-declared path relative to the destination root.
    :return: Absolute destination path proven to remain beneath ``destination``.
    """

    destination = destination.resolve()
    target = (destination / relative_path).resolve()
    if not target.is_relative_to(destination):
        raise SnapshotFetchError(f"locked path escapes destination: {relative_path}")
    return target


def sync_snapshot(
    lock_path: Path,
    *,
    destination: Path,
    replace: bool = False,
    opener: Opener = _open_snapshot,
) -> dict[str, int]:
    """Fetch missing locked files and verify bytes before atomic installation.

    :param lock_path: Path to the patch lock being verified or compared.
    :param destination: Local root under which locked snapshots are written.
    :param replace: Whether an existing mismatched snapshot may be atomically replaced.
    :param opener: Injectable HTTP opener used by build-time fetching and tests.
    :return: Counts of snapshots fetched and skipped after hash verification.
    """

    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    destination.mkdir(parents=True, exist_ok=True)
    fetched = 0
    skipped = 0

    for entry in lock["files"]:
        target = _safe_target(destination, entry["path"])
        if target.is_file():
            actual_hash = _sha256(target)
            if actual_hash == entry["sha256"]:
                skipped += 1
                continue
            if not replace:
                raise SnapshotFetchError(
                    f"existing file hash mismatch: {entry['path']}; use --replace to restore it"
                )

        target.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=target.parent, prefix=".download-", delete=False
            ) as temporary:
                temporary_path = Path(temporary.name)
                with opener(entry["url"]) as response:
                    while chunk := response.read(1024 * 1024):
                        temporary.write(chunk)

            downloaded_hash = _sha256(temporary_path)
            if downloaded_hash != entry["sha256"]:
                raise SnapshotFetchError(
                    f"download hash mismatch for {entry['path']}: "
                    f"expected {entry['sha256']}, got {downloaded_hash}"
                )
            os.replace(temporary_path, target)
            temporary_path = None
            fetched += 1
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    return {"fetched": fetched, "skipped": skipped}


def main() -> None:
    """Run the module command-line interface.

    :return: None.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=Path("patch.lock.json"))
    parser.add_argument("--destination", type=Path, default=Path("."))
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    result = sync_snapshot(args.lock, destination=args.destination, replace=args.replace)
    print(f"snapshot synchronized: fetched={result['fetched']} skipped={result['skipped']}")


if __name__ == "__main__":
    main()
