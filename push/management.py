"""Management-change card: who is joining or leaving, in what role, when and why.

Only the filing is used (BSE's title/detail/more plus the PDF's text, extracted in
Python). The model copies people, roles, dates, reasons and prior roles into a
schema; Python then checks every name, reason and prior role really appears in the
filing (anything that doesn't is dropped, with a note) and sets the warning flags:

  ceo_exit / cfo_exit   a CEO/MD or CFO resigning, retiring, ceasing or removed
  vague_reason          a resignation with no reason, or a boilerplate one
  mid_quarter           an executive leaving more than N days from a quarter end
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Callable

from ingest.common import clean_text, get_logger, iso_ist, now_ist

from .config import PushConfig

log = get_logger("push.management")

ROLE_LEVELS = {
    "ceo_md": "CEO, MD, Managing Director & CEO, or Whole-time Director who heads the company",
    "cfo": "Chief Financial Officer",
    "chair": "Chairperson or Vice-Chairperson of the board",
    "executive_director": "Executive / Whole-time Director (not the head)",
    "independent_director": "Independent Director",
    "non_executive_director": "Non-executive, non-independent director (incl. nominee)",
    "senior_management": "Key managerial or senior management personnel (CXO, business head, SVP)",
    "company_secretary": "Company Secretary / Compliance Officer",
    "auditor": "Statutory, secretarial or internal auditor",
    "other": "Anything else",
}
CHANGES = ["appointment", "reappointment", "promotion", "redesignation", "resignation", "retirement",
           "cessation", "removal", "death", "other"]
LEAVING = {"resignation", "retirement", "cessation", "removal", "death"}
CONTINUING = {"reappointment", "redesignation"}
EXECUTIVE = {"ceo_md", "cfo", "executive_director", "senior_management", "company_secretary"}
FLAG_LABELS = {
    "ceo_exit": "CEO/MD is leaving",
    "cfo_exit": "CFO is leaving",
    "vague_reason": "Reason for leaving is vague or not given",
    "mid_quarter": "Leaving mid-quarter",
}

_LETTERHEAD = re.compile(
    r"^\s*(tel|phone|fax|e-?mail|website|www\.|cin\b|regd|registered|corporate office|bse limited|national stock exchange|"
    r"phiroze|dalal street|exchange plaza|bandra|mumbai\s*-?\s*400|dear sir|kind(ly)? (attn|take)|scrip|symbol|series|"
    r"yours (faithfully|truly|sincerely)|thanking|encl|listing department|department of corporate)", re.I)


def schema() -> dict[str, Any]:
    person = {
        "type": "object",
        "additionalProperties": False,
        "required": ["name", "role", "role_level", "change", "entity", "effective_date", "stated_reason", "prior_roles", "tenure"],
        "properties": {
            "name": {"type": "string", "minLength": 2},
            "role": {"type": "string"},
            "role_level": {"enum": list(ROLE_LEVELS)},
            "change": {"enum": CHANGES},
            "entity": {"type": ["string", "null"]},
            "effective_date": {"type": ["string", "null"], "pattern": r"^\d{4}-\d{2}-\d{2}$"},
            "stated_reason": {"type": ["string", "null"]},
            "prior_roles": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
            "tenure": {"type": ["string", "null"]},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["people", "summary"],
        "properties": {
            "people": {"type": "array", "items": person, "maxItems": 12},
            "summary": {"type": "string", "maxLength": 240},
        },
    }


def system_prompt() -> str:
    lines = [
        "You read an Indian listed company's stock-exchange filing about changes in its directors or management.",
        "List every person whose position changes. Copy from the filing only; never use outside knowledge.",
        "- name: as written, without Mr./Ms./Dr.",
        "- role: the position as written. role_level: one of:",
    ]
    lines += [f"    {k}: {v}" for k, v in ROLE_LEVELS.items()]
    lines += [
        f"- change: one of {', '.join(CHANGES)}. Completing a term is 'cessation'.",
        "- entity: the company the role is at, if it is a subsidiary or another company; null if it is the filing company.",
        "- effective_date: YYYY-MM-DD when the change takes effect, if stated; else null.",
        "- stated_reason: the reason exactly as the filing words it (a short quote); null if none is given.",
        "- prior_roles: earlier positions the filing mentions for this person, short phrases; [] if none.",
        "- tenure: e.g. '3 years' if a term is stated; else null.",
        "- summary: one plain sentence, at most 30 words. If the filing covers other matters too, mention only the people changes.",
        "If nobody's position changes, return people: [].",
    ]
    return "\n".join(lines)


def clean_filing_text(text: str) -> str:
    lines = [clean_text(line) for line in (text or "").splitlines()]
    return "\n".join(line for line in lines if line and not _LETTERHEAD.match(line))


def source_text(item: dict[str, Any], pdf_text: str, max_chars: int) -> str:
    parts = [f"Title: {item.get('title') or '-'}", f"Detail: {item.get('detail') or '-'}"]
    more = (item.get("more") or "").strip()
    if more and more != (item.get("detail") or "").strip():
        parts.append(f"More: {more}")
    if pdf_text:
        parts.append("PDF text:\n" + clean_filing_text(pdf_text))
    return "\n".join(parts)[:max_chars]


def user_prompt(item: dict[str, Any], text: str) -> str:
    return f"Company symbol: {item.get('symbol')}\nFiling date: {(item.get('datetime') or '')[:10]}\n{text}"


# ------------------------------------------------------------------ checks (Python)


def _squash(text: str) -> str:
    """Lower-case, letters and digits only: OCR splits words ("T alau li car")."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def grounded_name(name: str, squashed_source: str) -> bool:
    tokens = [t for t in re.findall(r"[a-z]+", re.sub(r"^(mr|mrs|ms|dr|prof|shri|smt)\.?\s+", "", name.lower())) if len(t) >= 3]
    return bool(tokens) and all(t in squashed_source for t in tokens)


