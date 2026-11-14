"""Score classified filings, sort them into tiers, and build a windowed digest.

score = category base (or its notice score)
      + text modifiers from config (e.g. CFO exit +, re-appointment -)
      + market reaction in the first session that could react to the filing
clamped to 0-100. Every part is kept with a human reason, so a card can say why
it ranks where it does.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable

from ingest.common import parse_hhmm

from .classify import NOTICE, Classification, filing_text, filing_time
from .config import TIERS, PushConfig

_MONTHS = r"jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|june?|july?|aug(ust)?|sep(t(ember)?)?|oct(ober)?|nov(ember)?|dec(ember)?"
_NORMALIZE_DROP = re.compile(rf"\b({_MONTHS})\b|\d+|[^a-z ]+")
TIER_RANK = {tier: i for i, tier in enumerate(TIERS)}  # needs_attention=0 ... routine=2


@dataclass(frozen=True)
class Reaction:
    date: str
    pct_change: float | None
    move_z: float | None
    vol_ratio: float | None


class PriceIndex:
    """Looks up the first trading session that could react to a filing."""

    def __init__(self, price_records: dict[str, dict[str, Any]], market_close: str = "15:30"):
        self.close = parse_hhmm(market_close)
        self.series: dict[str, dict[str, list]] = {}
        for symbol, rec in price_records.items():
            s = (rec or {}).get("series") or {}
            if s.get("date"):
                self.series[symbol] = s

    def reaction(self, symbol: str, when: datetime | None) -> Reaction | None:
        s = self.series.get(symbol)
        if s is None or when is None:
            return None
        dates = s["date"]
        day = when.date().isoformat()
        # Filed before the close: that session can react. After the close: the next one.
        i = bisect.bisect_left(dates, day) if when.time() < self.close else bisect.bisect_right(dates, day)
        if i >= len(dates):
            return None

        def at(key: str) -> float | None:
            values = s.get(key) or []
            return values[i] if i < len(values) else None

        return Reaction(dates[i], at("pct_change"), at("move_z"), at("vol_ratio"))


@dataclass
class ScoredFiling:
    item: dict[str, Any]
    cls: Classification
    score: float
    tier: str
    parts: list[tuple[str, float]]
    reaction: Reaction | None
    group_key: str
    headline: str
    reaction_parts: list[tuple[str, float]] = field(default_factory=list)
    pre_reaction: float = 0.0  # unclamped score before any market-reaction points

    @property
    def id(self) -> str:
        return self.item["id"]

    @property
    def when(self) -> datetime | None:
        return filing_time(self.item)

    def to_dict(self, cfg: PushConfig) -> dict[str, Any]:
        it = self.item
        return {
            "id": it["id"],
            "symbol": it["symbol"],
            "datetime": it.get("datetime"),
            "headline": self.headline,
            "title": it.get("title"),
            "detail": it.get("detail"),
            "pdf_url": it.get("pdf_url"),
            "bse_category": it.get("bse_category"),
            "bse_subcategory": it.get("bse_subcategory"),
            "category": self.cls.category,
            "category_label": cfg.pending_label if self.cls.pending else cfg.label(self.cls.category),
            "kind": self.cls.kind,
            "classified_by": {"method": self.cls.method, "rule": self.cls.rule_id},
            "pending_llm": self.cls.pending,
            "score": round(self.score, 1),
            "tier": self.tier,
            "reasons": [label for label, _ in self.parts],
            "score_parts": [{"label": label, "delta": delta} for label, delta in self.parts],
            "reaction": self.reaction.__dict__ if self.reaction else None,
            "group_key": self.group_key,
        }


def headline(item: dict[str, Any], cfg: PushConfig, cls: Classification | None = None) -> str:
    """The line a card shows: the title, unless it is boilerplate and BSE gave a
    detail line. BSE truncates `detail` with "...." and keeps the full text in `more`;
    a boilerplate opening ("Disclosure under Regulation 30 ... 2015 -") is dropped.
    A filing the LLM classified, whose title is boilerplate, shows the LLM's summary."""
    title = " ".join((item.get("title") or "").split())
    detail = " ".join((item.get("detail") or "").split())
    more = " ".join((item.get("more") or "").split())
    if more and detail.rstrip(".… ") and more.startswith(detail.rstrip(".… ")):
        detail = more
    if cls is not None and cls.summary and (not title or cfg.generic_title.search(title)):
        return cls.summary
    if not detail or not cfg.generic_title.search(title):
        return title or detail
    trimmed = cfg.boilerplate_prefix.sub("", detail, count=1).strip()
    return trimmed[:1].upper() + trimmed[1:] if trimmed else detail


