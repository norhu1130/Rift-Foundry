"""Collect and audit patch-locked detailed data for every champion."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

SnapshotFetcher = Callable[[str], bytes]


class ChampionSnapshotError(RuntimeError):
    """Report an invalid roster, source response, or snapshot destination."""


class ChampionSnapshotKind(StrEnum):
    """Distinguish metadata profiles from calculation-grade spell dumps."""

    DATA_DRAGON_DETAIL = "DATA_DRAGON_DETAIL"
    COMMUNITY_PROFILE = "COMMUNITY_PROFILE"
    COMMUNITY_BIN = "COMMUNITY_BIN"


@dataclass(frozen=True)
class ChampionIdentity:
    """Identify one champion across Data Dragon and Community Dragon.

    :param key: Data Dragon identifier used in champion detail URLs.
    :param numeric_id: Numeric champion identifier shared by Riot datasets.
    """

    key: str
    numeric_id: int


@dataclass(frozen=True)
class ChampionSnapshotSpec:
    """Describe one detailed champion document that must be locked.

    :param champion: Champion represented by the source document.
    :param source: Upstream dataset that owns the document.
    :param kind: Semantic artifact type within the upstream dataset.
    :param url: Patch-specific URL used only by the build-time command.
    :param relative_path: Repository-relative destination recorded in the lock.
    :param locale: Locale attached to the source document.
    """

    champion: ChampionIdentity
    source: str
    kind: ChampionSnapshotKind
    url: str
    relative_path: str
    locale: str


@dataclass(frozen=True)
class ChampionSnapshotCoverage:
    """Summarize detailed snapshot coverage against the locked roster.

    :param roster_count: Number of champions declared by the roster summary.
    :param data_dragon_detail_count: Champions with locked Data Dragon details.
    :param community_profile_count: Champions with locked Community Dragon profiles.
    :param community_bin_count: Champions with locked calculation-grade BIN dumps.
    :param missing_data_dragon_detail: Roster keys lacking Data Dragon details.
    :param missing_community_profile: Roster keys lacking Community Dragon profiles.
    :param missing_community_bin: Roster keys lacking Community Dragon BIN dumps.
    """

    roster_count: int
    data_dragon_detail_count: int
    community_profile_count: int
    community_bin_count: int
    missing_data_dragon_detail: tuple[str, ...]
    missing_community_profile: tuple[str, ...]
    missing_community_bin: tuple[str, ...]

    @property
    def complete(self) -> bool:
        """Indicate whether all three required artifacts cover the roster.

        :return: ``True`` only when no required artifact has a missing champion.
        """

        return not (
            self.missing_data_dragon_detail
            or self.missing_community_profile
            or self.missing_community_bin
        )


def _sha256_bytes(payload: bytes) -> str:
    """Hash source bytes before they are installed or recorded in the lock.

    :param payload: Exact response body returned by a snapshot source.
    :return: Lowercase SHA-256 digest for the immutable response body.
    """

    return hashlib.sha256(payload).hexdigest()


def _load_document(path: Path) -> dict[str, Any]:
    """Load an object-valued JSON document with a domain-specific error.

    :param path: Roster or patch-lock document to decode.
    :return: Parsed top-level JSON object.
    """

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ChampionSnapshotError(f"cannot load JSON {path}: {error}") from error
    if not isinstance(document, dict):
        raise ChampionSnapshotError(f"expected an object-valued JSON document: {path}")
    return document


def _locked_roster_path(lock_path: Path, lock: dict[str, Any], locale: str) -> Path:
    """Locate the Data Dragon roster summary used to enumerate champions.

    :param lock_path: Patch lock whose directory anchors relative source paths.
    :param lock: Parsed patch-lock document.
    :param locale: Data Dragon locale selected for detail snapshots.
    :return: Sole locked ``champion.json`` summary for ``locale``.
    """

    matches = [
        lock_path.parent / entry["path"]
        for entry in lock.get("files", [])
        if entry.get("source") == "DATA_DRAGON"
        and entry.get("role") == "CHAMPIONS"
        and entry.get("locale") == locale
        and Path(entry["path"]).name == "champion.json"
    ]
    if len(matches) != 1:
        raise ChampionSnapshotError(
            f"expected one locked Data Dragon champion.json for {locale}, got {len(matches)}"
        )
    return matches[0]


def load_champion_roster(lock_path: Path, *, locale: str = "en_US") -> tuple[ChampionIdentity, ...]:
    """Read the authoritative champion identities from a locked roster summary.

    :param lock_path: Patch lock that points at the roster summary.
    :param locale: Data Dragon locale used to locate that summary.
    :return: Champions sorted by numeric ID for deterministic planning.
    """

    lock_path = lock_path.resolve()
    lock = _load_document(lock_path)
    roster_document = _load_document(_locked_roster_path(lock_path, lock, locale))
    records = roster_document.get("data")
    if not isinstance(records, dict) or not records:
        raise ChampionSnapshotError("champion roster must contain a non-empty data object")

    identities: list[ChampionIdentity] = []
    seen_ids: set[int] = set()
    for record_key, raw_record in records.items():
        if not isinstance(raw_record, dict):
            raise ChampionSnapshotError(f"champion roster record is not an object: {record_key}")
        key = raw_record.get("id")
        numeric_text = raw_record.get("key")
        if not isinstance(key, str) or not key or not isinstance(numeric_text, str):
            raise ChampionSnapshotError(f"champion roster identity is invalid: {record_key}")
        try:
            numeric_id = int(numeric_text)
        except ValueError as error:
            raise ChampionSnapshotError(
                f"champion numeric ID is invalid for {key}: {numeric_text!r}"
            ) from error
        if numeric_id in seen_ids:
            raise ChampionSnapshotError(f"duplicate champion numeric ID: {numeric_id}")
        seen_ids.add(numeric_id)
        identities.append(ChampionIdentity(key=key, numeric_id=numeric_id))
    return tuple(sorted(identities, key=lambda champion: champion.numeric_id))


def build_champion_snapshot_plan(
    lock_path: Path,
    *,
    locale: str = "en_US",
) -> tuple[ChampionSnapshotSpec, ...]:
    """Build deterministic metadata and calculation-detail requests.

    :param lock_path: Patch lock supplying versions, base URLs, and the roster.
    :param locale: Locale requested from Data Dragon and recorded for both sources.
    :return: Three snapshot specifications per roster champion.
    """

    lock = _load_document(lock_path.resolve())
    game_patch = lock.get("game_patch")
    data_dragon = lock.get("upstreams", {}).get("data_dragon", {})
    community_dragon = lock.get("upstreams", {}).get("community_dragon", {})
    if not isinstance(game_patch, str) or not game_patch:
        raise ChampionSnapshotError("patch lock has no game_patch")
    if community_dragon.get("status") != "LOCKED":
        raise ChampionSnapshotError("Community Dragon must be locked before collecting profiles")
    data_build = data_dragon.get("build")
    community_base = community_dragon.get("base_url")
    if not isinstance(data_build, str) or not isinstance(community_base, str):
        raise ChampionSnapshotError("patch lock has incomplete upstream metadata")

    specs: list[ChampionSnapshotSpec] = []
    for champion in load_champion_roster(lock_path, locale=locale):
        specs.extend(
            (
                ChampionSnapshotSpec(
                    champion=champion,
                    source="DATA_DRAGON",
                    kind=ChampionSnapshotKind.DATA_DRAGON_DETAIL,
                    url=(
                        f"https://ddragon.leagueoflegends.com/cdn/{data_build}/data/"
                        f"{locale}/champion/{champion.key}.json"
                    ),
                    relative_path=(f"data/raw/{game_patch}/{locale}/champion/{champion.key}.json"),
                    locale=locale,
                ),
                ChampionSnapshotSpec(
                    champion=champion,
                    source="COMMUNITY_DRAGON",
                    kind=ChampionSnapshotKind.COMMUNITY_PROFILE,
                    url=(
                        f"{community_base.rstrip('/')}/plugins/rcp-be-lol-game-data/"
                        "global/default/v1/champions/"
                        f"{champion.numeric_id}.json"
                    ),
                    relative_path=(
                        f"data/raw/{game_patch}/communitydragon/champions/"
                        f"{champion.numeric_id}.json"
                    ),
                    locale=locale,
                ),
                ChampionSnapshotSpec(
                    champion=champion,
                    source="COMMUNITY_DRAGON",
                    kind=ChampionSnapshotKind.COMMUNITY_BIN,
                    url=(
                        f"{community_base.rstrip('/')}/game/data/characters/"
                        f"{champion.key.lower()}/{champion.key.lower()}.bin.json"
                    ),
                    relative_path=(
                        f"data/raw/{game_patch}/communitydragon/champions/"
                        f"{champion.key.lower()}.bin.json"
                    ),
                    locale=locale,
                ),
            )
        )
    return tuple(specs)


def _download_bytes(url: str) -> bytes:
    """Download a snapshot only when the build-time CLI explicitly runs.

    :param url: Patch-specific upstream URL from the generated collection plan.
    :return: Exact response body used for validation and hashing.
    """

    request = Request(url, headers={"User-Agent": "rift-foundry/0.1 champion-snapshot"})
    with urlopen(request) as response:
        return response.read()


def _validate_payload(spec: ChampionSnapshotSpec, payload: bytes) -> None:
    """Reject source documents that do not identify the planned champion.

    :param spec: Expected champion and source for the response.
    :param payload: Exact upstream response body.
    :return: None after the response identity and required detail fields match.
    """

    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ChampionSnapshotError(f"invalid JSON from {spec.url}: {error}") from error
    if not isinstance(document, dict):
        raise ChampionSnapshotError(f"snapshot response is not an object: {spec.url}")

    if spec.kind is ChampionSnapshotKind.DATA_DRAGON_DETAIL:
        records = document.get("data")
        record = records.get(spec.champion.key) if isinstance(records, dict) else None
        spells = record.get("spells") if isinstance(record, dict) else None
        if (
            not isinstance(record, dict)
            or str(record.get("key")) != str(spec.champion.numeric_id)
            or not isinstance(spells, list)
        ):
            raise ChampionSnapshotError(f"Data Dragon detail does not match {spec.champion.key}")
        return

    if spec.kind is ChampionSnapshotKind.COMMUNITY_PROFILE:
        spells = document.get("spells")
        if document.get("id") != spec.champion.numeric_id or not isinstance(spells, list):
            raise ChampionSnapshotError(
                f"Community Dragon profile does not match {spec.champion.key}"
            )
        return

    expected_root = f"characters/{spec.champion.key}/".casefold()
    identity_paths = (
        key.casefold()
        for key in document
        if isinstance(key, str) and not (key.startswith("{") and key.endswith("}"))
    )
    if not any(path.startswith(expected_root) for path in identity_paths):
        raise ChampionSnapshotError(f"Community Dragon BIN does not match {spec.champion.key}")


def _safe_path(root: Path, relative_path: str) -> Path:
    """Resolve a planned file while preventing traversal outside the repository.

    :param root: Repository root under which snapshot paths are installed.
    :param relative_path: Repository-relative path generated by the plan.
    :return: Resolved path proven to remain beneath ``root``.
    """

    root = root.resolve()
    target = (root / relative_path).resolve()
    if not target.is_relative_to(root):
        raise ChampionSnapshotError(f"snapshot path escapes repository: {relative_path}")
    return target


def _write_atomic(path: Path, payload: bytes) -> None:
    """Install bytes atomically without exposing a partial snapshot or lock.

    :param path: Final file path within the repository.
    :param payload: Fully validated bytes to install.
    :return: None after replacement and directory synchronization by the OS.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".snapshot-", delete=False
        ) as file:
            temporary_path = Path(file.name)
            file.write(payload)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _is_trusted_existing(
    root: Path,
    entry: dict[str, Any],
    spec: ChampionSnapshotSpec | None = None,
) -> bool:
    """Check whether a lock entry still authenticates the intended snapshot.

    :param root: Repository root used to resolve the entry path.
    :param entry: Existing patch-lock file declaration.
    :param spec: Optional collection specification whose metadata must also match.
    :return: ``True`` when the declared file exists and matches its digest.
    """

    if spec is not None and (
        entry.get("source") != spec.source
        or entry.get("role") != "CHAMPIONS"
        or entry.get("url") != spec.url
        or entry.get("locale") != spec.locale
    ):
        return False
    target = _safe_path(root, entry["path"])
    if not target.is_file() or _sha256_bytes(target.read_bytes()) != entry.get("sha256"):
        return False
    if spec is not None:
        try:
            _validate_payload(spec, target.read_bytes())
        except ChampionSnapshotError:
            return False
    return True


