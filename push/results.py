"""Results card: this quarter vs last quarter vs the same quarter last year.

Pipeline (only step 3 uses a model):
  1. pick the results filing and, inside its PDF, the page with the P&L statement
     on the company's primary basis (consolidated/standalone), in Python
  2. send that page's text (or, for a scan, the PDF) to the extract_results task
  3. the model copies line items off the page into a JSON schema: no arithmetic
  4. Python checks the statement against its own totals (fixing a known OCR slip),
     works out the unit, fills unreadable rows from screener.in, computes EBITDA /
     NII / PPOP, margins and QoQ/YoY, and checks every figure against screener.in

EBITDA = profit before exceptional items and tax (and before share of associates)
         + finance costs + depreciation - other income
which is screener's "Operating Profit". Lenders get NII, PPOP, provisions and PAT.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from ingest.common import get_logger, iso_ist, now_ist
from ingest.pdfs import PdfText

from .config import PushConfig
from .priority import Card, ScoredFiling, build_cards

log = get_logger("push.results")

UNIT_TO_CRORE = {"crore": 1.0, "lakh": 0.01, "million": 0.1, "thousand": 1e-4, "rupees": 1e-7}
EBITDA_FORMULA = "PBT before exceptional items + finance costs + depreciation − other income"

STANDARD_FIELDS = {
    "revenue_from_operations": "Revenue from operations (total, not a sub-line)",
    "other_income": "Other income",
    "total_income": "Total income",
    "total_expenses": "Total expenses",
    "finance_costs": "Finance costs / interest expense",
    "depreciation": "Depreciation and amortisation expense",
    "profit_before_exceptional_and_tax": "Profit before share of associates/JVs, exceptional items and tax (if the statement shows a line 'before share of associates', use that line)",
    "share_of_associates": "Share of profit/(loss) of associates and joint ventures",
    "exceptional_items": "Exceptional items: positive for a gain, negative for a loss/charge",
    "profit_before_tax": "Profit before tax",
    "current_tax": "Current tax",
    "deferred_tax": "Deferred tax",
    "total_tax": "Total tax expense, only if printed as one line",
    "net_profit": "Net profit / profit for the period (before non-controlling interests)",
}
LENDER_FIELDS = {
    "interest_earned": "Interest earned (banks) or Interest income (NBFCs)",
    "revenue_from_operations": "Total revenue from operations (NBFC statements only; null for banks)",
    "other_income": "Other income",
    "total_income": "Total income",
    "interest_expended": "Interest expended (banks) or Finance costs (NBFCs)",
    "operating_expenses": "Operating expenses total (banks); null if not printed as one line",
    "operating_profit_before_provisions": "Operating profit before provisions and contingencies (only if printed)",
    "provisions": "Provisions (other than tax) and contingencies (banks) or Impairment on financial instruments (NBFCs)",
    "exceptional_items": "Exceptional items: positive for a gain, negative for a loss/charge",
    "profit_before_tax": "Profit before tax",
    "current_tax": "Current tax",
    "deferred_tax": "Deferred tax",
    "total_tax": "Total tax expense, only if printed as one line",
    "net_profit": "Net profit / profit for the period (before non-controlling interests)",
}

# PDF field -> stable screener key (push/ingest screener `fields` map)
SCREENER_KEYS_STANDARD = {
    "revenue_from_operations": "revenue",
    "other_income": "other_income",
    "finance_costs": "interest",
    "depreciation": "depreciation",
    "profit_before_tax": "pbt",
    "net_profit": "net_profit",
}
SCREENER_KEYS_LENDER = {
    "interest_expended": "interest_expended",
    "other_income": "other_income",
    "profit_before_tax": "pbt",
    "net_profit": "net_profit",
    # screener's lender "Revenue" is interest earned for banks, total revenue for NBFCs;
    # resolved per extraction in _screener_map()
}
# When a row is unreadable, fill from screener in this order (re-solving the
# statement's identities after each), so derived values can still be cross-checked.
FILL_ORDER = ["other_income", "finance_costs", "depreciation", "interest_expended",
              "revenue_from_operations", "interest_earned", "profit_before_tax", "net_profit"]


# ------------------------------------------------------------------ choosing the filing and page

_FIN_RESULTS = re.compile(r"financial results|results for the (quarter|period)|statement of .{0,40}results", re.I)


def is_statement_filing(item: dict[str, Any]) -> bool:
    if (item.get("bse_subcategory") or "").lower() == "financial results":
        return True
    return bool(_FIN_RESULTS.search(f"{item.get('title') or ''} {item.get('detail') or ''}"))


def latest_results_card(scored: list[ScoredFiling], symbol: str, cfg: PushConfig) -> Card | None:
    """The newest results card that contains the financial statements (not the
    half-yearly report, a deck or a newspaper ad)."""
    events = [s for s in scored if s.item["symbol"] == symbol and s.cls.category == "results" and s.cls.kind == "event"]
    cards = build_cards(events, cfg)
    with_statements = [c for c in cards if any(is_statement_filing(m.item) for m in c.members)]
    pool = with_statements or cards
    return max(pool, key=lambda c: c.lead.item.get("datetime") or "", default=None)


def pdf_candidates(card: Card) -> list[dict[str, Any]]:
    """Filings in the card with a PDF, the statement filing first."""
    def rank(s: ScoredFiling) -> tuple:
        sub = (s.item.get("bse_subcategory") or "").lower()
        return (0 if sub == "financial results" else 1 if is_statement_filing(s.item) else 2, s.item.get("datetime") or "")
    return [s.item for s in sorted(card.members, key=rank) if s.item.get("pdf_url")]


PNL_PATTERNS = [re.compile(w, re.I) for w in (
    r"revenue from operations", r"total income", r"profit before tax", r"finance costs?", r"depreciation",
    r"other income", r"net profit", r"profit for the (period|quarter)", r"exceptional items?",
    r"interest earned", r"interest expended", r"operating profit before provisions", r"provisions \(other than tax\)",
    r"interest income", r"impairment on financial", r"quarter ended|three months ended", r"(30|31)[./-](0?9|sep)",
)]
_HEAD_EXCLUDE = [
    (re.compile(r"statement of cash ?flows?|cash ?flow statement", re.I), "cash-flow statement"),
    (re.compile(r"dollars in millions|\bus\s?\$|\busd\b|in \$|\$ ?million", re.I), "not in rupees"),
    (re.compile(r"segment", re.I), "segment note"),
    (re.compile(r"statement of assets and liabilities|^balance sheet\b", re.I), "balance sheet"),
    (re.compile(r"highlights|press release|news release", re.I), "summary, not the statement"),
]
_HEAD_STATEMENT = re.compile(r"results|profit and loss|profit & loss", re.I)


@dataclass
class PageChoice:
    index: int  # 0-based
    number: int  # 1-based page number in the PDF
    basis: str
    score: int
    text: str
    note: str = ""


def page_score(text: str) -> int:
    return sum(1 for rx in PNL_PATTERNS if rx.search(text))


def page_head(text: str, lines: int = 20) -> str:
    """The first non-empty lines: where a statement's heading, basis and unit are."""
    return " ".join([line.strip() for line in text.splitlines() if line.strip()][:lines])


