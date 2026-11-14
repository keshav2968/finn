"""Build the data/seed snapshot: fundamentals, EOD prices and BSE filings.

Usage (from the repo root):
    python scripts/build_seed.py                       # everything in config/portfolio.yaml
    python scripts/build_seed.py --only prices,filings
    python scripts/build_seed.py --symbols TCS,PIDILITIND   # any NSE symbol, in config or not
    python scripts/build_seed.py --offline             # re-parse cached screener pages only
    python scripts/build_seed.py --refresh             # ignore the screener cache

One failing ticker or source never stops the run: it is logged, the previous seed
file for it is kept (and marked stale in manifest.json), and the run moves on.
Exit codes: 0 = something succeeded, 1 = nothing succeeded (or --strict and any
failure), 2 = bad config or arguments.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest.common import get_logger, iso_ist, now_ist, read_json, setup_logging, write_json  # noqa: E402
from ingest.config import Company, Config, ConfigError, ad_hoc_company, load_config  # noqa: E402
from ingest.filings_bse import build_filings_record  # noqa: E402
from ingest.http import DiskCache, PoliteSession  # noqa: E402
from ingest.prices import build_price_record  # noqa: E402
from ingest.report import FAILED, OK, SKIPPED, RunReport  # noqa: E402
from ingest.screener import build_fundamentals_record  # noqa: E402

log = get_logger("build")

SOURCES = ("fundamentals", "prices", "filings")
SOURCE_LABELS = {
    "fundamentals": "screener.in (consolidated + standalone pages)",
    "prices": "Yahoo Finance end-of-day via yfinance",
    "filings": "BSE corporate announcements API",
}


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build the FINN seed snapshot.")
    p.add_argument("--only", default=",".join(SOURCES), help="comma-separated subset of: " + ", ".join(SOURCES))
    p.add_argument("--symbols", default="", help="comma-separated NSE symbols; default is the config universe")
    p.add_argument("--refresh", action="store_true", help="ignore cached screener pages")
    p.add_argument("--offline", action="store_true", help="no network: re-parse cached screener pages only")
    p.add_argument("--days", type=int, default=None, help="filings lookback in days (default from settings)")
    p.add_argument("--strict", action="store_true", help="exit 1 if anything failed")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    args.only = [s.strip() for s in args.only.split(",") if s.strip()]
    bad = [s for s in args.only if s not in SOURCES]
    if bad:
        p.error(f"--only: unknown source(s) {bad}; choose from {list(SOURCES)}")
    if args.refresh and args.offline:
        p.error("--refresh and --offline contradict each other")
    return args


def select_companies(cfg: Config, symbols_arg: str) -> list[Company]:
    if not symbols_arg.strip():
        return cfg.universe()
    out: list[Company] = []
    for raw in symbols_arg.split(","):
        sym = raw.strip().upper()
        if not sym or any(c.symbol == sym for c in out):
            continue
        out.append(cfg.companies.get(sym) or ad_hoc_company(sym))
    return out


def seed_file(seed_dir: Path, source: str, symbol: str) -> Path:
    return seed_dir / source / f"{symbol}.json"


def size_bucket(market_cap_cr: float | None, thresholds: dict[str, Any]) -> str | None:
    if market_cap_cr is None:
        return None
    if market_cap_cr >= float(thresholds.get("large", 100000)):
        return "large"
    if market_cap_cr >= float(thresholds.get("mid", 30000)):
        return "mid"
    return "small"


def resolve_bse_code(company: Company, fundamentals: dict | None, report: RunReport) -> str | None:
    """Prefer the code on the company's screener.in page; config is the fallback."""
    from_screener = (fundamentals or {}).get("bse_code")
    if company.bse_code and from_screener and company.bse_code != from_screener:
        report.warn(
            f"{company.symbol}: bse_code {company.bse_code} in portfolio.yaml but screener.in "
            f"links {from_screener}; using {from_screener}. Fix the config."
        )
        return from_screener
    return company.bse_code or from_screener


