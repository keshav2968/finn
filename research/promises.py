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
                        "scope": {"type": "string", "maxLength": 60},
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
        "- scope: \"company\" when the target is for the whole company; otherwise the business segment, division or "
        "product line it is for, in the passage's own words (e.g. \"FMEG\", \"Wires & Cables\", \"quick commerce\").\n"
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
YEAR_BY = re.compile(r"\b(?:by|through|till|until|to)\s+(?:the\s+end\s+of\s+)?(?:march\s+)?(20[2-4]\d)\b", re.I)
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
    named += [int(m.group(1)[-2:]) for m in YEAR_BY.finditer(quote or "")]  # "by 2030" = by March 2030 = FY30
    cur = transcript.current_fy()
    if not named and MEDIUM_TERM.search(quote or "") and not THIS_YEAR.search(quote or ""):
        resolved = "medium_term"
        return resolved, (None if resolved == p else f"period set to medium term from the quote (model said {model_period or 'nothing'})")
    if named:
        fy = max(named)
    elif BY_MARCH.search(quote or "") and cur is not None:
        fy = cur
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


REPORTED_SPEECH = re.compile(r"\byou (?:have |had )?(?:spoke|spoken|said|mentioned|talked|guided|indicated|highlighted|called out)\b|\byour (?:guidance|target|aspiration)\b", re.I)


SEGMENT_CUE = re.compile(r"\b(for this business|this business|the business|segment|division|vertical|this category)\b", re.I)


def resolve_scope(item_scope: str | None, quote: str, passage_text: str) -> str:
    """"company", or the segment a target is for. A segment the model names must appear in
    the passage; a quote that says "this business"/"segment" is a segment even if unnamed."""
    s = (item_scope or "company").strip()
    if s.lower() not in ("company", "whole company", "consolidated", "") and s.lower() in passage_text.lower():
        return s
    if SEGMENT_CUE.search(quote or ""):
        return "a business segment"
    return "company"


def remap_metric(metric: str, quote: str, metrics: dict[str, Any]) -> str:
    """An "other" promise whose quote names exactly one known metric by a multi-word alias
    ("EBITDA margin", "revenue growth") is that metric."""
    if metric != "other":
        return metric
    low = (quote or "").lower()
    hits = {k for k, m in metrics.items() if k != "other" and any(" " in a and a in low for a in m.get("aliases") or [])}
    return hits.pop() if len(hits) == 1 else metric


# Words that make a sentence a commitment about the future. Period words ("full year") are
# not enough on their own: "we were at 70-75% for the full year" is a result.
PROMISE_RX = re.compile(
    r"(?:\b(?:guidance|guide[ds]?|guiding|expect\w*|target\w*|aim\w*|aspir\w*|plan\w*|will|would|should|shall|going forward|"
    r"going to|outlook|on track|commit\w*|confident|intend\w*|look(?:ing)? to|hope|envisage\w*|anticipat\w*|forecast\w*|"
    r"objective\w*|ambition\w*|towards|remains?|maintain(?:s|ing)?|by (?:the end of )?march|over the next|in the coming|"
    r"from next year|next year)\b|\b(?:we|i|they|it)'ll\b|\bby fy\s?'?\d{2,4}\b)", re.I)


def forward_looking(quote: str, words: list[str] | None = None) -> bool:
    return bool(PROMISE_RX.search(quote or ""))


def metric_named(metric: str, quote: str, metrics: dict[str, Any], passage: str = "") -> bool:
    """A metric is only taken from the model when the quote, or the words just before it in
    the passage ("...capex. We'll do Rs 1,200 to 1,600 crore for the year"), name it."""
    near = (quote or "").lower()
    if passage:
        np, head = normalise(passage), normalise(quote)[:40]
        at = np.find(head) if head else -1
        if at >= 0:
            near = np[max(0, at - 250): at + len(normalise(quote))]
    return any(re.search(rf"\b{re.escape(a)}", near) for a in (metrics.get(metric) or {}).get("aliases") or [])


# "30% revenue growth in solution and products", "EBITDA margins on FMEG": the target is for
# a business line, not the company.
SCOPE_AFTER = re.compile(r"\b(?:growth|revenue|revenues|margins?|ebitda|ebit)\s+(?:in|on|for|from|of)\s+(?:the\s+|our\s+)?([a-z][\w&/\- ]{2,40}?)"
                         r"(?=[.,;]|\s+(?:to|by|in|at|of|for|and we|which|that|from|as|is|are|was|were|will|would|should|with)\b|$)", re.I)
