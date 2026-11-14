import json

import pytest
from push_helpers import cfg, filings, find

from push.classify import CONTEXT, LLM, PENDING, RULE, classify_all, filing_text, is_notice, load_llm_cache


@pytest.fixture(scope="module")
def classes():
    return classify_all(filings(), cfg())


CASES = [
    # (symbol, needle, day, category, method)
    ("INFY", "Financial Results For The Quarter", "2026-10-23", "results", RULE),
    ("INFY", "Investor Conference", "2026-11-04", "investor_meetings", RULE),
    ("INFY", "Truist", None, "press_release", RULE),
    ("INFY", "Pocharam", None, "capex", RULE),
    ("INFY", "Canada", None, "press_release", RULE),
    ("INFY", "Earnings Call Transcript", None, "earnings_call", RULE),
    ("INFY", "Labor Certification", None, "press_release", RULE),
    ("POLYCAB", "setting aside", None, "litigation", RULE),
    ("POLYCAB", "Intimation of NCLT order", None, "litigation", RULE),
    ("POLYCAB", "receipt of Order dated", None, "litigation", RULE),
    ("POLYCAB", "Conference Call invite", None, "earnings_call", RULE),
    ("POLYCAB", "Press Release for the Unaudited", None, "results", RULE),
    ("POLYCAB", "Employee Stock Options Scheme", "2026-11-03", "unclassified", RULE),
    ("BAJFINANCE", "approved the issue of 5,74,25,740 Warrants", None, "fund_raise", RULE),
    ("BAJFINANCE", "Non-Convertible Debentures on Private Placement basis", "2026-10-30", "fund_raise", RULE),
    ("BAJFINANCE", "BFL Employee Stock Option Scheme", None, "unclassified", RULE),
    ("BAJFINANCE", "Submission Of Half Yearly Report", None, "results", RULE),
    ("BAJFINANCE", "Regulation 8 of SEBI PIT", None, "unclassified", PENDING),
    ("FEDERALBNK", "Rajesh Varrier", None, "management_change", RULE),
    ("FEDERALBNK", "Clarification sought from Federal Bank", None, "press_release", RULE),
    ("FEDERALBNK", "Disclosure Under Regulation 30 Of SEBI (LODR) Regulations 2015", "2026-11-13", "unclassified", PENDING),
    ("FEDERALBNK", "Board Meeting Outcome", "2026-09-17", "unclassified", PENDING),
    ("HDFCBANK", "Change in Managing Director and Chief Executive", None, "management_change", RULE),
    ("HDFCBANK", "Grant Of Stock Options", None, "unclassified", RULE),
    ("HDFCBANK", "Outcome of Postal_Ballot", None, "postal_ballot", RULE),
    ("LT", "Noida Metro", None, "press_release", RULE),
    ("LT", "Vyoma", None, "M&A", RULE),
    ("LT", "Disposal Of Stake", None, "M&A", RULE),
    ("LT", "Analyst Presentation", None, "results", RULE),
    ("RELIANCE", "Listing Of Equity Shares Of Jio", None, "M&A", RULE),
    ("RELIANCE", "Newspaper Clipping", None, "unclassified", RULE),
    ("RELIANCE", "J.P. Morgan India Conference", "2026-09-21", "investor_meetings", RULE),
    ("RELIANCE", "strike off", None, "unclassified", RULE),
    ("TITAN", "Noel", None, "management_change", RULE),
    ("TITAN", "Repayment of Commercial Paper", "2026-11-12", "fund_raise", RULE),
    ("TITAN", "Appointment of Statutory Auditor", None, "unclassified", RULE),
    ("TITAN", "Quarterly Update", None, "results", RULE),
    ("KPITTECH", "Reg. 29(2)", None, "insider_trading", RULE),
    ("KPITTECH", "Grant Of Options To Eligible Employees", None, "unclassified", RULE),
    ("ETERNAL", "Shareholders Letter", None, "results", RULE),
    ("ETERNAL", "ESG rating", None, "unclassified", RULE),
    ("SUNPHARMA", "Completion And Results Of Postal Ballot Dated 01", None, "postal_ballot", RULE),
    ("SUNPHARMA", "Appointment Of Statutory Auditors", None, "unclassified", RULE),
    ("TATACHEM", "ESG Rating", "2026-11-01", "unclassified", RULE),
    ("HINDUNILVR", "Schedule Of Events - Postal Ballot", None, "postal_ballot", RULE),
]