def analyse_page(text: str) -> tuple[str, str | None]:
    """(basis, reason to skip or None)."""
    head = page_head(text)
    for rx, why in _HEAD_EXCLUDE:
        if rx.search(head) and not (why == "segment note" and _HEAD_STATEMENT.search(head) and "statement of" in head.lower()):
            return ("consolidated" if "consolidated" in head.lower() else "standalone"), why
    return ("consolidated" if re.search(r"consolidated", head, re.I) else "standalone"), None


def choose_page(pages: list[tuple[int, str]], preferred_basis: str, min_score: int) -> PageChoice | None:
    """pages: [(page_number, text)]. Best-scoring statement page on the preferred basis;
    the other basis if none, with a note."""
    found: dict[str, list[PageChoice]] = {"consolidated": [], "standalone": []}
    for number, text in pages:
        basis, skip = analyse_page(text)
        score = page_score(text)
        if skip or score < min_score:
            continue
        found[basis].append(PageChoice(number - 1, number, basis, score, text))
    for basis in (preferred_basis, "standalone" if preferred_basis == "consolidated" else "consolidated"):
        if found[basis]:
            best = max(found[basis], key=lambda p: (p.score, -p.number))
            if basis != preferred_basis:
                best.note = f"No {preferred_basis} statement found; using the {basis} one"
            return best
    return None


def choose_page_from_pdf(text: PdfText, preferred_basis: str, min_score: int) -> PageChoice | None:
    return choose_page([(i + 1, t) for i, t in enumerate(text.pages)], preferred_basis, min_score)


# ------------------------------------------------------------------ the model call


def extraction_schema(lender: bool) -> dict[str, Any]:
    fields = LENDER_FIELDS if lender else STANDARD_FIELDS
    num = {"type": ["number", "null"]}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["statement_basis", "unit", "currency", "columns"],
        "properties": {
            "statement_basis": {"enum": ["consolidated", "standalone", "unknown"]},
            "unit": {"enum": ["crore", "lakh", "million", "thousand", "rupees", "unknown"]},
            "currency": {"enum": ["INR", "USD", "other"]},
            "columns": {
                "type": "array",
                "minItems": 1,
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["label", "period_end", "months", "values"],
                    "properties": {
                        "label": {"type": "string"},
                        "period_end": {"type": ["string", "null"], "pattern": r"^\d{4}-\d{2}-\d{2}$"},
                        "months": {"type": ["integer", "null"]},
                        "values": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": list(fields),
                            "properties": {k: num for k in fields},
                        },
                    },
                },
            },
        },
    }