NOT_SCOPE = re.compile(r"^(range|year|quarter|full|financial|fiscal|fy|this|next|coming|constant|cc|dollar|rupee|usd|inr|terms|h[12]|q[1-4]|"
                       r"line|guidance|guided|absolute|percentage|basis|medium|long|short|near|first|second|third|fourth|last|overall|"
                       r"company|business as a whole|top line|topline|revenue|sales|growth|around|about|approximately|at least|over|"
                       r"\d)", re.I)


def scope_from_quote(quote: str) -> str | None:
    for m in SCOPE_AFTER.finditer(quote or ""):
        phrase = m.group(1).strip()
        if phrase and not NOT_SCOPE.match(phrase):
            return phrase
    return None


GROWTH_METRICS = ("revenue_growth", "profit_growth", "loan_growth")
SHARE_OF = re.compile(r"\d\s?%\s+(?:of|contribution (?:to|from))\s+(?:our\s+|the\s+)?(?:overall\s+|total\s+|consolidated\s+)?(?:top[- ]?line|revenues?|sales|turnover)\b", re.I)
HAS_FIGURE = re.compile(r"\d+(?:\.\d+)?\s?(?:%|x\b|crores?|cr\b|bn|billion|mn|million|days|lakh)", re.I)
AMOUNT_UNITS = {"crore": 1.0, "bn": 100.0, "mn": 0.1}  # in ₹ crore


def to_crore(value: float | None, unit: str | None) -> float | None:
    return None if value is None or unit not in AMOUNT_UNITS else round(value * AMOUNT_UNITS[unit], 4)


ANNUAL = re.compile(r"\b(per annum|annually|every year|each year|a year|per year|annual run[- ]rate)\b", re.I)
MEDIUM_TERM = re.compile(r"\b(medium[- ]to[- ]long[- ]term|medium[- ]term|long[- ]term|longer[- ]term|over the next \d+ years|"
                         r"over (?:a period of )?(?:three|four|five|3|4|5) years|(?:three|four|five|\d)[- ]year (?:guidance|plan|target|horizon)|in steady state)\b", re.I)
BY_MARCH = re.compile(r"\b(?:by|for) (?:the end of )?march\b(?!\s+\d{2,4})", re.I)


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
        if REPORTED_SPEECH.search(quote):
            dropped.append({"call": transcript.period, "quote": quote[:200], "reason": "reports what management said (\"you said...\"): an analyst's words"})
            continue
        if not forward_looking(quote):
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
        if low is None and not HAS_FIGURE.search(quote) and len(re.findall(r"[A-Za-z]+", quote)) < 10:
            dropped.append({"call": transcript.period, "quote": quote[:200], "reason": "too vague to check: no number and under ten words"})
            continue
        metric = item.get("metric") if item.get("metric") in metrics else "other"
        if metric != "other" and not metric_named(metric, quote, metrics, best.text):
            notes.append(f"the quote does not name {metrics[metric]['label'].lower()}; filed as other (model said {metric})")
            metric = "other"
        remapped = remap_metric(metric, quote, metrics)
        if remapped != metric:
            notes.append(f"metric set to {metrics[remapped]['label']} from the quote (model said other)")
            metric = remapped
        if metric in GROWTH_METRICS and SHARE_OF.search(quote):
            # "north of 10% of our overall top line by 2030" names the top line but is a share, not growth.
            notes.append(f"the target is a share of revenue, not growth; filed as other (model said {item.get('metric')})")
            metric = "other"
        scope = resolve_scope(item.get("scope"), quote, best.text)
        if scope == "company":
            scope = scope_from_quote(quote) or "company"
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
            "low_crore": to_crore(low, unit),
            "high_crore": to_crore(high, unit),
            "annual": bool(ANNUAL.search(quote)),
            "basis": basis,
            "scope": scope,
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


GENERIC = {"target", "guidance", "growth", "plan", "expected", "expect", "around", "approximately", "about", "year", "this", "that",
           "with", "will", "long", "term", "medium", "range", "annual", "goal", "over", "remain", "within"}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", (text or "").lower()) if w not in GENERIC}


