"""Indian fiscal periods. FY27 = April 2026 to March 2027; screener labels a quarter by
the month it ends ("Sep 2026" = Q2 FY27)."""

from __future__ import annotations

import re

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
QUARTER_END = {6: 1, 9: 2, 12: 3, 3: 4}  # month a quarter ends -> fiscal quarter number
PERIOD_RE = re.compile(r"^(?:(Q[1-4]|H[12]|9M))?FY(\d{2})$")


def parse_label(label: str) -> tuple[int, int] | None:
    """"Sep 2026" -> (2026, 9)."""
    m = re.fullmatch(r"([A-Z][a-z]{2}) (\d{4})", (label or "").strip())
    if not m or m.group(1) not in MONTHS:
        return None
    return int(m.group(2)), MONTHS.index(m.group(1)) + 1


def label(year: int, month: int) -> str:
    return f"{MONTHS[month - 1]} {year}"


def fiscal_year(year: int, month: int) -> int:
    """Two-digit fiscal year a month falls in: Sep 2026 -> 27, Mar 2027 -> 27."""
    return (year + 1 if month > 3 else year) % 100


def fiscal_label(quarter_label: str) -> str | None:
    """"Sep 2026" -> "Q2 FY27"."""
    ym = parse_label(quarter_label)
    if not ym or ym[1] not in QUARTER_END:
        return None
    return f"Q{QUARTER_END[ym[1]]} FY{fiscal_year(*ym):02d}"


def quarters_of(period: str) -> list[str]:
    """Screener quarter labels a period covers: "FY27" -> Jun 2026 .. Mar 2027;
    "H1FY27" -> Jun, Sep 2026; "Q3FY27" -> Dec 2026; "9MFY27" -> Jun .. Dec 2026."""
    m = PERIOD_RE.match(period or "")
    if not m:
        return []
    part, fy = m.group(1), 2000 + int(m.group(2))
    ends = [(fy - 1, 6), (fy - 1, 9), (fy - 1, 12), (fy, 3)]
    pick = {None: [0, 1, 2, 3], "H1": [0, 1], "H2": [2, 3], "9M": [0, 1, 2]}.get(part)
    if pick is None:  # Q1..Q4
        pick = [int(part[1]) - 1]
    return [label(*ends[i]) for i in pick]


def year_earlier(quarter_label: str) -> str | None:
    ym = parse_label(quarter_label)
    return label(ym[0] - 1, ym[1]) if ym else None


def quarter_discussed(call_month: str) -> str | None:
    """The quarter an earnings call reports on: a call in "2026-10" covers "Sep 2026"."""
    m = re.fullmatch(r"(\d{4})-(\d{2})", call_month or "")
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    end_month = {1: 12, 2: 12, 3: 12, 4: 3, 5: 3, 6: 3, 7: 6, 8: 6, 9: 6, 10: 9, 11: 9, 12: 9}[month]
    return label(year - 1 if end_month == 12 and month <= 3 else year, end_month)


def is_valid(period: str) -> bool:
    return bool(PERIOD_RE.match(period or ""))


def sort_key(quarter_label: str) -> tuple[int, int]:
    return parse_label(quarter_label) or (0, 0)
