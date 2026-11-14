"""End to end: a seed folder built from the frozen fixtures -> scripts/build_push.py."""

import importlib.util
import json
from collections import defaultdict
from dataclasses import replace

import pytest
from conftest import ROOT
from push_helpers import cfg as push_cfg
from push_helpers import filings, prices

from ingest.common import write_json
from ingest.config import load_config

spec = importlib.util.spec_from_file_location("build_push", ROOT / "scripts" / "build_push.py")
build_push = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_push)


@pytest.fixture
def seed(tmp_path, monkeypatch):
    seed_dir = tmp_path / "seed"
    by_symbol = defaultdict(list)
    for it in filings():
        by_symbol[it["symbol"]].append(it)
    # an ad-hoc research company that is not held: its filings must stay out of the push feed
    outsider = dict(filings()[0], id="outsider-1", symbol="TCS", title="Financial Results For The Quarter")
    by_symbol["TCS"].append(outsider)
    companies = [{"symbol": s, "name": s.title(), "in_portfolio": s != "TCS"} for s in sorted(by_symbol)]
    write_json(seed_dir / "manifest.json", {"generated_at": "2026-11-14T15:06:37+05:30", "companies": companies})
    for sym, items in by_symbol.items():
        write_json(seed_dir / "filings" / f"{sym}.json", {"symbol": sym, "items": items})
    for sym, rec in prices().items():
        write_json(seed_dir / "prices" / f"{sym}.json", rec)

    base = load_config()
    base.settings = {**base.settings, "paths": {"seed_dir": str(seed_dir), "cache_dir": str(tmp_path / "cache")}}
    monkeypatch.setattr(build_push, "load_config", lambda: base)
    monkeypatch.setattr(build_push, "load_push_config", lambda: replace(push_cfg(), llm_cache=tmp_path / "no-llm-cache.json"))
    return seed_dir


def strict_json(path):
    def no_nan(token):
        raise ValueError(f"non-JSON constant {token}")
    return json.loads(path.read_text("utf-8"), parse_constant=no_nan)


def test_build_writes_feed_and_alerts(seed, capsys):
    assert build_push.main(["--window", "7d"]) == 0
    out = capsys.readouterr().out
    for heading in ("NEEDS ATTENTION", "WORTH KNOWING", "ROUTINE:", "ALERTS", "CLASSIFIER"):
        assert heading in out
    feed = strict_json(seed / "push" / "feed.json")
    alerts = strict_json(seed / "push" / "alerts.json")
    assert feed["counts"]["filings"] == len(filings())          # TCS (not held) excluded
    assert all(i["symbol"] != "TCS" for i in feed["items"])
    assert set(feed["counts"]["by_tier"]) == {"needs_attention", "worth_knowing", "routine"}
    assert feed["rules"]["alerts"]["price_move_pct"] == 4.0
    assert feed["snapshot_at"] == "2026-11-14T15:06:37+05:30"
    first = feed["items"][0]
    for key in ("headline", "category", "category_label", "score", "tier", "reasons", "group_key", "classified_by"):
        assert key in first
    assert any(a["type"] == "price" for a in alerts["alerts"]) and any(a["type"] == "filing" for a in alerts["alerts"])
    assert alerts["window"] == {"from": "2026-11-07T15:06:37+05:30", "to": "2026-11-14T15:06:37+05:30"}
    assert "same window, 07 Nov 15:06 → 14 Nov 15:06" in out
    assert all(a["date"][:10] >= "2026-11-07" for a in alerts["alerts"])


def test_threshold_overrides_change_alerts(seed, capsys):
    build_push.main(["--no-write", "--window", "30d", "--price-move", "50", "--volume", "50"])
    out = capsys.readouterr().out
    assert "price ±50.0%, volume 50.0×" in out
    alert_lines = out.split("ALERTS")[1].split("CLASSIFIER")[0].splitlines()[1:]  # skip the header line
    assert alert_lines and not any("price  " in line for line in alert_lines)  # only filing alerts remain
    assert not (seed / "push" / "feed.json").exists()
    build_push.main(["--price-move", "50"])
    assert strict_json(seed / "push" / "alerts.json")["rules"]["price_move_pct"] == 50  # stored as evaluated


def test_bad_arguments_exit_2(seed, capsys):
    assert build_push.main(["--window", "fortnight"]) == 2
    assert build_push.main(["--end", "2026-11-13T18:00"]) == 2  # no timezone
