"""Earnings-call transcripts: pick them, read them, split them into speaker passages and
keep only what a model needs to see. All of this is Python; no model is involved.

Sources are the transcript PDFs linked from the company's screener.in page (usually
exchange filings on bseindia.com), so the pipeline works for any listed company that
publishes transcripts, and degrades to "no transcripts" for one that doesn't.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from rapidfuzz import fuzz

from . import periods

# A line that is only a person's name: 2-5 capitalised words, optional title, no digits.
NAME_LINE = re.compile(r"^(?:(?:Mr|Mrs|Ms|Dr|Shri|Smt)\.?\s+)?[A-Z][A-Za-z'.\-]+(?:\s+[A-Z][A-Za-z'.\-]*){1,4}$")
# "Name:" or "Name - Company:" at the start of a line, with speech after it.
NAME_COLON = re.compile(r"^((?:(?:Mr|Mrs|Ms|Dr|Shri|Smt)\.?\s+)?[A-Z][A-Za-z'.\-]+(?:\s+[A-Z][A-Za-z'.\-]*){0,4})\s*[:：]\s*(.*)$")
TITLES = re.compile(r"^(mr|mrs|ms|dr|shri|smt)(\.\s*|\s+)", re.I)
NOISE = re.compile(r"(external document|page \d+ of \d+|^\d+$|©)", re.I)


@dataclass
class Passage:
    id: str
    speaker: str
    management: bool
    text: str
    forward_hits: int = 0
    outcome_hits: int = 0
    has_number: bool = False
    metrics: list[str] = field(default_factory=list)

    def score(self) -> int:
        return self.forward_hits * 2 + (3 if "guidance" in self.text.lower() else 0) + len(self.metrics) + int(self.has_number)


@dataclass
class Transcript:
    period: str            # screener's label, e.g. "Oct 2026"
    month: str             # "2026-10"
    quarter: str | None    # quarter reported on, e.g. "Sep 2026"
    url: str
    management: list[str]
    passages: list[Passage]
    text: str              # the full text, for quote checks
    error: str | None = None
    kind: str = "earnings"  # "earnings" call, or another "event" (investor day, analyst meet)

    @property
    def fiscal(self) -> str | None:
        """"Q2 FY27" for an earnings call; "FY26" for an event, by its date."""
        if self.kind == "earnings" and self.quarter:
            return periods.fiscal_label(self.quarter)
        ym = re.fullmatch(r"(\d{4})-(\d{2})", self.month or "")
        return f"FY{periods.fiscal_year(int(ym.group(1)), int(ym.group(2))):02d}" if ym else None

    @property
    def label(self) -> str:
        return f"{self.period} ({self.fiscal})" if self.kind == "earnings" else f"{self.period} (investor event)"

    def current_fy(self) -> int | None:
        """The fiscal year "this year" / "the full year" refers to on this call: the year of
        the quarter reported, or the next one when that quarter closed the year (a Q4 call
        is about the year ahead). Events use their date."""
        if self.kind == "earnings" and self.quarter:
            ym = periods.parse_label(self.quarter)
            fy = periods.fiscal_year(*ym)
            return (fy + 1) % 100 if ym[1] == 3 else fy
        ym = re.fullmatch(r"(\d{4})-(\d{2})", self.month or "")
        return periods.fiscal_year(int(ym.group(1)), int(ym.group(2))) if ym else None


def select(documents: dict[str, Any], count: int) -> list[dict[str, Any]]:
    """The latest `count` calls that have a transcript PDF (duplicates dropped)."""
    seen, out = set(), []
    calls = sorted(documents.get("concalls") or [], key=lambda c: c.get("month") or "", reverse=True)
    for c in calls:
        url = c.get("transcript_url")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(c)
        if len(out) >= count:
            break
    return out


COMPANY_WORDS = re.compile(r"\b(limited|ltd|pvt|private|corporation|company)\b", re.I)
ENUM = re.compile(r"^\s*(?:\d+[.)]|[-•●▪*])\s*")
PAGE_MARK = re.compile(r"^--- page \d+ ---$")
# "The next question is from the line of Nitin Padmanabhan from ..." names an analyst.
ANALYST_INTRO = re.compile(
    r"(?:question|questions|participant)\s+(?:is\s+|comes\s+|we have\s+)?(?:from|on)\s+(?:the\s+line\s+of\s+)?"
    r"(?:(?:mr|ms|mrs|dr)\.?\s+)?([A-Z][\w'.-]+(?:\s+[A-Z][\w'.-]+){0,3})")


def _clean_name(name: str) -> str:
    name = name.strip().lstrip(":;,.-–— ")
    name = ENUM.sub("", name)
    name = TITLES.sub("", name)
    name = re.split(r"\s+[-–—|,]\s+|\s*[–—|,]\s*", name)[0]
    return re.sub(r"\s+", " ", name).strip(" .:")


def _tokens(name: str) -> list[str]:
    return re.findall(r"[a-z]+", name.lower())


NAME_TITLES = {"mr", "mrs", "ms", "dr", "shri", "smt", "ca", "cfa", "prof"}


def _tok_match(x: str, y: str) -> bool:
    """One name token against another: equal, an initial ("b" ~ "bachhawat"), or a small
    spelling difference ("natasha" ~ "nattasha")."""
    if x == y:
        return True
    if len(x) == 1 or len(y) == 1:
        return x[0] == y[0]
    return min(len(x), len(y)) >= 4 and fuzz.ratio(x, y) >= 85


def same_person(a: str, b: str) -> bool:
    """"Nitin" ~ "Nitin Padmanabhan", "NIYANT MARU" ~ "Niyant Maru", "Garvit" ~ "CA Garvit",
    "Shrenik B" ~ "Shrenik Bachhawat". Every token of the shorter name must match a token
    of the longer one, and the first names must agree when both are given."""
    ta = [x for x in _tokens(a) if x not in NAME_TITLES]
    tb = [x for x in _tokens(b) if x not in NAME_TITLES]
    if not ta or not tb:
        return False
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len(short) >= 2 and not _tok_match(short[0], long_[0]):
        return False
    return all(any(_tok_match(x, y) for y in long_) for x in short)


# An all-capitals heading such as "JOURNALISTS" or "ANALYSTS" (typos included) ends a roster.
HEADING = re.compile(r"^[A-Z][A-Z &/:\-]{5,}:?$")


def strip_page_furniture(text: str) -> str:
    """Drop running headers and footers: lines at the top or bottom of many pages
    ("Polycab India Limited", "October 15, 2026")."""
    pages, cur = [], []
    for ln in text.splitlines():
        if PAGE_MARK.match(ln.strip()):
            pages.append(cur)
            cur = []
        else:
            cur.append(ln)
    pages.append(cur)
    pages = [p for p in pages if any(x.strip() for x in p)]
    if len(pages) < 4:
        return text
    counts: dict[str, int] = {}
    for p in pages:
        body = [x.strip() for x in p if x.strip()]
        for ln in set(body[:3] + body[-2:]):
            counts[ln] = counts.get(ln, 0) + 1
    furniture = {ln for ln, n in counts.items() if n >= max(3, 0.3 * len(pages)) and len(ln) < 80}
    return "\n".join(ln for ln in text.splitlines() if ln.strip() not in furniture and not PAGE_MARK.match(ln.strip()))


def management_roster(text: str, start: str, end: str) -> tuple[list[str], int]:
    """(names listed under the management / corporate participants header, index of the
    line where the roster ends). (([], 0) when the transcript has no such header.)
    Handles "Name / role" lines, "MANAGEMENT: MR. X – ROLE – COMPANY" blocks with roles
    wrapped over lines, and numbered lists."""
    lines = [ln.strip() for ln in text.splitlines()]
    start_re, end_re = re.compile(start, re.I), re.compile(end, re.I)
    names: list[str] = []
    stop = 0
    i = 0
    # A transcript file can hold several calls (press call, analyst call), each with a roster.
    while i < len(lines):
        ln = lines[i]
        if not start_re.search(ln):
            i += 1
            continue
        # The header line itself may carry names ("Management: Mr X - CEO, Ms Y - CFO").
        tail = start_re.split(ln, maxsplit=1)[-1]
        chunk = [tail] + lines[i + 1 : i + 60]
        end_at = i + len(chunk)
        found = False
        for k, raw in enumerate(chunk):
            # "Mr. X – role", "MR.X – ROLE" or "1. X – role, Company" opens a person's entry.
            titled = bool(re.match(r"^\W*(?:(?:mr|mrs|ms|dr|shri|smt)(?:\.\s*|\s+)|\d+[.)]\s+[A-Z])", raw, re.I))
            if raw is not tail and not titled and (end_re.search(raw) or (HEADING.match(raw) and not COMPANY_WORDS.search(raw))):
                end_at = i + k
                break
            if COMPANY_WORDS.search(raw) and not titled:
                continue  # a role or company line wrapped from the name above
            for part in re.split(r"[;,]\s*(?=(?:Mr|Mrs|Ms|Dr|Shri|Smt)\.?\s)|\s{3,}", raw):
                cand = _clean_name(part)
                if cand and NAME_LINE.match(cand) and len(cand.split()) <= 4 and not re.search(r"\d", cand):
                    names.append(cand)
                    found = True
        if found and not stop:
            stop = end_at
        i = max(end_at, i + 1)
    # Keep order, drop duplicates, role words and company names.
    roles = re.compile(r"^(chief|executive|director|head|president|vice|officer|manager|chairman|managing|company|investor|group|global|associate|senior|corporate|joint|board|financial)\b", re.I)
    out: list[str] = []
    for n in names:
        if roles.match(n) or COMPANY_WORDS.search(n) or any(same_person(n, o) and len(_tokens(n)) > 1 for o in out):
            continue
        out.append(n)
    return out, (stop if out else 0)


HANDOVER = re.compile(r"hand (?:the (?:conference|call|floor) )?over to (?:(?:mr|ms|mrs|dr)\.?\s+)?([A-Z][\w'.-]+(?:\s+[A-Z][\w'.-]+){0,3})")


def analysts_named(turns: list[tuple[str, str]], roster: list[str] | None = None) -> list[str]:
    """People who are not the company: those introduced as asking a question, and a call's
    host (the moderator hands over to them) when the roster doesn't list them."""
    out: list[str] = []
    for spk, speech in turns:
        for m in ANALYST_INTRO.finditer(speech):
            name = m.group(1).strip(" .")
            if name and name not in out:
                out.append(name)
        if spk.lower() == "moderator":
            for m in HANDOVER.finditer(speech):
                name = m.group(1).strip(" .")
                if name and not any(same_person(name, r) for r in roster or []) and name not in out:
                    out.append(name)
    return out