def system_prompt(lender: bool) -> str:
    fields = LENDER_FIELDS if lender else STANDARD_FIELDS
    kind = "a bank or NBFC" if lender else "a company"
    lines = [
        f"You read one page of an Indian listed {kind}'s quarterly results (text extracted from a PDF).",
        "Copy figures off the page into JSON. Rules:",
        "- Only the 3-month (quarter) columns, in the order printed. Skip half-year/nine-month/year columns.",
        "- period_end: the column's period end date as YYYY-MM-DD; months: 3.",
        "- Copy each number exactly as printed. Remove thousands separators. A figure in brackets, e.g. (1,234), is negative.",
        "- Never add, subtract, convert units or compute anything. If a line is not printed, blank, '-' or unreadable, use null.",
        "- The text comes from OCR: the letter O may stand for 0, l or I for 1, and a thousands comma may appear as a period "
        "(in a column of whole numbers, '1.702' means 1702). Write the number the page intends.",
        "- unit: the unit stated on the page (e.g. 'in crore', 'INR lakhs'); 'unknown' if not stated.",
        "- statement_basis: consolidated or standalone, from the statement's heading.",
        "Fields (values):",
    ]
    lines += [f"- {k}: {v}" for k, v in fields.items()]
    return "\n".join(lines)


def compress_page(text: str, max_chars: int) -> str:
    lines = []
    for line in text.splitlines():
        line = re.sub(r" {3,}", "  ", line.rstrip())
        if line.strip():
            lines.append(line)
    return "\n".join(lines)[:max_chars]


def user_prompt(symbol: str, page: PageChoice, max_chars: int) -> str:
    return f"Company: {symbol}\nPage {page.number} of the results PDF:\n\n{compress_page(page.text, max_chars)}"


def extract(
    symbol: str,
    lender: bool,
    page: PageChoice | None,
    complete: Callable[..., Any],
    cfg: PushConfig,
    pdf: bytes | None = None,
) -> tuple[dict[str, Any], str]:
    """(validated extraction, "provider/model"). pdf is sent instead of text for scans."""
    rc = results_settings(cfg)
    if page is not None:
        user = user_prompt(symbol, page, int(rc["max_page_chars"]))
        res = complete("extract_results", system_prompt(lender), user, extraction_schema(lender), label=f"{symbol}:p{page.number}")
    elif pdf is not None:
        user = f"Company: {symbol}\nThe attached PDF is a scan. Use the quarterly statement of profit and loss."
        res = complete("extract_results", system_prompt(lender), user, extraction_schema(lender), pdf=pdf, label=f"{symbol}:scan")
    else:
        raise ValueError("nothing to extract from")
    return res.data, f"{res.provider}/{res.model}"


def results_settings(cfg: PushConfig) -> dict[str, Any]:
    defaults = {"min_page_score": 4, "max_page_chars": 7000, "max_scanned_pdf_mb": 15,
                "identity_tolerance_per_term": 0.6, "screener_tolerance_pct": 1.0, "screener_tolerance_cr": 1.0}
    return {**defaults, **(cfg.raw.get("results") or {})}


# ------------------------------------------------------------------ periods


def month_index(d: date) -> int:
    return d.year * 12 + d.month - 1


def period_label(mi: int) -> str:
    return f"{calendar.month_abbr[mi % 12 + 1]} {mi // 12}"


def parse_period(text: str | None) -> int | None:
    try:
        return month_index(date.fromisoformat(text)) if text else None
    except ValueError:
        return None


def assign_periods(columns: list[dict[str, Any]], fallback_current: int | None) -> tuple[dict[str, dict], dict[str, int | None], list[str]]:
    """Map extracted quarter columns to current / previous / year_ago.

    Uses the printed dates when they are distinct; otherwise the standard SEBI order
    (current, previous quarter, same quarter last year)."""
    notes: list[str] = []
    quarter = [c for c in columns if c.get("months") in (3, None)]
    dated = [(parse_period(c.get("period_end")), c) for c in quarter]
    months = [m for m, _ in dated if m is not None]
    slots: dict[str, dict] = {}
    if months and len(set(months)) == len(dated):
        by_month = {m: c for m, c in dated}
        cur = max(months)
        for slot, offset in (("current", 0), ("previous", 3), ("year_ago", 12)):
            if cur - offset in by_month:
                slots[slot] = by_month[cur - offset]
    else:
        cur = max(months) if months else fallback_current
        for slot, col in zip(("current", "previous", "year_ago"), quarter):
            slots[slot] = col
        notes.append("Column dates unreadable or repeated; assumed the standard order (this quarter, last quarter, a year ago)")
    labels = {
        "current": cur,
        "previous": cur - 3 if cur is not None else None,
        "year_ago": cur - 12 if cur is not None else None,
    }
    return slots, labels, notes


# ------------------------------------------------------------------ statement arithmetic (Python only)


