"""Classify, rank and alert on the seed snapshot. No network, no LLM.

Usage (from the repo root):
    python scripts/build_push.py                  # write push outputs, print the last-24h digest
    python scripts/build_push.py --window 7d      # digest over 7 days (24h, 3d, 30d ...)
    python scripts/build_push.py --end now        # window ends now instead of at the snapshot
    python scripts/build_push.py --show-routine   # also list the collapsed routine cards
    python scripts/build_push.py --price-move 3 --volume 1.5   # try other alert thresholds
    python scripts/build_push.py --no-write       # print only

The window ends at the snapshot time by default, so a frozen snapshot always shows
the same digest. Outputs: data/seed/push/feed.json and alerts.json.
"""

from __future__ import annotations

import argparse
import collections
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest.common import now_ist, setup_logging  # noqa: E402
from ingest.config import ConfigError, load_config  # noqa: E402
from push.config import PushConfigError, load_push_config  # noqa: E402
from push.feed import alerts_document, build_alerts, feed_document, load_snapshot, score_snapshot, write_outputs  # noqa: E402
from push.priority import build_digest, parse_window  # noqa: E402

WIDTH = 92


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build FINN push outputs and print a digest.")
    p.add_argument("--window", default=None, help="digest window, e.g. 24h or 7d (default from push.yaml)")
    p.add_argument("--end", default="snapshot", help="'snapshot' (default), 'now', or an ISO time like 2026-11-13T18:00+05:30")
    p.add_argument("--show-routine", action="store_true", help="list routine cards instead of only counting them")
    p.add_argument("--price-move", type=float, default=None, help="override alerts.price_move_pct for this run")
    p.add_argument("--volume", type=float, default=None, help="override alerts.volume_ratio for this run")
    p.add_argument("--move-z", type=float, default=None, help="turn on volatility alerts at this many std-devs")
    p.add_argument("--no-write", action="store_true", help="print only; don't write feed.json / alerts.json")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def resolve_end(arg: str, snapshot_at: datetime) -> datetime:
    if arg == "snapshot":
        return snapshot_at
    if arg == "now":
        return now_ist()
    end = datetime.fromisoformat(arg)
    if end.tzinfo is None:
        raise ValueError("--end needs a timezone offset, e.g. 2026-11-13T18:00+05:30")
    return end


def clip(text: str, n: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def short_date(iso: str | None) -> str:
    if not iso:
        return "      "
    return datetime.fromisoformat(iso).strftime("%d %b") if "T" in iso else datetime.fromisoformat(iso).strftime("%d %b")


def print_cards(title: str, cards: list[dict]) -> None:
    print(f"\n{title} ({len(cards)})")
    for c in cards:
        more = f"  (+{c['repeats'] - 1} related)" if c["repeats"] > 1 else ""
        print(f"  {c['symbol']:<11}{short_date(c['datetime'])}  {c['category_label']:<22}{c['score']:>5.0f}  {clip(c['headline'], 46)}{more}")
        why = "; ".join(c["reasons"])
        print(f"  {'':<11}{'':<6}  why: {clip(why, WIDTH - 21)}")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args(argv)
    setup_logging(args.verbose)
    try:
        seed_dir = load_config().path("seed_dir")
        cfg = load_push_config()
        window = parse_window(args.window) if args.window else parse_window(f"{int(cfg.digest_window_hours)}h")
        snap = load_snapshot(seed_dir)
        end = resolve_end(args.end, snap.snapshot_at)
    except (ConfigError, PushConfigError, ValueError, FileNotFoundError) as exc:
        print(exc, file=sys.stderr)
        return 2

    scored = score_snapshot(snap, cfg)
    overrides = {}
    if args.price_move is not None:
        overrides["price_move_pct"] = args.price_move
    if args.volume is not None:
        overrides["volume_ratio"] = args.volume
    if args.move_z is not None:
        overrides["move_z"] = args.move_z
    alerts = build_alerts(snap, scored, cfg, end - window, end, overrides)

    digest = build_digest(scored, end - window, end, cfg)
    print("=" * WIDTH)
    print(f"FINN digest · {args.window or str(int(cfg.digest_window_hours)) + 'h'} to {end.strftime('%d %b %Y %H:%M')} IST · {digest['filings']} filings")
    print("=" * WIDTH)
    print_cards("NEEDS ATTENTION", digest["needs_attention"])
    print_cards("WORTH KNOWING", digest["worth_knowing"])
    r = digest["routine"]
    print(f"\nROUTINE: {r['filings']} filings in {r['cards']} cards (collapsed)")
    if args.show_routine:
        print_cards("ROUTINE", r["items"])

    alerts_doc = alerts_document(snap, alerts, cfg, end - window, end, overrides)
    rules = alerts_doc["rules"]
    z = f", {rules['move_z']}σ" if rules.get("move_z") is not None else ""
    span = f"{(end - window).strftime('%d %b %H:%M')} → {end.strftime('%d %b %H:%M')}"
    print(
        f"\nALERTS ({len(alerts)}) · same window, {span} · price ±{rules['price_move_pct']}%, "
        f"volume {rules['volume_ratio']}×{z}; filings scoring ≥{rules['filing_min_score']} in alert categories"
    )
    for a in alerts:
        flag = "!" if a["severity"] == "high" else " "
        print(f" {flag}{short_date(a['date'])}  {a['symbol']:<11}{a['type']:<7}{clip(a['reason'], WIDTH - 28)}")

    methods = collections.Counter(s.cls.method for s in scored)
    total = len(scored) or 1
    print(
        f"\nCLASSIFIER over all {len(scored)} portfolio filings: {methods.get('rule', 0)} by rule, "
        f"{methods.get('context', 0)} same-day, {methods.get('llm', 0)} from LLM cache, "
        f"{methods.get('pending', 0)} pending LLM ({100 * methods.get('pending', 0) / total:.0f}%)"
    )
    if not args.no_write:
        feed_path, alerts_path = write_outputs(seed_dir, feed_document(snap, scored, cfg), alerts_doc)
        print(f"Wrote {feed_path.relative_to(seed_dir.parent.parent)} and {alerts_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
