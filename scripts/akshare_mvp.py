#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import akshare as ak
import pandas as pd


@dataclass
class SnapshotPaths:
    markdown: Path


def _safe_call(name: str, fn: Callable[[], pd.DataFrame]) -> Optional[pd.DataFrame]:
    try:
        df = fn()
        if df is None:
            return None
        if not isinstance(df, pd.DataFrame):
            return None
        return df
    except Exception as exc:
        print(f"[warn] {name} failed: {type(exc).__name__}: {exc}")
        return None


def _to_md_table(df: pd.DataFrame, max_rows: int = 20) -> str:
    view = df.head(max_rows).copy()
    return view.to_markdown(index=False)


def build_market_snapshot(max_rows: int = 20) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: list[str] = []
    lines.append("# A股市场快照（AkShare MVP）")
    lines.append("")
    lines.append(f"**生成时间**: {now}")
    lines.append("")

    spot = _safe_call("stock_zh_a_spot_em", lambda: ak.stock_zh_a_spot_em())
    if spot is not None and not spot.empty:
        # Normalize common columns
        col_map = {
            "代码": "code",
            "名称": "name",
            "最新价": "last",
            "涨跌幅": "pct",
            "涨跌额": "chg",
            "成交量": "vol",
            "成交额": "amount",
            "振幅": "amp",
            "换手率": "turnover",
            "市盈率-动态": "pe_ttm",
            "总市值": "mktcap",
        }
        keep_cols = [c for c in col_map.keys() if c in spot.columns]
        spot2 = spot[keep_cols].rename(columns=col_map)

        # Ensure pct numeric
        if "pct" in spot2.columns:
            spot2["pct"] = pd.to_numeric(spot2["pct"], errors="coerce")

        lines.append("## 涨跌幅排行")
        lines.append("")
        if "pct" in spot2.columns:
            gainers = spot2.sort_values("pct", ascending=False)
            losers = spot2.sort_values("pct", ascending=True)
            lines.append("### 涨幅 Top")
            lines.append("")
            lines.append(_to_md_table(gainers, max_rows=max_rows))
            lines.append("")
            lines.append("### 跌幅 Top")
            lines.append("")
            lines.append(_to_md_table(losers, max_rows=max_rows))
            lines.append("")
        else:
            lines.append("- 未找到涨跌幅字段（pct）")
            lines.append("")

        lines.append("## 全市场概览（抽样）")
        lines.append("")
        lines.append(_to_md_table(spot2, max_rows=max_rows))
        lines.append("")
    else:
        lines.append("## 涨跌幅排行")
        lines.append("")
        lines.append("- 获取 A 股实时行情失败（stock_zh_a_spot_em）")
        lines.append("")

    # Industry boards
    ind = _safe_call("stock_board_industry_name_em", lambda: ak.stock_board_industry_name_em())
    if ind is not None and not ind.empty:
        lines.append("## 行业板块（东方财富）")
        lines.append("")
        # Common columns: 名称, 最新价, 涨跌幅, 领涨股
        cols = [c for c in ["板块名称", "名称", "最新价", "涨跌幅", "领涨股", "领涨股-涨跌幅", "上涨家数", "下跌家数"] if c in ind.columns]
        view = ind[cols].copy()
        if "涨跌幅" in view.columns:
            view["涨跌幅"] = pd.to_numeric(view["涨跌幅"], errors="coerce")
            view = view.sort_values("涨跌幅", ascending=False)
        lines.append(_to_md_table(view, max_rows=max_rows))
        lines.append("")
    else:
        lines.append("## 行业板块（东方财富）")
        lines.append("")
        lines.append("- 获取行业板块失败（stock_board_industry_name_em）")
        lines.append("")

    # Concept boards
    concept = _safe_call("stock_board_concept_name_em", lambda: ak.stock_board_concept_name_em())
    if concept is not None and not concept.empty:
        lines.append("## 概念板块（东方财富）")
        lines.append("")
        cols = [c for c in ["板块名称", "名称", "最新价", "涨跌幅", "领涨股", "领涨股-涨跌幅", "上涨家数", "下跌家数"] if c in concept.columns]
        view = concept[cols].copy()
        if "涨跌幅" in view.columns:
            view["涨跌幅"] = pd.to_numeric(view["涨跌幅"], errors="coerce")
            view = view.sort_values("涨跌幅", ascending=False)
        lines.append(_to_md_table(view, max_rows=max_rows))
        lines.append("")
    else:
        lines.append("## 概念板块（东方财富）")
        lines.append("")
        lines.append("- 获取概念板块失败（stock_board_concept_name_em）")
        lines.append("")

    # New highs (best-effort; function may vary)
    new_high = _safe_call("stock_zh_a_new_high (best-effort)", lambda: getattr(ak, "stock_zh_a_new_high", lambda: pd.DataFrame())())
    if new_high is not None and not new_high.empty:
        lines.append("## 创新高股票（best-effort）")
        lines.append("")
        lines.append(_to_md_table(new_high, max_rows=max_rows))
        lines.append("")

    return "\n".join(lines)


def write_snapshot(project_root: Path, max_rows: int) -> SnapshotPaths:
    out_dir = project_root / "data" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = out_dir / f"market_snapshot_{ts}.md"
    md_path.write_text(build_market_snapshot(max_rows=max_rows), encoding="utf-8")
    return SnapshotPaths(markdown=md_path)


def main():
    parser = argparse.ArgumentParser(description="AkShare market snapshot MVP")
    parser.add_argument("--max-rows", type=int, default=20, help="Max rows per table")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    paths = write_snapshot(project_root, max_rows=int(args.max_rows))
    print(f"✅ market snapshot saved: {paths.markdown}")


if __name__ == "__main__":
    main()

