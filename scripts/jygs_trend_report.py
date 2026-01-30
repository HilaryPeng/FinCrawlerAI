#!/usr/bin/env python3
"""Text-only trend report for Jiuyangongshe (韭研公社) action feeds.

Inputs:
- data/processed/jiuyangongshe_action_YYYYMMDD_*.json

Outputs:
- data/processed/jygs_trend_<RUNDATE>/ (Markdown + JSON)

Notes:
- This is *text-only* analysis. It does NOT use price/volume/real fund flow.
- ST-related items are excluded entirely (per request).
"""

from __future__ import annotations

import json
import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from glob import glob
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


CODE_RE = re.compile(r"^(?:sh|sz|bj)\d{6}$", re.IGNORECASE)

# Text proxies
RUMOR_KW = ("网传", "未经证实", "市场猜测", "传闻")
HARD_KW = (
    "公告",
    "盘后公告",
    "晚公告",
    "签署",
    "中标",
    "拟",
    "协议",
    "要约",
    "增资",
    "收购",
    "重组",
    "转让",
    "订单",
    "合同",
    "项目",
    "落地",
)

LB_RE = re.compile(r"连板/形态:\s*([^\s]+)")
DAYS_BOARDS_RE = re.compile(r"(\d+)天(\d+)板")


def is_st_item(item: Dict[str, Any]) -> bool:
    tags = item.get("tags") or []
    if isinstance(tags, list) and any(str(t) == "ST板块" for t in tags):
        return True
    title = str(item.get("title") or "")
    content = str(item.get("content") or "")
    # Match '*ST' / 'ST' in stock short name context
    if re.search(r"\b\*?ST", title) or re.search(r"\b\*?ST", content):
        return True
    return False


def parse_date_from_filename(path: str) -> Optional[str]:
    base = os.path.basename(path)
    m = re.search(r"jiuyangongshe_action_(\d{8})_", base)
    return m.group(1) if m else None


def safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


@dataclass
class DayThemeMetrics:
    mentions: int
    breadth: int
    rumor_ratio: float
    hard_ratio: float
    lb_ratio: float
    score: float


@dataclass
class DayMetrics:
    date: str
    total_items: int
    lb_ratio_all: float
    rumor_ratio_all: float
    concentration_top1: float
    concentration_top3: float
    top_themes: List[Tuple[str, DayThemeMetrics]]
    rotation_overlap_top5: Optional[float]
    rotation_label: str


