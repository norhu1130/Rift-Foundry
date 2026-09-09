"""Web service and local HTTP delivery tests."""

from __future__ import annotations

import json
from collections.abc import Callable
from email.message import Message
from http import HTTPStatus
from io import BytesIO
from pathlib import Path
from threading import BoundedSemaphore

import pytest

from lol_build.application.web.server import (
    _ERROR_STATUS,
    STATIC_ROOT,
    WebHandler,
    create_server,
)
from lol_build.application.web.service import WebRequestError, WebService

ROOT = Path(__file__).resolve().parents[1]


class StubWebService:
    """Return fixed values so HTTP behavior is tested without running build search."""

    def catalog(self) -> dict[str, object]:
        """Return a minimal catalog response."""

        return {"patch": "test", "champions": [], "items": []}

    def evaluate(self, payload: object) -> dict[str, object]:
        """Echo a fixed evaluation marker."""

        return {"kind": "evaluation", "payload": payload}

    def recommend(
        self,
        payload: object,
        *,
        progress: Callable[[str], None] | None = None,
        workers: int | None = None,
    ) -> dict[str, object]:
        """Echo a fixed recommendation marker."""

        if progress is not None:
            progress("3/7 테스트 후보 평가 중")
        return {"kind": "recommendation", "payload": payload}


def test_catalog_exposes_locked_champions_and_complete_items() -> None:
    service = WebService(ROOT)

    catalog = service.catalog()

    champion_keys = {champion["key"] for champion in catalog["champions"]}
    assert {"Darius", "Garen", "Aatrox", "Ahri"} <= champion_keys
    assert (
        next(champion for champion in catalog["champions"] if champion["key"] == "Darius")["name"]
        == "다리우스"
    )
    trinity_force = next(item for item in catalog["items"] if item["id"] == 3078)
    assert trinity_force["name"] == "삼위일체"
    assert trinity_force["icon"]["url"].startswith("/assets/item-sprites/item")
    assert service.item_sprite_path("item0.png").read_bytes().startswith(b"\x89PNG")
    assert catalog["runtime_network_calls"] == 0


def test_catalog_champion_status_matches_manifest_module_folder() -> None:
    """Keep the UI-facing todo/modeled_unverified/wip/curated status honest.

    The champion package folder is the single source of truth for both
    maturity and (within ``MODELED_UNVERIFIED``) mechanism-gap status, so the
    catalog's ``status`` must equal the folder segment of the manifest's
    ``module_name`` for every champion.

    :return: None.
    """

    from lol_build.cogs.manifest import CHAMPION_COG_MANIFEST

    specs_by_key = {spec.champion_key: spec for spec in CHAMPION_COG_MANIFEST}

    service = WebService(ROOT)
    catalog = service.catalog()

    assert {champion["status"] for champion in catalog["champions"]} <= {
        "todo",
        "modeled_unverified",
        "wip",
        "curated",
    }
    for champion in catalog["champions"]:
        spec = specs_by_key[champion["key"]]
        expected_folder = spec.module_name.split(".")[3]
        assert champion["status"] == expected_folder, champion["key"]


def test_web_payload_is_bounded_before_engine_dispatch() -> None:
    service = WebService(ROOT)

    with pytest.raises(WebRequestError, match="최대 3코어"):
        service.evaluate(
            {
                "actor": "Darius",
                "opponent": "Garen",
                "actor_item_ids": [3006, 3031, 3072, 3084],
            }
        )
    with pytest.raises(WebRequestError, match="알 수 없는 챔피언"):
        service.evaluate({"actor": "NotAChampion", "opponent": "Garen"})


def test_web_service_runs_role_symmetric_matchup() -> None:
    service = WebService(ROOT)

    result = service.evaluate(
        {
            "actor": "Garen",
            "opponent": "Aatrox",
            "actor_item_ids": [],
            "opponent_item_ids": [],
        }
    )

    assert result["resolved"]["actor_cog"] == "champion:Garen"
    assert result["resolved"]["opponent_cog"] == "champion:Aatrox"
    assert result["timeline"]["duration_ms"] == 8000


def test_local_server_delivers_assets_and_json_api(capsys: pytest.CaptureFixture[str]) -> None:
    handler = object.__new__(WebHandler)
    handler.service = StubWebService()
    handler.path = "/"
    handler.wfile = BytesIO()
    handler.headers = Message()
    recorded: dict[str, object] = {"headers": {}}
    handler.send_response = lambda status: recorded.update(status=status)
    handler.send_header = lambda key, value: recorded["headers"].update({key: value})
    handler.end_headers = lambda: None

    handler.do_GET()

    assert recorded["status"] == 200
    assert b"Rift Foundry" in handler.wfile.getvalue()
    assert "Content-Security-Policy" in recorded["headers"]

    handler.path = "/api/recommend"
    handler.wfile = BytesIO()
    encoded = json.dumps({"actor": "Darius"}).encode("utf-8")
    handler.rfile = BytesIO(encoded)
    handler.headers["Content-Type"] = "application/json"
    handler.headers["Content-Length"] = str(len(encoded))

    handler.do_POST()

    document = json.loads(handler.wfile.getvalue())
    assert recorded["status"] == 200
    assert document["data"]["kind"] == "recommendation"
    console = capsys.readouterr().out
    assert "START 후보 빌드 계산 요청 수신" in console
    assert "3/7 테스트 후보 평가 중" in console
    assert "DONE 후보 빌드 계산 완료" in console