def identities(lender: bool, v: dict[str, float | None]) -> list[tuple[str, str, list[tuple[float, str]]]]:
    """(name, target field, [(coef, field), ...]) meaning target = sum(coef * field)."""
    tax = "total_tax" if v.get("total_tax") is not None else None
    if not lender:
        rows = [
            ("total income = revenue + other income", "total_income", [(1, "revenue_from_operations"), (1, "other_income")]),
            ("profit before exceptional items = total income − total expenses", "profit_before_exceptional_and_tax",
             [(1, "total_income"), (-1, "total_expenses")]),
            ("PBT = profit before exceptional items + associates + exceptional items", "profit_before_tax",
             [(1, "profit_before_exceptional_and_tax"), (1, "share_of_associates"), (1, "exceptional_items")]),
        ]
    else:
        base = "revenue_from_operations" if v.get("revenue_from_operations") is not None else "interest_earned"
        rows = [
            ("total income = income + other income", "total_income", [(1, base), (1, "other_income")]),
            ("PPOP = total income − interest expended − operating expenses", "operating_profit_before_provisions",
             [(1, "total_income"), (-1, "interest_expended"), (-1, "operating_expenses")]),
            ("PBT = PPOP − provisions + exceptional items", "profit_before_tax",
             [(1, "operating_profit_before_provisions"), (-1, "provisions"), (1, "exceptional_items")]),
        ]
    if tax:
        rows.append(("net profit = PBT − tax", "net_profit", [(1, "profit_before_tax"), (-1, "total_tax")]))
    else:
        rows.append(("net profit = PBT − current tax − deferred tax", "net_profit",
                     [(1, "profit_before_tax"), (-1, "current_tax"), (-1, "deferred_tax")]))
    return rows


OPTIONAL_ZERO = {"share_of_associates", "exceptional_items", "deferred_tax"}  # blank usually means nil


def _get(v: dict, field: str) -> float | None:
    x = v.get(field)
    if x is None and field in OPTIONAL_ZERO:
        return 0.0
    return x


def check_identities(lender: bool, v: dict[str, float | None], tol_per_term: float) -> tuple[list[dict], list[str]]:
    """Checks that the printed figures add up. Repairs one known OCR slip (a thousands
    comma read as a decimal point: 1.702 -> 1702) when that alone makes a check pass."""
    results, notes = [], []
    for name, target, terms in identities(lender, v):
        tv = v.get(target)
        vals = [(c, f, _get(v, f)) for c, f in terms]
        if tv is None or any(x is None for _, _, x in vals):
            continue
        tol = tol_per_term * (len(terms) + 1)
        diff = tv - sum(c * x for c, _, x in vals)
        if abs(diff) <= tol:
            results.append({"check": name, "ok": True})
            continue
        fixed = _ocr_repair(v, target, terms, tol)
        if fixed:
            field, old = fixed
            notes.append(f"Read {field.replace('_', ' ')} '{old:g}' as {v[field]:g} (OCR misread a thousands comma)")
            results.append({"check": name, "ok": True, "repaired": field})
        else:
            results.append({"check": name, "ok": False, "difference": round(diff, 2),
                            "fields": [target] + [f for _, f in terms]})
    return results, notes


# Statement lines the card never shows: a slip in one of these is reported, not held
# against the card (HDFC Bank's OCR'd "97,267.62" total income, true 97,257.62).
UNUSED_LINES = {"total_income", "total_expenses", "operating_expenses", "current_tax", "deferred_tax", "total_tax"}


def explain_failures(checks: list[dict], v: dict[str, float | None]) -> tuple[list[str], bool]:
    """(notes, harmless). The suspect is the line that appears in every failing check
    and in no passing one; harmless if it is a line the card doesn't use."""
    failing = [c for c in checks if not c["ok"]]
    if not failing:
        return [], True
    passing = set().union(*[set(c.get("fields", [])) for c in checks if c["ok"]]) if any(c["ok"] for c in checks) else set()
    suspects = set.intersection(*[set(c["fields"]) for c in failing]) - passing
    if suspects and suspects <= UNUSED_LINES:
        names = ", ".join(f"{s.replace('_', ' ')} ({v.get(s):,.2f})" for s in sorted(suspects) if v.get(s) is not None)
        return [f"The {names} line as read doesn't match its parts (likely an OCR slip); it isn't used on the card"], True
    return [f"Statement does not add up: {c['check']} (off by {abs(c['difference']):,.2f} in printed units)" for c in failing], False


def _ocr_repair(v: dict, target: str, terms: list[tuple[float, str]], tol: float) -> tuple[str, float] | None:
    fields = [target] + [f for _, f in terms]
    hits = []
    for f in fields:
        x = v.get(f)
        if x is None or x == 0 or abs(x) >= 1000 or float(x).is_integer():
            continue
        trial = dict(v, **{f: x * 1000})
        tv = trial.get(target)
        total = sum(c * (_get(trial, g) or 0.0) for c, g in terms)
        if abs(tv - total) <= tol:
            hits.append((f, x))
    if len(hits) == 1:
        f, old = hits[0]
        v[f] = old * 1000
        return f, old
    return None


