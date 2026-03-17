from __future__ import annotations

import hashlib
import json
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, List

import requests


@dataclass
class HttpResponse:
    status_code: int
    headers: Dict[str, str]
    content: bytes
    url: str

    def json(self) -> Any:
        return json.loads(self.content.decode("utf-8", errors="replace"))

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


@dataclass
class HttpStats:
    source: str
    requests_total: int = 0
    replay_hits: int = 0
    retries_total: int = 0
    errors_total: int = 0
    status_counts: Dict[str, int] = field(default_factory=dict)  # "2xx"/"3xx"/"4xx"/"5xx"/"429"/"other"
    latency_ms_total: float = 0.0
    latency_ms_max: float = 0.0
    samples: int = 0
    last_errors: List[str] = field(default_factory=list)

    def add_status(self, status_code: int) -> None:
        key = "other"
        if status_code == 429:
            key = "429"
        elif 200 <= status_code <= 299:
            key = "2xx"
        elif 300 <= status_code <= 399:
            key = "3xx"
        elif 400 <= status_code <= 499:
            key = "4xx"
        elif 500 <= status_code <= 599:
            key = "5xx"
        self.status_counts[key] = int(self.status_counts.get(key, 0)) + 1

    def add_latency_ms(self, ms: float) -> None:
        self.latency_ms_total += float(ms)
        if ms > self.latency_ms_max:
            self.latency_ms_max = float(ms)
        self.samples += 1

    def as_dict(self) -> Dict[str, Any]:
        avg = (self.latency_ms_total / self.samples) if self.samples else 0.0
        return {
            "source": self.source,
            "requests_total": self.requests_total,
            "replay_hits": self.replay_hits,
            "retries_total": self.retries_total,
            "errors_total": self.errors_total,
            "status_counts": dict(self.status_counts),
            "latency_ms_avg": round(avg, 2),
            "latency_ms_max": round(self.latency_ms_max, 2),
            "samples": self.samples,
            "last_errors": list(self.last_errors),
        }


