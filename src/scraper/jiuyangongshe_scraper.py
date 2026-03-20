"""Jiuyangongshe (韭研公社/韭菜公社) scraper.

Features:
- Scrape daily "异动解析" from /action/YYYY-MM-DD by parsing SSR Nuxt state.
- Fetch "关注的人" (followed users / feed) via signed API requests (requires login).

Notes:
- Do NOT hardcode credentials. Use env vars JYGS_PHONE / JYGS_PASSWORD.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

from utils.http_client import HttpClient
from src.utils.symbols import normalize_symbol


@dataclass
class JYGSAuth:
    phone: str
    password: str


class JiuyangongsheScraper:
    """Scraper for https://www.jiuyangongshe.com."""

    WWW_BASE = "https://www.jiuyangongshe.com"
    API_BASE = "https://app.jiuyangongshe.com/jystock-app"

    def __init__(self, config: Any):
        self.config = config

        self.www = requests.Session()
        self.api = requests.Session()
        self.www_http = HttpClient(config, session=self.www, source="jygs_www")
        self.api_http = HttpClient(config, session=self.api, source="jygs_api")

        # Jiuyangongshe WAF is sensitive to headers; keep UA modern.
        self._www_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

        self._api_base_headers = {
            "User-Agent": self._www_headers["User-Agent"],
            "Accept": "application/json",
            "Content-Type": "application/json",
            "platform": "3",
            "X-Requested-With": "XMLHttpRequest",
        }

        self._session_token: Optional[str] = None
        self._user_info: Optional[Dict[str, Any]] = None
        self._token_seed_prefix: str = self._load_token_seed_prefix()

    def http_stats(self) -> Dict[str, Any]:
        return {
            "www": self.www_http.stats(),
            "api": self.api_http.stats(),
        }

    def _load_token_seed_prefix(self) -> str:
        """Load signing seed prefix for endpoints that require it.

        This value is intentionally NOT hardcoded in repo to avoid leaking sensitive or proprietary details.
        """
        env_v = (os.getenv("JYGS_TOKEN_SEED_PREFIX") or "").strip()
        if env_v:
            return env_v
        cfg_v = (getattr(self.config, "JYGS_TOKEN_SEED_PREFIX", "") or "").strip()
        return cfg_v

    def _require_token_seed_prefix(self) -> str:
        v = (self._token_seed_prefix or "").strip()
        if not v:
            raise RuntimeError(
                "Missing JYGS_TOKEN_SEED_PREFIX. Set it in config/local_settings.py or env JYGS_TOKEN_SEED_PREFIX "
                "(required for some signed APIs like followed users)."
            )
        return v

    # -----------------------------
    # Public: action scraping
    # -----------------------------
    def scrape_action_as_news(self, date: str) -> List[Dict[str, Any]]:
        """Scrape /action/YYYY-MM-DD and normalize to "news" items."""
        nuxt = self._fetch_nuxt_state_from_action(date)
        d0 = (nuxt.get("data") or [{}])[0] if isinstance(nuxt, dict) else {}

        fields = d0.get("actionFieldList") or []
        if not fields:
            field_result = d0.get("fieldResult")
            if isinstance(field_result, dict) and isinstance(field_result.get("data"), list):
                fields = field_result.get("data")

        out: List[Dict[str, Any]] = []
        for field in fields:
            if not isinstance(field, dict):
                continue
            field_name = (field.get("name") or "").strip()
            items = field.get("list")
            if not items or not isinstance(items, list):
                continue
            for item in items:
                normalized = self._normalize_action_item(date=date, field_name=field_name, item=item)
                if normalized:
                    out.append(normalized)

        # Some deployments only SSR the field list and load stock rows via API.
        if out:
            return out

        return self._scrape_action_as_news_via_api(date)

    def _scrape_action_as_news_via_api(self, date: str) -> List[Dict[str, Any]]:
        """Fallback: fetch action list via signed API (requires SESSION)."""
        if not self._session_token:
            try:
                self.login_auto()
            except Exception as exc:
                raise RuntimeError(
                    "Jiuyangongshe action details require login; set config/local_settings.py or env JYGS_PHONE/JYGS_PASSWORD"
                ) from exc

        count_res = self._api_post_json("/api/v1/action/count-pc", {"date": date})
        if str(count_res.get("errCode")) != "0":
            raise RuntimeError(
                f"Jiuyangongshe action count failed: errCode={count_res.get('errCode')}, msg={count_res.get('msg')}"
            )
        api_date = (count_res.get("data") or {}).get("date") or date

        field_res = self._api_post_json("/api/v1/action/field", {"date": api_date, "pc": 1})
        if str(field_res.get("errCode")) != "0":
            raise RuntimeError(
                f"Jiuyangongshe action field failed: errCode={field_res.get('errCode')}, msg={field_res.get('msg')}"
            )
        field_list = field_res.get("data") or []

        out: List[Dict[str, Any]] = []
        for field in field_list:
            if not isinstance(field, dict):
                continue
            field_id = (field.get("action_field_id") or "").strip()
            field_name = (field.get("name") or "").strip()
            if not field_id:
                continue

            list_payload = {
                "action_field_id": field_id,
                "sort_price": 0,
                "sort_range": 0,
                "sort_time": 0,
                "pc": 1,
                "start": 1,
                "limit": 999,
            }
            list_res = self._api_post_json("/api/v1/action/list", list_payload)
            if str(list_res.get("errCode")) != "0":
                # Skip a single field on failure
                continue
            items = list_res.get("data") or []
            if not isinstance(items, list):
                continue

            for item in items:
                normalized = self._normalize_action_item(date=api_date, field_name=field_name, item=item)
                if normalized:
                    out.append(normalized)

        return out

    # -----------------------------
    # Public: focus scraping
    # -----------------------------
    def login_from_env(self) -> None:
        phone = (os.getenv("JYGS_PHONE") or "").strip()
        password = os.getenv("JYGS_PASSWORD")
        if not phone or not password:
            raise RuntimeError("Missing env vars: JYGS_PHONE / JYGS_PASSWORD")
        self.login(JYGSAuth(phone=phone, password=password))

    def login_from_config(self) -> None:
        phone = (getattr(self.config, "JYGS_PHONE", None) or "").strip()
        password = getattr(self.config, "JYGS_PASSWORD", None)
        if not phone or not password:
            raise RuntimeError("Missing config values: JYGS_PHONE / JYGS_PASSWORD")
        self.login(JYGSAuth(phone=phone, password=password))

    def login_auto(self) -> None:
        """Try config first, then env."""
        try:
            self.login_from_config()
            return
        except Exception:
            self.login_from_env()

    def login(self, auth: JYGSAuth) -> None:
        """Login and store SESSION cookie (requires signed headers)."""
        payload = {"phone": auth.phone, "password": auth.password}
        data = self._api_post_json("/api/v1/user/login", payload)

        err = data.get("errCode")
        if str(err) != "0":
            raise RuntimeError(f"Jiuyangongshe login failed: errCode={err}, msg={data.get('msg')}")

        session_token = (data.get("data") or {}).get("sessionToken")
        if not session_token:
            raise RuntimeError("Jiuyangongshe login missing sessionToken")

        self._session_token = str(session_token)
        # Mirror site behavior: cookie name SESSION
        self.api.cookies.set("SESSION", self._session_token, domain="app.jiuyangongshe.com", path="/")
        self._user_info = None

    def get_user_info(self) -> Dict[str, Any]:
        if self._user_info is not None:
            return self._user_info
        data = self._api_post_json("/api/v1/user/info", {})
        err = data.get("errCode")
        if str(err) != "0":
            raise RuntimeError(f"Jiuyangongshe user info failed: errCode={err}, msg={data.get('msg')}")
        self._user_info = data.get("data") or {}
        return self._user_info

    def scrape_follow_users(self, limit: int = 200, start: int = 1) -> List[Dict[str, Any]]:
        """Fetch followed users list (/focus -> 关注的人列表). Requires login."""
        user_info = self.get_user_info()
        user_id = user_info.get("user_id") or user_info.get("id")
        if not user_id:
            raise RuntimeError("Jiuyangongshe user info missing user_id")

        payload = {"user_id": user_id, "limit": int(limit), "start": int(start)}
        data = self._api_post_json("/api/v1/user/fans/follow-list", payload)

        err = data.get("errCode")
        if str(err) != "0":
            raise RuntimeError(f"Jiuyangongshe follow-list failed: errCode={err}, msg={data.get('msg')}")

        body = data.get("data")
        if isinstance(body, dict) and isinstance(body.get("result"), list):
            return body.get("result")
        if isinstance(body, list):
            return body
        return []

    # -----------------------------
    # Internals
    # -----------------------------
    def _fetch_nuxt_state_from_action(self, date: str) -> Dict[str, Any]:
        url = f"{self.WWW_BASE}/action/{date}"
        resp = self.www_http.get(url, headers=self._www_headers)
        html = resp.text

        # Extract JS expression assigned to window.__NUXT__
        m = re.search(r"window\.__NUXT__=([\s\S]*?);\s*</script>", html)
        if not m:
            raise RuntimeError("Failed to locate window.__NUXT__ in action page")

        expr = m.group(1)
        node_src = (
            "global.window={};\n"
            f"window.__NUXT__={expr};\n"
            "console.log(JSON.stringify(window.__NUXT__));\n"
        )
        res = subprocess.run(["node", "-e", node_src], capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"Node eval failed: {res.stderr.strip()[:500]}")
        try:
            return json.loads(res.stdout)
        except Exception as exc:
            raise RuntimeError("Failed to parse Nuxt state JSON") from exc

    def _normalize_action_item(self, date: str, field_name: str, item: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(item, dict):
            return None

        stock_code = (item.get("code") or "").strip()
        stock_name = (item.get("name") or "").strip()
        article = item.get("article") if isinstance(item.get("article"), dict) else {}
        article_id = (article.get("article_id") or "").strip()
        title = (article.get("title") or "").strip()
        create_time = (article.get("create_time") or "").strip()

        action_info = article.get("action_info") if isinstance(article.get("action_info"), dict) else {}
        time_str = (action_info.get("time") or "").strip()
        num = (action_info.get("num") or "").strip()
        expound = (action_info.get("expound") or "").strip()

        if not title:
            title_parts = [date, stock_name or stock_code, "异动解析"]
            if field_name:
                title_parts.insert(1, field_name)
            title = " ".join([p for p in title_parts if p])

        publish_time, publish_ts = self._resolve_publish_time(date=date, time_str=time_str, fallback=create_time)
        url = f"{self.WWW_BASE}/a/{article_id}" if article_id else ""

        # Build content: keep key context in a compact block.
        content_parts = []
        if field_name:
            content_parts.append(f"板块: {field_name}")
        if stock_code or stock_name:
            content_parts.append(f"标的: {stock_name} ({stock_code})".strip())
        if num:
            content_parts.append(f"连板/形态: {num}")
        if expound:
            content_parts.append("")
            content_parts.append(expound)

        content = "\n".join([p for p in content_parts if p is not None]).strip()
        if not content:
            return None

        tags = [t for t in ["异动解析", field_name, stock_name, stock_code] if t]
        normalized_symbol = normalize_symbol(stock_code) if stock_code else ""
        signal_flags = []
        if num:
            if "板" in num:
                signal_flags.append("limit_shape")
            if any(keyword in num for keyword in ["连板", "首板", "2板", "3板", "4板", "5板", "6板"]):
                signal_flags.append("streak_signal")
        if expound:
            if any(keyword in expound for keyword in ["龙头", "核心", "总龙", "辨识度"]):
                signal_flags.append("core_signal")
            if any(keyword in expound for keyword in ["补涨", "跟涨", "跟风", "扩散", "分支"]):
                signal_flags.append("follow_signal")
            if any(keyword in expound for keyword in ["高位", "分歧", "炸板", "回落", "兑现", "博弈"]):
                signal_flags.append("risk_signal")

        explicit_symbols = []
        if normalized_symbol:
            explicit_symbols.append(
                {
                    "symbol": normalized_symbol,
                    "name": stock_name or stock_code,
                    "relation_type": "primary",
                }
            )

        explicit_themes = []
        if field_name:
            explicit_themes.append(
                {
                    "name": field_name,
                    "type": "concept",
                }
            )

        return {
            "source_uid": article_id or f"{date}:{field_name}:{stock_code}:{title}",
            "title": title,
            "content": content,
            "publish_time": publish_time,
            "publish_ts": publish_ts,
            "source": "韭研公社",
            "url": url,
            "tags": tags,
            "symbols": explicit_symbols,
            "themes": explicit_themes,
            "stock_code": stock_code,
            "stock_name": stock_name,
            "field_name": field_name,
            "action_num": num,
            "expound": expound,
            "signal_flags": signal_flags,
        }

    def _resolve_publish_time(self, date: str, time_str: str, fallback: str) -> Tuple[str, int]:
        candidates: List[str] = []
        if date and time_str:
            candidates.append(f"{date} {time_str}")
        if fallback:
            candidates.append(fallback)

        for ts in candidates:
            ts = ts.strip()
            if not ts:
                continue
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                try:
                    dt = datetime.strptime(ts, fmt)
                    return dt.strftime("%Y-%m-%d %H:%M:%S"), int(dt.timestamp())
                except Exception:
                    pass

        now = datetime.now()
        return now.strftime("%Y-%m-%d %H:%M:%S"), int(now.timestamp())

    def _api_post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.API_BASE}{path}"
        headers = dict(self._api_base_headers)
        headers.update(self._signed_headers())

        try:
            resp = self.api_http.post_json(url, json_body=payload, headers=headers)
            return resp.json()
        except Exception as exc:
            raise RuntimeError(f"API returned non-JSON for {path}") from exc

    def _signed_headers(self) -> Dict[str, str]:
        ts = int(time.time() * 1000)
        seed_prefix = self._require_token_seed_prefix()
        raw = f"{seed_prefix}{ts}"
        token = hashlib.md5(raw.encode("utf-8")).hexdigest()
        return {
            "timestamp": str(ts),
            "token": token,
        }
