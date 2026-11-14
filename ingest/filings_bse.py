"""Corporate announcements from BSE's public JSON API.

We call the endpoint the BSE website itself uses rather than a wrapper library,
because of one quirk the wrappers don't handle: on any server-side problem BSE
answers HTTP 200 with a redirect to an HTML error page (error_Bse.html), and that
exact URL can keep failing for a while. So we validate that the body is JSON and,
on retry, vary the query string (parameter order, then a one-day-earlier start)
so the retry is not served the same cached error.

Phase 1 only normalises filings. Classification and priority come in Phase 2.
"""

from __future__ import annotations

import html
import re
from datetime import date, datetime, timedelta
from typing import Any

import requests

from .common import IST, clean_text, get_logger, iso_ist
from .http import FetchError, PoliteSession

log = get_logger("filings")

API_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
PDF_URL = "https://www.bseindia.com/stockinfo/AnnPdfOpen.aspx?Pname={name}"
BSE_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.bseindia.com",
    "Referer": "https://www.bseindia.com/",
}

# Filler text BSE puts in HEADLINE when the real content is only in the PDF.
EMPTY_HEADLINES = {"", "enclosed", "attached", "please find enclosed", "please find attached", "na", "-"}
_PREFIX_RE = re.compile(r"^.{2,120}? - \d{6} - ")  # "INFOSYS LTD. - 500209 - Subject"
_TAG_RE = re.compile(r"<[^>]+>")


class BseError(RuntimeError):
    pass


def is_json_response(resp: requests.Response) -> bool:
    if "error_bse" in resp.url.lower():
        return False
    ctype = resp.headers.get("Content-Type", "")
    if "json" not in ctype.lower():
        return False
    try:
        body = resp.json()
    except ValueError:
        return False
    return isinstance(body, dict) and "Table" in body


def _query_variants(page: int, scrip: str, start: date, end: date) -> list[dict[str, Any]]:
    """Same request, three spellings. dict order controls the query-string order."""
    fmt = "%Y%m%d"
    base = {
        "pageno": page,
        "strCat": "-1",
        "strPrevDate": start.strftime(fmt),
        "strScrip": scrip,
        "strSearch": "P",
        "strToDate": end.strftime(fmt),
        "strType": "C",
        "subcategory": "-1",
    }
    reordered = {k: base[k] for k in list(base)[1:]}
    reordered["pageno"] = page
    earlier = dict(base, strPrevDate=(start - timedelta(days=1)).strftime(fmt))
    return [base, reordered, earlier]


def fetch_page(
    http: PoliteSession, page: int, scrip: str, start: date, end: date, backoff: float = 2.0
) -> dict[str, Any]:
    """One attempt per URL spelling: re-sending the identical URL tends to get the
    same cached error, so variety helps more than repetition."""
    errors = []
    variants = _query_variants(page, scrip, start, end)
    for i, params in enumerate(variants):
        try:
            resp = http.get(API_URL, params=params, headers=BSE_HEADERS, accept=is_json_response, attempts=1)
            return resp.json()
        except FetchError as exc:
            errors.append(str(exc))
            if i < len(variants) - 1:
                http.pause(backoff * (i + 1))
    raise BseError(f"BSE API page {page} for {scrip} failed {len(errors)} ways; last: {errors[-1]}")


def fetch_announcements(
    http: PoliteSession,
    scrip: str,
    start: date,
    end: date,
    max_pages: int = 10,
    backoff: float = 2.0,
) -> list[dict[str, Any]]:
    """All raw announcement rows for one scrip in [start, end], across pages."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    total: int | None = None
    for page in range(1, max_pages + 1):
        data = fetch_page(http, page, scrip, start, end, backoff=backoff)
        table = data.get("Table") or []
        if total is None:
            try:
                total = int((data.get("Table1") or [{}])[0].get("ROWCNT"))
            except (TypeError, ValueError, IndexError):
                total = None
        new = 0
        for row in table:
            key = str(row.get("NEWSID") or "")
            if key and key not in seen:
                seen.add(key)
                rows.append(row)
                new += 1
        if not table or new == 0:
            break
        if total is not None and len(rows) >= total:
            break
    else:
        log.warning("%s: stopped at max_pages=%d with %d of %s rows", scrip, max_pages, len(rows), total)
    return rows


def _parse_bse_time(value: Any) -> datetime | None:
    """BSE timestamps are IST without an offset, e.g. 2026-10-23T16:16:06.71."""
    if not value:
        return None
    text = str(value).strip()
    # Python 3.10's fromisoformat only accepts exactly 3 or 6 fractional digits;
    # BSE sends 1-3 (".71", ".9"). Pad or cut to 6.
    text = re.sub(r"\.(\d+)$", lambda m: "." + m.group(1)[:6].ljust(6, "0"), text)
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=IST)


def _strip_html(text: Any) -> str:
    return clean_text(html.unescape(_TAG_RE.sub(" ", str(text or ""))))


def normalize(row: dict[str, Any], symbol: str) -> dict[str, Any] | None:
    news_id = str(row.get("NEWSID") or "").strip()
    if not news_id:
        return None
    when = (
        _parse_bse_time(row.get("DissemDT"))
        or _parse_bse_time(row.get("NEWS_DT"))
        or _parse_bse_time(row.get("DT_TM"))
    )
    subject = clean_text(row.get("NEWSSUB"))
    title = _PREFIX_RE.sub("", subject) or subject
    headline = clean_text(row.get("HEADLINE"))
    detail = None
    if headline.lower().rstrip(".") not in EMPTY_HEADLINES and headline.lower() != title.lower():
        detail = headline
    more = _strip_html(row.get("MORE"))
    attachment = clean_text(row.get("ATTACHMENTNAME")) or None
    return {
        "id": news_id,
        "exchange": "BSE",
        "symbol": symbol,
        "bse_code": str(row.get("SCRIP_CD") or "") or None,
        "datetime": iso_ist(when) if when else None,
        "title": title,
        "detail": detail,
        "more": more[:2000] or None,
        "bse_category": clean_text(row.get("CATEGORYNAME")) or None,
        "bse_subcategory": clean_text(row.get("SUBCATNAME")) or None,
        "critical": bool(row.get("CRITICALNEWS")),
        "pdf_url": PDF_URL.format(name=attachment) if attachment else None,
        "attachment": attachment,
        "audio_video_url": clean_text(row.get("AUDIO_VIDEO_FILE")) or None,
        "company_url": clean_text(row.get("NSURL")) or None,
    }


def build_filings_record(
    http: PoliteSession,
    symbol: str,
    bse_code: str,
    lookback_days: int,
    max_pages: int,
    now: datetime,
    backoff: float = 2.0,
) -> dict[str, Any]:
    end = now.date()
    start = end - timedelta(days=lookback_days)
    raw = fetch_announcements(http, bse_code, start, end, max_pages=max_pages, backoff=backoff)
    items = [item for item in (normalize(r, symbol) for r in raw) if item]
    items.sort(key=lambda i: i["datetime"] or "", reverse=True)
    return {
        "symbol": symbol,
        "bse_code": bse_code,
        "window": {"from": start.isoformat(), "to": end.isoformat()},
        "fetched_at": iso_ist(now),
        "count": len(items),
        "items": items,
    }