def test_static_ui_has_no_external_runtime_assets() -> None:
    """Reject external network references while allowing the SVG XML namespace.

    ``favicon.svg``'s root element must declare
    ``xmlns="http://www.w3.org/2000/svg"`` to parse as valid standalone SVG in
    every browser when loaded directly (not inlined in HTML); this is a
    namespace identifier, never fetched at runtime, so it is excluded from the
    external-reference scan rather than loosening the scan itself.
    """

    assets = "\n".join(
        path.read_text(encoding="utf-8") for path in STATIC_ROOT.iterdir() if path.is_file()
    )
    scanned = assets.replace("http://www.w3.org/2000/svg", "")

    assert "https://" not in scanned
    assert "http://" not in scanned
    assert "왜 이 빌드인가?" in assets
    assert "아이템별 역할" in assets
    assert "게임 상태는 계산하지 않았습니다." in assets
    assert "체급 조건을 통과했지만 피해량 하한을 넘긴 후보가 없어" in assets


def test_team_rosters_are_validated_before_engine_dispatch() -> None:
    """Reject malformed team rosters with field-specific errors."""
    service = WebService(ROOT)
    base = {"actor": "Darius", "opponent": "Garen"}

    with pytest.raises(WebRequestError) as too_many:
        service._request({**base, "allies": [{"champion": "Lux"}] * 5})
    assert too_many.value.code == "TOO_MANY_PARTICIPANTS"

    with pytest.raises(WebRequestError) as not_a_list:
        service._request({**base, "additional_opponents": {"champion": "Lux"}})
    assert not_a_list.value.code == "INVALID_TEAM"

    with pytest.raises(WebRequestError) as not_an_object:
        service._request({**base, "allies": ["Lux"]})
    assert not_an_object.value.code == "INVALID_TEAM"

    with pytest.raises(WebRequestError) as unknown:
        service._request({**base, "allies": [{"champion": "NotAChampion"}]})
    assert unknown.value.code == "UNKNOWN_CHAMPION"


def test_both_team_rosters_reach_the_request() -> None:
    """Carry allies and further opponents through to the engine request."""
    service = WebService(ROOT)
    request = service._request(
        {
            "actor": "Darius",
            "opponent": "Garen",
            "allies": [{"champion": "Lux", "item_ids": [6653]}],
            "additional_opponents": [{"champion": "Ahri", "item_ids": [3020, 3089]}],
        }
    )

    assert [spec.champion for spec in request.allies] == ["Lux"]
    assert request.allies[0].item_ids == (6653,)
    assert [spec.champion for spec in request.additional_opponents] == ["Ahri"]
    assert len(request.opponent_specs) == 2
    assert len(request.ally_specs) == 2


def test_an_omitted_team_keeps_the_duel_contract() -> None:
    """Leave a request without rosters as the original two-champion matchup."""
    service = WebService(ROOT)
    request = service._request({"actor": "Darius", "opponent": "Garen"})

    assert request.allies == ()
    assert request.additional_opponents == ()
    assert len(request.opponent_specs) == 1
    assert len(request.ally_specs) == 1


def test_static_ui_exposes_team_slots_wired_to_the_api() -> None:
    """Keep the team markup, its script wiring, and the API field names aligned."""
    markup = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'id="allyColumn"' in markup
    assert 'id="enemyColumn"' in markup
    assert 'id="teamSummary"' in markup
    # The payload must use the names the Web service validates.
    assert "allies: teamPayload(TEAM_SLOTS.ally)" in script
    assert "additional_opponents: teamPayload(TEAM_SLOTS.enemy)" in script
    # Every generated slot id the script uses must have matching DOM plumbing.
    for slot in ("ally1", "ally4", "enemy1", "enemy4"):
        assert slot in script


def test_a_second_recommendation_is_refused_rather_than_queued() -> None:
    """Refuse work past capacity so worker processes cannot multiply.

    Each admitted search fans out across worker processes. Admitting requests
    freely would multiply processes instead of throughput, so a caller arriving
    while the server is busy gets a retryable 503 immediately.
    """
    handler = object.__new__(WebHandler)
    handler.service = StubWebService()
    handler.recommendation_slots = BoundedSemaphore(1)
    handler.recommendation_workers = 1

    # Hold the only slot, as an in-flight search would.
    assert handler.recommendation_slots.acquire(blocking=False)
    try:
        with pytest.raises(WebRequestError) as refused:
            handler._recommend_admitted({"actor": "Darius"})
    finally:
        handler.recommendation_slots.release()

    assert refused.value.code == "SERVER_BUSY"
    assert _ERROR_STATUS[refused.value.code] is HTTPStatus.SERVICE_UNAVAILABLE


def test_an_admitted_recommendation_releases_its_slot() -> None:
    """Return capacity after each search, including when the search fails."""
    handler = object.__new__(WebHandler)
    handler.service = StubWebService()
    handler.recommendation_slots = BoundedSemaphore(1)
    handler.recommendation_workers = 1

    handler._recommend_admitted({"actor": "Darius"})

    assert handler.recommendation_slots.acquire(blocking=False)
    handler.recommendation_slots.release()


def test_cores_are_divided_between_admitted_searches() -> None:
    """Split the machine between admitted searches instead of oversubscribing."""
    single = create_server(ROOT, port=0, service=StubWebService())
    try:
        many = create_server(
            ROOT, port=0, service=StubWebService(), max_concurrent_recommendations=4
        )
    finally:
        single.server_close()
    try:
        assert single.RequestHandlerClass.recommendation_workers >= (
            many.RequestHandlerClass.recommendation_workers
        )
        assert many.RequestHandlerClass.recommendation_workers >= 1
    finally:
        many.server_close()

    with pytest.raises(ValueError):
        create_server(ROOT, port=0, service=StubWebService(), max_concurrent_recommendations=0)
