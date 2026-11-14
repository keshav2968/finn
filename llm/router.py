"""Route a JSON-producing prompt through the chain of models configured for a task.

    router = Router.from_config()
    result = router.complete_json("classify_filing", system, user, schema)
    result.data        # validated against `schema`
    result.provider, result.model, result.input_tokens, result.output_tokens, result.cached

What the router guarantees:
- Output is parsed and validated against a JSON schema. An invalid reply gets one
  repair attempt on the same model (the validation error is sent back); if it is
  still invalid the next model in the chain is tried. Never returns unvalidated data.
- Per-model budgets from config: it waits rather than exceed tokens/requests per
  minute (up to max_wait_seconds), and skips a model whose daily tokens are used up
  or whose per-minute budget can't hold the request at all (too long for Groq ->
  Gemini).
- PDFs (for scanned documents) only go to providers marked pdf_input.
- Identical requests are answered from a disk cache keyed by a content hash.
- Every call, cached or not, is appended to the usage log (the cost log).

Models are asked for data, never arithmetic: callers compute every number.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import jsonschema
import requests
import yaml

from ingest.common import REPO_ROOT, get_logger, iso_ist, now_ist

from .env import load_env

log = get_logger("llm")

# transport(url, headers, payload, timeout) -> (status, headers, body)
Transport = Callable[[str, dict, dict, float], tuple[int, dict, Any]]


class LLMConfigError(ValueError):
    pass


class LLMError(RuntimeError):
    """Every model in the chain failed; `attempts` says why, per model."""

    def __init__(self, task: str, attempts: list[str]):
        super().__init__(f"{task}: all models failed: " + " | ".join(attempts))
        self.attempts = attempts


class ProviderError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


@dataclass(frozen=True)
class ChainEntry:
    provider: str
    model: str
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.provider}/{self.model}"


@dataclass
class LLMResult:
    data: Any
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cached: bool
    attempts: list[str]


def default_transport(url: str, headers: dict, payload: dict, timeout: float) -> tuple[int, dict, Any]:
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        # network trouble with one provider must move the chain on, not escape it
        raise ProviderError(f"network error: {type(exc).__name__}", status=599) from exc
    try:
        body = resp.json()
    except ValueError:
        body = resp.text
    return resp.status_code, dict(resp.headers), body


def estimate_tokens(text: str) -> int:
    """~4 characters per token for English; good enough for budgeting."""
    return max(1, len(text) // 4)


def extract_json(text: str) -> Any:
    """Parse a model reply that should be JSON: tolerate code fences and stray prose."""
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def schema_error(data: Any, schema: dict) -> str | None:
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.path))
    if not errors:
        return None
    return "; ".join(f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in errors[:5])


class Budget:
    """Sliding one-minute window of tokens and requests for one model, plus a daily total."""

    def __init__(self, tpm: int | None, rpm: int | None, tpd: int | None, used_today: int, clock: Callable[[], float]):
        self.tpm, self.rpm, self.tpd = tpm, rpm, tpd
        self.used_today = used_today
        self.clock = clock
        self.events: deque[tuple[float, int]] = deque()

    def _trim(self) -> None:
        now = self.clock()
        while self.events and now - self.events[0][0] >= 60:
            self.events.popleft()

    def fits_at_all(self, tokens: int) -> bool:
        return self.tpm is None or tokens <= self.tpm

    def day_left(self, tokens: int) -> bool:
        return self.tpd is None or self.used_today + tokens <= self.tpd

    def _ok(self, events: list[tuple[float, int]], tokens: int) -> bool:
        used = sum(t for _, t in events)
        return (self.tpm is None or used + tokens <= self.tpm) and (self.rpm is None or len(events) + 1 <= self.rpm)

    def wait_needed(self, tokens: int) -> float:
        """Seconds until a request of `tokens` fits in the one-minute window."""
        self._trim()
        events = list(self.events)
        if self._ok(events, tokens):
            return 0.0
        now = self.clock()
        while events:
            ts, _ = events.pop(0)  # the oldest event leaves the window at ts + 60
            if self._ok(events, tokens):
                return max(0.0, 60 - (now - ts))
        return 0.0

    def record(self, tokens: int) -> None:
        self.events.append((self.clock(), tokens))
        self.used_today += tokens


class Router:
    def __init__(
        self,
        config: dict[str, Any],
        env: dict[str, str],
        root: Path = REPO_ROOT,
        transport: Transport = default_transport,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        today: Callable[[], str] = lambda: now_ist().date().isoformat(),
    ):
        self.cfg = config
        self.env = env
        self.transport = transport
        self.clock = clock
        self.sleep = sleep
        self.today = today
        self.providers: dict[str, dict] = config.get("providers") or {}
        self.limits: dict[str, dict] = config.get("limits") or {}
        self.max_wait = float(config.get("max_wait_seconds", 60))
        self.timeout = float(config.get("timeout_seconds", 90))
        paths = config.get("paths") or {}
        self.cache_dir = root / paths.get("cache_dir", "data/cache/llm")
        self.usage_log = root / paths.get("usage_log", "data/seed/llm_usage.jsonl")
        self.tasks = {name: self._parse_task(name, spec) for name, spec in (config.get("tasks") or {}).items()}
        self.budgets: dict[str, Budget] = {}

    # ------------------------------------------------------------ setup

    @classmethod
    def from_config(cls, path: Path | None = None, **kwargs: Any) -> "Router":
        path = path or REPO_ROOT / "config" / "models.yaml"
        if not path.exists():
            raise LLMConfigError(f"{path} not found")
        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        load_env()
        return cls(config, dict(os.environ), **kwargs)

    def _parse_task(self, name: str, spec: dict) -> dict:
        chain = []
        for i, entry in enumerate((spec or {}).get("chain") or []):
            provider = entry.get("provider")
            if provider not in self.providers:
                raise LLMConfigError(f"tasks.{name}.chain[{i}]: unknown provider {provider!r}")
            if not entry.get("model"):
                raise LLMConfigError(f"tasks.{name}.chain[{i}]: model is required")
            chain.append(ChainEntry(provider, str(entry["model"]), dict(entry.get("params") or {})))
        if not chain:
            raise LLMConfigError(f"tasks.{name}: chain is empty")
        return {
            "chain": chain,
            "temperature": float((spec or {}).get("temperature", 0)),
            "max_output_tokens": int((spec or {}).get("max_output_tokens", 1000)),
        }

    def _budget(self, entry: ChainEntry) -> Budget:
        if entry.key not in self.budgets:
            lim = self.limits.get(entry.key) or {}
            self.budgets[entry.key] = Budget(
                lim.get("tpm"), lim.get("rpm"), lim.get("tpd"), self._used_today(entry.key), self.clock
            )
        return self.budgets[entry.key]

    def _used_today(self, key: str) -> int:
        if not self.usage_log.exists():
            return 0
        today, total = self.today(), 0
        for line in self.usage_log.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("date") == today and f"{rec.get('provider')}/{rec.get('model')}" == key and not rec.get("cached"):
                total += int(rec.get("input_tokens") or 0) + int(rec.get("output_tokens") or 0)
        return total

    # ------------------------------------------------------------ public

    def complete_json(
        self,
        task: str,
        system: str,
        user: str,
        schema: dict,
        pdf: bytes | None = None,
        label: str = "",
        only: str | None = None,
    ) -> LLMResult:
        """`only` restricts the chain to one "provider/model" (used by scripts/llm_check.py)."""
        if task not in self.tasks:
            raise LLMConfigError(f"unknown task {task!r}; add it to config/models.yaml")
        spec = self.tasks[task]
        if only is not None:
            chain = [e for e in spec["chain"] if e.key == only]
            if not chain:
                raise LLMConfigError(f"{only!r} is not in the {task} chain")
            spec = dict(spec, chain=chain)
        system = f"{system}\n\nReply with a single JSON object that matches this JSON schema:\n{json.dumps(schema)}"
        key = self._cache_key(task, spec, system, user, schema, pdf)
        hit = self._cache_get(key)
        if hit is not None:
            self._log(task, hit["provider"], hit["model"], 0, 0, True, True, label, 0)
            return LLMResult(hit["data"], hit["provider"], hit["model"], 0, 0, True, [])

        attempts: list[str] = []
        est_in = estimate_tokens(system + user) + (2000 if pdf else 0)
        for entry in spec["chain"]:
            provider = self.providers[entry.provider]
            if not self.env.get(provider.get("api_key_env", "")):
                attempts.append(f"{entry.key}: no {provider.get('api_key_env')} in environment")
                continue
            if pdf is not None and not provider.get("pdf_input"):
                attempts.append(f"{entry.key}: cannot read PDFs")
                continue
            budget = self._budget(entry)
            need = est_in + spec["max_output_tokens"]
            if not budget.fits_at_all(need):
                attempts.append(f"{entry.key}: request (~{need} tokens) exceeds its {budget.tpm} tokens/min")
                continue
            if not budget.day_left(need):
                attempts.append(f"{entry.key}: daily token budget used")
                continue
            try:
                result = self._run_entry(task, entry, spec, system, user, schema, pdf, budget, label)
            except ProviderError as exc:
                attempts.append(f"{entry.key}: {exc}")
                continue
            result.attempts = attempts + result.attempts
            self._cache_put(key, result)
            return result
        raise LLMError(task, attempts)

    # ------------------------------------------------------------ internals

    def _run_entry(self, task, entry, spec, system, user, schema, pdf, budget, label) -> LLMResult:
        messages = [("user", user)]
        notes: list[str] = []
        total_in = total_out = 0
        for attempt in (1, 2):  # first try + one repair
            text, tin, tout = self._call_with_limits(entry, spec, system, messages, pdf, budget, task, label)
            total_in += tin
            total_out += tout
            try:
                data = extract_json(text)
                problem = schema_error(data, schema)
            except (json.JSONDecodeError, ValueError) as exc:
                data, problem = None, f"not valid JSON ({exc})"
            if problem is None:
                return LLMResult(data, entry.provider, entry.model, total_in, total_out, False, notes)
            notes.append(f"{entry.key}: attempt {attempt} invalid: {problem[:200]}")
            log.warning("%s %s reply failed validation: %s", task, entry.key, problem[:200])
            messages += [
                ("assistant", text[:4000]),
                ("user", f"That reply was invalid: {problem}. Reply again with only the corrected JSON object."),
            ]
        raise ProviderError("reply failed the schema twice: " + notes[-1].split("invalid: ", 1)[-1])

    def _call_with_limits(self, entry, spec, system, messages, pdf, budget, task, label) -> tuple[str, int, int]:
        need = estimate_tokens(system + "".join(m for _, m in messages)) + spec["max_output_tokens"]
        for attempt in (1, 2):
            wait = budget.wait_needed(need)
            if wait > self.max_wait:
                raise ProviderError(f"would need to wait {wait:.0f}s for its per-minute budget")
            if wait > 0:
                log.info("%s: waiting %.0fs for %s's per-minute budget", task, wait, entry.key)
                self.sleep(wait)
            started = self.clock()
            try:
                text, tin, tout = self._call(entry, spec, system, messages, pdf)
            except ProviderError as exc:
                retryable = exc.status == 429 or (exc.status is not None and exc.status >= 500)
                delay = exc.retry_after if exc.retry_after is not None else 5.0 * attempt
                self._log(task, entry.provider, entry.model, 0, 0, False, False, label, 0, error=str(exc)[:400])
                if attempt == 1 and retryable and delay <= self.max_wait:
                    self.sleep(delay)
                    continue
                raise
            budget.record(tin + tout)
            self._log(task, entry.provider, entry.model, tin, tout, False, True, label, int((self.clock() - started) * 1000))
            return text, tin, tout
        raise ProviderError("unreachable")

    def _call(self, entry: ChainEntry, spec: dict, system: str, messages: list[tuple[str, str]], pdf: bytes | None):
        provider = self.providers[entry.provider]
        key = self.env[provider["api_key_env"]]
        base = provider["base_url"].rstrip("/")
        if provider["kind"] == "openai_compatible":
            payload = {
                "model": entry.model,
                "messages": [{"role": "system", "content": system}] + [{"role": r, "content": c} for r, c in messages],
                "temperature": spec["temperature"],
                "max_completion_tokens": spec["max_output_tokens"],
                "response_format": {"type": "json_object"},
                **entry.params,
            }
            status, headers, body = self.transport(
                f"{base}/chat/completions", {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, payload, self.timeout
            )
            self._raise_for(status, headers, body)
            try:
                text = body["choices"][0]["message"]["content"] or ""
                usage = body.get("usage") or {}
                return text, int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
            except (KeyError, IndexError, TypeError) as exc:
                raise ProviderError(f"unexpected response shape: {str(body)[:200]}") from exc

        if provider["kind"] == "gemini":
            contents = []
            for i, (role, content) in enumerate(messages):
                parts: list[dict] = [{"text": content}]
                if i == 0 and pdf is not None:
                    parts.insert(0, {"inline_data": {"mime_type": "application/pdf", "data": base64.b64encode(pdf).decode()}})
                contents.append({"role": "model" if role == "assistant" else "user", "parts": parts})
            gen = {
                "temperature": spec["temperature"],
                "maxOutputTokens": spec["max_output_tokens"],
                "responseMimeType": "application/json",
            }
            # Gemini 3.x takes a thinking level; 2.x took a token budget. Send whichever is configured.
            if "thinking_level" in entry.params:
                gen["thinkingConfig"] = {"thinkingLevel": str(entry.params["thinking_level"])}
            elif "thinking_budget" in entry.params:
                gen["thinkingConfig"] = {"thinkingBudget": int(entry.params["thinking_budget"])}
            payload = {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents, "generationConfig": gen}
            status, headers, body = self.transport(
                f"{base}/models/{entry.model}:generateContent", {"x-goog-api-key": key, "Content-Type": "application/json"}, payload, self.timeout
            )
            self._raise_for(status, headers, body)
            try:
                cand = body["candidates"][0]
                text = "".join(p.get("text", "") for p in cand["content"]["parts"])
                usage = body.get("usageMetadata") or {}
                out = int(usage.get("candidatesTokenCount") or 0) + int(usage.get("thoughtsTokenCount") or 0)
                return text, int(usage.get("promptTokenCount") or 0), out
            except (KeyError, IndexError, TypeError) as exc:
                raise ProviderError(f"unexpected response shape: {str(body)[:200]}") from exc

        raise LLMConfigError(f"provider kind {provider['kind']!r} is not supported")

    @staticmethod
    def _raise_for(status: int, headers: dict, body: Any) -> None:
        if 200 <= status < 300:
            return
        retry_after = None
        ra = {k.lower(): v for k, v in (headers or {}).items()}.get("retry-after")
        try:
            retry_after = float(ra) if ra is not None else None
        except ValueError:
            retry_after = None
        detail = body.get("error", body) if isinstance(body, dict) else body
        if isinstance(detail, dict):
            detail = detail.get("message", detail)
        raise ProviderError(f"HTTP {status}: {str(detail)[:400]}", status=status, retry_after=retry_after)

    def _cache_key(self, task, spec, system, user, schema, pdf) -> str:
        h = hashlib.sha256()
        chain = [(e.key, sorted(e.params.items())) for e in spec["chain"]]
        for part in (task, json.dumps(chain), system, user, json.dumps(schema, sort_keys=True)):
            h.update(part.encode("utf-8"))
            h.update(b"\0")
        if pdf is not None:
            h.update(hashlib.sha256(pdf).digest())
        return h.hexdigest()

    def _cache_get(self, key: str) -> dict | None:
        path = self.cache_dir / f"{key}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _cache_put(self, key: str, result: LLMResult) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        payload = {"provider": result.provider, "model": result.model, "data": result.data}
        (self.cache_dir / f"{key}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _log(self, task, provider, model, tin, tout, cached, ok, label, latency_ms, error=None) -> None:
        self.usage_log.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "at": iso_ist(now_ist()),
            "date": self.today(),
            "task": task,
            "label": label,
            "provider": provider,
            "model": model,
            "input_tokens": tin,
            "output_tokens": tout,
            "cached": cached,
            "ok": ok,
            "latency_ms": latency_ms,
        }
        if error:
            rec["error"] = error
        with open(self.usage_log, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