def check_against_fundamentals(company: Company, fund: dict, cfg: Config, report: RunReport) -> None:
    if company.ad_hoc:
        return
    mcap = (fund.get("key_metrics") or {}).get("market_cap_cr")
    derived = size_bucket(mcap, cfg.setting("size_buckets_cr", default={}))
    if derived and company.size and derived != company.size:
        report.warn(
            f"{company.symbol}: size is '{company.size}' in portfolio.yaml but market cap "
            f"Rs {mcap:,.0f} cr suggests '{derived}'"
        )
    layout = fund.get("layout")
    if layout in ("lender", "standard") and company.is_lender is not None:
        if (layout == "lender") != company.is_lender:
            report.warn(
                f"{company.symbol}: is_lender={str(company.is_lender).lower()} in portfolio.yaml but "
                f"screener.in uses the {layout} table layout"
            )


def run_fundamentals(companies, cfg, args, http, cache, seed_dir, report) -> None:
    ttl = float(cfg.setting("screener", "cache_ttl_hours", default=20))
    for c in companies:
        with report.track("fundamentals", c.symbol) as ctx:
            rec = build_fundamentals_record(
                http, cache, c.symbol, c.primary_view, ttl_hours=ttl, refresh=args.refresh, offline=args.offline
            )
            write_json(seed_file(seed_dir, "fundamentals", c.symbol), rec)
            cached = all(v.get("from_cache") for v in rec["views"].values())
            ctx["detail"] = (
                f"{rec['primary_view']} view, {rec['layout']} layout, "
                f"{len(rec['documents']['concalls'])} concalls, "
                f"{len(rec['documents']['annual_reports'])} annual reports" + (" (cache)" if cached else "")
            )
            for view, err in rec["view_errors"].items():
                if not err.startswith("404"):  # a missing view is normal, a failed fetch is not
                    report.warn(f"{c.symbol}: screener {view} view unavailable: {err}")


def run_prices(companies, cfg, args, seed_dir, report, now: datetime) -> None:
    settings = cfg.setting("prices", default={}) or {}
    timeout = float(cfg.setting("http", "timeout_seconds", default=20))
    gap = float(settings.get("min_interval_seconds", 0.5))
    for i, c in enumerate(companies):
        if args.offline:
            report.add("prices", c.symbol, SKIPPED, "--offline")
            continue
        if i:
            time.sleep(gap)
        with report.track("prices", c.symbol) as ctx:
            rec = build_price_record(c.symbol, settings, timeout=timeout, now=now)
            write_json(seed_file(seed_dir, "prices", c.symbol), rec, compact=True)
            lt = rec["latest"]
            ctx["detail"] = f"{rec['yahoo_symbol']} as of {lt['as_of']}: close {lt['close']} ({lt['pct_change']}%)"


def run_filings(companies, cfg, args, http, seed_dir, fundamentals, report, now: datetime) -> None:
    settings = cfg.setting("filings", default={}) or {}
    days = args.days or int(settings.get("lookback_days", 60))
    max_pages = int(settings.get("max_pages", 10))
    backoff = float(cfg.setting("http", "backoff_seconds", default=2.0))
    for c in companies:
        if args.offline:
            report.add("filings", c.symbol, SKIPPED, "--offline")
            continue
        code = resolve_bse_code(c, fundamentals.get(c.symbol), report)
        if not code:
            report.add("filings", c.symbol, FAILED, "no BSE code (not in config, not on screener.in)")
            continue
        with report.track("filings", c.symbol) as ctx:
            rec = build_filings_record(http, c.symbol, code, days, max_pages, now, backoff=backoff)
            write_json(seed_file(seed_dir, "filings", c.symbol), rec)
            ctx["detail"] = f"BSE {code}: {rec['count']} filings since {rec['window']['from']}"


def source_status(source: str, symbol: str, seed_dir: Path, report: RunReport, previous: dict | None) -> dict:
    data = read_json(seed_file(seed_dir, source, symbol))
    updated_at = (data or {}).get("fetched_at")
    outcome = report.status(source, symbol)
    if outcome and outcome.status == OK:
        return {"state": "ok", "updated_at": updated_at}
    if outcome and outcome.status == FAILED:
        return {"state": "stale" if data else "missing", "updated_at": updated_at, "error": outcome.detail}
    if previous:  # source not run this time: keep what the last run said
        return previous
    return {"state": "ok" if data else "missing", "updated_at": updated_at}


