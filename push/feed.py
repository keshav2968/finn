"""Build the push outputs from the seed snapshot (no network, no LLM).

    data/seed/push/feed.json    every portfolio filing: category, score, tier, reasons
    data/seed/push/alerts.json  price/volume and filing alerts with stored reasons

Both files carry the rule defaults, so the app shows the same labels and can
re-apply the user's own thresholds to the stored metrics.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ingest.common import iso_ist, now_ist, read_json, write_json

from .alerts import effective_rules, filing_alerts, price_alerts, sort_alerts
from .classify import classify_all, load_llm_cache
from .config import TIERS, PushConfig
from .priority import PriceIndex, ScoredFiling, attribute_reactions, score_filing


@dataclass
class Snapshot:
    manifest: dict[str, Any]
    filings: list[dict[str, Any]]
    prices: dict[str, dict[str, Any]]
    names: dict[str, str]
    snapshot_at: datetime


def load_snapshot(seed_dir: Path, portfolio_only: bool = True) -> Snapshot:
    manifest = read_json(seed_dir / "manifest.json")
    if not manifest:
        raise FileNotFoundError(f"{seed_dir / 'manifest.json'} not found: run scripts/build_seed.py first")
    companies = [c for c in manifest.get("companies", []) if c.get("in_portfolio") or not portfolio_only]
    filings: list[dict[str, Any]] = []
    prices: dict[str, dict[str, Any]] = {}
    for c in companies:
        sym = c["symbol"]
        f = read_json(seed_dir / "filings" / f"{sym}.json")
        if f:
            filings.extend(f.get("items") or [])
        p = read_json(seed_dir / "prices" / f"{sym}.json")
        if p:
            prices[sym] = p
    snapshot_at = datetime.fromisoformat(manifest["generated_at"]) if manifest.get("generated_at") else now_ist()
    return Snapshot(manifest, filings, prices, {c["symbol"]: c.get("name") or c["symbol"] for c in companies}, snapshot_at)


def score_snapshot(
    snap: Snapshot, cfg: PushConfig, llm_cache: dict[str, dict[str, Any]] | None = None
) -> list[ScoredFiling]:
    """llm_cache=None reads the cache file named in push.yaml; tests pass their own."""
    cache = load_llm_cache(cfg.llm_cache, cfg) if llm_cache is None else llm_cache
    classes = classify_all(snap.filings, cfg, cache)
    prices = PriceIndex(snap.prices, str(cfg.reaction.get("market_close_ist", "15:30")))
    scored = [score_filing(item, classes[item["id"]], cfg, prices) for item in snap.filings]
    attribute_reactions(scored, cfg)
    scored.sort(key=lambda s: s.item.get("datetime") or "", reverse=True)
    return scored


def build_alerts(
    snap: Snapshot,
    scored: list[ScoredFiling],
    cfg: PushConfig,
    start: datetime,
    end: datetime,
    overrides: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Alerts for (start, end]: the same window as the digest."""
    rules = effective_rules(cfg, overrides)
    close = str(cfg.reaction.get("market_close_ist", "15:30"))
    alerts: list[dict[str, Any]] = []
    for sym, rec in snap.prices.items():
        alerts.extend(price_alerts(sym, snap.names.get(sym, sym), rec, rules, start, end, close))
    alerts.extend(filing_alerts(scored, snap.names, rules, cfg, start, end))
    return sort_alerts(alerts)


def feed_document(snap: Snapshot, scored: list[ScoredFiling], cfg: PushConfig) -> dict[str, Any]:
    tiers = collections.Counter(s.tier for s in scored)
    cats = collections.Counter(s.cls.category for s in scored)
    methods = collections.Counter(s.cls.method for s in scored)
    times = [s.item["datetime"] for s in scored if s.item.get("datetime")]
    return {
        "generated_at": iso_ist(now_ist()),
        "snapshot_at": iso_ist(snap.snapshot_at),
        "covers": {"from": min(times) if times else None, "to": max(times) if times else None},
        "companies": snap.names,
        "rules": cfg.public_rules(),
        "counts": {
            "filings": len(scored),
            "by_tier": {t: tiers.get(t, 0) for t in TIERS},
            "by_category": dict(cats.most_common()),
            "by_method": dict(methods),
        },
        "items": [s.to_dict(cfg) for s in scored],
    }


def alerts_document(
    snap: Snapshot,
    alerts: list[dict[str, Any]],
    cfg: PushConfig,
    start: datetime,
    end: datetime,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`window` and `rules` record exactly what these alerts were evaluated over."""
    return {
        "generated_at": iso_ist(now_ist()),
        "snapshot_at": iso_ist(snap.snapshot_at),
        "window": {"from": iso_ist(start), "to": iso_ist(end)},
        "rules": effective_rules(cfg, overrides),
        "alerts": alerts,
    }


def write_outputs(seed_dir: Path, feed: dict[str, Any], alerts: dict[str, Any]) -> tuple[Path, Path]:
    out = seed_dir / "push"
    write_json(out / "feed.json", feed)
    write_json(out / "alerts.json", alerts)
    return out / "feed.json", out / "alerts.json"
