import json
from datetime import date

import pytest
import requests
from conftest import FIXTURES

from ingest.filings_bse import (
    API_URL,
    BseError,
    fetch_announcements,
    is_json_response,
    normalize,
)
from ingest.http import FetchError, PoliteSession

RAW = json.loads((FIXTURES / "bse_announcements_infy.json").read_text(encoding="utf-8"))


def by_id(rows, key):
    return next(r for r in rows if r["NEWSID"] == key)


def test_normalize_results_filing():
    item = normalize(by_id(RAW["Table"], "26c12463-results-fixture"), "INFY")
    assert item["datetime"] == "2026-10-23T16:16:06+05:30"
    assert item["title"].startswith("Financial Results For The Quarter")
    assert item["detail"].startswith("Results for the quarter")
    assert item["bse_category"] == "Result"
    assert item["bse_subcategory"] == "Financial Results"
    assert item["pdf_url"] == (
        "https://www.bseindia.com/stockinfo/AnnPdfOpen.aspx?Pname=26c12463-d44e-4050-bd47-b53cc294b4e0.pdf"
    )
    assert item["bse_code"] == "500209"
    assert item["critical"] is False


def test_filler_headline_is_dropped():
    item = normalize(by_id(RAW["Table"], "7982fc61-transcript-fixture"), "INFY")
    assert item["detail"] is None  # "Enclosed"
    assert item["bse_subcategory"] == "Earnings Call Transcript"


def test_legacy_subject_prefix_html_more_and_no_attachment():
    item = normalize(by_id(RAW["Table"], "e73071a5-board-meeting-fixture"), "INFY")
    assert item["title"] == "Board Meeting Intimation for Notice Of Board Meeting"
    assert item["more"].startswith("Infosys Ltd has informed BSE")
    assert "&amp;" not in item["more"] and "<p>" not in item["more"]
    assert item["pdf_url"] is None
    assert item["critical"] is True


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2026-10-23T16:16:06.71", "2026-10-23T16:16:06+05:30"),
        ("2026-09-16T18:22:45.9", "2026-09-16T18:22:45+05:30"),
        ("2026-10-28T17:34:48.1234567", "2026-10-28T17:34:48+05:30"),
        ("2026-10-28T17:34:48", "2026-10-28T17:34:48+05:30"),
    ],
)
def test_bse_timestamps_any_fraction_length(raw, expected):
    item = normalize({"NEWSID": "x", "DissemDT": raw}, "INFY")
    assert item["datetime"] == expected


def test_normalize_skips_rows_without_id():
    assert normalize({"NEWSSUB": "x"}, "INFY") is None


def _response(url, body, ctype):
    r = requests.Response()
    r.status_code = 200
    r.url = url
    r._content = body.encode("utf-8")
    r.headers["Content-Type"] = ctype
    return r


def test_is_json_response_rejects_bse_error_page():
    assert not is_json_response(_response("https://api.bseindia.com/error_Bse.html", "<html></html>", "text/html"))
    assert not is_json_response(_response(API_URL, "<!DOCTYPE html>", "text/html"))
    assert is_json_response(_response(API_URL, json.dumps(RAW), "application/json; charset=utf-8"))


def test_polite_session_retries_html_error_then_raises(monkeypatch):
    http = PoliteSession("t", retries=3, backoff=0, sleep=lambda s: None)
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(params)
        return _response("https://api.bseindia.com/error_Bse.html", "<html>", "text/html")

    monkeypatch.setattr(http.session, "get", fake_get)
    with pytest.raises(FetchError):
        http.get(API_URL, params={"a": 1}, accept=is_json_response)
    assert len(calls) == 3


class ScriptedHttp:
    """Stands in for PoliteSession: each call consumes the next scripted result."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def get(self, url, params=None, headers=None, accept=None, attempts=None):
        self.calls.append(dict(params))
        result = self.script.pop(0)
        if isinstance(result, Exception):
            raise result

        class R:
            def json(self_inner):
                return result

        return R()

    def pause(self, seconds):
        pass


def page(rows, total):
    return {"Table": rows, "Table1": [{"ROWCNT": total}]}


def test_retry_uses_a_different_url_spelling():
    rows = RAW["Table"]
    http = ScriptedHttp([FetchError("html error page"), page(rows, len(rows))])
    out = fetch_announcements(http, "500209", date(2026, 9, 15), date(2026, 11, 14))
    assert len(out) == len(rows)
    first, second = http.calls
    assert first == second  # same request...
    assert list(first) != list(second)  # ...spelled differently, so not served the cached error


def test_third_variant_moves_start_date_back_a_day():
    rows = RAW["Table"]
    http = ScriptedHttp([FetchError("x"), FetchError("y"), page(rows, len(rows))])
    fetch_announcements(http, "500209", date(2026, 9, 15), date(2026, 11, 14))
    assert http.calls[2]["strPrevDate"] == "20260914"


def test_all_variants_failing_raises():
    http = ScriptedHttp([FetchError("a"), FetchError("b"), FetchError("c")])
    with pytest.raises(BseError):
        fetch_announcements(http, "500209", date(2026, 9, 15), date(2026, 11, 14))


def test_pagination_and_dedupe():
    rows = RAW["Table"]
    http = ScriptedHttp([page(rows[:2], 3), page([rows[1], rows[2]], 3)])
    out = fetch_announcements(http, "500209", date(2026, 9, 15), date(2026, 11, 14))
    assert [r["NEWSID"] for r in out] == [r["NEWSID"] for r in rows[:3]]
    assert [c["pageno"] for c in http.calls] == [1, 2]


def test_pagination_stops_on_empty_page():
    rows = RAW["Table"]
    http = ScriptedHttp([page(rows[:2], 99), page([], 99)])
    out = fetch_announcements(http, "500209", date(2026, 9, 15), date(2026, 11, 14))
    assert len(out) == 2