def _solve_for(field: str, target: str, terms: list[tuple[float, str]], v: dict) -> float | None:
    """Value of `field` that makes target = sum(terms) hold, or None if something is missing."""
    vals = {f: _get(v, f) for f in [target] + [g for _, g in terms] if f != field}
    if any(x is None for x in vals.values()):
        return None
    if field == target:
        return sum(c * vals[g] for c, g in terms)
    coef = next(c for c, g in terms if g == field)
    return (vals[target] - sum(c * vals[g] for c, g in terms if g != field)) / coef


def repair_with_screener(
    lender: bool, v: dict[str, float | None], screener_printed: dict[str, float], factor: float, tol_per_term: float, slot: str
) -> list[str]:
    """Fix an OCR'd figure when the statement's own arithmetic and screener.in agree on
    a different value. HDFC Bank's June-quarter PBT read "26,108.30": PPOP − provisions
    gives 25,108.30 and screener has 25,108, so the figure is corrected. A figure with
    no screener counterpart is never changed, only flagged."""
    notes = []
    for _ in range(4):
        changed = False
        for name, target, terms in identities(lender, v):
            fields = [target] + [f for _, f in terms]
            current = {f: _get(v, f) for f in fields}
            if any(x is None for x in current.values()):
                continue
            diff = current[target] - sum(c * current[f] for c, f in terms)
            if abs(diff) <= tol_per_term * len(fields):
                continue
            for f in fields:
                s = screener_printed.get(f)
                if s is None or v.get(f) is None:
                    continue
                fixed = _solve_for(f, target, terms, v)
                if fixed is None:
                    continue
                rounding = max(0.6 / factor, 1e-9)  # screener rounds to whole crore
                if abs(fixed - s) <= rounding * 1.5 and abs(v[f] - s) > rounding * 2:
                    notes.append(
                        f"{slot.replace('_', ' ').capitalize()}: read {f.replace('_', ' ')} as {v[f]:,.2f}; the statement's own "
                        f"figures give {fixed:,.2f} and screener.in agrees, so that is used (OCR slip)"
                    )
                    v[f] = fixed
                    changed = True
                    break
            if changed:
                break
        if not changed:
            break
    return notes


def solve(lender: bool, v: dict[str, float | None], sources: dict[str, str]) -> None:
    """Fill a missing figure when exactly one term of an identity is missing."""
    changed = True
    while changed:
        changed = False
        for name, target, terms in identities(lender, v):
            fields = [target] + [f for _, f in terms]
            missing = [f for f in fields if v.get(f) is None and f not in OPTIONAL_ZERO]
            if len(missing) != 1:
                continue
            m = missing[0]
            if m == target:
                v[m] = sum(c * (_get(v, f) or 0.0) for c, f in terms)
            else:
                coef = next(c for c, f in terms if f == m)
                rest = sum(c * (_get(v, f) or 0.0) for c, f in terms if f != m)
                v[m] = (v[target] - rest) / coef
            sources[m] = "derived"
            changed = True


# ------------------------------------------------------------------ screener


def screener_values(fund: dict[str, Any], basis: str) -> tuple[dict[str, dict[str, float | None]], str, str]:
    """{stable_key: {period_label: value}} for the view matching the statement basis."""
    views = fund.get("views") or {}
    view = basis if basis in views else fund.get("primary_view")
    note = "" if view == basis else f"screener has no {basis} view; compared with {view}"
    d = views.get(view) or {}
    q = (d.get("tables") or {}).get("quarters") or {}
    fields = (d.get("fields") or {}).get("quarters") or {}
    periods = q.get("periods") or []
    out = {}
    for key, label in fields.items():
        vals = (q.get("rows") or {}).get(label) or []
        out[key] = {p: vals[i] for i, p in enumerate(periods) if i < len(vals)}
    return out, view, note


def _screener_map(lender: bool, v: dict[str, float | None]) -> dict[str, str]:
    if not lender:
        return dict(SCREENER_KEYS_STANDARD)
    m = dict(SCREENER_KEYS_LENDER)
    m["revenue_from_operations" if v.get("revenue_from_operations") is not None else "interest_earned"] = "revenue"
    return m


def within(a: float, b: float, rc: dict) -> bool:
    return abs(a - b) <= max(float(rc["screener_tolerance_cr"]), abs(b) * float(rc["screener_tolerance_pct"]) / 100)


