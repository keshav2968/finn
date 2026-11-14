"""Promise extraction (cheap model) and the Python checks that keep it honest.

The model only copies: a quote, the numbers in it, a metric name from a fixed list and a
fiscal period label. Python then:
- fuzzy-matches every quote to the transcript and drops any that don't match,
- takes the speaker from the parsed transcript (not from the model) and drops anything
  not said by management,
- drops target numbers that do not appear in the quote,
- normalises the period and groups the same promise across calls.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from rapidfuzz import fuzz

from . import periods

from .transcripts import Passage, Transcript

BASES = ["constant_currency", "reported", "usd", "unspecified"]
NUM = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")


# ---------------------------------------------------------------- quotes

def normalise(text: str) -> str:
    t = (text or "").lower()
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = re.sub(r"[‐-―−]", "-", t)
    t = re.sub(r"-\s*\n\s*", "", t)          # words hyphenated across a line break
    t = re.sub(r"[^a-z0-9%$.,'\-\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def quote_score(quote: str, source: str) -> float:
    """0-100: how well `quote` appears, word for word, somewhere in `source`."""
    q, s = normalise(quote), normalise(source)
    if not q or not s:
        return 0.0
    if q in s:
        return 100.0
    return float(fuzz.partial_ratio(q, s))


def quote_found(quote: str, source: str, min_score: float, min_chars: int) -> tuple[bool, float]:
    if len((quote or "").strip()) < min_chars:
        return False, 0.0
    score = quote_score(quote, source)
    return score >= min_score, round(score, 1)


def numbers_in(text: str) -> set[float]:
    return {float(n) for n in NUM.findall((text or "").replace(",", ""))}


# ---------------------------------------------------------------- extraction

def schema(metric_keys: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["promises"],
        "properties": {
            "promises": {
                "type": "array",
                "maxItems": 25,
                "items": {
                    "type": "object",
                    "required": ["metric", "metric_text", "quote", "passage_id", "period", "basis"],
                    "properties": {
                        "metric": {"type": "string", "enum": metric_keys},
                        "metric_text": {"type": "string", "maxLength": 160},
                        "target_low": {"type": ["number", "null"]},
                        "target_high": {"type": ["number", "null"]},
                        "unit": {"type": ["string", "null"], "maxLength": 12},
                        "basis": {"type": "string", "enum": BASES},
                        "period": {"type": "string", "maxLength": 24},
                        "quote": {"type": "string", "maxLength": 700},
                        "passage_id": {"type": "string", "maxLength": 40},
                    },
                },
            }
        },
    }


def system_prompt(metrics: dict[str, Any]) -> str:
    keys = ", ".join(f'"{k}" ({m["label"]})' for k, m in metrics.items())
    return (
        "You read passages from an Indian listed company's earnings call and list the forward-looking "
        "commitments its management made: guidance, targets and dated plans with a measurable outcome.\n"
        "Rules:\n"
        "- Only statements by the company's management. The speaker of each passage is given; ignore "
        "questions from analysts or journalists.\n"
        "- Only statements about a future period. Results already achieved are not promises.\n"
        "- quote: copy the exact words from the passage, one or two sentences. No paraphrase, no ellipsis.\n"
        f"- metric: one of {keys}. Use \"other\" when none fits and describe it in metric_text.\n"
        "- target_low / target_high: copy the numbers from the quote; never calculate. A single number goes "
        "in both. null when the promise has no number.\n"
        "- unit: \"%\", \"bps\", \"crore\", \"bn\", \"mn\", \"x\" or null. basis: as stated (constant currency, "
        "reported, USD) or \"unspecified\".\n"
        "- period: a fiscal label such as \"FY27\", \"H2FY27\" or \"Q3FY27\"; \"medium_term\" or \"unspecified\" "
        "when no period is stated. The Indian fiscal year FY27 runs April 2026 to March 2027. \"This year\" or "
        "\"for the year\" means the fiscal year of the quarter being reported (given below); \"next year\" or "
        "\"the coming financial year\" means the one after.\n"
        "- passage_id: the id of the passage the quote comes from.\n"
        'Return {"promises": []} when there are none.'
    )


def user_prompt(company: str, transcript: Transcript, passages: list[Passage]) -> str:
    fy = transcript.fiscal or "unknown"
    lines = [
        f"Company: {company}",
        f"Call: {transcript.period}; quarter reported: {transcript.quarter or 'unknown'} ({fy})",
        "",
        "Passages:",
    ]
    for p in passages:
        lines.append(f"[{p.id}] {p.speaker}: {p.text}")
    return "\n".join(lines)


def normalise_period(raw: str, transcript: Transcript) -> str:
    p = re.sub(r"[\s'’`]", "", (raw or "")).upper().replace("FY20", "FY")
    p = p.replace("FISCAL", "FY")
    if p in ("MEDIUM_TERM", "MEDIUMTERM", "LONGTERM", "LONG_TERM"):
        return "medium_term"
    m = re.fullmatch(r"(Q[1-4]|H[12]|9M)?FY(\d{2})", p)
    if m:
        return f"{m.group(1) or ''}FY{m.group(2)}"
    m = re.fullmatch(r"FY(\d{2})(Q[1-4]|H[12])", p)  # "FY27Q3" -> "Q3FY27"
    if m:
        return f"{m.group(2)}FY{m.group(1)}"
    return "unspecified"


# A year named in the quote: "FY27", "FY 2027", "FY2026-27", "financial year '27", "fiscal 2027".
YEAR_NAMED = re.compile(r"\b(?:fy|financial year|fiscal(?: year)?)\s*'?\s*(\d{2}(?:\d{2})?)(?:\s*[-–/]\s*(\d{2}))?\b", re.I)
NEXT_YEAR = re.compile(r"\b(next|coming|following)\s+(financial\s+|fiscal\s+)?year\b|\byear ahead\b", re.I)
THIS_YEAR = re.compile(r"\b(full year|this year|for the year|this financial year|current (financial |fiscal )?year|the financial year|the year)\b", re.I)
BASIS_WORDS = [
    ("constant_currency", re.compile(r"constant currency|\bcc (terms|basis)\b|\bin cc\b", re.I)),
    ("usd", re.compile(r"dollar terms|\busd\b|us\$|\$ terms", re.I)),
    ("reported", re.compile(r"rupee terms|\binr\b|₹ terms|reported (currency|terms)", re.I)),
]
UNIT_AFTER = [
    ("%", re.compile(r"^\s*(%|percent|per cent)", re.I)),
    ("bps", re.compile(r"^\s*(bps|basis points)", re.I)),
    ("crore", re.compile(r"^\s*(crore|cr\b)", re.I)),
    ("bn", re.compile(r"^\s*(bn|billion)", re.I)),
    ("mn", re.compile(r"^\s*(mn|million)", re.I)),
    ("x", re.compile(r"^\s*x\b", re.I)),
    ("days", re.compile(r"^\s*days?\b", re.I)),
]


def resolve_period(model_period: str, quote: str, transcript: Transcript) -> tuple[str, str | None]:
    """The fiscal period a promise is about, decided from the quote, not the model:
    a year named in the quote wins; "next/coming year" is the year after the call's;
    otherwise "full year"/"this year" is the call's own fiscal year. Returns (period, note)."""
    p = normalise_period(model_period, transcript)
    prefix = re.match(r"^(Q[1-4]|H[12]|9M)", p)
    prefix_s = prefix.group(1) if prefix else ""
    named = []
    for m in YEAR_NAMED.finditer(quote or ""):
        yy = m.group(2) or m.group(1)
        named.append(int(yy[-2:]))
    cur = transcript.current_fy()
    if named:
        fy = max(named)
    elif NEXT_YEAR.search(quote or "") and cur is not None:
        fy = (cur + 1) % 100
    elif cur is not None and (periods.is_valid(p) or THIS_YEAR.search(quote or "")):
        fy = cur
    else:
        return p, None
    resolved = f"{prefix_s}FY{fy:02d}"
    note = None if resolved == p else f"period set to {resolved} from the quote and the call date (model said {model_period or 'nothing'})"
    return resolved, note


