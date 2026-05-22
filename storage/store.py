from __future__ import annotations

import json
import os
from typing import List

from models.mapping import Mapping


class ConfigStore:
    """JSON-file-backed persistence for Mapping rules."""

    def __init__(self, filepath: str | None = None):
        if filepath is None:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            filepath = os.path.join(base, "mappings.json")
        self.filepath = filepath
        self._ensure_file()

    # ------------------------------------------------------------------
    def _ensure_file(self) -> None:
        if not os.path.exists(self.filepath):
            self.save_all([])

    # ------------------------------------------------------------------
    def load_all(self) -> List[Mapping]:
        with open(self.filepath, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return [Mapping.from_dict(item) for item in data]

    def save_all(self, mappings: List[Mapping]) -> None:
        payload = [m.to_dict() for m in mappings]
        with open(self.filepath, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
