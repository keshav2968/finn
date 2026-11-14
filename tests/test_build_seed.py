"""End-to-end orchestration: isolation of failures, stale marking, manifest."""

import importlib.util
import json
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import FIXTURES, ROOT

from ingest.config import load_config
from ingest.http import DiskCache
from ingest.screener import company_url

spec = importlib.util.spec_from_file_location("build_seed", ROOT / "scripts" / "build_seed.py")
build_seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_seed)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Real config, but seed and cache directories in a temp folder."""
    cfg = load_config()
    cfg.settings = {**cfg.settings, "paths": {"seed_dir": str(tmp_path / "seed"), "cache_dir": str(tmp_path / "cache")}}
    monkeypatch.setattr(build_seed, "load_config", lambda: cfg)
    cache = DiskCache(tmp_path / "cache" / "http")
    cache.save(company_url("INFY", "consolidated"), (FIXTURES / "screener_infy_consolidated.html").read_text("utf-8"))
    return cfg, tmp_path / "seed"


def manifest(seed: Path) -> dict:
    return json.loads((seed / "manifest.json").read_text("utf-8"))


def entry(m: dict, symbol: str) -> dict:
    return next(e for e in m["companies"] if e["symbol"] == symbol)


def test_offline_run_parses_cache_and_skips_network_sources(sandbox, capsys):
    cfg, seed = sandbox
    code = build_seed.main(["--offline", "--symbols", "INFY"])
    assert code == 0
    fund = json.loads((seed / "fundamentals" / "INFY.json").read_text("utf-8"))
    assert fund["layout"] == "standard" and fund["bse_code"] == "500209"
    m = manifest(seed)
    assert len(m["companies"]) == 15  # the app always sees the full universe
    infy = entry(m, "INFY")
    assert infy["status"]["fundamentals"]["state"] == "ok"
    assert infy["status"]["prices"]["state"] == "missing"
    assert infy["research_focus"].startswith("Guided revenue growth")
    assert entry(m, "TITAN")["status"]["fundamentals"]["state"] == "missing"
    out = capsys.readouterr().out
    assert "SEED BUILD SUMMARY" in out and "skipped=1" in out


def test_one_failing_ticker_does_not_stop_the_run(sandbox, monkeypatch, capsys):
    cfg, seed = sandbox

    def fake_prices(symbol, settings, timeout, now):
        if symbol == "TITAN":
            raise RuntimeError("Yahoo said no")
        return {"symbol": symbol, "yahoo_symbol": f"{symbol}.NS", "fetched_at": "2026-11-14T17:05:00+05:30",
                "as_of": "2026-11-13", "latest": {"as_of": "2026-11-13", "close": 1.0, "pct_change": 0.5}}

    monkeypatch.setattr(build_seed, "build_price_record", fake_prices)
    monkeypatch.setattr(build_seed.time, "sleep", lambda s: None)
    code = build_seed.main(["--only", "prices", "--symbols", "INFY,TITAN,HINDUNILVR"])
    assert code == 0
    m = manifest(seed)
    assert entry(m, "INFY")["status"]["prices"]["state"] == "ok"
    assert entry(m, "HINDUNILVR")["status"]["prices"]["state"] == "ok"
    titan = entry(m, "TITAN")["status"]["prices"]
    assert titan["state"] == "missing" and "Yahoo said no" in titan["error"]
    assert m["as_of"] == "2026-11-13"
    out = capsys.readouterr().out
    assert "FAILED" in out and "TITAN" in out

    # A later failure keeps the earlier file and marks it stale instead of deleting it.
    monkeypatch.setattr(build_seed, "build_price_record", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    assert build_seed.main(["--only", "prices", "--symbols", "INFY"]) == 1  # nothing succeeded
    infy = entry(manifest(seed), "INFY")["status"]["prices"]
    assert infy["state"] == "stale" and infy["updated_at"] == "2026-11-14T17:05:00+05:30"
    assert (seed / "prices" / "INFY.json").exists()
    # sources not run this time keep their previous status
    assert entry(manifest(seed), "HINDUNILVR")["status"]["prices"]["state"] == "ok"


def test_filings_use_screener_bse_code_and_warn_on_mismatch(sandbox, monkeypatch):
    cfg, seed = sandbox
    cfg.companies["INFY"] = replace(cfg.companies["INFY"], bse_code="999999")
    build_seed.main(["--offline", "--only", "fundamentals", "--symbols", "INFY"])
    used = {}

    def fake_filings(http, symbol, code, days, max_pages, now, backoff):
        used[symbol] = code
        return {"symbol": symbol, "bse_code": code, "fetched_at": "2026-11-14T17:05:00+05:30",
                "window": {"from": "2026-09-15", "to": "2026-11-14"}, "count": 0, "items": []}

    monkeypatch.setattr(build_seed, "build_filings_record", fake_filings)
    build_seed.main(["--only", "filings", "--symbols", "INFY"])
    assert used["INFY"] == "500209"
    assert any("bse_code 999999" in w for w in manifest(seed)["warnings"])


def test_ad_hoc_symbol_is_kept_in_manifest(sandbox, monkeypatch):
    cfg, seed = sandbox
    monkeypatch.setattr(build_seed, "build_fundamentals_record",
                        lambda *a, **k: {"symbol": "TCS", "name": "Tata Consultancy Services Ltd", "bse_code": "532540",
                                         "layout": "standard", "primary_view": "consolidated", "fetched_at": "x",
                                         "key_metrics": {"market_cap_cr": 1100000}, "views": {},
                                         "view_errors": {}, "documents": {"concalls": [], "annual_reports": []}})
    build_seed.main(["--only", "fundamentals", "--symbols", "TCS"])
    tcs = entry(manifest(seed), "TCS")
    assert tcs["ad_hoc"] and tcs["name"] == "Tata Consultancy Services Ltd"
    assert tcs["size"] == "large" and tcs["is_lender"] is False and not tcs["in_portfolio"]
    # still listed after a later run that didn't include it
    build_seed.main(["--offline", "--symbols", "INFY"])
    assert entry(manifest(seed), "TCS")["ad_hoc"]


def test_bad_arguments():
    with pytest.raises(SystemExit):
        build_seed.parse_args(["--only", "news"])
    with pytest.raises(SystemExit):
        build_seed.parse_args(["--offline", "--refresh"])