def basis_from_quote(quote: str) -> str:
    """Currency basis only as the quote states it; otherwise "unspecified"."""
    for basis, rx in BASIS_WORDS:
        if rx.search(quote or ""):
            return basis
    return "unspecified"


def unit_from_quote(quote: str, value: float) -> str | None:
    """The unit written right after `value` in the quote ("20%", "$2 bn"); None for a plain count."""
    plain = (quote or "").replace(",", "")
    for m in NUM.finditer(plain):
        if float(m.group(0)) == float(value):
            after = plain[m.end():m.end() + 16]
            for unit, rx in UNIT_AFTER:
                if rx.match(after):
                    return unit
            # A range like "20% to 22%" puts the unit after the second number only.
            nxt = re.match(r"^\s*(?:to|and|-|–)\s*(-?\d+(?:\.\d+)?)", after)
            if nxt:
                rest = plain[m.end() + nxt.end():m.end() + nxt.end() + 16]
                for unit, rx in UNIT_AFTER:
                    if rx.match(rest):
                        return unit
            return None
    return None


def forward_looking(quote: str, words: list[str]) -> bool:
    low = (quote or "").lower()
    return any(w in low for w in words)


def check_promises(
    raw: dict[str, Any],
    transcript: Transcript,
    sent: list[Passage],
    cfg: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(accepted promises, dropped items with the reason)."""
    qcfg, metrics = cfg["quotes"], cfg["metrics"]
    by_id = {p.id: p for p in transcript.passages}
    accepted, dropped, seen = [], [], set()
    for item in raw.get("promises") or []:
        quote = (item.get("quote") or "").strip()
        # Find the passage that really holds the quote: the cited one first, then the rest.
        candidates = [by_id[item["passage_id"]]] if item.get("passage_id") in by_id else []
        candidates += [p for p in sent if p not in candidates] + [p for p in transcript.passages if p not in candidates and p not in sent]
        best, best_score = None, 0.0
        for p in candidates:
            ok, score = quote_found(quote, p.text, qcfg["min_score"], qcfg["min_chars"])
            if ok:
                best, best_score = p, score
                break
            best_score = max(best_score, score)
        if best is None:
            dropped.append({"call": transcript.period, "quote": quote[:200], "reason": f"quote not found in the transcript (best match {best_score:.0f}/100)"})
            continue
        if not best.management:
            dropped.append({"call": transcript.period, "quote": quote[:200], "reason": f"said by {best.speaker}, not management"})
            continue
        if not forward_looking(quote, cfg["filter"]["forward"]):
            dropped.append({"call": transcript.period, "quote": quote[:200], "reason": "no forward-looking words: reads as a reported result, not a promise"})
            continue
        in_quote = numbers_in(quote)
        low, high = item.get("target_low"), item.get("target_high")
        notes = []
        bad = [v for v in (low, high) if v is not None and float(v) not in in_quote]
        if bad:
            # A number the speaker never said: keep the quote, drop the target rather than guess.
            notes.append(f"target {', '.join(f'{v:g}' for v in bad)} is not in the quote; target removed")
            low = high = None
        if low is None and high is not None:
            low = high
        if high is None and low is not None:
            high = low
        if low is not None and high is not None and low > high:
            low, high = high, low
        metric = item.get("metric") if item.get("metric") in metrics else "other"
        period, pnote = resolve_period(item.get("period", ""), quote, transcript)
        if pnote:
            notes.append(pnote)
        basis = basis_from_quote(quote)
        if basis != (item.get("basis") or "unspecified"):
            notes.append(f"basis {basis.replace('_', ' ')} taken from the quote (model said {item.get('basis') or 'nothing'})")
        unit = unit_from_quote(quote, low) if low is not None else None
        key = (metric, period, low, high, basis, (item.get("metric_text") or "").lower()[:40] if metric == "other" else "")
        if key in seen:
            continue
        seen.add(key)
        accepted.append({
            "metric": metric,
            "metric_label": metrics[metric]["label"],
            "metric_text": (item.get("metric_text") or "").strip(),
            "target_low": low,
            "target_high": high,
            "unit": unit,
            "basis": basis,
            "period": period,
            "quote": quote,
            "quote_score": best_score,
            "speaker": best.speaker,
            "passage_id": best.id,
            "call": transcript.period,
            "call_month": transcript.month,
            "quarter": transcript.quarter,
            "fiscal": transcript.fiscal,
            "call_label": transcript.label,
            "source_url": transcript.url,
            "notes": notes,
        })
    return accepted, dropped


def extract(
    company: str,
    transcript: Transcript,
    sent: list[Passage],
    cfg: dict[str, Any],
    complete: Callable[..., Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """Run the extractor on one transcript's filtered passages. Returns (promises, dropped, model)."""
    metrics = cfg["metrics"]
    result = complete(
        "extract_promises",
        system_prompt(metrics),
        user_prompt(company, transcript, sent),
        schema(list(metrics)),
        label=f"{company} {transcript.period}",
    )
    promises, dropped = check_promises(result.data, transcript, sent, cfg)
    return promises, dropped, f"{result.provider}/{result.model}"


# ---------------------------------------------------------------- grouping across calls

def _num(v: float) -> str:
    return f"{v:,.0f}" if abs(v) >= 1000 and float(v).is_integer() else f"{v:g}"


def _target_text(low: float | None, high: float | None, unit: str | None) -> str | None:
    if low is None:
        return None
    u = {"%": "%", "bps": " bps", "crore": " crore", "bn": " bn", "mn": " mn", "x": "x", "days": " days"}.get(unit or "", "")
    return f"{_num(low)}{u}" if low == high else f"{_num(low)}–{_num(high)}{u}"


GENERIC = {"target", "guidance", "growth", "plan", "expected", "expect", "around", "approximately", "about", "year", "this", "that", "with", "will"}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", (text or "").lower()) if w not in GENERIC}


def _same_other(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Two "other" promises are one commitment when they are for the same period and
    either name the same count/amount (a non-% target such as 20,000 hires) or share
    descriptive words and the same target."""
    if a["period"] != b["period"]:
        return False
    same_target = a["target_low"] is not None and (a["target_low"], a["target_high"]) == (b["target_low"], b["target_high"])
    if same_target and (a.get("unit") or "") not in ("%", "bps"):
        return True
    overlap = _words(a["metric_text"] + " " + a["quote"]) & _words(b["metric_text"] + " " + b["quote"])
    return bool(overlap) and (same_target or a["target_low"] is None or b["target_low"] is None) and len(overlap) >= 2


def _direction(first: tuple[float, float], last: tuple[float, float]) -> str:
    """"cut" or "raised" by the midpoint of the range (Python arithmetic, never the model's)."""
    a, b = (first[0] + first[1]) / 2, (last[0] + last[1]) / 2
    return "raised" if b > a else ("cut" if b < a else "changed")


def group(promises: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The same commitment across calls: one group per (metric, period), statements oldest
    first. "Other" promises merge only when they are clearly the same commitment."""
    buckets: list[list[dict[str, Any]]] = []
    for p in promises:
        p["target_text"] = _target_text(p["target_low"], p["target_high"], p.get("unit"))
        home = None
        for b in buckets:
            head = b[0]
            if p["metric"] != head["metric"]:
                continue
            if p["metric"] != "other" and p["period"] == head["period"]:
                home = b
                break
            if p["metric"] == "other" and any(_same_other(p, q) for q in b):
                home = b
                break
        if home is None:
            buckets.append([p])
        else:
            home.append(p)
    buckets.sort(key=lambda b: (b[0]["metric"] == "other", b[0]["metric"], b[0]["period"]))
    out = []
    for i, items in enumerate(buckets):
        items.sort(key=lambda p: p["call_month"])
        # One statement per call (the first with a number, else the first).
        per_call: dict[str, dict[str, Any]] = {}
        for p in items:
            cur = per_call.get(p["call_month"])
            if cur is None or (cur["target_low"] is None and p["target_low"] is not None):
                per_call[p["call_month"]] = p
        statements = [per_call[k] for k in sorted(per_call)]
        targets = [(s["target_low"], s["target_high"]) for s in statements if s["target_low"] is not None]
        distinct: list[tuple[float, float]] = []
        for tg in targets:
            if not distinct or distinct[-1] != tg:
                distinct.append(tg)
        latest = next((s for s in reversed(statements) if s["target_low"] is not None), statements[-1])
        revised = len(distinct) > 1
        out.append({
            "id": f"g{i + 1}",
            "metric": items[0]["metric"],
            "metric_label": statements[0]["metric_label"],
            "metric_text": latest["metric_text"],
            "period": items[0]["period"],
            "statements": statements,
            "latest": latest,
            "revised": revised,
            "direction": _direction(distinct[0], distinct[-1]) if revised else None,
            "path": " → ".join(_target_text(lo, hi, latest.get("unit")) or "" for lo, hi in distinct) if revised else None,
        })
    return out
