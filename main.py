"""
HTTP Mock Server — GUI application for mocking HTTP API responses.

Start with:
    python main.py
"""

from __future__ import annotations

import logging
import sys


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )

    from gui.app import MockServerGUI
    MockServerGUI()


if __name__ == "__main__":
    main()
