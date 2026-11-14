"""screener.in company pages: fetch (cached, throttled) and parse into plain tables.

Both the consolidated and standalone views are fetched for every company:
- Phase 2 cross-checks numbers pulled from results PDFs against screener, and a
  results filing reports both bases, so we need both to compare like with like.
- For lenders the right basis differs by company (HDFC Bank's consolidated view
  includes insurance subsidiaries; Bajaj Finance's consolidated view is the norm).

Tables are stored as screener labels them. `fields` maps stable keys (revenue,
pbt, cfo, ...) to the label used on this page, so later phases never depend on
label spelling or on whether the company uses the bank or the non-bank layout.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, quote, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from .common import clean_text, get_logger, iso_ist, now_ist, parse_number
from .http import DiskCache, FetchError, NotFound, PoliteSession, cached_get_text

log = get_logger("screener")

BASE_URL = "https://www.screener.in"
VIEWS = ("consolidated", "standalone")

TABLE_SECTIONS = {
    "quarters": "quarters",
    "profit_loss": "profit-loss",
    "balance_sheet": "balance-sheet",
    "cash_flow": "cash-flow",
    "ratios": "ratios",
}

# stable key -> labels screener uses for it (first match wins)
GROWTH_LABELS = ["YoY Sales growth", "Sales growth", "YoY Revenue growth", "Revenue growth"]
PNL_STANDARD = {
    "revenue": ["Sales", "Revenue"],
    "revenue_growth_pct": GROWTH_LABELS,
    "expenses": ["Expenses"],
    "operating_profit": ["Operating Profit"],
    "opm_pct": ["OPM %"],
    "other_income": ["Other Income"],
    "interest": ["Interest"],
    "depreciation": ["Depreciation"],
    "pbt": ["Profit before tax"],
    "tax_pct": ["Tax %"],
    "net_profit": ["Net Profit"],
    "eps": ["EPS in Rs"],
    "dividend_payout_pct": ["Dividend Payout %"],
}
PNL_LENDER = {
    "revenue": ["Revenue"],  # interest earned
    "revenue_growth_pct": GROWTH_LABELS,
    "interest_expended": ["Interest"],
    "expenses": ["Expenses"],  # operating expenses + provisions
    "financing_profit": ["Financing Profit"],
    "financing_margin_pct": ["Financing Margin %"],
    "other_income": ["Other Income"],
    "depreciation": ["Depreciation"],
    "pbt": ["Profit before tax"],
    "tax_pct": ["Tax %"],
    "net_profit": ["Net Profit"],
    "eps": ["EPS in Rs"],
    "gross_npa_pct": ["Gross NPA %"],
    "net_npa_pct": ["Net NPA %"],
    "dividend_payout_pct": ["Dividend Payout %"],
}
BALANCE_SHEET = {
    "equity_capital": ["Equity Capital"],
    "reserves": ["Reserves"],
    "borrowings": ["Borrowings", "Borrowing"],
    "deposits": ["Deposits"],
    "other_liabilities": ["Other Liabilities"],
    "total_liabilities": ["Total Liabilities"],
    "fixed_assets": ["Fixed Assets"],
    "cwip": ["CWIP"],
    "investments": ["Investments"],
    "other_assets": ["Other Assets"],
    "total_assets": ["Total Assets"],
}
CASH_FLOW = {
    "cfo": ["Cash from Operating Activity"],
    "cfi": ["Cash from Investing Activity"],
    "cff": ["Cash from Financing Activity"],
    "net_cash_flow": ["Net Cash Flow"],
    "fcf": ["Free Cash Flow"],
    "cfo_to_ebitda_pct": ["CFO/EBITDA"],
}
RATIOS = {
    "debtor_days": ["Debtor Days"],
    "inventory_days": ["Inventory Days"],
    "days_payable": ["Days Payable"],
    "cash_conversion_cycle": ["Cash Conversion Cycle"],
    "working_capital_days": ["Working Capital Days"],
    "roce_pct": ["ROCE %"],
    "roe_pct": ["ROE %"],
}
TOP_RATIO_KEYS = {
    "Market Cap": "market_cap_cr",
    "Current Price": "price",
    "Stock P/E": "pe",
    "Book Value": "book_value",
    "Dividend Yield": "dividend_yield_pct",
    "ROCE": "roce_pct",
    "ROE": "roe_pct",
    "Face Value": "face_value",
}
CONCALL_LINKS = {"transcript": "transcript_url", "ppt": "ppt_url", "rec": "recording_url", "notes": "notes_url"}


class ScreenerError(RuntimeError):
    pass


def company_url(symbol: str, view: str) -> str:
    path = f"/company/{quote(symbol, safe='')}/"
    return BASE_URL + path + ("consolidated/" if view == "consolidated" else "")


# ---------------------------------------------------------------- parsing


def _row_label(td: Tag) -> str:
    cell = copy.copy(td)
    for el in cell.select(".has-tooltip, .tooltip, .blue-icon"):
        el.decompose()
    return clean_text(cell.get_text(" ")).rstrip("+").strip()


def parse_data_table(table: Tag | None) -> dict[str, Any] | None:
    """A screener data-table -> {periods, rows{label: [values]}, pct_rows, links}.

    Values are floats (crores, %, days or counts, as labelled); blanks are None.
    Rows whose cells are only links (e.g. "Raw PDF") go to `links` as {period: url}.
    """
    if table is None:
        return None
    head = table.find("thead")
    if head is None:
        return None
    periods = [clean_text(th.get_text()) for th in head.find_all("th")][1:]
    rows: dict[str, list[float | None]] = {}
    pct_rows: list[str] = []
    links: dict[str, dict[str, str]] = {}
    body = table.find("tbody") or table
    for tr in body.find_all("tr", recursive=False):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 2:
            continue
        label = _row_label(tds[0])
        if not label:
            continue
        cells = tds[1:]
        texts = [clean_text(c.get_text()) for c in cells]
        anchors = [c.find("a", href=True) for c in cells]
        if any(anchors) and not any(texts):
            links[label] = {
                periods[i]: urljoin(BASE_URL, a["href"])
                for i, a in enumerate(anchors)
                if a is not None and i < len(periods)
            }
            continue
        values = [parse_number(t) for t in texts][: len(periods)]
        values += [None] * (len(periods) - len(values))
        key = label
        n = 2
        while key in rows:
            key = f"{label} ({n})"
            n += 1
        rows[key] = values
        filled = [t for t in texts if t]
        if filled and sum(t.endswith("%") for t in filled) * 2 > len(filled):
            pct_rows.append(key)
    return {"periods": periods, "rows": rows, "pct_rows": pct_rows, "links": links}


def map_fields(table: dict[str, Any] | None, mapping: dict[str, list[str]]) -> dict[str, str]:
    if not table:
        return {}
    out = {}
    for key, candidates in mapping.items():
        for label in candidates:
            if label in table["rows"]:
                out[key] = label
                break
    return out


def detect_layout(quarters: dict[str, Any] | None) -> str:
    """'lender' (banks/NBFCs: Revenue, Interest, Financing Profit...), 'standard'
    (Sales, Operating Profit, OPM %...), or 'unknown'."""
    labels = set((quarters or {}).get("rows", {}))
    if {"Financing Profit", "Financing Margin %"} & labels:
        return "lender"
    if {"Operating Profit", "OPM %"} & labels:
        return "standard"
    return "unknown"


def has_numbers(table: dict[str, Any] | None) -> bool:
    return bool(table) and any(v is not None for vals in table["rows"].values() for v in vals)


def parse_growth_ranges(section: Tag | None) -> dict[str, dict[str, float | None]]:
    out: dict[str, dict[str, float | None]] = {}
    if section is None:
        return out
    for table in section.select("table.ranges-table"):
        th = table.find("th")
        title = clean_text(th.get_text()) if th else f"Range {len(out) + 1}"
        values = {}
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) == 2:
                values[clean_text(tds[0].get_text()).rstrip(":")] = parse_number(tds[1].get_text())
        out[title] = values
    return out


def parse_top_ratios(soup: BeautifulSoup) -> tuple[dict[str, Any], dict[str, float | None]]:
    raw: dict[str, Any] = {}
    key_metrics: dict[str, float | None] = {}
    for li in soup.select("#top-ratios li"):
        name_el, value_el = li.select_one(".name"), li.select_one(".value")
        if not name_el or not value_el:
            continue
        name = clean_text(name_el.get_text())
        numbers = [parse_number(n.get_text()) for n in value_el.select(".number")]
        raw[name] = {"text": clean_text(value_el.get_text()), "values": numbers}
        if name in TOP_RATIO_KEYS and numbers:
            key_metrics[TOP_RATIO_KEYS[name]] = numbers[0]
        elif name == "High / Low" and len(numbers) == 2:
            key_metrics["high_52w"], key_metrics["low_52w"] = numbers
    return raw, key_metrics


def parse_documents(soup: BeautifulSoup) -> dict[str, list[dict[str, Any]]]:
    annual_reports = []
    for li in soup.select(".documents.annual-reports ul.list-links li"):
        a = li.find("a", href=True)
        if a is None:
            continue
        title = clean_text(a.get_text())
        year = re.search(r"(19|20)\d{2}", title)
        source = li.find(string=re.compile(r"from\s+\w+", re.I))
        annual_reports.append(
            {
                "title": title,
                "year": int(year.group(0)) if year else None,
                "url": urljoin(BASE_URL, a["href"]),
                "source": clean_text(source).replace("from ", "") if source else None,
            }
        )
    concalls = []
    for li in soup.select(".documents.concalls ul.list-links li"):
        label_el = li.find("div")
        period = clean_text(label_el.get_text()) if label_el else ""
        try:
            month = datetime.strptime(period, "%b %Y").strftime("%Y-%m")
        except ValueError:
            month = None
        entry: dict[str, Any] = {"period": period, "month": month}
        for a in li.find_all("a", href=True):
            key = CONCALL_LINKS.get(clean_text(a.get_text()).lower())
            if key:
                entry[key] = urljoin(BASE_URL, a["href"])
        concalls.append(entry)
    return {"annual_reports": annual_reports, "concalls": concalls}


def parse_identity(soup: BeautifulSoup) -> dict[str, Any]:
    info = soup.select_one("#company-info")
    bse_code = None
    bse_link = soup.select_one('a[href*="bseindia.com/stock-share-price"]')
    if bse_link:
        m = re.search(r"/(\d{6})/?", bse_link["href"])
        bse_code = m.group(1) if m else None
    nse_symbol = None
    nse_link = soup.select_one('a[href*="nseindia.com/get-quotes/equity"]')
    if nse_link:
        nse_symbol = (parse_qs(urlsplit(nse_link["href"]).query).get("symbol") or [None])[0]
    about_el = soup.select_one(".company-profile .about")
    h1 = soup.find("h1")
    return {
        "name": clean_text(h1.get_text()) if h1 else None,
        "screener_company_id": info.get("data-company-id") if info else None,
        "is_consolidated_page": bool(info and info.has_attr("data-consolidated")),
        "bse_code": bse_code,
        "nse_symbol": nse_symbol,
        "about": clean_text(about_el.get_text(" "))[:800] if about_el else None,
    }


def parse_company_page(html_text: str) -> dict[str, Any]:
    soup = BeautifulSoup(html_text, "lxml")
    if soup.select_one("#company-info") is None and soup.select_one("section#quarters") is None:
        raise ScreenerError("page has no company data (blocked, login wall or layout change)")
    tables: dict[str, Any] = {}
    for key, section_id in TABLE_SECTIONS.items():
        section = soup.find("section", id=section_id)
        tables[key] = parse_data_table(section.select_one("table.data-table") if section else None)
    tables["shareholding_quarterly"] = parse_data_table(soup.select_one("#quarterly-shp table.data-table"))
    tables["shareholding_yearly"] = parse_data_table(soup.select_one("#yearly-shp table.data-table"))

    layout = detect_layout(tables["quarters"])
    pnl_map = PNL_LENDER if layout == "lender" else PNL_STANDARD
    fields = {
        "quarters": map_fields(tables["quarters"], pnl_map),
        "profit_loss": map_fields(tables["profit_loss"], pnl_map),
        "balance_sheet": map_fields(tables["balance_sheet"], BALANCE_SHEET),
        "cash_flow": map_fields(tables["cash_flow"], CASH_FLOW),
        "ratios": map_fields(tables["ratios"], RATIOS),
    }
    top_ratios, key_metrics = parse_top_ratios(soup)
    return {
        "identity": parse_identity(soup),
        "layout": layout,
        "has_data": has_numbers(tables["quarters"]) or has_numbers(tables["profit_loss"]),
        "tables": tables,
        "fields": fields,
        "growth_ranges": parse_growth_ranges(soup.find("section", id="profit-loss")),
        "top_ratios": top_ratios,
        "key_metrics": key_metrics,
        "documents": parse_documents(soup),
    }


# ---------------------------------------------------------------- fetching


def choose_primary(preferred: str, views: dict[str, dict[str, Any]]) -> tuple[str, str]:
    usable = [v for v in VIEWS if views.get(v, {}).get("has_data")]
    if not usable:
        raise ScreenerError("neither view has financial data")
    if preferred in usable:
        return preferred, "configured" if preferred != "consolidated" else "default"
    other = usable[0]
    return other, f"{preferred} view has no data; using {other}"


def build_fundamentals_record(
    http: PoliteSession,
    cache: DiskCache,
    symbol: str,
    preferred_view: str = "consolidated",
    ttl_hours: float = 20,
    refresh: bool = False,
    offline: bool = False,
) -> dict[str, Any]:
    views: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    for view in VIEWS:
        url = company_url(symbol, view)
        try:
            resp = cached_get_text(http, cache, url, timedelta(hours=ttl_hours), refresh, offline)
            parsed = parse_company_page(resp.text)
        except NotFound:
            errors[view] = "404: no such company page"
            continue
        except (FetchError, ScreenerError) as exc:
            errors[view] = str(exc)
            continue
        parsed["url"] = url
        parsed["fetched_at"] = resp.fetched_at
        parsed["from_cache"] = resp.from_cache
        views[view] = parsed

    if not views:
        if all(e.startswith("404") for e in errors.values()):
            raise ScreenerError(f"{symbol} not found on screener.in")
        raise ScreenerError("; ".join(f"{v}: {e}" for v, e in errors.items()))

    primary, reason = choose_primary(preferred_view, views)
    main = views[primary]
    identity = main["identity"]
    documents = main["documents"]  # the same list appears on both views' pages
    for v in views.values():  # page-level data is kept once, at the top level
        v.pop("identity", None)
        v.pop("documents", None)
    return {
        "symbol": symbol,
        "source": "screener.in",
        "fetched_at": iso_ist(now_ist()),
        "name": identity["name"],
        "screener_company_id": identity["screener_company_id"],
        "bse_code": identity["bse_code"],
        "nse_symbol": identity["nse_symbol"],
        "about": identity["about"],
        "primary_view": primary,
        "primary_view_reason": reason,
        "layout": main["layout"],
        "key_metrics": main["key_metrics"],
        "documents": documents,
        "views": views,
        "view_errors": errors,
    }
