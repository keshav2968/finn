"""Map BSE filings onto the 17 reference categories.

Order of precedence:
  1. config rules, first match wins (BSE subcategory, routine patterns, keywords)
  2. same-day context: a generic "Outcome of Board Meeting" (or a press release
     about the board meeting) on a day the company filed results belongs to the
     results release
  3. the LLM cache, for filings the rules could not place (written in step d)
  4. otherwise pending: shown at a neutral score until the LLM classifies it

Rules always run, even when the cache has an answer, so improving a rule takes
effect on the next build without clearing anything.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from ingest.common import get_logger

from .config import PushConfig, Rule

log = get_logger("push.classify")

EVENT, NOTICE = "event", "notice"
RULE, CONTEXT, LLM, PENDING = "rule", "context", "llm", "pending"


@dataclass(frozen=True)
class Classification:
    category: str
    kind: str  # event | notice
    method: str  # rule | context | llm | pending
    rule_id: str | None = None  # the rule id, or the model for llm answers
    summary: str | None = None  # one-line summary from the LLM, used as the card headline

    @property
    def pending(self) -> bool:
        return self.method == PENDING

    def to_dict(self) -> dict[str, Any]:
        return {"category": self.category, "kind": self.kind, "method": self.method, "rule": self.rule_id}


_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)


def filing_text(item: dict[str, Any]) -> str:
    """Title + detail + more, without repeating identical pieces. Links are dropped:
    a news URL like .../usfda-order-... must not read as "order"."""
    parts: list[str] = []
    for key in ("title", "detail", "more"):
        value = _URL_RE.sub(" ", item.get(key) or "").strip()
        if value and value not in parts:
            parts.append(value)
    return " | ".join(parts)


def filing_time(item: dict[str, Any]) -> datetime | None:
    try:
        return datetime.fromisoformat(item["datetime"]) if item.get("datetime") else None
    except ValueError:
        return None


def rule_matches(rule: Rule, item: dict[str, Any], text: str) -> bool:
    checks = (
        (rule.subcategory, item.get("bse_subcategory") or ""),
        (rule.bse_category, item.get("bse_category") or ""),
        (rule.title, item.get("title") or ""),
        (rule.text, text),
        (rule.also, text),
    )
    for pattern, value in checks:
        if pattern is not None and not pattern.search(value):
            return False
    return not (rule.unless is not None and rule.unless.search(text))


def is_notice(item: dict[str, Any], cfg: PushConfig) -> bool:
    if (item.get("bse_category") or "").lower() == "board meeting" and (
        item.get("bse_subcategory") or ""
    ).lower() == "board meeting":
        return True
    return bool(cfg.notice_title.search(item.get("title") or ""))


def classify_by_rules(item: dict[str, Any], cfg: PushConfig) -> Classification | None:
    text = filing_text(item)
    for rule in cfg.rules:
        if rule_matches(rule, item, text):
            return Classification(rule.category, NOTICE if is_notice(item, cfg) else EVENT, RULE, rule.id)
    return None


def load_llm_cache(path: Path, cfg: PushConfig) -> dict[str, dict[str, Any]]:
    """{filing_id: {"category", "kind", "confidence", "summary", "model"}}.

    Entries with an unknown category, or a confidence below classifier.llm_min_confidence,
    are ignored: those filings stay visible as Unclassified rather than trust a guess."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("ignoring unreadable LLM cache %s: %s", path, exc)
        return {}
    entries = data.get("items", data) if isinstance(data, dict) else {}
    valid = {}
    for fid, entry in entries.items():
        if not isinstance(entry, dict) or entry.get("category") not in cfg.categories:
            log.warning("ignoring LLM cache entry %s: %r", fid, entry)
            continue
        confidence = entry.get("confidence")
        if isinstance(confidence, (int, float)) and confidence < cfg.llm_min_confidence:
            continue
        valid[str(fid)] = entry
    return valid


def classify_all(
    items: Iterable[dict[str, Any]],
    cfg: PushConfig,
    llm_cache: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Classification]:
    items = list(items)
    out: dict[str, Classification] = {}
    for item in items:
        cls = classify_by_rules(item, cfg)
        out[item["id"]] = cls or Classification("unclassified", NOTICE if is_notice(item, cfg) else EVENT, PENDING)

    # Same-day context: anchors are filings the rules placed in the context category.
    anchors: dict[str, list[datetime]] = {}
    for item in items:
        cls = out[item["id"]]
        when = filing_time(item)
        if cls.method == RULE and cls.category == cfg.context_category and cls.kind == EVENT and when:
            anchors.setdefault(item["symbol"], []).append(when)
    window = cfg.context_window_hours * 3600
    for item in items:
        cls = out[item["id"]]
        overridable = cls.pending or (cls.method == RULE and cls.category in cfg.context_override)
        if not overridable or not cfg.context_text.search(filing_text(item)):
            continue
        when = filing_time(item)
        near = when and any(abs((when - a).total_seconds()) <= window for a in anchors.get(item["symbol"], []))
        if near:
            out[item["id"]] = Classification(cfg.context_category, EVENT, CONTEXT, "same_day_" + cfg.context_category)

    for item in items:
        cached = (llm_cache or {}).get(item["id"])
        if out[item["id"]].pending and cached:
            kind = cached.get("kind") if cached.get("kind") in (EVENT, NOTICE) else out[item["id"]].kind
            out[item["id"]] = Classification(cached["category"], kind, LLM, cached.get("model"), cached.get("summary") or None)
    return out
