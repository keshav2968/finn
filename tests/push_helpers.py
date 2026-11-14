"""Shared loaders for the push-side tests (real filings and prices, frozen)."""

import json
from functools import lru_cache

from conftest import FIXTURES

from push.config import load_push_config


@lru_cache(maxsize=1)
def cfg():
    return load_push_config()


@lru_cache(maxsize=1)
def _filings():
    return json.loads((FIXTURES / "push_filings_sample.json").read_text(encoding="utf-8"))["items"]


def filings():
    return [dict(it) for it in _filings()]


@lru_cache(maxsize=1)
def _prices():
    return json.loads((FIXTURES / "push_prices_sample.json").read_text(encoding="utf-8"))["prices"]


def prices():
    return json.loads(json.dumps(_prices()))


def find(symbol, needle, day=None, sub=None):
    """The one fixture filing for `symbol` whose title/detail/more contains `needle`
    (optionally on `day`, optionally with BSE subcategory `sub`)."""
    hits = [
        it
        for it in filings()
        if it["symbol"] == symbol
        and (day is None or it["datetime"].startswith(day))
        and (sub is None or it.get("bse_subcategory") == sub)
        and needle.lower() in " ".join([it["title"], it.get("detail") or "", it.get("more") or ""]).lower()
    ]
    assert len(hits) == 1, f"{symbol}/{needle}/{day}/{sub}: expected 1 fixture filing, found {len(hits)}"
    return hits[0]
