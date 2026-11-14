"""Download the latest results PDF per company and save its statement pages as test input.

Usage (from the repo root):
    python scripts/fetch_results_pdfs.py --symbols INFY,HDFCBANK,BAJFINANCE,ELECON

For each symbol: the newest results card that holds the financial statements (not a
half-yearly report or a deck), its statement filing's PDF (cached in data/cache/pdf),
text extracted in Python, and every page that scores as a P&L statement. Writes
tests/fixtures/results_pages/SYMBOL.json and prints which page the card builder
would use.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest.common import REPO_ROOT, read_json, setup_logging, write_json  # noqa: E402
from ingest.config import load_config  # noqa: E402
from ingest.http import PoliteSession  # noqa: E402
from ingest.pdfs import PdfError, extract_text, fetch_pdf  # noqa: E402
from push.config import load_push_config  # noqa: E402
from push.feed import load_snapshot, score_snapshot  # noqa: E402
from push.results import analyse_page, choose_page_from_pdf, latest_results_card, page_score, pdf_candidates, results_settings  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser()
    p.add_argument("--symbols", required=True, help="comma-separated, e.g. INFY,HDFCBANK")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    setup_logging(args.verbose)

    base, cfg = load_config(), load_push_config()
    rc = results_settings(cfg)
    seed_dir = base.path("seed_dir")
    snap = load_snapshot(seed_dir, portfolio_only=False)
    scored = score_snapshot(snap, cfg)
    http = PoliteSession(user_agent=base.setting("http", "user_agent", default="Mozilla/5.0"), timeout=60)
    http.set_min_interval("www.bseindia.com", 1.5)
    pdf_dir = base.path("cache_dir") / "pdf"
    out_dir = REPO_ROOT / "tests" / "fixtures" / "results_pages"
    failures = 0

    for sym in [s.strip().upper() for s in args.symbols.split(",") if s.strip()]:
        fund = read_json(seed_dir / "fundamentals" / f"{sym}.json") or {}
        preferred = fund.get("primary_view") or "consolidated"
        card = latest_results_card(scored, sym, cfg)
        if card is None:
            print(f"{sym:<11} no results filing in the snapshot")
            failures += 1
            continue
        done = False
        for item in pdf_candidates(card):
            try:
                data = fetch_pdf(http, item["pdf_url"], pdf_dir)
                text = extract_text(data)
            except PdfError as exc:
                print(f"{sym:<11} {item['datetime'][:10]} {item['title'][:50]!r}: {exc}")
                continue
            choice = choose_page_from_pdf(text, preferred, int(rc["min_page_score"]))
            keep = [i for i, t in enumerate(text.pages) if page_score(t) >= int(rc["min_page_score"])]
            print(
                f"{sym:<11} {item['datetime'][:10]}  {item['title'][:48]!r}  {len(data) / 1024:,.0f} KB  "
                f"{text.page_count} pages  scanned={text.scanned}  statement pages={[i + 1 for i in keep]}  "
                f"uses page {choice.number if choice else '-'} ({choice.basis if choice else '-'})"
            )
            if choice is None and not text.scanned:
                continue
            write_json(out_dir / f"{sym}.json", {
                "symbol": sym,
                "filing_id": item["id"],
                "datetime": item["datetime"],
                "title": item["title"],
                "pdf_url": item["pdf_url"],
                "page_count": text.page_count,
                "scanned": text.scanned,
                "chosen_page": choice.number if choice else None,
                "pages": [{"page": i + 1, "score": page_score(text.pages[i]), "basis": analyse_page(text.pages[i])[0],
                           "text": text.pages[i]} for i in keep],
            })
            done = True
            break
        if not done:
            failures += 1
            print(f"{sym:<11} no PDF with a P&L statement found")
    print(f"Saved page text to {out_dir.relative_to(REPO_ROOT)}" + (f" · {failures} symbol(s) failed" if failures else ""))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
