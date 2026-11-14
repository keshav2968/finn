"""Build results cards: this quarter vs last quarter vs the same quarter last year.

Usage (from the repo root):
    python scripts/build_results_cards.py                       # every portfolio company
    python scripts/build_results_cards.py --symbols INFY,ELECON
    python scripts/build_results_cards.py --offline             # cached PDFs only (no downloads)
    python scripts/build_results_cards.py --no-llm              # screener.in figures only
    python scripts/build_results_cards.py --symbols INFY --dry-run   # show the page and prompt; no calls

Writes data/seed/push/results_cards.json, keyed by symbol. One company failing never
stops the rest: it falls back to a screener.in card and the reason is noted.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest.common import iso_ist, now_ist, read_json, setup_logging, write_json  # noqa: E402
from ingest.config import load_config  # noqa: E402
from ingest.http import PoliteSession  # noqa: E402
from ingest.pdfs import PdfError, extract_text, fetch_pdf  # noqa: E402
from llm.router import LLMConfigError, LLMError, Router  # noqa: E402
from push.config import load_push_config  # noqa: E402
from push.feed import load_snapshot, score_snapshot  # noqa: E402
from push.results import (  # noqa: E402
    build_card,
    choose_page_from_pdf,
    extract,
    latest_results_card,
    pdf_candidates,
    results_settings,
    screener_only_card,
    system_prompt,
    user_prompt,
)

MARK = {"verified": "✓", "mismatch": "✗", "screener": "s", "unchecked": "·", "missing": "–"}


def fmt(x, kind="amount"):
    if x is None:
        return "–"
    return f"{x:.1f}%" if kind == "margin" else f"{x:,.0f}"


def change(m, which):
    if m["kind"] == "margin":
        v = m.get(f"{which}_pp")
        return "" if v is None else f"{v:+.1f}pp"
    v = m.get(f"{which}_pct")
    return "n/m" if v is None else f"{v:+.1f}%"


def print_card(card):
    p = card.get("periods") or {}
    src = card.get("source") or {}
    where = f"page {src['page']}" if src.get("page") else "screener.in"
    print(f"\n{card['symbol']} · {card.get('name', '')} · {card.get('basis', '-')} · {card['status'].upper()} · {where}"
          + (f" · {src['model']}" if src.get("model") else ""))
    print(f"  {'₹ crore':<26}{p.get('current') or '':>10}{p.get('previous') or '':>10}{p.get('year_ago') or '':>10}{'QoQ':>9}{'YoY':>9}  check")
    for m in card.get("metrics", []):
        print(f"  {m['label']:<26}{fmt(m['current'], m['kind']):>10}{fmt(m['previous'], m['kind']):>10}{fmt(m['year_ago'], m['kind']):>10}"
              f"{change(m, 'qoq'):>9}{change(m, 'yoy'):>9}  {MARK.get(m['check'].get('current'), '?')}"
              + (f"  screener {fmt(m['screener'].get('current'))}" if m["check"].get("current") == "mismatch" else ""))
    for n in card.get("notes", []):
        print(f"  note: {n}")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Build FINN results cards.")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    setup_logging(args.verbose)

    base, cfg = load_config(), load_push_config()
    rc = results_settings(cfg)
    seed_dir = base.path("seed_dir")
    snap = load_snapshot(seed_dir)
    meta = {c["symbol"]: c for c in snap.manifest.get("companies", [])}
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] or list(snap.names)
    scored = score_snapshot(snap, cfg)
    http = PoliteSession(user_agent=base.setting("http", "user_agent", default="Mozilla/5.0"), timeout=60)
    http.set_min_interval("www.bseindia.com", 1.5)
    pdf_dir = base.path("cache_dir") / "pdf"
    router = None
    if not (args.no_llm or args.dry_run):
        try:
            router = Router.from_config()
        except LLMConfigError as exc:
            print(exc, file=sys.stderr)
            return 2

    out_path = seed_dir / "push" / "results_cards.json"
    existing = (read_json(out_path) or {}).get("cards") or {}
    cards = dict(existing)
    for sym in symbols:
        c = meta.get(sym, {})
        company = {"is_lender": c.get("is_lender"), "primary_view": c.get("primary_view"), "name": c.get("name")}
        fund = read_json(seed_dir / "fundamentals" / f"{sym}.json") or {}
        preferred = fund.get("primary_view") or c.get("primary_view") or "consolidated"
        card_group = latest_results_card(scored, sym, cfg)
        if card_group is None:
            cards[sym] = screener_only_card(sym, company, fund, None, rc, ["No results filing in the last 60 days"])
            print_card(cards[sym])
            continue
        source = {"filing_id": None, "filing_ids": [m.id for m in card_group.members], "datetime": card_group.lead.item.get("datetime")}
        reasons: list[str] = []
        card = None
        for item in pdf_candidates(card_group):
            try:
                data = fetch_pdf(http, item["pdf_url"], pdf_dir, offline=args.offline)
                text = extract_text(data)
            except PdfError as exc:
                reasons.append(f"{item['title'][:40]}: {exc}")
                continue
            page = choose_page_from_pdf(text, preferred, int(rc["min_page_score"]))
            scan = data if text.scanned and len(data) <= float(rc["max_scanned_pdf_mb"]) * 2**20 else None
            if page is None and scan is None:
                reasons.append(f"{item['title'][:40]}: no statement page")
                continue
            source.update({"filing_id": item["id"], "pdf_url": item["pdf_url"], "title": item["title"],
                           "page": page.number if page else None, "scanned": text.scanned})
            if args.dry_run:
                print(f"--- {sym}: page {page.number if page else 'scan'} of {item['pdf_url']}")
                print(system_prompt(bool(company["is_lender"])))
                print(user_prompt(sym, page, int(rc["max_page_chars"])) if page else "(scanned PDF attached)")
                card = "dry"
                break
            if router is None:
                card = screener_only_card(sym, company, fund, source, rc, ["--no-llm: figures from screener.in"])
                break
            try:
                extraction, model = extract(sym, bool(company["is_lender"]), page, router.complete_json, cfg, pdf=None if page else scan)
            except LLMError as exc:
                reasons.append(f"extraction failed: {'; '.join(exc.attempts)[:300]}")
                break
            source["model"] = model
            card = build_card(sym, company, fund, extraction, rc, source)
            if page and page.note:
                card["notes"].insert(0, page.note)
            break
        if card == "dry":
            continue
        if card is None:
            card = screener_only_card(sym, company, fund, source, rc, ["Could not read the results PDF; figures from screener.in"] + reasons)
        cards[sym] = card
        print_card(card)

    if not args.dry_run:
        write_json(out_path, {"generated_at": iso_ist(now_ist()), "cards": cards})
        counts = {}
        for card in cards.values():
            counts[card["status"]] = counts.get(card["status"], 0) + 1
        print(f"\nWrote {out_path.relative_to(seed_dir.parent.parent)} · " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
