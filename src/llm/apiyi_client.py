"""api易 LLM client."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import requests


class ApiYiClient:
    def __init__(self, config):
        self.base_url = (getattr(config, "APIYI_BASE_URL", "") or "").strip()
        self.api_key = (getattr(config, "APIYI_API_KEY", "") or "").strip()
        self.model = (getattr(config, "APIYI_MODEL", "gpt-4o-mini") or "gpt-4o-mini").strip()

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 1200,
        timeout: int = 60,
    ) -> str:
        if not self.base_url:
            raise RuntimeError("Missing APIYI_BASE_URL in config")
        if not self.api_key:
            raise RuntimeError("Missing APIYI_API_KEY in config/local_settings.py")

        payload: Dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        resp = requests.post(self.base_url, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and "choices" in data:
            choices = data.get("choices") or []
            if choices and isinstance(choices, list):
                message = choices[0].get("message") or {}
                content = message.get("content")
                if isinstance(content, str):
                    return content.strip()
        raise RuntimeError("LLM response missing content")