def _timestamp(value: str | None) -> str:
    """Choose an explicit test timestamp or generate a current UTC timestamp.

    :param value: Optional ISO-8601 timestamp supplied by deterministic callers.
    :return: Timestamp stored on newly fetched lock entries.
    """

    return value or datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def sync_champion_snapshots(
    lock_path: Path,
    *,
    repository: Path,
    locale: str = "en_US",
    refresh: bool = False,
    fetcher: SnapshotFetcher = _download_bytes,
    retrieved_at: str | None = None,
) -> dict[str, int]:
    """Collect every detailed champion document and atomically update the lock.

    All responses are fetched and validated before any new bytes are installed. Existing
    files are reused only when their lock digest still matches, preserving an offline
    second run. The function is build-time infrastructure and is never imported by the
    runtime recommendation path.

    :param lock_path: Patch lock updated with one entry per source and champion.
    :param repository: Repository root receiving planned snapshot paths.
    :param locale: Data Dragon detail locale and roster-summary locale.
    :param refresh: Whether to fetch even snapshots already authenticated by the lock.
    :param fetcher: Injectable byte fetcher; tests provide an entirely local substitute.
    :param retrieved_at: Optional deterministic timestamp for newly fetched entries.
    :return: Roster, fetched, reused, and total managed snapshot counts.
    """

    lock_path = lock_path.resolve()
    repository = repository.resolve()
    lock = _load_document(lock_path)
    plan = build_champion_snapshot_plan(lock_path, locale=locale)
    existing_by_path = {entry["path"]: entry for entry in lock.get("files", [])}
    resolved_entries: dict[str, dict[str, Any]] = {}
    pending_payloads: dict[str, bytes] = {}
    reused = 0
    fetched = 0
    timestamp = _timestamp(retrieved_at)

    for spec in plan:
        existing = existing_by_path.get(spec.relative_path)
        if (
            not refresh
            and existing is not None
            and _is_trusted_existing(repository, existing, spec)
        ):
            resolved_entries[spec.relative_path] = existing
            reused += 1
            continue

        payload = fetcher(spec.url)
        _validate_payload(spec, payload)
        pending_payloads[spec.relative_path] = payload
        resolved_entries[spec.relative_path] = {
            "source": spec.source,
            "role": "CHAMPIONS",
            "url": spec.url,
            "path": spec.relative_path,
            "locale": spec.locale,
            "sha256": _sha256_bytes(payload),
            "retrieved_at": timestamp,
        }
        fetched += 1

    for relative_path, payload in pending_payloads.items():
        _write_atomic(_safe_path(repository, relative_path), payload)

    managed_paths = {spec.relative_path for spec in plan}
    unrelated_entries = [
        entry for entry in lock.get("files", []) if entry.get("path") not in managed_paths
    ]
    lock["files"] = unrelated_entries + [resolved_entries[spec.relative_path] for spec in plan]
    rendered_lock = (json.dumps(lock, ensure_ascii=False, indent=2) + "\n").encode()
    _write_atomic(lock_path, rendered_lock)
    return {
        "roster": len(plan) // 3,
        "fetched": fetched,
        "reused": reused,
        "snapshots": len(plan),
    }