def normalize_title(text: str) -> str:
    return " ".join(_NORMALIZE_DROP.sub(" ", text.lower()).split())[:160]


def group_key(item: dict[str, Any], cls: Classification, cfg: PushConfig) -> str:
    """Filings with the same key collapse into one card.

    Pending filings never group: we don't know what they say.
    Same-day categories (results) group everything a company filed that day.
    Otherwise: same company, category and title+detail with numbers/dates removed.
    """
    sym = item["symbol"]
    if cls.pending:
        return f"{sym}|pending|{item['id']}"
    if cls.category in cfg.same_day_categories:
        return f"{sym}|{cls.category}|{(item.get('datetime') or '')[:10]}"
    text = f"{item.get('title') or ''} {item.get('detail') or ''}"
    return f"{sym}|{cls.category}|{normalize_title(text)}"


def _fmt_move(r: Reaction) -> str:
    direction = "up" if (r.pct_change or 0) >= 0 else "down"
    z = f" ({abs(r.move_z):.1f}σ)" if r.move_z is not None else ""
    return f"Stock {direction} {abs(r.pct_change or 0):.1f}%{z} on {r.date}"


def score_filing(
    item: dict[str, Any], cls: Classification, cfg: PushConfig, prices: PriceIndex | None = None
) -> ScoredFiling:
    text = filing_text(item)
    if cls.pending:
        parts: list[tuple[str, float]] = [("Not yet classified: read the filing", float(cfg.pending_score))]
    else:
        cat = cfg.categories[cls.category]
        if cls.kind == NOTICE:
            parts = [(f"{cat.label} (advance notice)", float(cat.notice))]
        else:
            parts = [(cat.label, float(cat.base))]
        for m in cfg.modifiers:
            if m.category == cls.category and m.text.search(text) and not (m.unless and m.unless.search(text)):
                parts.append((m.reason, float(m.delta)))

    reaction = prices.reaction(item["symbol"], filing_time(item)) if prices else None
    reaction_parts: list[tuple[str, float]] = []
    rx = cfg.reaction
    # Advance notices (a meeting date, a record date) don't move a stock: no reaction points,
    # and they never take a move away from the filing that did.
    if reaction and cls.category not in set(rx.get("skip_categories") or []) and not cls.pending and cls.kind != NOTICE:
        z_min, vol_min = rx.get("move_z"), rx.get("vol_ratio")
        if z_min is not None and reaction.move_z is not None and abs(reaction.move_z) >= float(z_min):
            reaction_parts.append((_fmt_move(reaction), float(rx.get("move_bonus", 0))))
        if vol_min is not None and reaction.vol_ratio is not None and reaction.vol_ratio >= float(vol_min):
            reaction_parts.append(
                (f"Volume {reaction.vol_ratio:.1f}× its 20-day average on {reaction.date}", float(rx.get("volume_bonus", 0)))
            )

    all_parts = parts + reaction_parts
    score = _clamp(sum(delta for _, delta in all_parts))
    return ScoredFiling(
        item,
        cls,
        score,
        cfg.tier_for(score),
        all_parts,
        reaction,
        group_key(item, cls, cfg),
        headline(item, cfg, cls),
        reaction_parts,
        sum(delta for _, delta in parts),
    )


def _clamp(x: float) -> float:
    return max(0.0, min(100.0, x))


