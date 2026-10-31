"""LLM provider abstraction.

The default provider is deterministic and offline.  Optional Ollama and OpenAI
providers are used only when explicitly configured.  If an external provider
fails, the orchestrator falls back to a deterministic evidence-bound answer.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

import httpx

from app.core.config import get_settings


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    estimated_cost_usd: float | None = None
    latency_ms: int = 0
    error: str | None = None


class BaseProvider:
    name = "base"
    model = "none"
    available = False

    def generate(self, system: str, user: str, max_tokens: int = 900) -> LLMResponse:
        raise NotImplementedError


class DeterministicProvider(BaseProvider):
    name = "deterministic"
    model = "evidence-template-v1"
    available = True

    def generate(self, system: str, user: str, max_tokens: int = 900) -> LLMResponse:
        return LLMResponse(
            text="",
            provider=self.name,
            model=self.model,
            latency_ms=0,
            error="deterministic provider does not generate free text",
        )


class OllamaProvider(BaseProvider):
    name = "ollama"

    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = settings.ollama_model
        self.available = True

    def generate(self, system: str, user: str, max_tokens: int = 900) -> LLMResponse:
        started = time.perf_counter()
        try:
            response = httpx.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "stream": False,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "options": {"num_predict": max_tokens, "temperature": 0.1},
                },
                timeout=45.0,
            )
            response.raise_for_status()
            payload = response.json()
            text = (payload.get("message") or {}).get("content", "")
            return LLMResponse(
                text=text,
                provider=self.name,
                model=self.model,
                prompt_tokens=payload.get("prompt_eval_count"),
                completion_tokens=payload.get("eval_count"),
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:
            return LLMResponse(
                text="",
                provider=self.name,
                model=self.model,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error=str(exc),
            )


class OpenAIProvider(BaseProvider):
    name = "openai"

    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.openai_api_key
        self.model = settings.openai_model
        self.input_price = settings.openai_input_usd_per_1m
        self.output_price = settings.openai_output_usd_per_1m
        self.available = bool(self.api_key)

    def generate(self, system: str, user: str, max_tokens: int = 900) -> LLMResponse:
        if not self.api_key:
            return LLMResponse(
                text="", provider=self.name, model=self.model, error="OPENAI_API_KEY is not set"
            )
        started = time.perf_counter()
        try:
            response = httpx.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.1,
                    "max_tokens": max_tokens,
                },
                timeout=45.0,
            )
            response.raise_for_status()
            payload = response.json()
            text = payload["choices"][0]["message"]["content"]
            usage = payload.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")
            cost = None
            if prompt_tokens is not None and completion_tokens is not None:
                cost = (
                    prompt_tokens * self.input_price / 1_000_000
                    + completion_tokens * self.output_price / 1_000_000
                )
            return LLMResponse(
                text=text,
                provider=self.name,
                model=self.model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                estimated_cost_usd=cost,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:
            return LLMResponse(
                text="",
                provider=self.name,
                model=self.model,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error=str(exc),
            )


def get_provider() -> BaseProvider:
    settings = get_settings()
    provider = settings.llm_provider.lower().strip()
    if provider == "ollama":
        return OllamaProvider()
    if provider == "openai":
        return OpenAIProvider()
    return DeterministicProvider()


def parse_json_response(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except ValueError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                value = json.loads(text[start : end + 1])
                return value if isinstance(value, dict) else None
            except ValueError:
                return None
    return None
