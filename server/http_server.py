from __future__ import annotations

import json
import logging
import queue
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import List, Optional
from urllib.parse import urlparse

from models.mapping import Mapping, RequestInfo, PendingRequest

logger = logging.getLogger(__name__)

# ---- shared state, set by the GUI / main thread --------------------
_mappings: List[Mapping] = []
_auto_reply: bool = False
_pending_queue: queue.Queue[PendingRequest] = queue.Queue()
_server_instance: Optional["MockServer"] = None


def get_mappings() -> List[Mapping]:
    return _mappings


def set_mappings(mappings: List[Mapping]) -> None:
    global _mappings
    _mappings = mappings


def set_auto_reply(enabled: bool) -> None:
    global _auto_reply
    _auto_reply = enabled


def get_pending_queue() -> queue.Queue[PendingRequest]:
    return _pending_queue


# ---- matching ------------------------------------------------------

def _is_json_subset(actual: dict | list, expected: dict | list) -> bool:
    """Return True if every key/value in *expected* is present in *actual* (recursive)."""
    if type(expected) is not type(actual):
        return False
    if isinstance(expected, dict):
        for k, v in expected.items():
            if k not in actual:
                return False
            if not _is_json_subset(actual[k], v):
                return False
        return True
    if isinstance(expected, list):
        if len(expected) > len(actual):
            return False
        for i, item in enumerate(expected):
            if not _is_json_subset(actual[i], item):
                return False
        return True
    return actual == expected


def _body_matches(cfg_body: str, actual_body: str) -> bool:
    """Check whether *cfg_body* JSON is a subset of *actual_body* JSON.
    Falls back to raw-string ``in`` when JSON parsing fails."""
    cfg_body = cfg_body.strip()
    if not cfg_body:
        return True
    try:
        cfg = json.loads(cfg_body)
        actual = json.loads(actual_body)
    except (json.JSONDecodeError, TypeError):
        return cfg_body in actual_body
    return _is_json_subset(actual, cfg)


def _find_mapping(method: str, path: str, body: str, mappings: List[Mapping]) -> Optional[Mapping]:
    for mp in mappings:
        if not mp.enabled:
            continue
        if mp.method != "ANY" and mp.method.upper() != method.upper():
            continue
        if mp.url_path and mp.url_path not in path:
            continue
        if not _body_matches(mp.request_body, body):
            continue
        return mp
    return None


# ---- request handler -----------------------------------------------

class _MockHandler(BaseHTTPRequestHandler):

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def do_PUT(self) -> None:
        self._handle("PUT")

    def do_DELETE(self) -> None:
        self._handle("DELETE")

    def do_PATCH(self) -> None:
        self._handle("PATCH")

    def _handle(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length).decode("utf-8", errors="replace") if content_length > 0 else ""

        headers = dict(self.headers)

        # --- try auto-reply -----------------------------------------
        if _auto_reply:
            mp = _find_mapping(method, path, raw_body, _mappings)
            if mp is not None:
                logger.info("auto-reply  matched  %s %s  →  mapping  %s", method, path, mp.name)
                self._send_response(mp.response_status, mp.response_body, mp.response_content_type)
                return

        # --- manual mode --------------------------------------------
        request_info = RequestInfo(
            method=method,
            path=path,
            headers=headers,
            body=raw_body,
        )

        pending = PendingRequest(request_info)
        _pending_queue.put(pending)
        logger.info("pending  %s %s  →  waiting for manual response", method, path)

        resp_body, resp_status, resp_ct = pending.wait_for_response(timeout=120.0)
        self._send_response(resp_status, resp_body, resp_ct)

    def _send_response(self, status: int, body: str, content_type: str) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args) -> None:
        logger.info("HTTP  %s", format % args)


# ---- server wrapper ------------------------------------------------

class MockServer:
    """Manages the HTTP server lifecycle in a background daemon thread."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8080):
        self.host = host
        self.port = port
        self._httpd: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    @property
    def is_running(self) -> bool:
        return self._httpd is not None and self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------
    def start(self) -> None:
        if self.is_running:
            return
        self._httpd = HTTPServer((self.host, self.port), _MockHandler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True, name="mock-http-server")
        self._thread.start()
        logger.info("server started on  %s:%d", self.host, self.port)

    # ------------------------------------------------------------------
    def stop(self) -> None:
        if self._httpd is None:
            return
        self._httpd.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=3)
        self._httpd = None
        self._thread = None
        logger.info("server stopped")
