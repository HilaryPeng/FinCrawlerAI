"""LLM-based analysis for news outputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Tuple

from llm.apiyi_client import ApiYiClient


@dataclass
class AnalysisResult:
    title: str
    markdown: str
    truncated_notes: List[str]


class LLMAnalyzer:
    def __init__(self, config):
        self.config = config
        self.client = ApiYiClient(config)

    def analyze(self, sources: List[Tuple[str, Dict]]) -> AnalysisResult:
        title = f"2小时分析汇总 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        prompt_text, notes, overview_lines = self._build_prompt(sources)

        system_msg = (
            "你是金融资讯分析助手。请输出中文 Markdown，结构必须严格按以下顺序：\n"
            "1) ## 总览（1-2行，包含时间窗口、来源数、总条数）\n"
            "2) ## 主题（5条，格式：主题名（条数）- 代表关键词/标题）\n"
            "3) ## 平台分段（每个平台输出‘要点 2 条 + Top 5’）\n"
            "4) ## 总体热度Top15（标题 + 来源 + 时间）\n"
            "要求：整体简短清晰；每个平台要点最多2条；Top 5 只列标题+时间；不得输出全量清单。\n"
            "总体热度Top15要求：保留排序概念，优先信息量更高/更有影响的条目；如果条目缺少链接或内容摘要，仍可保留，但尽量排在后部。"
        )

        user_msg = (
            "以下是过去2小时的新闻列表（按平台分组，字段为：时间 | 标题 | 标签 | 链接）。\n"
            "概览信息：\n"
            f"{overview_lines}\n\n"
            "请只基于以下数据做分析：\n\n"
            f"{prompt_text}"
        )

        content = self.client.chat_completion(
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.2,
            max_tokens=1400,
        )

        return AnalysisResult(title=title, markdown=content.strip(), truncated_notes=notes)

    def build_full_list_markdown(self, sources: List[Tuple[str, Dict]]) -> str:
        lines: List[str] = ["## 全量清单", ""]
        for source_name, data in sources:
            lines.append(f"### {source_name}")
            items = sorted(
                data.get("raw_news", []),
                key=lambda item: item.get("publish_ts", 0) or 0,
                reverse=True,
            )
            if not items:
                lines.append("- 无数据")
                lines.append("")
                continue
            for item in items:
                publish_time = item.get("publish_time", "")
                title = item.get("title", "")
                source = item.get("source", source_name)
                url = item.get("url", "")
                if url:
                    line = f"- {title}（{publish_time}，{source}）[{url}]({url})"
                else:
                    line = f"- {title}（{publish_time}，{source}）"
                lines.append(line)
            lines.append("")
        return "\n".join(lines)

    def _build_prompt(self, sources: List[Tuple[str, Dict]]) -> Tuple[str, List[str], str]:
        max_chars = 22000
        notes: List[str] = []
        parts: List[str] = []
        overview_lines: List[str] = []
        used = 0

        for source_name, data in sources:
            items = sorted(
                data.get("raw_news", []),
                key=lambda item: item.get("publish_ts", 0) or 0,
                reverse=True,
            )
            summary = data.get("summary", {}) if isinstance(data, dict) else {}
            total_news = summary.get("total_news", len(items))
            time_range = summary.get("time_range", "")

            overview_lines.append(f"- {source_name}: {total_news} 条，时间范围 {time_range}")

            header = f"### {source_name}（{len(items)}条）"
            if used + len(header) + 2 > max_chars:
                notes.append(f"{source_name} 输入被截断")
                break
            parts.append(header)
            used += len(header) + 2

            count = 0
            for item in items:
                publish_time = item.get("publish_time", "")
                title = item.get("title", "")
                tags = item.get("tags", [])
                url = item.get("url", "")
                tags_text = "、".join(tags) if isinstance(tags, list) and tags else ""
                line = f"{publish_time} | {title} | {tags_text} | {url}".strip()
                if used + len(line) + 1 > max_chars:
                    notes.append(f"{source_name} 输入被截断，仅保留最近 {count} 条")
                    break
                parts.append(line)
                used += len(line) + 1
                count += 1

            parts.append("")
            used += 1

        return "\n".join(parts).strip(), notes, "\n".join(overview_lines).strip()