def infer_factor(declared: str, cur: dict[str, float | None], scr: dict, label: str | None, lender: bool, rc: dict) -> tuple[float, list[str]]:
    """Unit -> crore factor. The declared unit is checked against screener; a clear
    mismatch with a clean alternative switches it."""
    notes = []
    factor = UNIT_TO_CRORE.get(declared)
    probe = []
    for f, key in _screener_map(lender, cur).items():
        x, s = cur.get(f), (scr.get(key) or {}).get(label) if label else None
        if x and s and abs(s) >= 5:
            probe.append((x, s))
    if probe:
        def fits(fac: float) -> bool:
            return sum(1 for x, s in probe if abs(x * fac - s) <= max(1.0, abs(s) * 0.03)) * 2 > len(probe)

        if factor is None or not fits(factor):
            alt = next((f for f in UNIT_TO_CRORE.values() if fits(f)), None)
            if alt is not None:
                name = next(k for k, f in UNIT_TO_CRORE.items() if f == alt)
                notes.append(f"Unit taken as {name} (page said {declared}); it matches screener.in")
                factor = alt
    if factor is None:
        factor = 1.0
        notes.append("Unit not stated and nothing to compare with; assumed ₹ crore")
    return factor, notes


# ------------------------------------------------------------------ the card


def pct(cur: float | None, base: float | None) -> float | None:
    if cur is None or base is None or base <= 0:
        return None
    return round((cur / base - 1) * 100, 1)


