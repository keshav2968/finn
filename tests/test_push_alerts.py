from datetime import datetime, timedelta

import pytest
from push_helpers import cfg, filings, prices

from ingest.common import IST
from push.alerts import effective_rules, filing_alerts, price_alerts, session_close, sort_alerts
from push.feed import Snapshot, score_snapshot

END = datetime(2026, 11, 14, 15, 6, tzinfo=IST)
WEEK = END - timedelta(days=7)
ALL = datetime(2026, 1, 1, tzinfo=IST)


def record(pct, vol, z, dates=None):
    dates = dates or [f"2026-11-{d:02d}" for d in range(3, 3 + len(pct))]
    return {
        "params": {"volume_avg_window": 20},
        "series": {"date": dates, "close": [100.0] * len(dates), "pct_change": pct, "vol_ratio": vol, "move_z": z},
    }


def rules(**over):
    return effective_rules(cfg(), over)


def test_reason_strings_and_severity():
    rec = record([0.5, -5.2], [1.0, 3.4], [0.3, -2.9])
    [a] = price_alerts("INFY", "Infosys", rec, rules(), ALL, END)
    assert a["reasons"] == ["Down 5.2% on the day", "Volume 3.4× its 20-day average"]
    assert a["reason"] == "Down 5.2% on the day; Volume 3.4× its 20-day average"
    assert a["triggers"] == ["price_move", "volume_spike"] and a["severity"] == "high"
    assert a["id"] == "INFY:2026-11-04:price" and a["metrics"]["vol_ratio"] == 3.4


def test_volatility_alert_is_off_by_default_and_on_when_set():
    rec = record([2.0], [1.0], [3.1])
    assert price_alerts("X", "X", rec, rules(), ALL, END) == []
    [a] = price_alerts("X", "X", rec, rules(move_z=2.5), ALL, END)
    assert a["reasons"] == ["3.1σ move for this stock"] and a["severity"] == "normal"


def test_thresholds_are_inclusive_and_none_disables():
    rec = record([4.0, 3.99], [2.0, 1.99], [None, None])
    assert [a["date"] for a in price_alerts("X", "X", rec, rules(), ALL, END)] == ["2026-11-03"]
    assert price_alerts("X", "X", rec, rules(price_move_pct=None, volume_ratio=None), ALL, END) == []


def test_sessions_count_by_their_close_inside_the_window():
    rec = record([9.0, 9.0, None], [1.0, 1.0, None], [None] * 3, dates=["2026-11-06", "2026-11-07", "2026-11-12"])
    start = datetime(2026, 11, 7, 15, 6, tzinfo=IST)
    # 6 Nov closed before the window opened; 7 Nov's 15:30 close is inside it; missing values never fire
    assert [a["date"] for a in price_alerts("X", "X", rec, rules(), start, END)] == ["2026-11-07"]
    assert session_close("2026-11-07", "15:30") == datetime(2026, 11, 7, 15, 30, tzinfo=IST)


def test_real_price_records_over_a_week():
    p = prices()
    elecon = price_alerts("ELECON", "Elecon", p["ELECON"], rules(), WEEK, END)
    assert [(a["date"], a["reason"]) for a in elecon] == [("2026-11-12", "Up 5.8% on the day")]
    # HDFC Bank's 2.3x volume day was 6 Nov: outside a 7-day window ending 14 Nov 15:06
    assert price_alerts("HDFCBANK", "HDFC Bank", p["HDFCBANK"], rules(), WEEK, END) == []
    ten_days = price_alerts("HDFCBANK", "HDFC Bank", p["HDFCBANK"], rules(), END - timedelta(days=10), END)
    assert ("2026-11-06", "Volume 2.3× its 20-day average") in [(a["date"], a["reason"]) for a in ten_days]


@pytest.fixture(scope="module")
def scored():
    return score_snapshot(Snapshot({}, filings(), prices(), {}, END), cfg(), llm_cache={})


def test_filing_alerts_need_category_and_minimum_score(scored):
    out = filing_alerts(scored, {"BAJFINANCE": "Bajaj Finance"}, rules(), cfg(), WEEK, END)
    assert all(a["category"] in cfg().alerts["filing_categories"] for a in out)
    assert all(a["score"] >= 60 for a in out)
    assert all(WEEK < datetime.fromisoformat(a["date"]) <= END for a in out)
    reasons = " | ".join(a["reason"] for a in out)
    assert "Fund raise: PI 2026" in reasons
    assert "Re-appointment" not in reasons          # management change at 50: in the feed, no ping
    assert "Half Yearly Report" not in reasons      # results category but 40
    warrants = next(a for a in out if "PI 2026 - Special Committee" in a["reason"])
    assert warrants["severity"] == "high" and warrants["name"] == "Bajaj Finance"


def test_filing_alert_overrides_and_repeats(scored):
    lower = filing_alerts(scored, {}, rules(filing_min_score=50), cfg(), WEEK, END)
    assert any("Re-appointment" in a["reason"] for a in lower)
    assert filing_alerts(scored, {}, rules(filing_categories=["capex"]), cfg(), WEEK, END) == []
    cp = filing_alerts(scored, {}, rules(filing_categories=["fund_raise"], filing_min_score=None), cfg(), ALL, END)
    titan_cp = [a for a in cp if a["symbol"] == "TITAN"]
    assert len(titan_cp) == 1 and len(titan_cp[0]["member_ids"]) == 2  # two repayments, one ping


def test_sort_newest_first():
    alerts = [
        {"date": "2026-11-06", "severity": "normal"},
        {"date": "2026-11-12T10:00:00+05:30", "severity": "normal"},
        {"date": "2026-11-12", "severity": "high"},
    ]
    assert [a["date"] for a in sort_alerts(alerts)] == ["2026-11-12", "2026-11-12T10:00:00+05:30", "2026-11-06"]
