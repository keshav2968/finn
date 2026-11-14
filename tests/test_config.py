import pytest

from ingest.config import ConfigError, ad_hoc_company, load_config, parse_config


def test_real_config_loads():
    cfg = load_config()
    assert len(cfg.portfolio) == 15
    assert [r.symbol for r in cfg.research] == ["INFY", "POLYCAB", "KPITTECH", "ETERNAL"]
    assert len(cfg.universe()) == 15  # every research pick is also held
    lenders = sorted(c.symbol for c in cfg.companies.values() if c.is_lender)
    assert lenders == ["BAJFINANCE", "FEDERALBNK", "HDFCBANK"]
    assert cfg.companies["HDFCBANK"].primary_view == "standalone"
    assert cfg.companies["INFY"].primary_view == "consolidated"
    assert all(c.bse_code and len(c.bse_code) == 6 for c in cfg.companies.values())
    assert cfg.warnings == []


def test_every_problem_is_reported_at_once():
    raw = {
        "companies": [
            {"symbol": "AAA", "name": "A", "sector": "X", "size": "huge", "is_lender": "no", "bse_code": 12},
            {"symbol": "AAA", "name": "A", "sector": "X", "size": "mid", "is_lender": False},
        ],
        "portfolio": ["AAA", "ZZZ"],
        "research": [{"symbol": "QQQ"}],
    }
    with pytest.raises(ConfigError) as exc:
        parse_config(raw, {})
    msg = str(exc.value)
    for fragment in ["size must be", "is_lender must be", "bse_code must be 6 digits", "duplicate symbol", "ZZZ", "QQQ"]:
        assert fragment in msg


def test_small_portfolio_warns_not_fails():
    raw = {
        "companies": [{"symbol": "AAA", "name": "A", "sector": "X", "size": "mid", "is_lender": False}],
        "portfolio": ["AAA"],
        "research": ["AAA"],
    }
    cfg = parse_config(raw, {})
    assert cfg.warnings and "15-20" in cfg.warnings[0]


def test_ad_hoc_company():
    c = ad_hoc_company(" tcs ")
    assert c.symbol == "TCS" and c.ad_hoc and c.is_lender is None
    with pytest.raises(ConfigError):
        ad_hoc_company("not a symbol!")
