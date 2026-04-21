#!/usr/bin/env python3
"""
Validate market daily OpenSpec files.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def main() -> int:
    from src.specs import load_market_daily_spec

    spec = load_market_daily_spec()
    payload = {
        "root": str(spec.root),
        "strategy_keys": sorted(spec.strategy.keys()),
        "data_keys": sorted(spec.data.keys()),
        "runtime_keys": sorted(spec.runtime.keys()),
        "presentation_keys": sorted(spec.presentation.keys()),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
