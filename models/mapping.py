from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Mapping:
    """A configured request-to-response mapping rule."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    method: str = "ANY"       # GET | POST | ANY
    url_path: str = ""         # e.g. /api/emark/start
    request_body: str = ""     # expected body for matching (can be partial)
    response_body: str = ""
    response_status: int = 200
    response_content_type: str = "application/json"
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "method": self.method,
            "url_path": self.url_path,
            "request_body": self.request_body,
            "response_body": self.response_body,
            "response_status": self.response_status,
            "response_content_type": self.response_content_type,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Mapping":
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            method=d.get("method", "ANY"),
            url_path=d.get("url_path", ""),
            request_body=d.get("request_body", ""),
            response_body=d.get("response_body", ""),
            response_status=d.get("response_status", 200),
            response_content_type=d.get("response_content_type", "application/json"),
            enabled=d.get("enabled", True),
        )


@dataclass
class RequestInfo:
    """Captured HTTP request data for display in the GUI."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    method: str = ""
    path: str = ""
    headers: dict = field(default_factory=dict)
    body: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    @property
    def summary(self) -> str:
        body_preview = self.body[:80] + "..." if len(self.body) > 80 else self.body
        return f"[{self.timestamp}] {self.method} {self.path}  {body_preview}"


class PendingRequest:
    """Holds a request that is waiting for a manual response from the GUI."""

    def __init__(self, request_info: RequestInfo):
        self.request_info = request_info
        self._response_body: Optional[str] = None
        self._response_status: int = 200
        self._response_content_type: str = "application/json"
        self._event = threading.Event()

    def wait_for_response(self, timeout: float = 60.0) -> tuple[str, int, str]:
        """Block until the GUI sets a response. Returns (body, status, content_type)."""
        if not self._event.wait(timeout):
            return (
                json.dumps({"error": "request timeout - no manual response"}),
                500,
                "application/json",
            )
        return self._response_body, self._response_status, self._response_content_type

    def set_response(self, body: str, status: int = 200, content_type: str = "application/json") -> None:
        self._response_body = body
        self._response_status = status
        self._response_content_type = content_type
        self._event.set()