class HttpClient:
    """Shared HTTP client with retries/backoff and raw response caching.

    - Retries on: network errors, timeouts, 429, 5xx
    - Backoff: exponential + jitter
    - Raw cache: write response bytes + metadata to data/raw/
    - Replay: when enabled, prefer cached response for the same request key
    """

    def __init__(self, config: Any, session: Optional[requests.Session] = None, source: str = "generic"):
        self.config = config
        self.session = session or requests.Session()
        self.source = source

        self.max_retries = int(getattr(config, "HTTP_MAX_RETRIES", getattr(config, "MAX_RETRIES", 3)) or 3)
        self.timeout = int(getattr(config, "TIMEOUT", 30) or 30)
        self.backoff_base = float(getattr(config, "HTTP_BACKOFF_BASE_SECONDS", 0.8) or 0.8)
        self.backoff_cap = float(getattr(config, "HTTP_BACKOFF_CAP_SECONDS", 10.0) or 10.0)

        self.enable_cache = bool(getattr(config, "RAW_CACHE_ENABLED", True))
        self.replay_cache = bool(getattr(config, "RAW_CACHE_REPLAY", False))
        # Allow env override for quick debugging
        if os.getenv("RAW_CACHE_REPLAY", "").strip() in ("1", "true", "True", "YES", "yes"):
            self.replay_cache = True
        if os.getenv("RAW_CACHE_ENABLED", "").strip() in ("0", "false", "False", "NO", "no"):
            self.enable_cache = False

        raw_dir = getattr(config, "RAW_DATA_DIR", None)
        self.cache_dir = Path(raw_dir) / "http_cache" / self.source if raw_dir else None
        self._stats = HttpStats(source=self.source)

    def stats(self) -> Dict[str, Any]:
        return self._stats.as_dict()

    def get(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> HttpResponse:
        return self.request("GET", url, params=params, headers=headers)

    def post_json(
        self,
        url: str,
        *,
        json_body: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> HttpResponse:
        return self.request("POST", url, json=json_body, headers=headers)

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> HttpResponse:
        self._stats.requests_total += 1
        key = self._cache_key(method, url, params=params, json=json, headers=headers)

        if self.replay_cache:
            cached = self._load_cache(key)
            if cached is not None:
                self._stats.replay_hits += 1
                return cached

        last_exc: Optional[BaseException] = None
        for attempt in range(self.max_retries + 1):
            try:
                t0 = time.perf_counter()
                resp = self.session.request(
                    method=method.upper(),
                    url=url,
                    params=params,
                    json=json,
                    headers=headers,
                    timeout=self.timeout,
                )
                dt_ms = (time.perf_counter() - t0) * 1000.0
                self._stats.add_latency_ms(dt_ms)
                self._stats.add_status(int(resp.status_code))

                # Retry on 429 / 5xx
                if resp.status_code == 429 or 500 <= resp.status_code <= 599:
                    if attempt < self.max_retries:
                        self._stats.retries_total += 1
                        self._sleep_backoff(attempt, resp)
                        continue

                out = HttpResponse(
                    status_code=int(resp.status_code),
                    headers={k: v for k, v in resp.headers.items()},
                    content=resp.content or b"",
                    url=str(resp.url),
                )

                if self.enable_cache:
                    self._write_cache(key, out, method=method, url=url, params=params, json_body=json)

                # Mirror requests' raise_for_status behavior for callers that expect exceptions
                resp.raise_for_status()
                return out

            except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
                last_exc = exc
                self._stats.errors_total += 1
                msg = f"{type(exc).__name__}: {str(exc)[:200]}"
                self._stats.last_errors.append(msg)
                if len(self._stats.last_errors) > 5:
                    self._stats.last_errors = self._stats.last_errors[-5:]
                if attempt < self.max_retries:
                    self._stats.retries_total += 1
                    self._sleep_backoff(attempt, None)
                    continue
                raise

        # Should not reach here
        if last_exc:
            raise last_exc
        raise RuntimeError("HTTP request failed without exception")

    def _sleep_backoff(self, attempt: int, resp: Optional[requests.Response]) -> None:
        retry_after = None
        if resp is not None:
            ra = resp.headers.get("Retry-After")
            if ra:
                try:
                    retry_after = float(ra)
                except Exception:
                    retry_after = None

        base = min(self.backoff_cap, self.backoff_base * (2**attempt))
        jitter = random.random() * 0.4 * base
        delay = retry_after if retry_after is not None else base + jitter
        time.sleep(delay)

    def _cache_key(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Dict[str, Any]],
        json: Optional[Dict[str, Any]],
        headers: Optional[Dict[str, str]],
    ) -> str:
        # Only include stable parts; avoid cookies/authorization
        safe_headers = {}
        if headers:
            for k, v in headers.items():
                lk = k.lower()
                if lk in ("authorization", "cookie"):
                    continue
                safe_headers[k] = v
        payload = {
            "m": method.upper(),
            "u": url,
            "p": params or {},
            "j": json or {},
            "h": safe_headers,
        }
        raw = json_dumps(payload).encode("utf-8")
        return hashlib.sha1(raw).hexdigest()

    def _paths_for_key(self, key: str) -> Tuple[Optional[Path], Optional[Path]]:
        if not self.cache_dir:
            return None, None
        meta = self.cache_dir / f"{key}.meta.json"
        body = self.cache_dir / f"{key}.body"
        return meta, body

    def _write_cache(
        self,
        key: str,
        resp: HttpResponse,
        *,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]],
        json_body: Optional[Dict[str, Any]],
    ) -> None:
        meta_path, body_path = self._paths_for_key(key)
        if not meta_path or not body_path:
            return

        try:
            meta_path.parent.mkdir(parents=True, exist_ok=True)
            body_path.write_bytes(resp.content)
            meta = {
                "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "method": method.upper(),
                "url": url,
                "final_url": resp.url,
                "params": params or {},
                "json": json_body or {},
                "status_code": resp.status_code,
                "headers": resp.headers,
            }
            meta_path.write_text(json_dumps(meta, indent=2), encoding="utf-8")
        except Exception:
            # Cache is best-effort; never break crawling
            return

    def _load_cache(self, key: str) -> Optional[HttpResponse]:
        meta_path, body_path = self._paths_for_key(key)
        if not meta_path or not body_path:
            return None
        if not meta_path.exists() or not body_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            body = body_path.read_bytes()
            return HttpResponse(
                status_code=int(meta.get("status_code", 200)),
                headers={k: str(v) for k, v in (meta.get("headers") or {}).items()},
                content=body,
                url=str(meta.get("final_url") or meta.get("url") or ""),
            )
        except Exception:
            return None


def json_dumps(obj: Any, indent: Optional[int] = None) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=indent)