def speaker_turns(text: str, roster: list[str], start: int = 0) -> list[tuple[str, str]]:
    """[(speaker, speech)] in order, from line `start` (after the participants list).
    Transcripts written as "Name: speech" are read that way only; otherwise a speaker line
    is a roster name, "Moderator" or a name that recurs as a line of its own."""
    lines = [ln.strip() for ln in text.splitlines()][start:]
    lines = [ln for ln in lines if ln and not NOISE.search(ln)]
    counts: dict[str, int] = {}
    colon = 0
    for ln in lines:
        if NAME_LINE.match(ln) and len(ln) <= 48:
            counts[ln] = counts.get(ln, 0) + 1
        m = NAME_COLON.match(ln)
        if m and m.group(2) and len(m.group(1).split()) <= 4:
            colon += 1
    colon_mode = colon >= 8
    known = {n.lower() for n in roster}

    def is_speaker(ln: str) -> bool:
        clean = _clean_name(ln)
        if not clean:
            return False
        if clean.lower() == "moderator":
            return True
        if colon_mode:
            return False
        return clean.lower() in known or (NAME_LINE.match(ln) is not None and len(ln) <= 48 and counts.get(ln, 0) >= 2)

    turns: list[tuple[str, list[str]]] = []
    for ln in lines:
        m = NAME_COLON.match(ln)
        if m and (colon_mode or _clean_name(m.group(1)).lower() in known or m.group(1).lower() == "moderator"
                  or len(m.group(2)) > 0 and counts.get(m.group(1), 0) == 0 and len(m.group(1).split()) >= 2):
            turns.append((_clean_name(m.group(1)), [m.group(2)] if m.group(2) else []))
        elif is_speaker(ln):
            turns.append((_clean_name(ln), []))
        elif turns:
            turns[-1][1].append(ln)
    return [(spk, " ".join(body).strip()) for spk, body in turns if body]


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.?!])\s+(?=[A-Z(\"'“])", text) if s.strip()]


def split_passages(speech: str, size: int) -> list[str]:
    out, cur = [], ""
    for s in _sentences(speech):
        if cur and len(cur) + len(s) + 1 > size:
            out.append(cur.strip())
            cur = ""
        cur += " " + s
    if cur.strip():
        out.append(cur.strip())
    return out


def _hits(text: str, words: list[str]) -> int:
    low = text.lower()
    return sum(1 for w in words if w in low)


def metric_hits(text: str, metrics: dict[str, Any]) -> list[str]:
    low = text.lower()
    return [key for key, m in metrics.items() if any(re.search(rf"\b{re.escape(a)}", low) for a in m.get("aliases") or [])]


def is_management(speaker: str, roster: list[str], analysts: list[str]) -> bool | None:
    """True/False when the transcript says so; None when it can't tell.
    Analysts are introduced by name ("the next question is from ..."), so once a call names
    its analysts, anyone else who speaks (other than the moderator) is the company; rosters
    often list only some of the executives who answer."""
    if speaker.lower() == "moderator" or any(same_person(speaker, a) for a in analysts):
        return False
    if any(same_person(speaker, r) for r in roster):
        return True
    if len(analysts) >= 2:
        return True
    if roster:
        return False
    return None


def build_passages(turns: list[tuple[str, str]], roster: list[str], cfg: dict[str, Any], tag: str) -> list[Passage]:
    flt, metrics = cfg["filter"], cfg["metrics"]
    number = re.compile(flt["number"], re.I)
    analysts = analysts_named(turns, roster)
    out: list[Passage] = []
    for spk, speech in turns:
        known = is_management(spk, roster, analysts)
        for chunk in split_passages(speech, int(cfg["transcripts"]["passage_chars"])):
            # Without a roster, anyone but the moderator and named analysts counts,
            # unless the passage is mostly questions.
            sents = _sentences(chunk)
            questions = sum(1 for s in sents if s.rstrip().endswith("?"))
            # Mostly questions is never a promise, whoever the transcript says is speaking.
            mostly_questions = questions * 2 >= max(1, len(sents))
            mgmt = (known if known is not None else True) and not mostly_questions
            p = Passage(id=f"{tag}-p{len(out) + 1}", speaker=spk, management=mgmt, text=chunk)
            p.forward_hits = _hits(chunk, flt["forward"])
            p.outcome_hits = _hits(chunk, flt["outcome"])
            p.has_number = bool(number.search(chunk))
            p.metrics = metric_hits(chunk, metrics)
            out.append(p)
    return out


def forward_passages(passages: list[Passage], cfg: dict[str, Any]) -> list[Passage]:
    """Management passages that look like guidance, best first, within the per-call budget,
    then put back in transcript order."""
    min_hits = int(cfg["filter"]["min_forward_hits"])
    keep = [p for p in passages if p.management and p.has_number
            and ((p.metrics and p.forward_hits >= min_hits) or "guidance" in p.text.lower())]
    keep.sort(key=lambda p: -p.score())
    budget, picked, used = int(cfg["transcripts"]["max_chars_per_call"]), [], 0
    for p in keep:
        if used + len(p.text) > budget:
            continue
        picked.append(p)
        used += len(p.text)
    order = {p.id: i for i, p in enumerate(passages)}
    return sorted(picked, key=lambda p: order[p.id])


def outcome_passages(passages: list[Passage], metric: str) -> list[Passage]:
    """Management passages that report an actual for `metric` (a number and a past-tense cue)."""
    hits = [p for p in passages if p.management and p.has_number and metric in p.metrics and p.outcome_hits]
    return sorted(hits, key=lambda p: -(p.outcome_hits + p.forward_hits))


def fingerprint(t: Transcript) -> str | None:
    """Same spoken content, whatever the cover letter or link: the first passages' words."""
    if not t.passages:
        return None
    words = re.findall(r"[a-z]+", " ".join(p.text for p in t.passages[:12]).lower())
    return " ".join(words[:400]) if len(words) >= 50 else None


def read(call: dict[str, Any], tag: str, cfg: dict[str, Any], get_text: Callable[[str], str]) -> Transcript:
    """Fetch and parse one call. A failure is recorded on the transcript, never raised."""
    t = cfg["transcripts"]
    base = Transcript(period=call.get("period", ""), month=call.get("month", ""),
                      quarter=periods.quarter_discussed(call.get("month", "")), url=call["transcript_url"],
                      management=[], passages=[], text="")
    try:
        text = get_text(call["transcript_url"])
    except Exception as exc:  # noqa: BLE001 - one transcript must never stop the run
        base.error = f"{type(exc).__name__}: {exc}"[:200]
        return base
    if len(text.strip()) < int(t.get("min_text_chars", 2000)):
        base.error = "transcript PDF has no readable text (scanned?)"
        return base
    head = text[:3000]
    if re.search(t["event_markers"], head, re.I) and not re.search(t["earnings_markers"], head, re.I):
        base.kind, base.quarter = "event", None
    text = strip_page_furniture(text)
    roster, start = management_roster(text, t["roster_start"], t["roster_end"])
    turns = speaker_turns(text, roster, start)
    base.text, base.management = text, roster
    base.passages = build_passages(turns, roster, cfg, tag)
    if not base.passages:
        base.error = "could not split the transcript into speakers"
    return base
