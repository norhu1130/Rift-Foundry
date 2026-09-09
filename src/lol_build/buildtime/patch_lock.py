"""Validate the patch lock and its local immutable files."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from lol_build.buildtime.paths import repository_root


class PatchLockError(RuntimeError):
    """Raised when a patch lock cannot be trusted."""


def _sha256(path: Path) -> str:
    """Calculate the SHA-256 digest of a local file.

    :param path: Local snapshot whose bytes must be authenticated.
    :return: Lowercase hexadecimal SHA-256 digest.
    """

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Any:
    """Read JSON while translating I/O and decoding failures into lock errors.

    :param path: Lock or snapshot JSON file to read.
    :return: Parsed JSON value from ``path``.
    """

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PatchLockError(f"cannot load JSON {path}: {error}") from error


def verify_patch_lock(lock_path: Path, schema_path: Path | None = None) -> dict[str, Any]:
    """Validate lock structure, version coherence, paths, and file hashes.

    :param lock_path: Path to the patch lock being verified or compared.
    :param schema_path: JSON Schema used to validate the patch-lock structure.
    :return: Verified lock document with every declared file hash checked.
    """

    lock_path = lock_path.resolve()
    if schema_path is None:
        schema_path = repository_root() / "schemas/patch-lock.schema.json"

    lock = _load_json(lock_path)
    schema = _load_json(schema_path)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(lock), key=lambda error: list(error.absolute_path))
    if errors:
        details = "; ".join(
            f"/{'/'.join(map(str, error.absolute_path))}: {error.message}" for error in errors
        )
        raise PatchLockError(f"patch lock schema violation: {details}")

    data_dragon = lock["upstreams"]["data_dragon"]
    versions = {
        lock["game_patch"],
        data_dragon["build"],
        data_dragon["realm_version"],
        data_dragon["latest_observed_version"],
    }
    if len(versions) != 1:
        raise PatchLockError(f"Data Dragon version mismatch: {sorted(versions)}")

    expected_realm_suffix = f"/realms/{lock['region'].lower()}.json"
    if not data_dragon["realm_url"].endswith(expected_realm_suffix):
        raise PatchLockError(
            f"realm URL does not match region {lock['region']}: {data_dragon['realm_url']}"
        )

    seen_paths: set[str] = set()
    role_paths: dict[str, list[Path]] = {}
    for index, entry in enumerate(lock["files"]):
        relative_path = entry["path"]
        if relative_path in seen_paths:
            raise PatchLockError(f"duplicate locked path at /files/{index}: {relative_path}")
        seen_paths.add(relative_path)

        file_path = lock_path.parent / relative_path
        role_paths.setdefault(entry["role"], []).append(file_path)
        if not file_path.is_file():
            raise PatchLockError(f"locked file missing at /files/{index}: {file_path}")
        actual_hash = _sha256(file_path)
        if actual_hash != entry["sha256"]:
            raise PatchLockError(
                f"SHA-256 mismatch at /files/{index} ({relative_path}): "
                f"expected {entry['sha256']}, got {actual_hash}"
            )

    realm_paths = role_paths.get("REALM", [])
    versions_paths = role_paths.get("VERSIONS", [])
    if len(realm_paths) != 1 or len(versions_paths) != 1:
        raise PatchLockError("patch lock requires exactly one REALM and one VERSIONS file")

    realm = _load_json(realm_paths[0])
    if realm.get("v") != data_dragon["realm_version"]:
        raise PatchLockError(
            f"realm file version {realm.get('v')!r} does not match "
            f"locked realm version {data_dragon['realm_version']}"
        )
    versions_document = _load_json(versions_paths[0])
    if not isinstance(versions_document, list) or not versions_document:
        raise PatchLockError("versions file must be a non-empty array")
    if versions_document[0] != data_dragon["latest_observed_version"]:
        raise PatchLockError(
            f"versions file latest {versions_document[0]!r} does not match "
            f"locked latest {data_dragon['latest_observed_version']}"
        )

    return lock


def main() -> None:
    """Run the module command-line interface.

    :return: None.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lock", nargs="?", type=Path, default=Path("patch.lock.json"))
    args = parser.parse_args()
    verified = verify_patch_lock(args.lock)
    print(
        f"verified {len(verified['files'])} files for "
        f"{verified['region']} patch {verified['game_patch']}"
    )


if __name__ == "__main__":
    main()