def _same_other(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Two "other" promises are one commitment when they are for the same period and
    either name the same count/amount (a non-% target such as 20,000 hires) or share
    descriptive words and the same target."""
    if a["period"] != b["period"]:
        return False
    if (a["target_low"] is None) != (b["target_low"] is None):
        return False  # a number and a no-number statement are never the same promise
    same_target = a["target_low"] is not None and (a["target_low"], a["target_high"]) == (b["target_low"], b["target_high"])
    if same_target and (a.get("unit") or "") not in ("%", "bps"):
        return True
    overlap = _words(a["metric_text"]) & _words(b["metric_text"])
    return len(overlap) >= 2 and (same_target or a["target_low"] is None)


def _scope_key(scope: str | None) -> str:
    """"Wires & Cables", "Wires and Cables segment", "the cables and wires business" -> "cables wires"."""
    if not scope or scope == "company":
        return "company"
    words = [w for w in re.findall(r"[a-z]+", scope.lower()) if w not in {"and", "the", "our", "segment", "business", "division", "vertical", "a"}]
    return " ".join(sorted(words)) or "segment"


def _direction(first: tuple[float, float], last: tuple[float, float]) -> str:
    """"cut" or "raised" by the midpoint of the range (Python arithmetic, never the model's)."""
    a, b = (first[0] + first[1]) / 2, (last[0] + last[1]) / 2
    return "raised" if b > a else ("cut" if b < a else "changed")


UNDATED = ("medium_term", "unspecified")
MARGINS = ("operating_margin", "ebitda_margin")
NAMES_MARGIN_KIND = re.compile(r"\bebitda\b|\bebit\b|\boperating\b", re.I)


def _targets(b: list[dict[str, Any]]) -> set[tuple[Any, ...]]:
    return {(p["low_crore"], p["high_crore"], "crore") if p.get("low_crore") is not None else (p["target_low"], p["target_high"], p.get("unit"))
            for p in b if p["target_low"] is not None}


def _bare_margin(b: list[dict[str, Any]]) -> bool:
    """Every quote says just "margin": it could be the EBITDA or the EBIT margin guide."""
    return all("margin" in p["quote"].lower() and not NAMES_MARGIN_KIND.search(p["quote"]) for p in b) and b[0]["metric"] in MARGINS + ("other",)


def _mergeable(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """The bucket the two should become one under (its metric, period and scope win), or None.
    Only for a single identical target, so a revision is never hidden: "Rs 6,000-8,000 crore
    over the next 5 years" and "Rs 6,000-8,000 crore capex by FY2030" are one plan; "11-13%
    margin guidance for this business" and "11-13% EBITDA margins in cables and wires" are one guide."""
    ta, tb = _targets(a), _targets(b)
    if len(ta) != 1 or ta != tb or a[0].get("annual") != b[0].get("annual"):
        return None
    ha, hb = a[0], b[0]
    if ha["period"] != hb["period"] and ha["period"] not in UNDATED and hb["period"] not in UNDATED:
        return None
    if ha["metric"] == hb["metric"]:
        main = a
    elif ha["metric"] in MARGINS and _bare_margin(b):
        main = a
    elif hb["metric"] in MARGINS and _bare_margin(a):
        main = b
    elif "crore" in next(iter(ta)) and "other" in (ha["metric"], hb["metric"]):
        main = a if hb["metric"] == "other" else b
    else:
        return None
    if ha["metric"] == hb["metric"] == "other" and not (_words(" ".join(p["quote"] for p in a)) & _words(" ".join(p["quote"] for p in b))):
        return None
    ka, kb = _scope_key(ha.get("scope")), _scope_key(hb.get("scope"))
    if ka != kb:
        low, high = next(iter(ta))[:2]
        unnamed = {"company", "segment"}
        if not ({ka, kb} & unnamed) or low == high:
            return None  # two named segments, or a single figure: too weak to call them one target
    return main


def _consolidate(buckets: list[list[dict[str, Any]]]) -> list[list[dict[str, Any]]]:
    merged = True
    while merged:
        merged = False
        for i in range(len(buckets)):
            for j in range(i + 1, len(buckets)):
                main = _mergeable(buckets[i], buckets[j])
                if main is None:
                    continue
                other = buckets[j] if main is buckets[i] else buckets[i]
                head = main[0]
                period = head["period"] if head["period"] not in UNDATED else other[0]["period"]
                if period in UNDATED and "medium_term" in (head["period"], other[0]["period"]):
                    period = "medium_term"
                scope = head.get("scope")
                if _scope_key(scope) in ("company", "segment") and _scope_key(other[0].get("scope")) not in ("company", "segment"):
                    scope = other[0].get("scope")
                for p in main + other:
                    moved = p in other
                    if moved or p["period"] != period or p.get("scope") != scope:
                        p["notes"] = list(p.get("notes") or []) + [
                            f"grouped with the same {p.get('target_text') or 'target'} statement(s) filed as {head['metric_label']} {period}"]
                    p["metric"], p["metric_label"], p["period"], p["scope"] = head["metric"], head["metric_label"], period, scope
                buckets[i] = main + other
                del buckets[j]
                merged = True
                break
            if merged:
                break
    return buckets


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
            if _scope_key(p.get("scope")) != _scope_key(head.get("scope")) or p.get("annual") != head.get("annual"):
                continue
            if p["metric"] != "other" and p["period"] == head["period"]:
                home = b
                break
            if p["metric"] == "other" and any(_same_other(p, q) for q in b):
                home = b
                break
        if home is None and p["metric"] == "other" and p.get("low_crore") is not None:
            # "spending roughly Rs 6,000-8,000 crore over the next 5 years" without the word capex
            # is the capex plan already on file with the same target and period.
            for b in buckets:
                h = b[0]
                if (h["metric"] != "other" and h["period"] == p["period"] and h.get("annual") == p.get("annual")
                        and (h.get("low_crore"), h.get("high_crore")) == (p["low_crore"], p["high_crore"])):
                    p["metric"], p["metric_label"] = h["metric"], h["metric_label"]
                    home = b
                    break
        if home is None:
            buckets.append([p])
        else:
            home.append(p)
    buckets = _consolidate(buckets)
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
        # Compare targets in one unit (₹ crore for amounts), so "₹6,000-8,000 crore" and
        # "INR 60-80 billion" are the same target, not a revision.
        targets = [((s["low_crore"], s["high_crore"]) if s.get("low_crore") is not None else (s["target_low"], s["target_high"]), s)
                   for s in statements if s["target_low"] is not None]
        distinct: list[tuple[float, float]] = []
        shown: list[str] = []
        for tg, s in targets:
            if not distinct or distinct[-1] != tg:
                distinct.append(tg)
                shown.append(s.get("target_text") or "")
        latest = next((s for s in reversed(statements) if s["target_low"] is not None), statements[-1])
        revised = len(distinct) > 1
        out.append({
            "id": f"g{i + 1}",
            "metric": items[0]["metric"],
            "metric_label": statements[0]["metric_label"],
            "metric_text": latest["metric_text"],
            "scope": items[0].get("scope", "company"),
            "period": items[0]["period"],
            "statements": statements,
            "latest": latest,
            "revised": revised,
            "direction": _direction(distinct[0], distinct[-1]) if revised else None,
            "path": " → ".join(shown) if revised else None,
        })
    return out


# ---------------------------------------------------------------- short labels for the phone

LABEL_WORDS = 5
LABEL_FILLER = {"we", "our", "i", "will", "should", "would", "be", "able", "to", "the", "a", "an", "and", "at", "least", "of",
                "start", "seeing", "that", "is", "are", "going", "continue", "continues", "remain", "remains", "in", "on",
                "for", "with", "this", "it", "as", "by", "there"}


def clip_label(text: str, words: int = LABEL_WORDS) -> str:
    """At most `words` words; an ellipsis marks a cut."""
    ws = (text or "").split()
    return " ".join(ws[:words]) + ("…" if len(ws) > words else "")


def fallback_label(text: str) -> str:
    """No model label: the description's content words, clipped. "FMEG industry will start
    seeing at least double-digit growth" -> "FMEG industry double-digit growth"."""
    ws = [w.strip(",.;:()\"'") for w in (text or "").split()]
    content = [w for w in ws if w and w.lower() not in LABEL_FILLER and not re.search(r"\d", w)]
    label = clip_label(" ".join(content or ws))
    return label[:1].upper() + label[1:] if label else "Other promise"


def python_label(group: dict[str, Any]) -> str | None:
    """Labels Python can give without a model: a named metric's own label, and a share of revenue."""
    if any(SHARE_OF.search(s["quote"]) for s in group["statements"]):
        return "Share of revenue"
    if group["metric"] != "other":
        return group["metric_label"]
    return None
