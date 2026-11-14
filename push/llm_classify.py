"""Classify the filings no rule could place, with one LLM call each.

Input per filing: BSE's title/category/subcategory/detail plus the first pages of the
PDF, extracted in Python. Scanned PDFs (no text layer) are passed as bytes, which the
router only sends to a provider that reads PDFs. The answer must match a JSON schema
(category from the 17, kind, confidence, a one-line summary) and is stored by filing
id in the LLM cache that push/classify.py reads. No arithmetic is asked for.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ingest.common import get_logger, iso_ist, now_ist, read_json, write_json
from ingest.pdfs import PdfError, extract_text

from .config import PushConfig

log = get_logger("push.llm")

PDF_PAGES = 2
PDF_MAX_CHARS = 6000  # ~1,500 tokens: keeps a call well inside Groq's per-minute budget


def classification_schema(cfg: PushConfig) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["category", "kind", "confidence", "summary"],
        "properties": {
            "category": {"enum": list(cfg.categories)},
            "kind": {"enum": ["event", "notice"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "summary": {"type": "string", "minLength": 3, "maxLength": 200},
        },
    }


def system_prompt(cfg: PushConfig) -> str:
    lines = [
        "You classify Indian listed-company stock-exchange filings (BSE) for an investor's feed.",
        "Pick exactly one category:",
    ]
    lines += [f"- {cid}: {cat.description}" for cid, cat in cfg.categories.items()]
    lines += [
        "kind is 'notice' when the filing only announces something that will happen later "
        "(a meeting date, a record date, an upcoming call); otherwise 'event'.",
        "confidence is your probability (0 to 1) that the category is right. If the text does "
        "not say what the filing is about, use a low confidence.",
        "summary: one plain sentence, at most 25 words, saying what the filing discloses. Copy "
        "names and figures exactly as written; never calculate anything.",
    ]
    return "\n".join(lines)


def user_prompt(item: dict[str, Any], pdf_text: str) -> str:
    parts = [
        f"Company symbol: {item.get('symbol')}",
        f"BSE category: {item.get('bse_category') or '-'} / {item.get('bse_subcategory') or '-'}",
        f"Title: {item.get('title') or '-'}",
        f"Detail: {item.get('detail') or '-'}",
    ]
    more = (item.get("more") or "").strip()
    if more and more != (item.get("detail") or "").strip():
        parts.append(f"More: {more[:1500]}")
    parts.append("PDF text (first pages):\n" + (pdf_text or "(not available)"))
    return "\n".join(parts)


@dataclass
class Outcome:
    item: dict[str, Any]
    entry: dict[str, Any] | None
    note: str


def classify_items(
    items: list[dict[str, Any]],
    cfg: PushConfig,
    complete: Callable[..., Any],
    get_pdf: Callable[[str], bytes] | None,
) -> list[Outcome]:
    """`complete` is Router.complete_json; `get_pdf(url) -> bytes` (None = don't fetch PDFs)."""
    schema = classification_schema(cfg)
    system = system_prompt(cfg)
    outcomes = []
    for item in items:
        pdf_text, pdf_bytes, source = "", None, "filing text"
        if get_pdf and item.get("pdf_url"):
            try:
                data = get_pdf(item["pdf_url"])
                text = extract_text(data, max_pages=PDF_PAGES)
                if text.scanned:
                    pdf_bytes, source = data, "scanned PDF"
                else:
                    pdf_text, source = text.text(max_chars=PDF_MAX_CHARS), "filing text + PDF"
            except PdfError as exc:
                source = f"filing text (PDF unavailable: {exc})"
        try:
            result = complete(
                "classify_filing", system, user_prompt(item, pdf_text), schema, pdf=pdf_bytes, label=f"{item['symbol']}:{item['id']}"
            )
        except Exception as exc:  # noqa: BLE001 - one filing failing must not stop the rest
            log.error("classify %s %s failed: %s", item["symbol"], item["id"], exc)
            outcomes.append(Outcome(item, None, f"failed: {exc}"))
            continue
        data = result.data
        entry = {
            "category": data["category"],
            "kind": data["kind"],
            "confidence": round(float(data["confidence"]), 2),
            "summary": " ".join(str(data["summary"]).split()),
            "model": f"{result.provider}/{result.model}",
            "source": source,
            "at": iso_ist(now_ist()),
        }
        outcomes.append(Outcome(item, entry, "cached" if result.cached else "ok"))
    return outcomes


def merge_into_cache(path: Path, outcomes: list[Outcome]) -> int:
    existing = read_json(path) or {}
    items = dict(existing.get("items") or {})
    added = 0
    for o in outcomes:
        if o.entry is not None:
            items[o.item["id"]] = o.entry
            added += 1
    write_json(path, {"note": "LLM classifications for filings no rule could place; keyed by BSE filing id.", "items": items})
    return added


def dump_prompt(item: dict[str, Any], cfg: PushConfig, pdf_text: str = "") -> str:
    """What a call would send, for --dry-run."""
    return json.dumps(
        {"system": system_prompt(cfg), "user": user_prompt(item, pdf_text), "schema": classification_schema(cfg)},
        ensure_ascii=False,
        indent=1,
    )
