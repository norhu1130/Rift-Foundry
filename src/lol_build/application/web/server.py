"""Dependency-free local HTTP server for the offline Web UI."""

from __future__ import annotations

import argparse
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import count
from pathlib import Path
from threading import BoundedSemaphore, Lock
from time import perf_counter
from typing import Any
from urllib.parse import urlsplit

from lol_build.application.web.service import WebRequestError, WebService
from lol_build.buildtime.paths import repository_root
from lol_build.core.canonical import dumps

MAX_REQUEST_BYTES = 64 * 1024

#: Seconds a client may take to send or receive one request before its thread is
#: reclaimed. Without this a stalled peer holds a worker thread indefinitely.
SOCKET_TIMEOUT_SECONDS = 30.0

#: Recommendations that may run at once. Each one fans out across worker
#: processes, so admitting several at a time multiplies process count rather
#: than throughput. Extra callers are refused quickly instead of queueing.
DEFAULT_MAX_CONCURRENT_RECOMMENDATIONS = 1

#: Validation errors are the client's to fix and stay 400. Capacity refusal is
#: the server's own state and must be retryable, so it answers 503 instead.
_ERROR_STATUS = {"SERVER_BUSY": HTTPStatus.SERVICE_UNAVAILABLE}
STATIC_ROOT = Path(__file__).with_name("static")
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
}
_REQUEST_IDS = count(1)
_CONSOLE_LOCK = Lock()


def _console_progress(request_id: int, message: str) -> None:
    """Print one atomic recommendation progress line immediately.

    :param request_id: Process-local identifier joining concurrent request logs.
    :param message: Calculation milestone supplied by the recommendation engine.
    :return: None.
    """

    with _CONSOLE_LOCK:
        print(f"[추천 #{request_id:04d}] {message}", flush=True)


