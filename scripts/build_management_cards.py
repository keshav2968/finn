"""Build management-change cards from the filings themselves (no web lookups).

Usage (from the repo root):
    python scripts/build_management_cards.py                    # every management filing in the feed
    python scripts/build_management_cards.py --symbols TITAN,LT
    python scripts/build_management_cards.py --offline          # cached PDFs only; BSE's text otherwise
    python scripts/build_management_cards.py --symbols LT --dry-run   # show the prompt; no calls

Writes data/seed/push/management_cards.json keyed by filing id. A filing that fails
gets an "unavailable" card with the reason; the run carries on.
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
from push.management import build_card, extract, management_settings, source_text, system_prompt, user_prompt  # noqa: E402

SEV = {"high": "!!", "normal": "! ", "low": "  "}


def print_card(card: dict) -> None:
    print(f"{SEV.get(card['severity'], '  ')} {card['symbol']:<11}{(card['datetime'] or '')[:10]}  {card['status']:<11} {card['summary'][:80]}")
    for p in card["people"]:
        when = p["effective_date"] or "date not stated"
        at = f" at {p['entity']}" if p["at_subsidiary"] else ""
        print(f"      {p['direction']:<10} {p['name']} · {p['role'][:55]}{at} · {p['change']} · {when}")
        if p["stated_reason"]:
            print(f"      {'':<10} reason: {p['stated_reason'][:90]}")
        if p["prior_roles"]:
            print(f"      {'':<10} before: {'; '.join(p['prior_roles'])[:90]}")
    for f in card["flags"]:
        print(f"      FLAG {f['label']} ({f['name']})")
    for n in card["notes"]:
        print(f"      note: {n[:110]}")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Build FINN management-change cards.")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    setup_logging(args.verbose)

    base, cfg = load_config(), load_push_config()
    mcfg = management_settings(cfg)
    seed_dir = base.path("seed_dir")
    snap = load_snapshot(seed_dir)
    wanted = {s.strip().upper() for s in args.symbols.split(",") if s.strip()}
    items = [s.item for s in score_snapshot(snap, cfg)
             if s.cls.category == "management_change" and (not wanted or s.item["symbol"] in wanted)]
    print(f"{len(items)} management filing(s)")
    http = PoliteSession(user_agent=base.setting("http", "user_agent", default="Mozilla/5.0"), timeout=60)
    http.set_min_interval("www.bseindia.com", 1.5)
    pdf_dir = base.path("cache_dir") / "pdf"
    router = None
    if not args.dry_run:
        try:
            router = Router.from_config()
        except LLMConfigError as exc:
            print(exc, file=sys.stderr)
            return 2

    out_path = seed_dir / "push" / "management_cards.json"
    cards = dict((read_json(out_path) or {}).get("cards") or {})
    for item in items:
        pdf_text, scan, source = "", None, {"text": "filing text"}
        if item.get("pdf_url"):
            try:
                data = fetch_pdf(http, item["pdf_url"], pdf_dir, offline=args.offline)
                text = extract_text(data, max_pages=int(mcfg["max_pdf_pages"]), layout=False)
                if text.scanned:
                    scan, source = data, {"text": "scanned PDF"}
                else:
                    pdf_text, source = text.text(), {"text": "filing text + PDF"}
            except PdfError as exc:
                source = {"text": f"filing text (PDF unavailable: {str(exc)[:80]})"}
        text = source_text(item, pdf_text, int(mcfg["max_text_chars"]))
        if args.dry_run:
            print(system_prompt())
            print(user_prompt(item, text))
            break
        try:
            extraction, model = extract(item, text, router.complete_json, pdf=scan)
            source["model"] = model
            card = build_card(item, extraction, text, mcfg, source)
        except LLMError as exc:
            card = build_card(item, None, text, mcfg, source, error=f"Extraction failed: {'; '.join(exc.attempts)[:200]}")
        except Exception as exc:  # noqa: BLE001 - one filing must never stop the run
            card = build_card(item, None, text, mcfg, source, error=f"{type(exc).__name__}: {exc}"[:200])
        cards[item["id"]] = card
        print_card(card)

    if not args.dry_run:
        write_json(out_path, {"generated_at": iso_ist(now_ist()), "cards": cards})
        flagged = sum(1 for c in cards.values() if c["flags"])
        print(f"\nWrote {out_path.relative_to(seed_dir.parent.parent)} · {len(cards)} cards, {flagged} with warning flags")
    return 0


if __name__ == "__main__":
    sys.exit(main())
