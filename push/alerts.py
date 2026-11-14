"""Triggered alerts: unusual end-of-day moves and material filings.

Alerts cover the same window as the digest. A trading session belongs to the window
if its close (market_close_ist) falls inside (start, end]; a filing if its timestamp
does. Thresholds come from config/push.yaml `alerts` (the app's defaults); `overrides`
apply a user's own settings. Each alert stores the reasons it fired, e.g.
"Volume 3.4× its 20-day average".
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable

from ingest.common import IST, parse_hhmm

from .config import PushConfig
from .priority import ScoredFiling, build_cards


def effective_rules(cfg: PushConfig, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Config defaults with the user's overrides on top. A None threshold turns that check off."""
    rules = dict(cfg.alerts)
    rules.update(overrides or {})
    return rules


def session_close(day: str, market_close: str) -> datetime:
    return datetime.combine(date.fromisoformat(day), parse_hhmm(market_close), tzinfo=IST)


def price_alerts(
    symbol: str,
    name: str,
    price_record: dict[str, Any],
    rules: dict[str, Any],
    start: datetime,
    end: datetime,
    market_close: str = "15:30",
) -> list[dict[str, Any]]:
    """Moves and volume spikes in sessions that closed inside (start, end]."""
    series = (price_record or {}).get("series") or {}
    dates = series.get("date") or []
    window = int(((price_record or {}).get("params") or {}).get("volume_avg_window") or 20)
    move_pct = rules.get("price_move_pct")
    vol_x = rules.get("volume_ratio")
    z_min = rules.get("move_z")
    closes = series.get("close") or []

    out = []
    for i, day in enumerate(dates):
        if not start < session_close(day, market_close) <= end:
            continue
        pct = _get(series, "pct_change", i)
        vr = _get(series, "vol_ratio", i)
        z = _get(series, "move_z", i)
        triggers, reasons = [], []
        if move_pct is not None and pct is not None and abs(pct) >= float(move_pct):
            triggers.append("price_move")
            reasons.append(f"{'Up' if pct > 0 else 'Down'} {abs(pct):.1f}% on the day")
        if z_min is not None and z is not None and abs(z) >= float(z_min):
            triggers.append("move_z")
            reasons.append(f"{abs(z):.1f}σ move for this stock")
        if vol_x is not None and vr is not None and vr >= float(vol_x):
            triggers.append("volume_spike")
            reasons.append(f"Volume {vr:.1f}× its {window}-day average")
        if not triggers:
            continue
        out.append(
            {
                "id": f"{symbol}:{day}:price",
                "type": "price",
                "symbol": symbol,
                "name": name,
                "date": day,
                "triggers": triggers,
                "reasons": reasons,
                "reason": "; ".join(reasons),
                "severity": "high" if len(triggers) > 1 else "normal",
                "metrics": {
                    "close": closes[i] if i < len(closes) else None,
                    "pct_change": pct,
                    "vol_ratio": vr,
                    "move_z": z,
                },
            }
        )
    return out


def filing_alerts(
    scored: Iterable[ScoredFiling],
    names: dict[str, str],
    rules: dict[str, Any],
    cfg: PushConfig,
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    """One alert per card (repeats collapsed): chosen categories, score >= filing_min_score."""
    categories = set(rules.get("filing_categories") or [])
    min_score = rules.get("filing_min_score")
    eligible = [
        s
        for s in scored
        if s.cls.category in categories
        and not s.cls.pending
        and (min_score is None or s.score >= float(min_score))
        and s.when is not None
        and start < s.when <= end
    ]
    out = []
    for card in build_cards(eligible, cfg):
        lead = card.lead
        reason = f"{cfg.label(lead.cls.category)}: {lead.headline}"
        out.append(
            {
                "id": f"{lead.item['symbol']}:{lead.id}:filing",
                "type": "filing",
                "symbol": lead.item["symbol"],
                "name": names.get(lead.item["symbol"], lead.item["symbol"]),
                "date": lead.item.get("datetime"),
                "triggers": ["category"],
                "reasons": [reason] + [r for r, _ in lead.parts[1:]],
                "reason": reason,
                "severity": "high" if lead.tier == "needs_attention" else "normal",
                "filing_id": lead.id,
                "member_ids": [m.id for m in card.members],
                "category": lead.cls.category,
                "tier": lead.tier,
                "score": round(lead.score, 1),
                "pdf_url": lead.item.get("pdf_url"),
            }
        )
    return out


def _get(series: dict[str, list], key: str, i: int) -> float | None:
    values = series.get(key) or []
    return values[i] if i < len(values) else None


def sort_alerts(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Newest first; within the same day, high severity first."""
    return sorted(alerts, key=lambda a: (str(a.get("date") or "")[:10], a["severity"] == "high", str(a.get("date"))), reverse=True)