class WebHandler(BaseHTTPRequestHandler):
    """Serve the bundled UI and dispatch its bounded JSON endpoints."""

    service: WebService
    #: Replaced per server by :func:`create_server`. The defaults keep a handler
    #: constructed directly — in a test or an embedding — admitting work rather
    #: than failing on a missing attribute.
    recommendation_slots: BoundedSemaphore = BoundedSemaphore(
        DEFAULT_MAX_CONCURRENT_RECOMMENDATIONS
    )
    recommendation_workers: int = 1
    timeout = SOCKET_TIMEOUT_SECONDS

    def do_GET(self) -> None:
        """Serve health, catalog, or allowlisted static asset requests.

        :return: None.
        """

        path = urlsplit(self.path).path
        if path == "/api/health":
            self._write_json({"ok": True, "data": {"status": "ok"}})
            return
        if path == "/api/catalog":
            self._write_json({"ok": True, "data": self.service.catalog()})
            return
        if path.startswith("/assets/item-sprites/"):
            filename = path.removeprefix("/assets/item-sprites/")
            try:
                body = self.service.item_sprite_path(filename).read_bytes()
            except WebRequestError as error:
                self._write_json(
                    {"ok": False, "error": {"code": error.code, "message": str(error)}},
                    HTTPStatus.NOT_FOUND,
                )
                return
            self._write(body, HTTPStatus.OK, "image/png")
            return
        static = STATIC_FILES.get(path)
        if static is None:
            self._write_json(
                {"ok": False, "error": {"code": "NOT_FOUND", "message": "Not found"}},
                HTTPStatus.NOT_FOUND,
            )
            return
        filename, content_type = static
        body = (STATIC_ROOT / filename).read_bytes()
        self._write(body, HTTPStatus.OK, content_type)

    def do_POST(self) -> None:
        """Dispatch matchup evaluation and recommendation JSON requests.

        :return: None.
        """

        path = urlsplit(self.path).path
        if path not in {"/api/evaluate", "/api/recommend"}:
            self._write_json(
                {"ok": False, "error": {"code": "NOT_FOUND", "message": "Not found"}},
                HTTPStatus.NOT_FOUND,
            )
            return
        try:
            payload = self._read_json()
            data = (
                self._recommend_admitted(payload)
                if path == "/api/recommend"
                else self.service.evaluate(payload)
            )
        except WebRequestError as error:
            self._write_json(
                {"ok": False, "error": {"code": error.code, "message": str(error)}},
                _ERROR_STATUS.get(error.code, HTTPStatus.BAD_REQUEST),
            )
            return
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._write_json(
                {
                    "ok": False,
                    "error": {"code": "INVALID_JSON", "message": "올바른 JSON이 아닙니다."},
                },
                HTTPStatus.BAD_REQUEST,
            )
            return
        except Exception as error:
            self._write_json(
                {
                    "ok": False,
                    "error": {"code": "ENGINE_ERROR", "message": str(error)},
                },
                HTTPStatus.UNPROCESSABLE_ENTITY,
            )
            return
        self._write_json({"ok": True, "data": data})

    def _recommend_admitted(self, payload: Any) -> dict[str, Any]:
        """Run one recommendation while holding an admission slot.

        :param payload: Decoded JSON request forwarded to the Web service.
        :return: Canonical JSON-compatible recommendation document.
        :raises WebRequestError: If the server is already at capacity.
        """
        if not self.recommendation_slots.acquire(blocking=False):
            raise WebRequestError(
                "SERVER_BUSY",
                "다른 추천 계산이 진행 중입니다. 완료 후 다시 시도해 주세요.",
            )
        try:
            return self._recommend_with_progress(payload)
        finally:
            self.recommendation_slots.release()

    def _recommend_with_progress(self, payload: Any) -> dict[str, Any]:
        """Run one recommendation while streaming milestones to the server console.

        :param payload: Decoded JSON request forwarded to the Web service.
        :return: Canonical JSON-compatible recommendation document.
        """

        request_id = next(_REQUEST_IDS)
        started_at = perf_counter()
        _console_progress(request_id, "START 후보 빌드 계산 요청 수신")

        def publish(message: str) -> None:
            """Attach the active request identifier to an engine milestone.

            :param message: Human-readable progress message from the engine.
            :return: None.
            """

            _console_progress(request_id, message)

        try:
            result = self.service.recommend(
                payload, progress=publish, workers=self.recommendation_workers
            )
        except Exception:
            elapsed = perf_counter() - started_at
            _console_progress(request_id, f"FAILED {elapsed:.2f}초 후 계산 중단")
            raise
        elapsed = perf_counter() - started_at
        _console_progress(request_id, f"DONE 후보 빌드 계산 완료 · {elapsed:.2f}초")
        return result

    def _read_json(self) -> Any:
        """Read a bounded UTF-8 JSON request body.

        :return: Decoded JSON value.
        """

        if self.headers.get_content_type() != "application/json":
            raise WebRequestError("INVALID_CONTENT_TYPE", "application/json 요청만 지원합니다.")
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise WebRequestError("MISSING_LENGTH", "Content-Length가 필요합니다.")
        try:
            length = int(raw_length)
        except ValueError as error:
            raise WebRequestError("INVALID_LENGTH", "잘못된 Content-Length입니다.") from error
        if not 0 < length <= MAX_REQUEST_BYTES:
            raise WebRequestError("INVALID_LENGTH", "요청 본문 크기가 허용 범위를 벗어났습니다.")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _write_json(self, document: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        """Serialize a canonical JSON response.

        :param document: JSON-compatible response envelope.
        :param status: HTTP status sent with the response.
        :return: None.
        """

        self._write(dumps(document).encode("utf-8"), status, "application/json; charset=utf-8")

    def _write(self, body: bytes, status: HTTPStatus, content_type: str) -> None:
        """Send response bytes with browser hardening and no-store headers.

        :param body: Complete encoded response body.
        :param status: HTTP response status.
        :param content_type: MIME type and optional character encoding.
        :return: None.
        """

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        """Keep the embedded local server quiet during engine calculations.

        :param format: Standard-library access-log format string.
        :param args: Values interpolated by the default request logger.
        :return: None.
        """


def create_server(
    root: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    service: WebService | None = None,
    max_concurrent_recommendations: int = DEFAULT_MAX_CONCURRENT_RECOMMENDATIONS,
) -> ThreadingHTTPServer:
    """Create a local threaded server without starting its event loop.

    :param root: Project root containing locked engine data.
    :param host: Interface to bind; loopback is the safe default.
    :param port: TCP port, or zero to request an ephemeral test port.
    :param service: Optional application service used for dependency injection.
    :param max_concurrent_recommendations: Searches admitted at once. Each one
        spreads across worker processes, so the available cores are divided
        between the admitted searches rather than handed to each of them.
    :return: Configured HTTP server ready for ``serve_forever``.
    :raises ValueError: If fewer than one recommendation may be admitted.
    """

    if max_concurrent_recommendations < 1:
        raise ValueError("max_concurrent_recommendations must be at least one")
    # LOL_BUILD_WORKERS caps the worker budget on memory-constrained hosts;
    # every worker holds its own engine, and results do not depend on the count.
    cores = int(os.environ.get("LOL_BUILD_WORKERS", "0")) or os.cpu_count() or 1
    bound_handler = type(
        "BoundWebHandler",
        (WebHandler,),
        {
            "service": service or WebService(root),
            "recommendation_slots": BoundedSemaphore(max_concurrent_recommendations),
            "recommendation_workers": max(1, cores // max_concurrent_recommendations),
        },
    )
    server = ThreadingHTTPServer((host, port), bound_handler)
    server.daemon_threads = True
    return server


def main() -> None:
    """Run the local Web UI until interrupted.

    :return: None.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=repository_root())
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--max-concurrent-recommendations",
        type=int,
        default=DEFAULT_MAX_CONCURRENT_RECOMMENDATIONS,
        help="Searches admitted at once; further callers receive 503.",
    )
    args = parser.parse_args()
    server = create_server(
        args.root,
        host=args.host,
        port=args.port,
        max_concurrent_recommendations=args.max_concurrent_recommendations,
    )
    host, port = server.server_address[:2]
    print(f"Rift Foundry: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
