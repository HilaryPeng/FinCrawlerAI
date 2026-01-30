"""Crawl state helpers."""

import json
from pathlib import Path
from typing import Dict, Any


def load_state(state_file: Path) -> Dict[str, Any]:
    """Load crawl state from file."""
    if not state_file.exists():
        return {}
    try:
        with state_file.open("r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return {}


def save_state(state_file: Path, state: Dict[str, Any]) -> None:
    """Save crawl state to file."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with state_file.open("w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)
