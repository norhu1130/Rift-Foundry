"""JSON-facing application service for the local Web UI."""

from __future__ import annotations

import json
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from lol_build.application.matchup import (
    MatchupEngine,
    MatchupRequest,
    ParticipantSpec,
)
from lol_build.application.progress import ProgressCallback, report_progress
from lol_build.cogs.base import ChampionCog
from lol_build.core.canonical import normalize

_CATALOG_STATUSES = frozenset({"todo", "modeled_unverified", "wip", "curated"})


def _catalog_status(cog: ChampionCog) -> str:
    """Derive the UI-facing todo/modeled_unverified/wip/curated status.

    The champion package folder (``lol_build.cogs.champions.<folder>.<stem>``)
    already encodes both ``CogMaturity`` and, for ``MODELED_UNVERIFIED``,
    whether a champion-scoped mechanism gap is documented (see
    ``tests/test_all_champion_modules.py``), so it is the single source of
    truth for this label rather than a maturity-only lookup.

    :param cog: Champion Cog instance loaded from the manifest.
    :return: One of ``_CATALOG_STATUSES``.
    """
    folder = type(cog).__module__.split(".")[3]
    assert folder in _CATALOG_STATUSES, folder
    return folder


class WebRequestError(ValueError):
    """Raised when a Web API request violates its public input contract."""

    def __init__(self, code: str, message: str) -> None:
        """Attach a stable machine code to a user-facing validation message.

        :param code: Stable error identifier returned by the JSON API.
        :param message: Human-readable explanation safe to display in the UI.
        :return: None.
        """

        super().__init__(message)
        self.code = code