def compute_day(path: str) -> Tuple[str, Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    date = parse_date_from_filename(path)
    if not date:
        raise ValueError(f"Cannot parse date from filename: {path}")
    data = (doc.get("data") or {})
    raw = data.get("raw_news") or []
    if not isinstance(raw, list):
        raw = []

    # Filter out ST items entirely
    raw = [it for it in raw if isinstance(it, dict) and not is_st_item(it)]

    # If empty after filtering, return minimal structure
    ts_vals = [it.get("publish_ts") for it in raw if isinstance(it.get("publish_ts"), int)]
    tmin = min(ts_vals) if ts_vals else None
    tmax = max(ts_vals) if ts_vals else None
    span = max(1, (tmax - tmin)) if (tmin is not None and tmax is not None) else 1

    def early_factor(ts: int) -> float:
        if tmin is None or tmax is None:
            return 0.5
        return 1.0 - ((ts - tmin) / span)

    # Day-level proxies
    total = len(raw)
    rumor_n = 0
    lb_n = 0

    # Theme-level stats
    theme_mentions = Counter()
    theme_codes = defaultdict(set)
    theme_rumor = Counter()
    theme_hard = Counter()
    theme_lb = Counter()

    # Stock occurrences for watchlist
    stock_occ = defaultdict(list)  # code -> list[item]

    for it in raw:
        tags = it.get("tags") or []
        if not (isinstance(tags, list) and len(tags) >= 4):
            continue
        theme = str(tags[1])
        name = str(tags[2])
        code = str(tags[3])
        if not CODE_RE.match(code):
            continue

        content = str(it.get("content") or "")
        has_rumor = any(k in content for k in RUMOR_KW)
        has_lb = "连板/形态" in content
        has_hard = any(k in content for k in HARD_KW)

        theme_mentions[theme] += 1
        theme_codes[theme].add(code)
        if has_rumor:
            rumor_n += 1
            theme_rumor[theme] += 1
        if has_lb:
            lb_n += 1
            theme_lb[theme] += 1
        if has_hard:
            theme_hard[theme] += 1
        stock_occ[code].append(
            {
                "code": code,
                "name": name,
                "theme": theme,
                "title": it.get("title") or "",
                "content": content,
                "publish_time": it.get("publish_time") or "",
                "publish_ts": it.get("publish_ts"),
                "url": it.get("url") or "",
                "early": early_factor(safe_int(it.get("publish_ts"), 0)),
                "has_rumor": has_rumor,
                "has_lb": has_lb,
                "has_hard": has_hard,
            }
        )

    # Compute theme scores
    theme_metrics: Dict[str, DayThemeMetrics] = {}
    for theme, mentions in theme_mentions.items():
        breadth = len(theme_codes[theme])
        if mentions <= 0 or breadth <= 0:
            continue
        rumor_ratio = theme_rumor[theme] / mentions
        hard_ratio = theme_hard[theme] / mentions
        lb_ratio = theme_lb[theme] / mentions
        # Text-only "attention heat" score
        score = mentions * math.log(1 + breadth) * (1.0 + lb_ratio) * (1.0 + 0.6 * hard_ratio) * (1.0 - 0.5 * rumor_ratio)
        theme_metrics[theme] = DayThemeMetrics(
            mentions=mentions,
            breadth=breadth,
            rumor_ratio=rumor_ratio,
            hard_ratio=hard_ratio,
            lb_ratio=lb_ratio,
            score=score,
        )

    # Concentration
    ranked_themes = sorted(theme_metrics.items(), key=lambda kv: kv[1].score, reverse=True)
    top_themes = ranked_themes[:8]
    total_mentions = sum(m.mentions for m in theme_metrics.values())
    top1_share = (top_themes[0][1].mentions / total_mentions) if (total_mentions and top_themes) else 0.0
    top3_share = (sum(m.mentions for _, m in top_themes[:3]) / total_mentions) if total_mentions else 0.0

    # Day-level proxies
    lb_ratio_all = (lb_n / total) if total else 0.0
    rumor_ratio_all = (rumor_n / total) if total else 0.0

    return date, {
        "date": date,
        "raw": raw,
        "total": total,
        "theme_metrics": theme_metrics,
        "top_themes": top_themes,
        "concentration_top1": top1_share,
        "concentration_top3": top3_share,
        "lb_ratio_all": lb_ratio_all,
        "rumor_ratio_all": rumor_ratio_all,
        "stock_occ": stock_occ,
    }


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    sa, sb = set(a), set(b)
    if not (sa or sb):
        return 0.0
    return len(sa & sb) / len(sa | sb)


def rotation_label(overlap: float) -> str:
    if overlap >= 0.5:
        return "延续"
    if overlap <= 0.3:
        return "切换"
    return "分歧"


def extract_evidence(content: str) -> str:
    # Try to keep 1-2 strongest clauses.
    # Heuristic: split by digits enumerations "1" "2" ... and take first two segments.
    s = re.sub(r"\s+", " ", content).strip()
    parts = re.split(r"\s(?=\d{1,2})", s)
    if len(parts) <= 1:
        return s[:240]
    out = (parts[0] + " " + parts[1]).strip()
    return out[:240]


def build_watchlist(days: List[Dict[str, Any]], lookback_days: int = 3, topn: int = 20) -> List[Dict[str, Any]]:
    # Aggregate recent appearances by code
    by_code = defaultdict(lambda: {"name": "", "days": set(), "themes": Counter(), "items": []})
    recent = days[-lookback_days:] if len(days) >= lookback_days else days
    for d in recent:
        date = d["date"]
        for code, items in d["stock_occ"].items():
            for it in items:
                if is_st_item(it):
                    continue
            by_code[code]["name"] = items[0].get("name") or by_code[code]["name"]
            by_code[code]["days"].add(date)
            for it in items:
                by_code[code]["themes"][it.get("theme") or ""] += 1
                by_code[code]["items"].append(it)

    # Score using latest day theme scores and early/hard/lb
    latest = days[-1]
    theme_score_latest = {k: v.score for k, v in latest["theme_metrics"].items()}

    scored = []
    for code, info in by_code.items():
        items = sorted(info["items"], key=lambda x: safe_int(x.get("publish_ts"), 0), reverse=True)
        if not items:
            continue
        # Pick best item representation from latest day if present else most recent
        best = max(items, key=lambda x: (theme_score_latest.get(x.get("theme") or "", 0.0), x.get("has_hard"), x.get("early", 0.0)))
        theme = best.get("theme") or ""
        base = theme_score_latest.get(theme, 0.0)
        early = float(best.get("early", 0.5) or 0.5)
        hard = 1.0 + (0.4 if best.get("has_hard") else 0.0)
        rumor = 0.6 if best.get("has_rumor") else 1.0
        lbw = 1.0
        m = LB_RE.search(str(best.get("content") or ""))
        if m:
            m2 = DAYS_BOARDS_RE.search(m.group(1))
            if m2:
                boards = safe_int(m2.group(2), 0)
                lbw = 1.0 + min(0.8, boards / 10.0)
            else:
                lbw = 1.1

        score = base * (0.6 + 0.4 * early) * hard * rumor * lbw
        scored.append((score, code, info, best))

    scored.sort(reverse=True, key=lambda x: x[0])
    out = []
    for score, code, info, best in scored[:topn]:
        out.append(
            {
                "code": code,
                "name": info["name"],
                "theme": best.get("theme") or "",
                "recent_days": sorted(info["days"]),
                "evidence": extract_evidence(str(best.get("content") or "")),
                "source_url": best.get("url") or "",
                "score": round(float(score), 2),
                "rules": {
                    "keep_if": "次日该题材仍在Top3或该标的继续被点名",
                    "drop_if": "题材连续2天跌出Top5或标的连续3天未再出现",
                },
            }
        )
    return out


def build_report(days: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    # Overall theme leaderboard
    theme_total_score = Counter()
    theme_total_mentions = Counter()
    for d in days:
        for theme, m in d["theme_metrics"].items():
            theme_total_score[theme] += m.score
            theme_total_mentions[theme] += m.mentions

    top_overall = theme_total_score.most_common(12)

    # Detect phases by top1 theme
    phases = []
    cur = None
    for d in days:
        top1 = d["top_themes"][0][0] if d["top_themes"] else "-"
        if cur is None or cur["theme"] != top1:
            if cur is not None:
                phases.append(cur)
            cur = {"theme": top1, "start": d["date"], "end": d["date"], "days": 1}
        else:
            cur["end"] = d["date"]
            cur["days"] += 1
    if cur is not None:
        phases.append(cur)

    # Rotation per day
    day_metrics: List[DayMetrics] = []
    prev_top5 = None
    for d in days:
        top5 = [t for t, _ in d["top_themes"][:5]]
        overlap = jaccard(prev_top5, top5) if prev_top5 is not None else None
        rot_label = rotation_label(overlap) if overlap is not None else "-"
        day_metrics.append(
            DayMetrics(
                date=d["date"],
                total_items=d["total"],
                lb_ratio_all=d["lb_ratio_all"],
                rumor_ratio_all=d["rumor_ratio_all"],
                concentration_top1=d["concentration_top1"],
                concentration_top3=d["concentration_top3"],
                top_themes=d["top_themes"],
                rotation_overlap_top5=overlap,
                rotation_label=rot_label,
            )
        )
        prev_top5 = top5

    # Watchlist (latest)
    watchlist = build_watchlist(days, lookback_days=3, topn=20)

    # Markdown
    lines: List[str] = []
    start = days[0]["date"] if days else "-"
    end = days[-1]["date"] if days else "-"
    lines.append(f"# 韭研公社异动解析：趋势与轮动（文本代理）")
    lines.append("")
    lines.append(f"**范围**: {start} - {end}（已剔除ST相关条目）")
    lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    lines.append("## 总体结论")
    lines.append("")
    if phases:
        ph = " -> ".join([f"{p['theme']}({p['start']}-{p['end']})" for p in phases if p["theme"] != "-"])
        lines.append(f"- **主线阶段**: {ph}" if ph else "- **主线阶段**: 无")
    if top_overall:
        lines.append(
            "- **期间热度Top**: "
            + ", ".join([f"{t}" for t, _ in top_overall[:6]])
        )
    lines.append("- **情绪代理**: 用连板叙事占比/传闻占比/题材集中度来判断次日偏延续/分歧/切换")
    lines.append("")

    lines.append("## 轮动与情绪（按日）")
    lines.append("")
    lines.append("| 日期 | 样本数 | Top1题材(mentions) | Top3集中度 | 连板叙事 | 传闻 | 轮动 |")
    lines.append("|---|---:|---|---:|---:|---:|---|")
    for dm in day_metrics:
        top1 = dm.top_themes[0] if dm.top_themes else ("-", None)
        top1_name = top1[0]
        top1_mentions = top1[1].mentions if top1[1] else 0
        lines.append(
            "| {date} | {n} | {top1}({m}) | {c3:.0f}% | {lb:.0f}% | {ru:.0f}% | {rot} |".format(
                date=dm.date,
                n=dm.total_items,
                top1=top1_name,
                m=top1_mentions,
                c3=dm.concentration_top3 * 100,
                lb=dm.lb_ratio_all * 100,
                ru=dm.rumor_ratio_all * 100,
                rot=(dm.rotation_label if dm.rotation_label != "-" else "-"),
            )
        )
    lines.append("")

    lines.append("## 近期5日跟踪池（不含ST）")
    lines.append("")
    lines.append("| 排名 | 标的 | 题材 | 近3日出现 | 证据摘要 |")
    lines.append("|---:|---|---|---|---|")
    for i, w in enumerate(watchlist, start=1):
        code = w["code"]
        name = w["name"]
        theme = w["theme"]
        days_s = ",".join(w["recent_days"])
        ev = str(w["evidence"]).replace("|", "/")
        lines.append(f"| {i} | {name}({code}) | {theme} | {days_s} | {ev} |")
    lines.append("")

    out_json = {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "type": "jygs_trend_text_proxy",
            "range": {"start": start, "end": end},
            "filters": {"exclude_st": True},
        },
        "overall": {
            "top_themes_by_score": [{"theme": t, "score": float(s)} for t, s in top_overall],
            "phases": phases,
        },
        "daily": [
            {
                "date": dm.date,
                "total": dm.total_items,
                "lb_ratio": dm.lb_ratio_all,
                "rumor_ratio": dm.rumor_ratio_all,
                "concentration_top1": dm.concentration_top1,
                "concentration_top3": dm.concentration_top3,
                "rotation_overlap_top5": dm.rotation_overlap_top5,
                "rotation_label": dm.rotation_label,
                "top_themes": [
                    {
                        "theme": t,
                        "mentions": m.mentions,
                        "breadth": m.breadth,
                        "score": m.score,
                        "lb_ratio": m.lb_ratio,
                        "hard_ratio": m.hard_ratio,
                        "rumor_ratio": m.rumor_ratio,
                    }
                    for t, m in dm.top_themes
                ],
            }
            for dm in day_metrics
        ],
        "watchlist_5d": watchlist,
    }

    return "\n".join(lines), out_json


def main() -> int:
    run_date = datetime.now().strftime("%Y%m%d")
    out_dir = Path("data/processed") / f"jygs_trend_{run_date}"
    out_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(glob("data/processed/jiuyangongshe_action_202601??_*.json"))
    files = [f for f in files if "errors" not in f]
    if not files:
        raise SystemExit("No daily jiuyangongshe_action files found")

    day_map: Dict[str, Dict[str, Any]] = {}
    for p in files:
        date, d = compute_day(p)
        day_map[date] = d

    days = [day_map[k] for k in sorted(day_map.keys())]
    # Remove days that become empty after ST filtering
    days = [d for d in days if d["total"] > 0]
    if not days:
        raise SystemExit("All days are empty after ST exclusion")

    md, out_json = build_report(days)

    md_path = out_dir / f"trend_summary_{days[-1]['date']}.md"
    json_path = out_dir / f"trend_summary_{days[-1]['date']}.json"
    with md_path.open("w", encoding="utf-8") as f:
        f.write(md)
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)

    print(f"Wrote: {md_path}")
    print(f"Wrote: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