def build_manifest(cfg: Config, companies: list[Company], seed_dir: Path, report: RunReport, now: datetime) -> dict:
    prev = read_json(seed_dir / "manifest.json") or {}
    prev_entries = {e["symbol"]: e for e in prev.get("companies", [])}
    research = {r.symbol: r.focus for r in cfg.research}

    ordered: list[Company] = list(cfg.universe())
    known = {c.symbol for c in ordered}
    for c in companies:  # ad-hoc symbols from this run
        if c.symbol not in known:
            ordered.append(c)
            known.add(c.symbol)
    for sym, entry in prev_entries.items():  # ad-hoc symbols from earlier runs
        if sym not in known and entry.get("ad_hoc"):
            ordered.append(ad_hoc_company(sym))
            known.add(sym)

    entries = []
    as_of_dates = []
    for c in ordered:
        fund = read_json(seed_file(seed_dir, "fundamentals", c.symbol)) or {}
        price = read_json(seed_file(seed_dir, "prices", c.symbol)) or {}
        if price.get("as_of"):
            as_of_dates.append(price["as_of"])
        layout = fund.get("layout")
        mcap = (fund.get("key_metrics") or {}).get("market_cap_cr")
        prev_status = (prev_entries.get(c.symbol) or {}).get("status", {})
        entries.append(
            {
                "symbol": c.symbol,
                "name": fund.get("name") if c.ad_hoc and fund.get("name") else c.name,
                "sector": c.sector or None,
                "size": c.size or size_bucket(mcap, cfg.setting("size_buckets_cr", default={})),
                "is_lender": c.is_lender if c.is_lender is not None else (layout == "lender" if layout else None),
                "in_portfolio": c.symbol in cfg.portfolio,
                "research_focus": research.get(c.symbol),
                "ad_hoc": c.ad_hoc,
                "bse_code": fund.get("bse_code") or c.bse_code,
                "primary_view": fund.get("primary_view") or c.primary_view,
                "status": {s: source_status(s, c.symbol, seed_dir, report, prev_status.get(s)) for s in SOURCES},
            }
        )
    return {
        "generated_at": iso_ist(now),
        "as_of": max(as_of_dates) if as_of_dates else None,
        "sources": SOURCE_LABELS,
        "companies": entries,
        "warnings": report.warnings,
    }


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args(argv)
    setup_logging(args.verbose)
    try:
        cfg = load_config()
        companies = select_companies(cfg, args.symbols)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2

    report = RunReport()
    for w in cfg.warnings:
        report.warn(w)
    now = now_ist()
    seed_dir = cfg.path("seed_dir")
    cache = DiskCache(cfg.path("cache_dir") / "http")
    http = PoliteSession(
        user_agent=cfg.setting("http", "user_agent", default="Mozilla/5.0"),
        timeout=float(cfg.setting("http", "timeout_seconds", default=20)),
        retries=int(cfg.setting("http", "retries", default=3)),
        backoff=float(cfg.setting("http", "backoff_seconds", default=2.0)),
    )
    http.set_min_interval("www.screener.in", float(cfg.setting("screener", "min_interval_seconds", default=2.0)))
    http.set_min_interval("api.bseindia.com", float(cfg.setting("filings", "min_interval_seconds", default=0.6)))

    log.info("building seed for %d companies: %s", len(companies), ", ".join(c.symbol for c in companies))
    if "fundamentals" in args.only:
        run_fundamentals(companies, cfg, args, http, cache, seed_dir, report)

    fundamentals = {c.symbol: read_json(seed_file(seed_dir, "fundamentals", c.symbol)) for c in companies}
    for c in companies:
        if fundamentals.get(c.symbol):
            check_against_fundamentals(c, fundamentals[c.symbol], cfg, report)

    if "prices" in args.only:
        run_prices(companies, cfg, args, seed_dir, report, now)
    if "filings" in args.only:
        run_filings(companies, cfg, args, http, seed_dir, fundamentals, report, now)

    write_json(seed_dir / "manifest.json", build_manifest(cfg, companies, seed_dir, report, now))
    print(report.render())

    if args.strict and report.any_failure():
        return 1
    if report.outcomes and not report.any_success():
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