class WebService:
    """Expose catalog, evaluation, and recommendation use cases as JSON values."""

    def __init__(self, root: Path, engine: MatchupEngine | None = None) -> None:
        """Create a service backed only by the repository's locked local data.

        :param root: Project root containing the patch lock and data snapshots.
        :param engine: Optional prebuilt matchup engine for tests or embedding.
        :return: None.
        """

        self.root = root.resolve()
        self.engine = engine or MatchupEngine(self.root)
        self._item_ids = frozenset(item["id"] for item in self.engine.complete_items)
        self._patch_lock = json.loads((self.root / "patch.lock.json").read_text(encoding="utf-8"))
        patch = self._patch_lock["game_patch"]
        self._localized_items = json.loads(
            (self.root / f"data/raw/{patch}/ko_KR/item.json").read_text(encoding="utf-8")
        )["data"]
        self._localized_champions = json.loads(
            (self.root / f"data/raw/{patch}/ko_KR/champion.json").read_text(encoding="utf-8")
        )["data"]
        self._item_sprites = frozenset(
            item["image"]["sprite"] for item in self._localized_items.values()
        )

    def catalog(self) -> dict[str, Any]:
        """Build the champion and complete-item catalog consumed by the UI.

        :return: Patch metadata plus stable champion and item option arrays.
        """

        champions = sorted(
            [
                {
                    "id": cog.champion_id,
                    "key": cog.champion_key,
                    "name": self._localized_champions[cog.champion_key]["name"],
                    "status": _catalog_status(cog),
                }
                for cog in self.engine.registry.walk_cogs()
            ],
            key=lambda champion: champion["name"],
        )
        items = []
        for item in self.engine.complete_items:
            localized = self._localized_items[str(item["id"])]
            image = localized["image"]
            items.append(
                {
                    "id": item["id"],
                    "name": localized["name"],
                    "cost": item["cost"]["total"],
                    "stats": tuple(sorted(item["stats"])),
                    "icon": {
                        "url": f"/assets/item-sprites/{image['sprite']}",
                        "column": image["x"] // image["w"],
                        "row": image["y"] // image["h"],
                        "columns": 10,
                        "rows": 7 if image["sprite"] == "item8.png" else 10,
                    },
                }
            )
        items.sort(key=lambda item: item["name"])
        return {
            "patch": self._patch_lock["game_patch"],
            "region": self._patch_lock["region"],
            "runtime_network_calls": 0,
            "champions": champions,
            "items": items,
        }

    def item_sprite_path(self, filename: str) -> Path:
        """Resolve one allowlisted item sprite from the locked patch snapshot.

        :param filename: Sprite basename declared by localized Data Dragon item metadata.
        :return: Existing local PNG path for the requested sprite.
        """

        if filename not in self._item_sprites:
            raise WebRequestError("UNKNOWN_ASSET", "알 수 없는 아이템 아이콘입니다.")
        path = self.root / "data/raw" / self._patch_lock["game_patch"] / "img/sprite" / filename
        if not path.is_file():
            raise WebRequestError("MISSING_ASSET", "로컬 아이템 아이콘이 없습니다.")
        return path

    def evaluate(self, payload: Any) -> dict[str, Any]:
        """Validate a Web payload and run a two-sided deterministic simulation.

        :param payload: Decoded JSON request containing participants and their builds.
        :return: Canonical JSON-compatible matchup evaluation.
        """

        request = self._request(payload)
        return normalize(asdict(self.engine.evaluate(request)))

    def recommend(
        self,
        payload: Any,
        *,
        progress: ProgressCallback | None = None,
        workers: int | None = None,
    ) -> dict[str, Any]:
        """Validate a Web payload and rank three actor build branches.

        :param payload: Decoded JSON request containing participants and opponent items.
        :param progress: Optional callback receiving live calculation milestones.
        :param workers: Worker processes the search may use. ``None`` lets the
            search size itself, which is only safe when one request runs at a
            time; a server serving several must divide its cores explicitly.
        :return: Canonical JSON-compatible recommendation and dispatch metadata.
        """

        request = self._request(payload)
        report_progress(progress, "1/7 입력 검증 완료")
        result = self.engine.recommend(request, progress=progress, workers=workers)
        document = normalize(asdict(result))
        report_progress(progress, "7/7 응답 직렬화 완료")
        return document

    def _request(self, payload: Any) -> MatchupRequest:
        """Convert untrusted decoded JSON into a bounded matchup request.

        :param payload: Decoded request body received from the local HTTP server.
        :return: Validated immutable request accepted by ``MatchupEngine``.
        """

        if not isinstance(payload, dict):
            raise WebRequestError("INVALID_JSON_OBJECT", "요청 본문은 JSON 객체여야 합니다.")
        actor = self._champion(payload.get("actor"), "actor")
        opponent = self._champion(payload.get("opponent"), "opponent")
        actor_items = self._item_list(payload.get("actor_item_ids", []), "actor_item_ids")
        opponent_items = self._item_list(payload.get("opponent_item_ids", []), "opponent_item_ids")
        level = self._bounded_int(payload.get("level", 13), "level", 1, 18)
        duration_ms = self._bounded_int(
            payload.get("duration_ms", 8000), "duration_ms", 1000, 60000
        )
        horizon_ms = self._bounded_int(
            payload.get("horizon_ms", 3000), "horizon_ms", 1, duration_ms
        )
        return MatchupRequest(
            actor,
            opponent,
            level=level,
            duration_ms=duration_ms,
            horizon_ms=horizon_ms,
            actor_item_ids=actor_items,
            opponent_item_ids=opponent_items,
            actor_bonus_health=self._nonnegative_decimal(
                payload.get("actor_bonus_health", "0"), "actor_bonus_health"
            ),
            opponent_bonus_health=self._nonnegative_decimal(
                payload.get("opponent_bonus_health", "0"), "opponent_bonus_health"
            ),
            additional_opponents=self._participant_team(
                payload.get("additional_opponents", []), "additional_opponents"
            ),
            allies=self._participant_team(payload.get("allies", []), "allies"),
        )

    def _participant_team(self, value: Any, field: str) -> tuple[ParticipantSpec, ...]:
        """Validate one side's members beyond the champion that leads it.

        :param value: JSON array of objects naming a champion and its build.
        :param field: Request field name included in validation messages.
        :return: Validated participant specifications in request order.
        :raises WebRequestError: If the roster or any member is malformed.
        """

        if not isinstance(value, list):
            raise WebRequestError("INVALID_TEAM", f"{field}는 배열이어야 합니다.")
        if len(value) > 4:
            raise WebRequestError(
                "TOO_MANY_PARTICIPANTS", f"{field}는 진영을 이끄는 챔피언 외 최대 4명입니다."
            )
        specs: list[ParticipantSpec] = []
        for index, entry in enumerate(value):
            if not isinstance(entry, dict):
                raise WebRequestError("INVALID_TEAM", f"{field}[{index}]는 객체여야 합니다.")
            specs.append(
                ParticipantSpec(
                    self._champion(entry.get("champion"), f"{field}[{index}]"),
                    self._item_list(entry.get("item_ids", []), f"{field}[{index}].item_ids"),
                    self._nonnegative_decimal(
                        entry.get("bonus_health", "0"), f"{field}[{index}].bonus_health"
                    ),
                )
            )
        return tuple(specs)

    def _champion(self, value: Any, field: str) -> str | int:
        """Resolve a champion alias while preserving the engine's accepted identity types.

        :param value: Champion name, key, or numeric identifier from the request.
        :param field: Request field name included in validation messages.
        :return: Alias accepted by the registered champion Cog.
        """

        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise WebRequestError("INVALID_CHAMPION", f"{field} 챔피언을 선택해 주세요.")
        if isinstance(value, str) and not value.strip():
            raise WebRequestError("INVALID_CHAMPION", f"{field} 챔피언을 선택해 주세요.")
        try:
            self.engine.registry.require_cog(value)
        except KeyError as error:
            raise WebRequestError("UNKNOWN_CHAMPION", f"알 수 없는 챔피언: {value}") from error
        return value

    def _item_list(self, value: Any, field: str) -> tuple[int, ...]:
        """Validate a unique ordered build of at most three complete items.

        :param value: JSON array of Riot item identifiers.
        :param field: Request field name included in validation messages.
        :return: Validated ordered item identifiers.
        """

        if not isinstance(value, list) or any(
            isinstance(item_id, bool) or not isinstance(item_id, int) for item_id in value
        ):
            raise WebRequestError("INVALID_ITEM_LIST", f"{field}는 아이템 ID 배열이어야 합니다.")
        if len(value) > 3:
            raise WebRequestError("TOO_MANY_ITEMS", "v1은 양쪽 모두 최대 3코어만 지원합니다.")
        if len(set(value)) != len(value):
            raise WebRequestError("DUPLICATE_ITEM", f"{field}에 같은 아이템이 중복됐습니다.")
        unknown = sorted(set(value) - self._item_ids)
        if unknown:
            raise WebRequestError("UNKNOWN_ITEM", f"현재 패치에 없는 완성 아이템: {unknown}")
        return tuple(value)

    @staticmethod
    def _bounded_int(value: Any, field: str, minimum: int, maximum: int) -> int:
        """Require a non-boolean integer inside an inclusive range.

        :param value: Decoded JSON scalar to validate.
        :param field: Request field name included in validation messages.
        :param minimum: Smallest accepted integer.
        :param maximum: Largest accepted integer.
        :return: Validated integer.
        """

        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise WebRequestError(
                "INVALID_INTEGER", f"{field}는 {minimum}~{maximum} 범위의 정수여야 합니다."
            )
        return value

    @staticmethod
    def _nonnegative_decimal(value: Any, field: str) -> Decimal:
        """Parse a finite non-negative decimal without accepting binary floats.

        :param value: Integer or decimal string supplied by the Web client.
        :param field: Request field name included in validation messages.
        :return: Validated exact decimal value.
        """

        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise WebRequestError("INVALID_DECIMAL", f"{field}는 0 이상의 숫자여야 합니다.")
        try:
            result = Decimal(value)
        except InvalidOperation as error:
            raise WebRequestError(
                "INVALID_DECIMAL", f"{field}는 0 이상의 숫자여야 합니다."
            ) from error
        if not result.is_finite() or result < 0:
            raise WebRequestError("INVALID_DECIMAL", f"{field}는 0 이상의 숫자여야 합니다.")
        return result
