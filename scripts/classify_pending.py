"""Send the filings no rule could place to the LLM router, once each.

Usage (from the repo root):
    python scripts/classify_pending.py             # classify all pending filings
    python scripts/classify_pending.py --limit 3   # try a few first
    python scripts/classify_pending.py --dry-run   # show the prompt for the first one; no calls
    python scripts/classify_pending.py --no-pdf    # use BSE's text only, don't download PDFs

Answers go to data/seed/push/llm_classifications.json (by filing id); re-run
scripts/build_push.py afterwards to see them in the feed. Repeat runs are free:
identical requests are served from the response cache.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest.common import setup_logging  # noqa: E402
from ingest.config import load_config  # noqa: E402
from ingest.http import PoliteSession  # noqa: E402
from ingest.pdfs import fetch_pdf  # noqa: E402
from llm.router import LLMConfigError, Router  # noqa: E402
from push.config import load_push_config  # noqa: E402
from push.feed import load_snapshot, score_snapshot  # noqa: E402
from push.llm_classify import classify_items, dump_prompt, merge_into_cache  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description="Classify pending filings with the LLM router.")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-pdf", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    setup_logging(args.verbose)

    base = load_config()
    cfg = load_push_config()
    seed_dir = base.path("seed_dir")
    snap = load_snapshot(seed_dir)
    pending = [s.item for s in score_snapshot(snap, cfg) if s.cls.pending]
    if args.limit is not None:
        pending = pending[: args.limit]
    print(f"{len(pending)} pending filing(s)")
    if not pending:
        return 0
    if args.dry_run:
        print(dump_prompt(pending[0], cfg))
        return 0

    try:
        router = Router.from_config()
    except LLMConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    http = PoliteSession(
        user_agent=base.setting("http", "user_agent", default="Mozilla/5.0"),
        timeout=float(base.setting("http", "timeout_seconds", default=20)),
        retries=int(base.setting("http", "retries", default=3)),
    )
    http.set_min_interval("www.bseindia.com", 1.0)
    pdf_dir = base.path("cache_dir") / "pdf"
    get_pdf = None if args.no_pdf else (lambda url: fetch_pdf(http, url, pdf_dir))

    outcomes = classify_items(pending, cfg, router.complete_json, get_pdf)
    added = merge_into_cache(cfg.llm_cache, outcomes)
    for o in outcomes:
        it = o.item
        if o.entry:
            e = o.entry
            print(f"  {it['symbol']:<11}{it['datetime'][:10]}  {e['category']:<18}{e['confidence']:<5} {e['model']:<34}{o.note}")
            print(f"  {'':<21}{e['summary'][:90]}  [{e['source'][:40]}]")
        else:
            print(f"  {it['symbol']:<11}{it['datetime'][:10]}  {o.note[:100]}")
    print(f"Stored {added} answer(s) in {cfg.llm_cache.relative_to(seed_dir.parent.parent)}. Now run: python scripts/build_push.py")
    return 0 if added else 1


if __name__ == "__main__":
    sys.exit(main())