def grounded_phrase(phrase: str, squashed_source: str, share: float = 0.7) -> bool:
    words = [w for w in re.findall(r"[a-z0-9]+", phrase.lower()) if len(w) >= 4]
    if not words:
        return True
    return sum(1 for w in words if w in squashed_source) / len(words) >= share


def parse_date(text: str | None) -> date | None:
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


def days_from_quarter_end(d: date) -> int:
    ends = [date(y, m, dd) for y in (d.year - 1, d.year, d.year + 1) for m, dd in ((3, 31), (6, 30), (9, 30), (12, 31))]
    return min(abs((d - e).days) for e in ends)


def check_people(extraction: dict[str, Any], text: str, filed: date | None, mcfg: dict[str, Any]) -> tuple[list[dict], list[str]]:
    squashed = _squash(text)
    vague = re.compile(str(mcfg.get("vague_reason") or "$^"), re.I)
    mid_days = int(mcfg.get("mid_quarter_days", 10))
    people, notes = [], []
    for raw in extraction.get("people") or []:
        name = clean_text(raw.get("name"))
        if not grounded_name(name, squashed):
            notes.append(f"Dropped '{name}': the name isn't in the filing")
            continue
        p = {k: raw.get(k) for k in ("role", "role_level", "change", "entity", "tenure")}
        p["name"] = name
        reason = clean_text(raw.get("stated_reason")) or None
        if reason and not grounded_phrase(reason, squashed):
            notes.append(f"{name}: reason '{reason[:60]}' isn't worded like that in the filing; left out")
            reason = None
        p["stated_reason"] = reason
        prior = []
        for role in raw.get("prior_roles") or []:
            role = clean_text(role)
            if role and grounded_phrase(role, squashed):
                prior.append(role)
            elif role:
                notes.append(f"{name}: prior role '{role[:60]}' isn't in the filing; left out")
        p["prior_roles"] = prior
        eff = parse_date(raw.get("effective_date"))
        if eff and filed and abs((eff - filed).days) > 400:
            notes.append(f"{name}: effective date {eff} is over a year from the filing date; left out")
            eff = None
        p["effective_date"] = eff.isoformat() if eff else None
        change = p.get("change")
        p["direction"] = "leaving" if change in LEAVING else "continuing" if change in CONTINUING else "joining"
        p["at_subsidiary"] = bool(clean_text(p.get("entity")))

        flags = []
        if p["direction"] == "leaving" and not p["at_subsidiary"]:
            if p.get("role_level") == "ceo_md":
                flags.append("ceo_exit")
            if p.get("role_level") == "cfo":
                flags.append("cfo_exit")
            if change == "resignation" and (reason is None or vague.search(reason)):
                flags.append("vague_reason")
            if p.get("role_level") in EXECUTIVE and eff and days_from_quarter_end(eff) > mid_days:
                flags.append("mid_quarter")
        p["flags"] = [{"code": f, "label": FLAG_LABELS[f]} for f in flags]
        people.append(p)
    return people, notes


def severity(people: list[dict]) -> str:
    codes = {f["code"] for p in people for f in p["flags"]}
    if codes & {"ceo_exit", "cfo_exit"} or len(codes) >= 2:
        return "high"
    top = {"ceo_md", "cfo", "chair"}
    if codes or any(p["role_level"] in top and not p["at_subsidiary"] and p["direction"] != "continuing" for p in people) or any(
        p["direction"] == "leaving" and p["role_level"] in EXECUTIVE and not p["at_subsidiary"] for p in people
    ):
        return "normal"
    return "low"


# ------------------------------------------------------------------ the card


def build_card(item: dict[str, Any], extraction: dict[str, Any] | None, text: str, mcfg: dict[str, Any],
               source: dict[str, Any] | None = None, error: str | None = None) -> dict[str, Any]:
    filed = None
    try:
        filed = datetime.fromisoformat(item["datetime"]).date() if item.get("datetime") else None
    except ValueError:
        pass
    base = {
        "filing_id": item["id"],
        "symbol": item["symbol"],
        "datetime": item.get("datetime"),
        "title": item.get("title"),
        "pdf_url": item.get("pdf_url"),
        "source": source or {},
        "built_at": iso_ist(now_ist()),
    }
    if extraction is None:
        return {**base, "status": "unavailable", "people": [], "flags": [], "severity": "low",
                "summary": clean_text(item.get("detail") or item.get("title")), "notes": [error or "Not extracted"]}
    people, notes = check_people(extraction, text, filed, mcfg)
    flags, seen = [], set()
    for p in people:
        for f in p["flags"]:
            if f["code"] not in seen:
                seen.add(f["code"])
                flags.append({**f, "name": p["name"]})
    return {
        **base,
        "status": "ok" if people else "no_people",
        "people": people,
        "flags": flags,
        "severity": severity(people),
        "summary": clean_text(extraction.get("summary")),
        "notes": notes,
    }


def extract(item: dict[str, Any], text: str, complete: Callable[..., Any], pdf: bytes | None = None) -> tuple[dict, str]:
    res = complete("extract_management", system_prompt(), user_prompt(item, text), schema(), pdf=pdf,
                   label=f"{item['symbol']}:{item['id']}")
    return res.data, f"{res.provider}/{res.model}"


def management_settings(cfg: PushConfig) -> dict[str, Any]:
    return {"max_pdf_pages": 6, "max_text_chars": 9000, "mid_quarter_days": 10, **(cfg.raw.get("management") or {})}