def _managed_keys(
    specs: Iterable[ChampionSnapshotSpec],
    lock: dict[str, Any],
    kind: ChampionSnapshotKind,
    root: Path,
) -> set[str]:
    """Find champion keys whose planned path is authenticated by the lock.

    :param specs: Complete expected snapshot plan.
    :param lock: Parsed patch-lock document being audited.
    :param kind: Required artifact type whose managed paths are counted.
    :param root: Repository root used to authenticate declared local files.
    :return: Champion keys with matching metadata, identity, and file digest.
    """

    entries = {entry.get("path"): entry for entry in lock.get("files", [])}
    return {
        spec.champion.key
        for spec in specs
        if spec.kind is kind
        and (entry := entries.get(spec.relative_path)) is not None
        and _is_trusted_existing(root, entry, spec)
    }


def audit_champion_snapshot_coverage(
    lock_path: Path,
    *,
    locale: str = "en_US",
) -> ChampionSnapshotCoverage:
    """Compare locked detailed files with the authoritative champion roster.

    :param lock_path: Patch lock whose declared coverage is inspected.
    :param locale: Data Dragon roster and detail locale to audit.
    :return: Coverage counts and missing-champion lists for all three artifacts.
    """

    lock = _load_document(lock_path.resolve())
    specs = build_champion_snapshot_plan(lock_path, locale=locale)
    roster = {spec.champion.key for spec in specs}
    root = lock_path.resolve().parent
    data_dragon = _managed_keys(specs, lock, ChampionSnapshotKind.DATA_DRAGON_DETAIL, root)
    community_profile = _managed_keys(specs, lock, ChampionSnapshotKind.COMMUNITY_PROFILE, root)
    community_bin = _managed_keys(specs, lock, ChampionSnapshotKind.COMMUNITY_BIN, root)
    return ChampionSnapshotCoverage(
        roster_count=len(roster),
        data_dragon_detail_count=len(data_dragon),
        community_profile_count=len(community_profile),
        community_bin_count=len(community_bin),
        missing_data_dragon_detail=tuple(sorted(roster - data_dragon)),
        missing_community_profile=tuple(sorted(roster - community_profile)),
        missing_community_bin=tuple(sorted(roster - community_bin)),
    )


def main() -> None:
    """Run the detailed champion snapshot build-time command.

    :return: None.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("audit", "sync"))
    parser.add_argument("--lock", type=Path, default=Path("patch.lock.json"))
    parser.add_argument("--repository", type=Path, default=Path("."))
    parser.add_argument("--locale", default="en_US")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    if args.command == "audit":
        coverage = audit_champion_snapshot_coverage(args.lock, locale=args.locale)
        print(
            f"roster={coverage.roster_count} "
            f"data_dragon_detail={coverage.data_dragon_detail_count} "
            f"community_profile={coverage.community_profile_count} "
            f"community_bin={coverage.community_bin_count} complete={coverage.complete}"
        )
        return
    result = sync_champion_snapshots(
        args.lock,
        repository=args.repository,
        locale=args.locale,
        refresh=args.refresh,
    )
    print(
        f"champion snapshots synchronized: roster={result['roster']} "
        f"fetched={result['fetched']} reused={result['reused']}"
    )


if __name__ == "__main__":
    main()
