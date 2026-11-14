import json
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from ingest.common import IST, json_safe
from ingest.prices import PriceFetchError, build_price_record, clean_history, compute_metrics, fetch_prices

SETTINGS = {"history_days": 400, "chart_days": 260, "volume_avg_window": 20, "volatility_window": 60, "eod_ready_ist": "16:00"}


def yahoo_like(n=300, last_volume=3000.0, end="2026-11-13"):
    """Shape of yfinance daily history: tz-aware midnight index in Asia/Kolkata."""
    idx = pd.bdate_range(end=end, periods=n, tz="Asia/Kolkata")
    rng = np.random.default_rng(7)
    close = 100 * np.cumprod(1 + rng.normal(0, 0.01, n))
    vol = np.full(n, 1000.0)
    vol[-1] = last_volume
    return pd.DataFrame(
        {
            "Open": close * 0.995,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Adj Close": close,
            "Volume": vol,
        },
        index=idx,
    )


def test_metrics_volume_ratio_excludes_today():
    df = clean_history(yahoo_like(), datetime(2026, 11, 14, 9, 0, tzinfo=IST), "16:00")
    m = compute_metrics(df)
    assert m["latest"]["vol_ratio"] == 3.0  # 3000 vs a clean 1000 baseline
    assert m["latest"]["volume_avg"] == 1000
    assert m["latest"]["as_of"] == "2026-11-13"


def test_metrics_values():
    df = clean_history(yahoo_like(), datetime(2026, 11, 14, 9, 0, tzinfo=IST), "16:00")
    m = compute_metrics(df)
    close = df["Close"]
    expected_pct = round((close.iloc[-1] / close.iloc[-2] - 1) * 100, 2)
    assert m["latest"]["pct_change"] == expected_pct
    assert m["latest"]["high_52w"] == round(df["High"].tail(252).max(), 2)
    assert m["latest"]["returns_pct"]["1w"] == round((close.iloc[-1] / close.iloc[-6] - 1) * 100, 2)
    assert m["latest"]["move_z"] is not None
    assert len(m["series"]["date"]) == 260
    assert m["series"]["date"][-1] == "2026-11-13"
    # too little history for the rolling windows: None (not NaN, not a misleading number)
    short = compute_metrics(df.head(10))
    assert short["latest"]["vol_ratio"] is None  # needs 15 prior sessions
    assert short["latest"]["move_z"] is None
    assert short["latest"]["returns_pct"]["1m"] is None
    assert short["latest"]["returns_pct"]["1w"] is not None
    ok = compute_metrics(df.head(16))
    assert ok["latest"]["vol_ratio"] is not None


def test_partial_bar_dropped_only_before_eod():
    raw = yahoo_like(end="2026-11-13")
    during = clean_history(raw, datetime(2026, 11, 13, 11, 0, tzinfo=IST), "16:00")
    after = clean_history(raw, datetime(2026, 11, 13, 17, 0, tzinfo=IST), "16:00")
    assert during.index[-1].isoformat() == "2026-11-12"
    assert after.index[-1].isoformat() == "2026-11-13"


def test_nan_close_rows_and_duplicates_removed():
    raw = yahoo_like(n=30)
    raw.iloc[5, raw.columns.get_loc("Close")] = np.nan
    raw = pd.concat([raw, raw.tail(1)])
    df = clean_history(raw, datetime(2026, 11, 14, 9, 0, tzinfo=IST), "16:00")
    assert len(df) == 29
    assert df.index.is_unique


def test_falls_back_to_bse_suffix():
    seen = []

    def fetcher(ysym, start, timeout):
        seen.append(ysym)
        if ysym.endswith(".NS"):
            raise RuntimeError("YFPricesMissingError: possibly delisted")
        return yahoo_like(n=60)

    df, used = fetch_prices("ODDCO", 400, "16:00", fetcher=fetcher, now=datetime(2026, 11, 14, 9, tzinfo=IST))
    assert used == "ODDCO.BO" and seen == ["ODDCO.NS", "ODDCO.BO"]
    assert len(df) == 60


def test_both_suffixes_failing_reports_both():
    def fetcher(ysym, start, timeout):
        raise RuntimeError(f"no data for {ysym}")

    with pytest.raises(PriceFetchError) as exc:
        fetch_prices("NOPE", 400, "16:00", fetcher=fetcher, now=datetime(2026, 11, 14, 9, tzinfo=IST))
    assert "NOPE.NS" in str(exc.value) and "NOPE.BO" in str(exc.value)


def test_record_is_strict_json():
    raw = yahoo_like()
    raw.iloc[-3, raw.columns.get_loc("Volume")] = 0  # zero-volume session
    rec = build_price_record(
        "TEST", SETTINGS, timeout=5, fetcher=lambda *a: raw, now=datetime(2026, 11, 14, 9, tzinfo=IST)
    )
    text = json.dumps(json_safe(rec), allow_nan=False)  # raises if any NaN slipped through
    assert '"yahoo_symbol": "TEST.NS"' in text
    assert rec["series"]["vol_ratio"][-3] == 0.0
