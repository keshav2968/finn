"""Research any NSE company from primary sources: numbers + management's promise ledger.

Usage (from the repo root):
    python scripts/build_research.py INFY                 # any NSE symbol, one or more
    python scripts/build_research.py INFY POLYCAB --transcripts 4
    python scripts/build_research.py INFY --no-llm        # numbers + transcript filter only, no model calls
    python scripts/build_research.py INFY --offline       # cached screener pages and PDFs only
    python scripts/build_research.py INFY --dry-run       # print what the extractor would be sent

Writes data/seed/research/SYMBOL.json (one file per symbol, also on failure, with the
reason) and prints the ledger. Sources: the company's screener.in page and the call
transcript PDFs it links. Nothing else.
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml  # noqa: E402

from ingest.common import REPO_ROOT, iso_ist, now_ist, read_json, setup_logging, write_json  # noqa: E402
from ingest.config import load_config  # noqa: E402
from ingest.http import DiskCache, PoliteSession  # noqa: E402
from ingest.pdfs import extract_text, fetch_pdf  # noqa: E402
from ingest.screener import build_fundamentals_record  # noqa: E402
from llm.router import LLMConfigError, Router  # noqa: E402
from research import transcripts as T  # noqa: E402
from research.build import build_research  # noqa: E402

MARK = {"Delivered": "✓", "Missed": "✗", "Pending": "…", "Goalposts moved": "↺", "Unverified": "?"}


def load_research_config() -> dict:
    return yaml.safe_load((REPO_ROOT / "config" / "research.yaml").read_text(encoding="utf-8"))


def company_record(symbol: str, base, http, offline: bool, refresh: bool) -> dict:
    """screener.in fundamentals: the seed copy when fresh, otherwise fetched (any symbol)."""
    seed = read_json(base.path("seed_dir") / "fundamentals" / f"{symbol}.json")
    ttl = float(base.setting("screener", "cache_ttl_hours", default=20))
    if seed and (offline or not refresh):
        return seed
    cache = DiskCache(base.path("cache_dir") / "http")
    return build_fundamentals_record(http, cache, symbol, ttl_hours=ttl, refresh=refresh, offline=offline)


def print_ledger(doc: dict) -> None:
    print(f"\n{doc['symbol']} · {doc['name']} · status {doc['status']}")
    if doc.get("track_record"):
        print(f"  Track record: {doc['track_record']['text']}")
    n = doc.get("numbers") or {}
    ytd = (n.get("fiscal_year_to_date") or {}).get("metrics") or {}
    for m in ytd.values():
        if m:
            print(f"  {m['label']}: {m['value']:g}%")
    for t in doc["transcripts"]:
        extra = f" · {t['error']}" if t.get("error") else ""
        print(f"  call {t['call']:<9} {(t['fiscal'] or '') + (' event' if t.get('kind') == 'event' else ''):<10} passages {t['passages']:>3} → sent {t['sent']:>2} ({t['sent_chars']} chars) · promises {t['promises']}{extra}")
    for e in doc["ledger"]:
        print(f"\n  {MARK.get(e['verdict'], ' ')} {e['verdict']:<16} {e['metric_label']}{' (' + e['metric_text'] + ')' if e['metric'] == 'other' else ''} · {e['period']} · {e['period_status']}")
        if e["revision_path"]:
            print(f"    target path: {e['revision_path']}")
        for s in e["statements"]:
            print(f"    {s['id']} {s['call']} {s['speaker']} [{s['target_text'] or '-'}; quote match {s['quote_score']:g}]")
            print(textwrap.indent(textwrap.fill(f"\"{s['quote']}\"", 100), "        "))
        for ev in e["evidence"]:
            if ev["kind"] == "screener":
                print(f"    {ev['id']} screener: {ev['label']} = {ev['value']:g}{ev['unit']}")
        if e["actual_quote"]:
            q = e["actual_quote"]
            print(f"    actual ({q['call']}, {q['speaker']}): \"{q['text']}\"")
        print(f"    why: {e['rationale']}  [{e['verdict_by']}]")
        for note in e["notes"]:
            print(f"    note: {note}")
    if doc["dropped"]:
        print(f"\n  dropped {len(doc['dropped'])} extraction(s):")
        for d in doc["dropped"][:12]:
            print(f"    - {d['call']}: {d['reason']}: \"{d['quote'][:90]}\"")
    for note in doc["notes"]:
        print(f"  note: {note}")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Build FINN research files (numbers + promise ledger).")
    ap.add_argument("symbols", nargs="+", help="NSE symbols, e.g. INFY POLYCAB")
    ap.add_argument("--transcripts", type=int, default=None, help="how many recent calls to read")
    ap.add_argument("--no-llm", action="store_true", help="numbers and transcript filtering only")
    ap.add_argument("--offline", action="store_true", help="cached screener pages and PDFs only")
    ap.add_argument("--refresh", action="store_true", help="re-fetch the screener page")
    ap.add_argument("--dry-run", action="store_true", help="print the extractor's input for the latest call")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    setup_logging(args.verbose)

    base, cfg = load_config(), load_research_config()
    if args.transcripts:
        cfg["transcripts"]["count"] = args.transcripts
    out_dir = REPO_ROOT / cfg["output_dir"]
    http = PoliteSession(user_agent=base.setting("http", "user_agent", default="Mozilla/5.0"), timeout=60)
    http.set_min_interval("www.bseindia.com", 1.5)
    http.set_min_interval("www.screener.in", float(base.setting("screener", "min_interval_seconds", default=2.0)))
    pdf_dir = base.path("cache_dir") / "pdf"
    max_pages = int(cfg["transcripts"]["max_pdf_pages"])

    def get_text(url: str) -> str:
        return extract_text(fetch_pdf(http, url, pdf_dir, offline=args.offline), max_pages=max_pages, layout=False).text()

    router = None
    if not (args.no_llm or args.dry_run):
        try:
            router = Router.from_config()
        except LLMConfigError as exc:
            print(exc, file=sys.stderr)
            return 2

    failures = 0
    for raw in args.symbols:
        symbol = raw.strip().upper()
        try:
            record = company_record(symbol, base, http, args.offline, args.refresh)
            if args.dry_run:
                from research.promises import system_prompt, user_prompt

                call = T.select(record.get("documents") or {}, 1)
                if not call:
                    print(f"{symbol}: no transcripts listed on screener.in")
                    continue
                t = T.read(call[0], "t1", cfg, get_text)
                sent = T.forward_passages(t.passages, cfg)
                print(system_prompt(cfg["metrics"]))
                print(user_prompt(record.get("name") or symbol, t, sent))
                print(f"\n[{len(sent)} of {len(t.passages)} passages, {sum(len(p.text) for p in sent)} chars; management: {t.management}]")
                continue
            doc = build_research(symbol, record, cfg, get_text, router.complete_json if router else None,
                                 log=lambda m, s=symbol: print(f"  {s}: {m}"))
        except Exception as exc:  # noqa: BLE001 - one ticker must never stop the others
            failures += 1
            doc = {"schema": 1, "symbol": symbol, "status": "failed", "generated_at": iso_ist(now_ist()),
                   "error": f"{type(exc).__name__}: {exc}"[:300], "ledger": [], "numbers": None}
            print(f"{symbol}: failed: {doc['error']}", file=sys.stderr)
        write_json(out_dir / f"{symbol}.json", doc)
        if doc.get("status") != "failed":
            print_ledger(doc)
        print(f"\nWrote {(out_dir / f'{symbol}.json').relative_to(REPO_ROOT)}")
    return 1 if failures == len(args.symbols) else 0


if __name__ == "__main__":
    sys.exit(main())