SUBCATEGORY = {("INFY", "Financial Results For The Quarter"): "Financial Results"}


@pytest.mark.parametrize("symbol, needle, day, category, method", CASES)
def test_real_filings(classes, symbol, needle, day, category, method):
    item = find(symbol, needle, day, SUBCATEGORY.get((symbol, needle)))
    c = classes[item["id"]]
    assert (c.category, c.method) == (category, method), f"{item['title']} -> {c}"


def test_same_day_context_turns_generic_board_outcomes_into_results(classes):
    for symbol, day in [("ELECON", "2026-10-14"), ("ETERNAL", "2026-10-21")]:
        outcome = find(symbol, "Board Meeting Outcome for Outcome Of Board Meeting", day)
        assert classes[outcome["id"]].method == CONTEXT
        assert classes[outcome["id"]].category == "results"
    # and a results-day press release that BSE filed under Press Release
    pr = find("ELECON", "Press release of board meeting", "2026-10-14")
    assert (classes[pr["id"]].category, classes[pr["id"]].method) == ("results", CONTEXT)


def test_generic_outcome_without_results_that_day_stays_pending(classes):
    item = find("FEDERALBNK", "Board Meeting Outcome", "2026-09-17")
    assert classes[item["id"]].pending


def test_investor_deck_without_quarter_words_is_not_results(classes):
    deck = find("HINDUNILVR", "Investor Presentation", "2026-11-04")
    assert classes[deck["id"]].category == "investor_meetings"


def test_notice_kind(classes):
    assert classes[find("INFY", "To Announce Second Quarter Results")["id"]].kind == "notice"
    assert classes[find("BAJFINANCE", "Considering And Approving")["id"]].kind == "notice"
    assert classes[find("ELECON", "Record Date For Purpose")["id"]].kind == "notice"
    assert classes[find("INFY", "Pocharam")["id"]].kind == "event"
    assert is_notice({"title": "Intimation Of Product Launch", "bse_category": "Company Update", "bse_subcategory": "General"}, cfg()) is False


def test_urls_do_not_count_as_words():
    text = filing_text({"title": "Clarification", "detail": "news at https://example.com/usfda-order-plant quoting ...."})
    assert "order" not in text


def test_llm_cache_fills_only_what_rules_left(tmp_path):
    pending = find("FEDERALBNK", "Disclosure Under Regulation 30 Of SEBI (LODR) Regulations 2015", "2026-11-13")
    ruled = find("LT", "Vyoma")
    cache_file = tmp_path / "llm.json"
    cache_file.write_text(json.dumps({"items": {
        pending["id"]: {"category": "capex", "kind": "event", "model": "groq/test"},
        ruled["id"]: {"category": "dividend"},           # rules win: ignored
        "not-a-filing": {"category": "gossip"},           # unknown category: dropped on load
    }}), encoding="utf-8")
    cache = load_llm_cache(cache_file, cfg())
    assert "not-a-filing" not in cache
    out = classify_all(filings(), cfg(), cache)
    assert (out[pending["id"]].category, out[pending["id"]].method, out[pending["id"]].rule_id) == ("capex", LLM, "groq/test")
    assert out[ruled["id"]].category == "M&A"


def test_missing_or_broken_cache_is_empty(tmp_path):
    assert load_llm_cache(tmp_path / "none.json", cfg()) == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_llm_cache(bad, cfg()) == {}


def test_every_fixture_filing_gets_a_classification(classes):
    assert len(classes) == len(filings())
    assert all(c.category in cfg().categories for c in classes.values())
