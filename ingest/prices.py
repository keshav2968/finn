"""End-of-day prices from Yahoo Finance plus the derived numbers alerts are built on.

We store numbers, not alerts: thresholds are the user's and are applied when the
app reads the data, so moving a slider re-evaluates instantly.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any, Callable

import pandas as pd

from .common import get_logger, iso_ist, now_ist, parse_hhmm

log = get_logger("prices")

REQUIRED_COLUMNS = ("Open", "High", "Low", "Close", "Volume")
RETURN_WINDOWS = {"1w": 5, "1m": 21, "3m": 63, "6m": 126, "1y": 252}
SESSIONS_PER_YEAR = 252

Fetcher = Callable[[str, date, float], pd.DataFrame]


class PriceFetchError(RuntimeError):
    pass


def yahoo_candidates(symbol: str) -> list[str]:
    """NSE first; BSE as a fallback for names Yahoo lists only on BSE."""
    return [f"{symbol}.NS", f"{symbol}.BO"]


def download_history(yahoo_symbol: str, start: date, timeout: float) -> pd.DataFrame:
    import yfinance as yf  # imported lazily so tests and offline runs don't need it

    # auto_adjust=False keeps Close as the traded (split-adjusted) price, so the
    # number matches what the exchange shows; dividends don't rewrite history.
    return yf.Ticker(yahoo_symbol).history(
        start=start.isoformat(),
        interval="1d",
        auto_adjust=False,
        actions=False,
        raise_errors=True,
        timeout=timeout,
    )


def clean_history(df: pd.DataFrame, now: datetime, eod_ready: str) -> pd.DataFrame:
    """Normalise to one row per trading date, oldest first, with today's partial bar removed."""
    if df is None or df.empty:
        return pd.DataFrame(columns=list(REQUIRED_COLUMNS))
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise PriceFetchError(f"missing columns {missing}")
    out = df.loc[:, list(REQUIRED_COLUMNS)].copy()
    # Yahoo's daily index is midnight in the exchange's timezone, so .date() is the trading day.
    out.index = pd.Index([pd.Timestamp(ts).date() for ts in out.index], name="date")
    out = out[pd.to_numeric(out["Close"], errors="coerce").notna()]
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out = out.astype({"Open": float, "High": float, "Low": float, "Close": float, "Volume": float})
    if len(out) and out.index[-1] == now.date() and now.time() < parse_hhmm(eod_ready):
        out = out.iloc[:-1]
    return out


def fetch_prices(
    symbol: str,
    history_days: int,
    eod_ready: str,
    timeout: float = 20,
    fetcher: Fetcher = download_history,
    now: datetime | None = None,
) -> tuple[pd.DataFrame, str]:
    now = now or now_ist()
    start = now.date() - timedelta(days=history_days)
    errors: list[str] = []
    for ysym in yahoo_candidates(symbol):
        try:
            df = clean_history(fetcher(ysym, start, timeout), now, eod_ready)
        except Exception as exc:  # noqa: BLE001 - try the next exchange suffix
            errors.append(f"{ysym}: {type(exc).__name__}: {exc}")
            continue
        if len(df) < 2:
            errors.append(f"{ysym}: only {len(df)} usable rows")
            continue
        return df, ysym
    raise PriceFetchError("; ".join(errors))


def _r(value: Any, digits: int) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return round(f, digits) if math.isfinite(f) else None


def _int(value: Any) -> int | None:
    f = _r(value, 0)
    return None if f is None else int(f)


def compute_metrics(
    df: pd.DataFrame,
    volume_avg_window: int = 20,
    volatility_window: int = 60,
    chart_days: int = 260,
) -> dict[str, Any]:
    """Derived daily series plus a 'latest' block.

    pct_change    close-to-close % move
    vol_ratio     volume / mean volume of the previous N sessions (today excluded,
                  so a spike doesn't dilute its own baseline)
    move_z        today's % move / std-dev of the previous M sessions' moves.
                  A 3% day is routine for a small cap and rare for HUL; z puts both
                  on one scale, so "unusual" can be volatility-aware.
    """
    close = df["Close"]
    volume = df["Volume"].where(df["Volume"] > 0)
    pct = close.pct_change() * 100

    vol_min = max(5, (volume_avg_window * 3) // 4)
    vol_avg = volume.shift(1).rolling(volume_avg_window, min_periods=vol_min).mean()
    vol_ratio = (df["Volume"] / vol_avg).replace([math.inf, -math.inf], float("nan"))

    std_min = max(20, (volatility_window * 2) // 3)
    move_std = pct.shift(1).rolling(volatility_window, min_periods=std_min).std()
    move_z = (pct / move_std).replace([math.inf, -math.inf], float("nan"))

    year = df.tail(SESSIONS_PER_YEAR)
    high_52w = year["High"].max()
    low_52w = year["Low"].min()
    last_close = close.iloc[-1]

    returns = {}
    for label, n in RETURN_WINDOWS.items():
        returns[label] = _r((last_close / close.iloc[-1 - n] - 1) * 100, 2) if len(close) > n else None

    tail = slice(-chart_days, None)
    series = {
        "date": [d.isoformat() for d in df.index[tail]],
        "open": [_r(v, 2) for v in df["Open"].iloc[tail]],
        "high": [_r(v, 2) for v in df["High"].iloc[tail]],
        "low": [_r(v, 2) for v in df["Low"].iloc[tail]],
        "close": [_r(v, 2) for v in close.iloc[tail]],
        "volume": [_int(v) for v in df["Volume"].iloc[tail]],
        "pct_change": [_r(v, 2) for v in pct.iloc[tail]],
        "vol_ratio": [_r(v, 2) for v in vol_ratio.iloc[tail]],
        "move_z": [_r(v, 2) for v in move_z.iloc[tail]],
    }
    latest = {
        "as_of": df.index[-1].isoformat(),
        "close": _r(last_close, 2),
        "prev_close": _r(close.iloc[-2], 2),
        "pct_change": _r(pct.iloc[-1], 2),
        "volume": _int(df["Volume"].iloc[-1]),
        "volume_avg": _int(vol_avg.iloc[-1]),
        "vol_ratio": _r(vol_ratio.iloc[-1], 2),
        "move_z": _r(move_z.iloc[-1], 2),
        "high_52w": _r(high_52w, 2),
        "low_52w": _r(low_52w, 2),
        "pct_from_52w_high": _r((last_close / high_52w - 1) * 100, 2) if high_52w else None,
        "returns_pct": returns,
    }
    return {
        "latest": latest,
        "series": series,
        "params": {"volume_avg_window": volume_avg_window, "volatility_window": volatility_window},
    }


def build_price_record(
    symbol: str,
    settings: dict[str, Any],
    timeout: float,
    fetcher: Fetcher = download_history,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or now_ist()
    df, yahoo_symbol = fetch_prices(
        symbol,
        history_days=int(settings.get("history_days", 400)),
        eod_ready=str(settings.get("eod_ready_ist", "16:00")),
        timeout=timeout,
        fetcher=fetcher,
        now=now,
    )
    metrics = compute_metrics(
        df,
        volume_avg_window=int(settings.get("volume_avg_window", 20)),
        volatility_window=int(settings.get("volatility_window", 60)),
        chart_days=int(settings.get("chart_days", 260)),
    )
    return {
        "symbol": symbol,
        "yahoo_symbol": yahoo_symbol,
        "currency": "INR",
        "fetched_at": iso_ist(now),
        "as_of": metrics["latest"]["as_of"],
        "rows_fetched": len(df),
        **metrics,
    }
