from datetime import timedelta

import pytest
from conftest import FIXTURES

from ingest.http import DiskCache, PoliteSession
from ingest.screener import (
    ScreenerError,
    build_fundamentals_record,
    choose_primary,
    company_url,
    parse_company_page,
)

INFY = (FIXTURES / "screener_infy_consolidated.html").read_text(encoding="utf-8")
HDFC = (FIXTURES / "screener_hdfcbank_standalone.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def infy():
    return parse_company_page(INFY)


@pytest.fixture(scope="module")
def hdfc():
    return parse_company_page(HDFC)


def test_identity(infy):
    ident = infy["identity"]
    assert ident["name"] == "Infosys Ltd"
    assert ident["bse_code"] == "500209"
    assert ident["nse_symbol"] == "INFY"
    assert ident["screener_company_id"] == "1489"
    assert ident["is_consolidated_page"] is True
    assert ident["about"].startswith("Infosys Ltd provides consulting")


def test_quarterly_table_labels_values_and_links(infy):
    q = infy["tables"]["quarters"]
    assert q["periods"] == ["Mar 2026", "Jun 2026", "Sep 2026"]
    # button text, &nbsp; and the "+" expander are stripped from labels
    assert list(q["rows"])[:3] == ["Sales", "YoY Sales growth", "Expenses"]
    assert q["rows"]["Sales"] == [46402, 48211, 49244]
    assert q["rows"]["YoY Sales growth"] == [13, 14, 11]
    assert {"YoY Sales growth", "OPM %", "Tax %"} <= set(q["pct_rows"])
    assert "Sales" not in q["pct_rows"]
    # link-only row goes to links, keyed by period, as absolute URLs
    assert "Raw PDF" not in q["rows"]
    assert q["links"]["Raw PDF"]["Sep 2026"] == "https://www.screener.in/company/source/quarter/1489/9/2026/"


def test_standard_layout_and_fields(infy):
    assert infy["layout"] == "standard"
    f = infy["fields"]["quarters"]
    assert f["revenue"] == "Sales"
    assert f["operating_profit"] == "Operating Profit"
    assert f["revenue_growth_pct"] == "YoY Sales growth"
    assert infy["fields"]["profit_loss"]["revenue_growth_pct"] == "Sales growth"


def test_ebitda_ex_other_income_equals_screener_operating_profit(infy):
    """PBT + finance cost + depreciation - other income == screener's Operating Profit.
    Phase 2 can use this as a free cross-check on numbers pulled from results PDFs."""
    q = infy["tables"]["quarters"]["rows"]
    i = -1  # Sep 2026
    ebitda = q["Profit before tax"][i] + q["Interest"][i] + q["Depreciation"][i] - q["Other Income"][i]
    assert ebitda == q["Operating Profit"][i] == 11689


def test_blank_cells_and_tooltip_labels(infy):
    pl = infy["tables"]["profit_loss"]
    assert pl["periods"][-1] == "TTM"
    assert pl["rows"]["Tax %"] == [29, 26, None]
    cf = infy["tables"]["cash_flow"]
    assert "CFO/EBITDA" in cf["rows"]  # tooltip text removed
    assert cf["rows"]["CFO/EBITDA"] == [105, 101]
    assert cf["rows"]["Net Cash Flow"] == [9669, -2254]
    assert infy["fields"]["cash_flow"]["cfo_to_ebitda_pct"] == "CFO/EBITDA"
    assert infy["tables"]["ratios"]["rows"]["Inventory Days"] == [None, None]
    assert infy["fields"]["balance_sheet"]["borrowings"] == "Borrowings"


def test_indian_digit_grouping_and_shareholding(infy):
    shp = infy["tables"]["shareholding_quarterly"]
    assert shp["rows"]["No. of Shareholders"] == [2958297, 2948075]
    assert shp["rows"]["Promoters"] == [13.82, 13.90]
    assert infy["tables"]["shareholding_yearly"]["periods"] == ["Mar 2026", "Sep 2026"]


def test_growth_ranges_and_top_ratios(infy):
    g = infy["growth_ranges"]
    assert g["Compounded Sales Growth"]["TTM"] == 12
    assert g["Stock Price CAGR"]["5 Years"] == -9
    km = infy["key_metrics"]
    assert km["market_cap_cr"] == 463254
    assert (km["high_52w"], km["low_52w"]) == (1728, 980)
    assert km["dividend_yield_pct"] == 4.2
    assert infy["top_ratios"]["High / Low"]["values"] == [1728, 980]


def test_documents(infy):
    docs = infy["documents"]
    ar = docs["annual_reports"]
    assert [a["year"] for a in ar] == [2026, 2025]
    assert ar[0]["source"] == "bse"
    assert ar[0]["url"].endswith("19dd605c-2b6b-4084-8dca-9d578a3eb7a0.pdf")
    cc = docs["concalls"]
    assert cc[0]["period"] == "Oct 2026" and cc[0]["month"] == "2026-10"
    assert cc[0]["transcript_url"].endswith("7982fc61-7765-4981-ab3d-6aec36ba2137.pdf")
    assert cc[0]["recording_url"].endswith(".mp3")
    assert "ppt_url" not in cc[0]  # PPT chip without a link
    assert "recording_url" not in cc[1]


def test_lender_layout(hdfc):
    assert hdfc["layout"] == "lender"
    f = hdfc["fields"]["quarters"]
    assert f["revenue"] == "Revenue"
    assert f["interest_expended"] == "Interest"
    assert f["gross_npa_pct"] == "Gross NPA %"
    assert "operating_profit" not in f
    q = hdfc["tables"]["quarters"]["rows"]
    assert q["Revenue"][-1] - q["Interest"][-1] == 34620  # net interest income
    assert q["Net NPA %"] == [0.38, 0.37]
    bs = hdfc["fields"]["balance_sheet"]
    assert bs["borrowings"] == "Borrowing" and bs["deposits"] == "Deposits"
    assert hdfc["identity"]["is_consolidated_page"] is False


def test_blocked_page_raises():
    with pytest.raises(ScreenerError):
        parse_company_page("<html><body><h2>Please verify you are human</h2></body></html>")


def test_choose_primary():
    views = {"consolidated": {"has_data": True}, "standalone": {"has_data": True}}
    assert choose_primary("standalone", views) == ("standalone", "configured")
    assert choose_primary("consolidated", views) == ("consolidated", "default")
    view, reason = choose_primary("consolidated", {"standalone": {"has_data": True}})
    assert view == "standalone" and "no data" in reason
    with pytest.raises(ScreenerError):
        choose_primary("consolidated", {"standalone": {"has_data": False}})


def test_company_url_escapes_symbols():
    assert company_url("M&M", "standalone") == "https://www.screener.in/company/M%26M/"
    assert company_url("INFY", "consolidated") == "https://www.screener.in/company/INFY/consolidated/"


def test_build_record_offline_with_one_view_missing(tmp_path):
    """Standalone page isn't cached: that view is reported, the record still builds."""
    cache = DiskCache(tmp_path)
    cache.save(company_url("INFY", "consolidated"), INFY)
    http = PoliteSession("test-agent")
    rec = build_fundamentals_record(http, cache, "INFY", "consolidated", offline=True)
    assert rec["primary_view"] == "consolidated"
    assert rec["bse_code"] == "500209"
    assert rec["layout"] == "standard"
    assert set(rec["views"]) == {"consolidated"}
    assert "standalone" in rec["view_errors"]
    assert len(rec["documents"]["concalls"]) == 2
    assert "identity" not in rec["views"]["consolidated"]
    assert rec["views"]["consolidated"]["from_cache"] is True


def test_build_record_falls_back_when_preferred_view_missing(tmp_path):
    cache = DiskCache(tmp_path)
    cache.save(company_url("HDFCBANK", "consolidated"), HDFC)
    rec = build_fundamentals_record(PoliteSession("t"), cache, "HDFCBANK", "standalone", offline=True)
    assert rec["primary_view"] == "consolidated"
    assert "standalone view has no data" in rec["primary_view_reason"]


def test_network_failure_falls_back_to_stale_cache(tmp_path, monkeypatch):
    from ingest.http import FetchError, cached_get_text

    cache = DiskCache(tmp_path)
    cache.save("https://www.screener.in/company/INFY/", "old page")
    http = PoliteSession("t", retries=1, sleep=lambda s: None)

    def down(*a, **k):
        raise FetchError("HTTP 503")

    monkeypatch.setattr(http, "get", down)
    hit = cached_get_text(http, cache, "https://www.screener.in/company/INFY/", ttl=timedelta(seconds=-1))
    assert hit.text == "old page" and hit.from_cache
    with pytest.raises(FetchError):
        cached_get_text(http, cache, "https://www.screener.in/company/NEW/", ttl=timedelta(hours=1))


def test_cache_ttl(tmp_path):
    cache = DiskCache(tmp_path)
    cache.save("https://example.com/x", "body")
    assert cache.load("https://example.com/x", max_age=timedelta(hours=1)).text == "body"
    assert cache.load("https://example.com/x", max_age=timedelta(seconds=-1)) is None
    assert cache.load("https://example.com/other", max_age=None) is None