def build_card(
    symbol: str,
    company: dict[str, Any],
    fund: dict[str, Any] | None,
    extraction: dict[str, Any] | None,
    rc: dict[str, Any],
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """company: {"is_lender", "primary_view", "name"}; source: filing/page/model metadata."""
    lender = bool(company.get("is_lender"))
    fund = fund or {}
    notes: list[str] = []
    if extraction is None:
        return screener_only_card(symbol, company, fund, source, rc, ["No PDF extraction; figures from screener.in"])

    basis = extraction.get("statement_basis")
    if basis not in ("consolidated", "standalone"):
        basis = company.get("primary_view") or "consolidated"
        notes.append(f"Statement basis not stated; assumed {basis}")
    if extraction.get("currency") not in (None, "INR"):
        return screener_only_card(symbol, company, fund, source, rc, ["Statement is not in rupees; figures from screener.in"])
    scr, view, vnote = screener_values(fund, basis)
    if vnote:
        notes.append(vnote)
    scr_periods = sorted({parse_label(p) for vals in scr.values() for p in vals} - {None})
    slots, labels, pnotes = assign_periods(extraction.get("columns") or [], scr_periods[-1] if scr_periods else None)
    notes += pnotes
    if "current" not in slots:
        return screener_only_card(symbol, company, fund, source, rc, notes + ["No quarter column extracted; figures from screener.in"])

    fields = LENDER_FIELDS if lender else STANDARD_FIELDS
    tol = float(rc["identity_tolerance_per_term"])
    per: dict[str, dict[str, Any]] = {}
    for slot, col in slots.items():
        v = {k: _num((col.get("values") or {}).get(k)) for k in fields}
        _, inotes = check_identities(lender, v, tol)  # also repairs a comma read as a decimal point
        notes += [f"{slot.replace('_', ' ').capitalize()}: {n}" for n in inotes]
        per[slot] = {"v": v, "src": {k: "pdf" for k, x in v.items() if x is not None}}

    label = {s: period_label(m) if m is not None else None for s, m in labels.items()}
    factor, unotes = infer_factor(extraction.get("unit", "unknown"), per["current"]["v"], scr, label["current"], lender, rc)
    notes += unotes

    smap = _screener_map(lender, per["current"]["v"])
    checks: dict[str, list[dict]] = {}
    for slot, data in per.items():
        v = data["v"]
        printed_scr = {}
        for f, key in smap.items():
            s = (scr.get(key) or {}).get(label[slot])
            if s is not None:
                printed_scr[f] = s / factor
        notes += repair_with_screener(lender, v, printed_scr, factor, tol, slot)
        res, _ = check_identities(lender, v, tol)
        fnotes, data["statement_ok"] = explain_failures(res, v)
        checks[slot] = res
        notes += [f"{slot.replace('_', ' ').capitalize()}: {n}" for n in fnotes]
    for slot, data in per.items():
        v, src = data["v"], data["src"]
        solve(lender, v, src)
        for f in FILL_ORDER:  # unreadable rows: take screener's figure, then re-solve
            key = smap.get(f)
            sval = (scr.get(key) or {}).get(label[slot]) if key else None
            if f in v and v[f] is None and sval is not None:
                v[f] = sval / factor
                src[f] = "screener"
                solve(lender, v, src)
        data["cr"] = {k: (x * factor if x is not None else None) for k, x in v.items()}

    metrics = lender_metrics(per, scr, label, rc, smap) if lender else standard_metrics(per, scr, label, rc, smap)
    for slot, lab in label.items():  # "Previous: ..." -> "Jun 2026: ..."
        if lab:
            notes = [n.replace(f"{slot.replace('_', ' ').capitalize()}: ", f"{lab}: ", 1) for n in notes]
    filled = sorted({f.replace("_", " ") for d in per.values() for f, s in d["src"].items() if s == "screener"})
    if filled:
        notes.append(f"Unreadable in the PDF, taken from screener.in: {', '.join(filled)}")
    main = [m for m in metrics if m.get("main")]
    states = [m["check"]["current"] for m in main]
    status = "mismatch" if "mismatch" in states else "verified" if all(s == "verified" for s in states) else "partial"
    if not per["current"]["statement_ok"]:
        status = "mismatch"
    return {
        "symbol": symbol,
        "name": company.get("name") or symbol,
        "layout": "lender" if lender else "standard",
        "basis": basis,
        "screener_view": view,
        "status": status,
        "periods": label,
        "unit": "₹ crore",
        "metrics": metrics,
        "statement_checks": checks,
        "notes": notes,
        "formula": None if lender else EBITDA_FORMULA,
        "source": source or {},
        "built_at": iso_ist(now_ist()),
    }


def parse_label(text: str) -> int | None:
    m = re.fullmatch(r"([A-Z][a-z]{2}) (\d{4})", text or "")
    if not m or m.group(1) not in calendar.month_abbr:
        return None
    return int(m.group(2)) * 12 + list(calendar.month_abbr).index(m.group(1)) - 1


def _num(x: Any) -> float | None:
    if isinstance(x, bool) or x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _metric(key, label, values: dict[str, float | None], check: dict[str, str], screener: dict[str, float | None],
            main: bool = True, kind: str = "amount") -> dict[str, Any]:
    cur, prev, ya = values.get("current"), values.get("previous"), values.get("year_ago")
    out = {
        "key": key, "label": label, "main": main, "kind": kind,
        "current": _r(cur), "previous": _r(prev), "year_ago": _r(ya),
        "check": check, "screener": {k: _r(v) for k, v in screener.items()},
    }
    if kind == "amount":
        out["qoq_pct"], out["yoy_pct"] = pct(cur, prev), pct(cur, ya)
    else:  # margin, in percentage points
        out["qoq_pp"] = _r(cur - prev, 1) if cur is not None and prev is not None else None
        out["yoy_pp"] = _r(cur - ya, 1) if cur is not None and ya is not None else None
    return out


def _r(x: float | None, digits: int = 2) -> float | None:
    return None if x is None else round(x, digits)


def _field_check(per, slot, field, scr, label, rc, smap) -> tuple[str, float | None]:
    data = per.get(slot)
    if not data or data["cr"].get(field) is None:
        return "missing", None
    if data["src"].get(field) == "screener":
        return "screener", (scr.get(smap.get(field, "")) or {}).get(label[slot])
    key = smap.get(field)
    s = (scr.get(key) or {}).get(label[slot]) if key else None
    if s is None:
        return "unchecked", None
    return ("verified" if within(data["cr"][field], s, rc) else "mismatch"), s


def standard_metrics(per, scr, label, rc, smap) -> list[dict]:
    slots = ("current", "previous", "year_ago")
    out = []

    def series(field):
        return {s: per[s]["cr"].get(field) if s in per else None for s in slots}

    def checked(field):
        res = {s: _field_check(per, s, field, scr, label, rc, smap) for s in slots}
        return {s: r[0] for s, r in res.items()}, {s: r[1] for s, r in res.items()}

    rev = series("revenue_from_operations")
    c, sv = checked("revenue_from_operations")
    out.append(_metric("revenue", "Revenue", rev, c, sv))

    ebitda = {}
    for s in slots:
        cr = per[s]["cr"] if s in per else {}
        parts = [cr.get("profit_before_exceptional_and_tax"), cr.get("finance_costs"), cr.get("depreciation"), cr.get("other_income")]
        ebitda[s] = None if any(p is None for p in parts) else parts[0] + parts[1] + parts[2] - parts[3]
    e_check, e_scr = {}, {}
    for s in slots:
        op = (scr.get("operating_profit") or {}).get(label[s])
        e_scr[s] = op
        if ebitda[s] is None:
            e_check[s] = "missing"
        elif op is None:
            e_check[s] = "unchecked"
        else:
            e_check[s] = "verified" if within(ebitda[s], op, rc) else "mismatch"
    out.append(_metric("ebitda", "EBITDA", ebitda, e_check, e_scr))

    margin = {s: (ebitda[s] / rev[s] * 100) if ebitda[s] is not None and rev[s] else None for s in slots}
    out.append(_metric("ebitda_margin", "EBITDA margin %", margin, {s: e_check[s] for s in slots}, {}, main=False, kind="margin"))
    for field, key, name in (("profit_before_tax", "pbt", "PBT"), ("net_profit", "pat", "PAT")):
        c, sv = checked(field)
        out.append(_metric(key, name, series(field), c, sv))
    c, sv = checked("other_income")
    out.append(_metric("other_income", "Other income", series("other_income"), c, sv, main=False))
    return out


def lender_metrics(per, scr, label, rc, smap) -> list[dict]:
    slots = ("current", "previous", "year_ago")
    out = []

    def cr(s, f):
        return per[s]["cr"].get(f) if s in per else None

    def fchk(s, f):
        return _field_check(per, s, f, scr, label, rc, smap)

    income_field = "revenue_from_operations" if cr("current", "revenue_from_operations") is not None else "interest_earned"
    nii, nii_check = {}, {}
    for s in slots:
        ie, ix = cr(s, "interest_earned"), cr(s, "interest_expended")
        nii[s] = ie - ix if ie is not None and ix is not None else None
        a = fchk(s, income_field)[0] if income_field == "interest_earned" else "unchecked"
        b = fchk(s, "interest_expended")[0]
        nii_check[s] = ("missing" if nii[s] is None else "mismatch" if "mismatch" in (a, b)
                        else "verified" if a == b == "verified" else "unchecked")
    out.append(_metric("nii", "Net interest income", nii, nii_check, {}))

    ppop, prov_check = {}, {}
    for s in slots:
        reported = cr(s, "operating_profit_before_provisions")
        pbt, prov, exc = cr(s, "profit_before_tax"), cr(s, "provisions"), cr(s, "exceptional_items") or 0.0
        ppop[s] = reported if reported is not None else (pbt + prov - exc if pbt is not None and prov is not None else None)
        pbt_state = fchk(s, "profit_before_tax")[0]
        # PPOP and provisions have no screener line; they are verified through PBT
        # (checked against screener) and the statement identity PBT = PPOP − provisions.
        if ppop[s] is None or prov is None:
            prov_check[s] = "missing"
        elif pbt_state == "verified" and pbt is not None and abs(ppop[s] - prov + exc - pbt) <= max(1.0, abs(pbt) * 0.001):
            prov_check[s] = "verified"
        elif pbt_state == "mismatch":
            prov_check[s] = "mismatch"
        else:
            prov_check[s] = "unchecked"
    out.append(_metric("ppop", "Operating profit (PPOP)", ppop, prov_check, {}))
    out.append(_metric("provisions", "Provisions", {s: cr(s, "provisions") for s in slots}, prov_check, {}))
    pat_c = {s: fchk(s, "net_profit") for s in slots}
    out.append(_metric("pat", "PAT", {s: cr(s, "net_profit") for s in slots}, {s: r[0] for s, r in pat_c.items()},
                       {s: r[1] for s, r in pat_c.items()}))
    oi_c = {s: fchk(s, "other_income") for s in slots}
    out.append(_metric("other_income", "Other income", {s: cr(s, "other_income") for s in slots},
                       {s: r[0] for s, r in oi_c.items()}, {s: r[1] for s, r in oi_c.items()}, main=False))
    return out


def screener_only_card(symbol, company, fund, source, rc, notes) -> dict[str, Any]:
    """Fallback when the PDF can't be read: screener's quarterly table, same metrics
    where screener has them (lenders: no PPOP/provisions split)."""
    lender = bool(company.get("is_lender"))
    basis = (fund or {}).get("primary_view") or company.get("primary_view") or "consolidated"
    scr, view, _ = screener_values(fund or {}, basis)
    labels = sorted({parse_label(p) for vals in scr.values() for p in vals} - {None})
    if not labels:
        return {"symbol": symbol, "name": company.get("name") or symbol, "status": "unavailable", "metrics": [],
                "notes": notes + ["No screener data either"], "source": source or {}, "built_at": iso_ist(now_ist())}
    cur = labels[-1]
    label = {"current": period_label(cur), "previous": period_label(cur - 3), "year_ago": period_label(cur - 12)}

    def s(key):
        return {slot: (scr.get(key) or {}).get(lab) for slot, lab in label.items()}

    metrics = []
    none = {k: "screener" for k in label}
    if lender:
        rev, intr = s("revenue"), s("interest_expended")
        metrics.append(_metric("nii", "Net interest income",
                               {k: rev[k] - intr[k] if rev[k] is not None and intr[k] is not None else None for k in label}, none, {}))
        metrics.append(_metric("pat", "PAT", s("net_profit"), none, {}))
    else:
        rev, op = s("revenue"), s("operating_profit")
        metrics.append(_metric("revenue", "Revenue", rev, none, {}))
        metrics.append(_metric("ebitda", "EBITDA", op, none, {}))
        metrics.append(_metric("ebitda_margin", "EBITDA margin %",
                               {k: op[k] / rev[k] * 100 if op[k] is not None and rev[k] else None for k in label}, none, {},
                               main=False, kind="margin"))
        metrics.append(_metric("pbt", "PBT", s("pbt"), none, {}))
        metrics.append(_metric("pat", "PAT", s("net_profit"), none, {}))
    return {
        "symbol": symbol, "name": company.get("name") or symbol, "layout": "lender" if lender else "standard",
        "basis": basis, "screener_view": view, "status": "screener_only", "periods": label, "unit": "₹ crore",
        "metrics": metrics, "statement_checks": {}, "notes": notes, "formula": None if lender else EBITDA_FORMULA,
        "source": source or {}, "built_at": iso_ist(now_ist()),
    }
