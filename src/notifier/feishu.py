"""Feishu bot notifier."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

import requests


@dataclass
class FeishuCardSection:
    title: str
    summary_line: str
    items: List[str]


class FeishuNotifier:
    def __init__(self, config):
        self.config = config
        self.webhook = (getattr(config, "FEISHU_WEBHOOK", "") or "").strip()
        self.secret = (getattr(config, "FEISHU_SECRET", "") or "").strip()

    def send_sections(self, title: str, sections: List[FeishuCardSection]) -> None:
        if not self.webhook:
            raise RuntimeError("Missing FEISHU_WEBHOOK in config/local_settings.py")

        cards = self._build_cards(title=title, sections=sections)
        for index, card in enumerate(cards, start=1):
            if len(cards) > 1:
                card_title = f"{title} ({index}/{len(cards)})"
                card["card"]["header"]["title"]["content"] = card_title
            self._post(card)

    def send_markdown(self, title: str, markdown: str) -> None:
        if not self.webhook:
            raise RuntimeError("Missing FEISHU_WEBHOOK in config/local_settings.py")

        cards = self._build_markdown_cards(title=title, markdown=markdown)
        for index, card in enumerate(cards, start=1):
            if len(cards) > 1:
                card_title = f"{title} ({index}/{len(cards)})"
                card["card"]["header"]["title"]["content"] = card_title
            self._post(card)

    def _post(self, payload: Dict) -> None:
        body = dict(payload)
        if self.secret:
            timestamp = str(int(time.time()))
            sign = self._sign(timestamp, self.secret)
            body["timestamp"] = timestamp
            body["sign"] = sign

        resp = requests.post(self.webhook, json=body, timeout=20)
        resp.raise_for_status()
        try:
            data = resp.json()
        except Exception:
            return
        if isinstance(data, dict):
            code = data.get("code")
            if code not in (0, "0", None):
                raise RuntimeError(f"Feishu API error: code={code}, msg={data.get('msg')}")

    def _sign(self, timestamp: str, secret: str) -> str:
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_code = hmac.new(
            secret.encode("utf-8"), string_to_sign.encode("utf-8"), digestmod=hashlib.sha256
        ).digest()
        return base64.b64encode(hmac_code).decode("utf-8")

    def _build_cards(self, title: str, sections: List[FeishuCardSection]) -> List[Dict]:
        max_chars = 12000
        cards: List[str] = []
        current_lines: List[str] = []
        current_len = 0

        def flush() -> None:
            nonlocal current_lines, current_len
            if current_lines:
                cards.append("\n".join(current_lines))
            current_lines = []
            current_len = 0

        def add_line(line: str) -> None:
            nonlocal current_len
            line_len = len(line) + 1
            if current_len + line_len > max_chars and current_lines:
                flush()
            current_lines.append(line)
            current_len += line_len

        for section in sections:
            header = f"### {section.title}"
            summary = section.summary_line

            if current_lines and current_len + len(header) + len(summary) + 4 > max_chars:
                flush()

            if not current_lines:
                add_line(header)
                add_line(summary)
            else:
                add_line(header)
                add_line(summary)

            if not section.items:
                add_line("- 无数据")
                add_line("")
                continue

            for item in section.items:
                line = f"- {item}"
                if current_len + len(line) + 1 > max_chars:
                    flush()
                    add_line(f"### {section.title} (cont.)")
                    add_line(summary)
                add_line(line)

            add_line("")

        if current_lines:
            flush()

        payloads = []
        for content in cards:
            payloads.append(
                {
                    "msg_type": "interactive",
                    "card": {
                        "config": {"wide_screen_mode": True},
                        "header": {
                            "title": {"tag": "plain_text", "content": title}
                        },
                        "elements": [
                            {"tag": "div", "text": {"tag": "lark_md", "content": content}}
                        ],
                    },
                }
            )
        return payloads

    def _build_markdown_cards(self, title: str, markdown: str) -> List[Dict]:
        max_chars = 12000
        chunks: List[str] = []
        current: List[str] = []
        current_len = 0

        for line in markdown.splitlines():
            line_len = len(line) + 1
            if current_len + line_len > max_chars and current:
                chunks.append("\n".join(current))
                current = []
                current_len = 0
            current.append(line)
            current_len += line_len

        if current:
            chunks.append("\n".join(current))

        payloads: List[Dict] = []
        for content in chunks:
            payloads.append(
                {
                    "msg_type": "interactive",
                    "card": {
                        "config": {"wide_screen_mode": True},
                        "header": {
                            "title": {"tag": "plain_text", "content": title}
                        },
                        "elements": [
                            {"tag": "div", "text": {"tag": "lark_md", "content": content}}
                        ],
                    },
                }
            )
        return payloads


def build_section(
    source_name: str,
    summary: Dict,
    items: Iterable[Dict],
    max_items: Optional[int] = None,
) -> FeishuCardSection:
    total = summary.get("total_news", 0)
    time_range = summary.get("time_range", "无数据")
    main_topics = summary.get("main_topics", [])
    topics_text = "、".join(main_topics) if main_topics else "无"
    summary_line = f"**总数**: {total} | **时间范围**: {time_range} | **主要话题**: {topics_text}"

    lines: List[str] = []
    count = 0
    for item in items:
        if max_items is not None and count >= max_items:
            break
        publish_time = item.get("publish_time", "")
        title = item.get("title", "")
        url = item.get("url", "")
        if url:
            line = f"{publish_time} [{title}]({url})"
        else:
            line = f"{publish_time} {title}"
        lines.append(line.strip())
        count += 1

    return FeishuCardSection(title=source_name, summary_line=summary_line, items=lines)
