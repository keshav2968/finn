from datetime import datetime, timedelta

import pytest
from push_helpers import cfg, filings, find, prices

from ingest.common import IST
from push.classify import classify_all
from push.feed import Snapshot, score_snapshot
from push.priority import (
    PriceIndex,
    build_cards,
    build_digest,
    headline,
    normalize_title,
    parse_window,
    score_filing,
)

SNAP_AT = datetime(2026, 11, 14, 15, 6, tzinfo=IST)


@pytest.fixture(scope="module")
def scored():
    snap = Snapshot({}, filings(), prices(), {}, SNAP_AT)
    return {s.id: s for s in score_snapshot(snap, cfg(), llm_cache={})}


def S(scored, symbol, needle, day=None, sub=None):
    return scored[find(symbol, needle, day, sub)["id"]]


@pytest.mark.parametrize(
    "symbol, needle, day, score, tier",
    [
        ("HDFCBANK", "Change in Managing Director and Chief Executive", None, 85, "needs_attention"),
        ("HDFCBANK", "Change in Directorate", "2026-11-13", 50, "worth_knowing"),   # re-appointment of a WTD
        ("FEDERALBNK", "Rajesh Varrier", None, 45, "worth_knowing"),                # independent director
        ("BAJFINANCE", "approved the issue of 5,74,25,740 Warrants", None, 75, "needs_attention"),
        ("BAJFINANCE", "Non-Convertible Debentures on Private Placement basis", "2026-10-30", 15, "routine"),
        ("BAJFINANCE", "Submission Of Half Yearly Report", None, 40, "worth_knowing"),
        ("TITAN", "Wholly Owned", None, 45, "worth_knowing"),
        ("INFY", "To Announce Second Quarter Results", None, 25, "routine"),
        ("ELECON", "Record Date For Purpose", None, 15, "routine"),
        ("FEDERALBNK", "Disclosure Under Regulation 30 Of SEBI (LODR) Regulations 2015", "2026-11-13", 40, "worth_knowing"),
        ("LT", "Noida Metro", None, 55, "worth_knowing"),
        ("POLYCAB", "Intimation of NCLT order", None, 70, "needs_attention"),
    ],
)
def test_scores_and_tiers(scored, symbol, needle, day, score, tier):
    s = S(scored, symbol, needle, day)
    assert (s.score, s.tier) == (score, tier), s.parts


def test_reasons_explain_the_score(scored):
    s = S(scored, "HDFCBANK", "Change in Managing Director and Chief Executive")
    assert [label for label, _ in s.parts] == ["Management change", "Top-level role", "CEO change"]
    assert sum(d for _, d in s.parts) == s.score
    pending = S(scored, "FEDERALBNK", "Disclosure Under Regulation 30 Of SEBI (LODR) Regulations 2015", "2026-11-13")
    assert pending.to_dict(cfg())["category_label"] == "Unclassified" and pending.to_dict(cfg())["pending_llm"]


def test_results_day_move_is_credited_once(scored):
    """Titan filed results and Noel Tata's retirement after the 5 Nov close; the stock
    rose 3.4% (2.6σ) on 5.5x volume on 6 Nov. Results own the move."""
    results = S(scored, "TITAN", "Outcome Of The Board Meeting In Accordance", "2026-11-05", "Financial Results")
    retirement = S(scored, "TITAN", "Noel")
    assert results.reaction.date == retirement.reaction.date == "2026-11-06"
    assert results.score == 100 and any("Stock up 3.4% (2.6σ)" in label for label, _ in results.parts)
    assert retirement.score == 85
    assert any("credited to a bigger filing" in label and delta == 0 for label, delta in retirement.parts)


def test_price_index_sessions():
    idx = PriceIndex(prices(), "15:30")
    before = idx.reaction("TITAN", datetime(2026, 11, 5, 11, 0, tzinfo=IST))
    after = idx.reaction("TITAN", datetime(2026, 11, 5, 17, 0, tzinfo=IST))
    weekend = idx.reaction("TITAN", datetime(2026, 11, 8, 10, 0, tzinfo=IST))  # Sunday
    assert (before.date, after.date, weekend.date) == ("2026-11-05", "2026-11-06", "2026-11-09")
    assert after.pct_change == 3.42 and after.vol_ratio == 5.55
    assert idx.reaction("TITAN", datetime(2026, 11, 13, 18, 0, tzinfo=IST)) is None  # no later session yet
    assert idx.reaction("NOPE", datetime(2026, 11, 5, 11, 0, tzinfo=IST)) is None