def attribute_reactions(scored: list[ScoredFiling], cfg: PushConfig) -> None:
    """One price move, one owner. Among filings that share a symbol and reaction
    session, the move is credited to the most market-moving kind of filing (highest
    category base, so results beat a board change on results day), then the highest
    pre-reaction score; exact ties share it. The others keep a zero-point note so
    the card still mentions the move."""
    sessions: dict[tuple[str, str], list[ScoredFiling]] = {}
    for s in scored:
        if s.reaction_parts and s.reaction:
            sessions.setdefault((s.item["symbol"], s.reaction.date), []).append(s)
    for group in sessions.values():
        def rank(x: ScoredFiling) -> tuple[float, float]:
            return (float(cfg.categories[x.cls.category].base), x.pre_reaction)

        top = max(rank(x) for x in group)
        for s in group:
            if rank(s) >= top:
                continue
            keep = [p for p in s.parts if p not in s.reaction_parts]
            notes = [(f"{label} (credited to a bigger filing that session)", 0.0) for label, _ in s.reaction_parts]
            s.parts = keep + notes
            s.reaction_parts = []
            s.score = _clamp(sum(d for _, d in s.parts))
            s.tier = cfg.tier_for(s.score)


@dataclass
class Card:
    """One card in the digest: a representative filing plus any repeats it absorbed."""

    lead: ScoredFiling
    members: list[ScoredFiling] = field(default_factory=list)

    @property
    def tier(self) -> str:
        return self.lead.tier

    def to_dict(self, cfg: PushConfig) -> dict[str, Any]:
        out = self.lead.to_dict(cfg)
        out["repeats"] = len(self.members)
        out["member_ids"] = [m.id for m in self.members]
        return out


_METHOD_RANK = {"rule": 0, "llm": 1, "context": 2, "pending": 3}


def _sort_key(s: ScoredFiling) -> tuple:
    return (-s.score, -(s.when.timestamp() if s.when else 0))


def _lead_key(s: ScoredFiling, same_day: bool) -> tuple:
    """Highest score leads. Ties: on a same-day card the earliest rule-matched filing
    (the results themselves, not the later press release); otherwise the newest."""
    ts = s.when.timestamp() if s.when else 0
    if same_day:
        return (-s.score, _METHOD_RANK.get(s.cls.method, 9), ts)
    return (-s.score, -ts)


def build_cards(scored: Iterable[ScoredFiling], cfg: PushConfig | None = None) -> list[Card]:
    same_day_categories = cfg.same_day_categories if cfg else set()
    groups: dict[str, list[ScoredFiling]] = {}
    for s in scored:
        groups.setdefault(s.group_key, []).append(s)
    cards = []
    for members in groups.values():
        same_day = members[0].cls.category in same_day_categories and not members[0].cls.pending
        members.sort(key=lambda m: _lead_key(m, same_day))
        cards.append(Card(members[0], members))
    cards.sort(key=lambda c: _sort_key(c.lead))
    return cards


def in_window(s: ScoredFiling, start: datetime, end: datetime) -> bool:
    return s.when is not None and start < s.when <= end


def build_digest(scored: Iterable[ScoredFiling], start: datetime, end: datetime, cfg: PushConfig) -> dict[str, Any]:
    window = [s for s in scored if in_window(s, start, end)]
    cards = build_cards(window, cfg)
    by_tier: dict[str, list[Card]] = {t: [] for t in TIERS}
    for card in cards:
        by_tier[card.tier].append(card)
    routine = by_tier["routine"]
    return {
        "window": {"from": start.isoformat(), "to": end.isoformat()},
        "filings": len(window),
        "needs_attention": [c.to_dict(cfg) for c in by_tier["needs_attention"]],
        "worth_knowing": [c.to_dict(cfg) for c in by_tier["worth_knowing"]],
        "routine": {
            "cards": len(routine),
            "filings": sum(len(c.members) for c in routine),
            "items": [c.to_dict(cfg) for c in routine],
        },
    }


def parse_window(text: str) -> timedelta:
    """'24h', '7d', '30d' -> timedelta."""
    m = re.fullmatch(r"\s*(\d+)\s*([hd])\s*", text or "")
    if not m:
        raise ValueError(f"window must look like 24h or 7d, got {text!r}")
    n = int(m.group(1))
    return timedelta(hours=n) if m.group(2) == "h" else timedelta(days=n)


def tier_at_least(tier: str, minimum: str) -> bool:
    return TIER_RANK[tier] <= TIER_RANK[minimum]
