"""
Load and validate market daily OpenSpec files.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

from config.settings import get_config


@dataclass(frozen=True)
class MarketDailySpec:
    """Container for the active market daily OpenSpec payloads."""

    root: Path
    strategy: Dict[str, Any]
    data: Dict[str, Any]
    runtime: Dict[str, Any]
    presentation: Dict[str, Any]


def _project_root() -> Path:
    config = get_config()
    return Path(config.PROJECT_ROOT).resolve()


def _default_root() -> Path:
    env_value = os.getenv("MARKET_DAILY_OPENSPEC_ROOT", "").strip()
    if env_value:
        return Path(env_value).expanduser().resolve()
    return (_project_root() / "openspec").resolve()


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"OpenSpec file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in OpenSpec file: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"OpenSpec file must contain a JSON object: {path}")
    return data


def _require_keys(path: Path, payload: Dict[str, Any], keys: list[str]) -> None:
    missing = [key for key in keys if key not in payload]
    if missing:
        raise ValueError(f"OpenSpec file missing keys {missing}: {path}")


def _require_mapping(path: Path, payload: Dict[str, Any], key: str) -> Dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"OpenSpec key '{key}' must be an object: {path}")
    return value


def _validate_strategy(path: Path, payload: Dict[str, Any]) -> None:
    _require_keys(path, payload, ["board_feature", "stock_feature", "observation_pool", "strong_stock_pool"])
    board_feature = _require_mapping(path, payload, "board_feature")
    _require_keys(path, board_feature, ["weights", "negative_pct_penalties", "phase_thresholds"])

    stock_feature = _require_mapping(path, payload, "stock_feature")
    _require_keys(
        path,
        stock_feature,
        [
            "dragon_score",
            "center_score",
            "follow_score",
            "risk_thresholds",
            "risk_weights",
            "role_rules",
            "final_score_weights",
        ],
    )

    observation_pool = _require_mapping(path, payload, "observation_pool")
    _require_keys(
        path,
        observation_pool,
        ["top_board_limit", "top20_size", "backup_size", "max_per_board", "max_per_board_role", "role_targets"],
    )

    strong_stock_pool = _require_mapping(path, payload, "strong_stock_pool")
    _require_keys(
        path,
        strong_stock_pool,
        [
            "trend_channel",
            "emotion_channel",
            "capacity_bonus",
            "multi_channel_bonus",
            "capacity_label_min_amount",
            "board_concentration",
            "selection",
        ],
    )
    trend_channel = _require_mapping(path, strong_stock_pool, "trend_channel")
    _require_keys(
        path,
        trend_channel,
        [
            "min_amount",
            "min_trend_score",
            "min_medium_window_score",
            "min_weak_window_score",
            "min_medium_window_count",
            "window_weights",
            "window_score_bands",
        ],
    )
    emotion_channel = _require_mapping(path, strong_stock_pool, "emotion_channel")
    _require_keys(path, emotion_channel, ["min_amount", "limit_up_score", "streak_2_score", "streak_3_score"])
    board_concentration = _require_mapping(path, strong_stock_pool, "board_concentration")
    _require_keys(path, board_concentration, ["min_count", "min_amount"])
    selection = _require_mapping(path, strong_stock_pool, "selection")
    _require_keys(path, selection, ["main_pool_group", "main_pool_limit", "backup_size"])


def _validate_runtime(path: Path, payload: Dict[str, Any]) -> None:
    _require_keys(path, payload, ["quality", "pipeline"])
    quality = _require_mapping(path, payload, "quality")
    _require_keys(path, quality, ["baseline_quote_ratio", "thresholds", "blocked_checks", "publish_allow_statuses"])

    thresholds = _require_mapping(path, quality, "thresholds")
    _require_keys(path, thresholds, ["quotes", "boards", "limits", "breadth", "membership"])

    pipeline = _require_mapping(path, payload, "pipeline")
    _require_keys(path, pipeline, ["normal_run_steps", "rerun_same_day_steps"])


def _validate_presentation(path: Path, payload: Dict[str, Any]) -> None:
    _require_keys(path, payload, ["roles", "markdown", "html"])
    roles = _require_mapping(path, payload, "roles")
    _require_keys(path, roles, ["trend_strong", "emotion_strong", "watchlist"])
    markdown = _require_mapping(path, payload, "markdown")
    _require_keys(
        path,
        markdown,
        ["report_title", "market_overview", "top_boards", "observation_pool", "observation_reason", "role_distribution", "board_distribution", "strong_board_summary", "backup_pool"],
    )
    html = _require_mapping(path, payload, "html")
    _require_keys(path, html, ["page_title", "hero", "sections", "labels"])


def _validate_data(path: Path, payload: Dict[str, Any]) -> None:
    _require_keys(path, payload, ["tables", "contracts", "rebuild_dependencies"])
    tables = _require_mapping(path, payload, "tables")
    if not tables:
        raise ValueError(f"OpenSpec data.tables cannot be empty: {path}")


@lru_cache(maxsize=1)
def load_market_daily_spec(openspec_root: str | Path | None = None) -> MarketDailySpec:
    root = Path(openspec_root).expanduser().resolve() if openspec_root else _default_root()
    spec_root = root / "specs"

    strategy_path = spec_root / "strategy" / "current.json"
    data_path = spec_root / "data" / "current.json"
    runtime_path = spec_root / "runtime" / "current.json"
    presentation_path = spec_root / "presentation" / "current.json"

    strategy = _load_json(strategy_path)
    data = _load_json(data_path)
    runtime = _load_json(runtime_path)
    presentation = _load_json(presentation_path)

    _validate_strategy(strategy_path, strategy)
    _validate_data(data_path, data)
    _validate_runtime(runtime_path, runtime)
    _validate_presentation(presentation_path, presentation)

    return MarketDailySpec(
        root=root,
        strategy=strategy,
        data=data,
        runtime=runtime,
        presentation=presentation,
    )