def test_reaction_bonus_needs_thresholds():
    item = find("HDFCBANK", "Grant Of Stock Options")
    cls = classify_all([item], cfg())[item["id"]]
    s = score_filing(item, cls, cfg(), PriceIndex(prices()))
    assert s.score == 0 and not s.reaction_parts  # routine category: no reaction points


def test_repeats_collapse_into_one_card(scored):
    """Titan's two commercial-paper repayments (5 and 12 Nov) are one card, led by the newer."""
    cp = [s for s in scored.values() if s.item["symbol"] == "TITAN" and "Commercial Paper" in s.item["title"]]
    assert len(cp) == 2
    cards = build_cards(cp, cfg())
    assert len(cards) == 1 and len(cards[0].members) == 2
    assert cards[0].lead.item["datetime"].startswith("2026-11-12")
    assert cards[0].to_dict(cfg())["repeats"] == 2


def test_results_day_bundle_is_one_card_led_by_a_rule_match(scored):
    day = [s for s in scored.values() if s.item["symbol"] == "ELECON" and s.item["datetime"].startswith("2026-10-14") and s.cls.category == "results"]
    cards = build_cards(day, cfg())
    assert len(cards) == 1 and len(cards[0].members) == len(day) >= 3
    assert cards[0].lead.cls.method == "rule"


def test_pending_filings_never_group(scored):
    pending = [s for s in scored.values() if s.cls.pending]
    assert len(build_cards(pending, cfg())) == len(pending)


def test_digest_window_and_tiers(scored):
    start = datetime(2026, 11, 5, 0, 0, tzinfo=IST)
    d = build_digest(scored.values(), start, start + timedelta(days=1), cfg())
    na = [(c["symbol"], c["category"]) for c in d["needs_attention"]]
    assert ("TITAN", "results") in na and ("TITAN", "management_change") in na
    assert d["needs_attention"][0]["score"] >= d["needs_attention"][-1]["score"]
    assert d["routine"]["filings"] >= d["routine"]["cards"]
    total = sum(c["repeats"] for c in d["needs_attention"] + d["worth_knowing"] + d["routine"]["items"])
    assert total == d["filings"]


def test_window_bounds_exclude_start_include_end(scored):
    s = S(scored, "TITAN", "Noel")
    t = s.when
    assert build_digest([s], t, t + timedelta(hours=1), cfg())["filings"] == 0
    assert build_digest([s], t - timedelta(hours=1), t, cfg())["filings"] == 1


def test_headlines():
    c = cfg()
    ceo = find("HDFCBANK", "Change in Managing Director and Chief Executive")
    assert headline(ceo, c) == "Change in Managing Director and Chief Executive Officer of the Bank"
    varrier = find("FEDERALBNK", "Rajesh Varrier")
    assert headline(varrier, c).startswith("Appointment of Mr. Rajesh Varrier")
    noida = find("LT", "Noida Metro")
    assert "Noida" in headline(noida, c)
    plain = find("INFY", "Pocharam")
    assert headline(plain, c) == plain["title"]


def test_parse_window_and_normalize():
    assert parse_window("24h") == timedelta(hours=24) and parse_window("7d") == timedelta(days=7)
    with pytest.raises(ValueError):
        parse_window("week")
    assert normalize_title("Outcome Of PI 2026 - Meeting Held On 10 November 2026") == "outcome of pi meeting held on"


def test_advance_notices_never_earn_reaction_points():
    """KPIT's results-meeting notice (15 Oct) must not collect the 16 Oct move."""
    notice = {
        "id": "notice-1", "symbol": "TITAN", "datetime": "2026-11-05T17:00:00+05:30",
        "title": "Board Meeting Intimation for Financial Results", "detail": None, "more": None,
        "bse_category": "Board Meeting", "bse_subcategory": "Board Meeting",
    }
    cls = classify_all([notice], cfg())[notice["id"]]
    assert (cls.category, cls.kind) == ("results", "notice")
    s = score_filing(notice, cls, cfg(), PriceIndex(prices()))  # 6 Nov: +3.4%, 2.6σ, 5.5× volume
    assert s.reaction is not None and not s.reaction_parts and s.score == cfg().categories["results"].notice
