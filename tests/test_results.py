"""Results card: page choice, statement checks, OCR repairs, screener cross-checks.

The page texts are real (tests/fixtures/results_pages, from the 14 Nov 2026 PDFs).
The extractions below are what a correct model copies off those pages, including
the OCR slips that are really on them, so these tests prove Python catches them.
"""

import json

import jsonschema
import pytest
from conftest import FIXTURES

from llm.router import estimate_tokens
from push.results import (
    STANDARD_FIELDS,
    LENDER_FIELDS,
    build_card,
    choose_page,
    extraction_schema,
    latest_results_card,
    results_settings,
    screener_only_card,
    system_prompt,
    user_prompt,
)
from push_helpers import cfg

SCREENER = json.loads((FIXTURES / "results_screener.json").read_text("utf-8"))["fundamentals"]
RC = results_settings(cfg())


def pages(sym):
    d = json.loads((FIXTURES / "results_pages" / f"{sym}.json").read_text("utf-8"))
    return [(p["page"], p["text"]) for p in d["pages"]]


def col(label, end, lender=False, **values):
    fields = LENDER_FIELDS if lender else STANDARD_FIELDS
    return {"label": label, "period_end": end, "months": 3, "values": {k: values.get(k) for k in fields}}


def metric(card, key):
    return next(m for m in card["metrics"] if m["key"] == key)


ELECON_CONSOLIDATED = {  # page 9, INR lakhs
    "statement_basis": "consolidated", "unit": "lakh", "currency": "INR",
    "columns": [
        col("30 Sep 2026", "2026-09-30", revenue_from_operations=63894, other_income=1979, total_income=65873, total_expenses=53397,
            finance_costs=1033, depreciation=3260, profit_before_exceptional_and_tax=12476, profit_before_tax=12476,
            current_tax=2905, deferred_tax=-64, net_profit=9635),
        col("30 June 2026", "2026-06-30", revenue_from_operations=52056, other_income=2191, total_income=54247, total_expenses=44931,
            finance_costs=811, depreciation=2976, profit_before_exceptional_and_tax=9316, profit_before_tax=9316,
            current_tax=2301, deferred_tax=-20, net_profit=7035),
        col("30 Sep 2025", "2025-09-30", revenue_from_operations=57813, other_income=1832, total_income=59645, total_expenses=48346,
            finance_costs=569, depreciation=2528, profit_before_exceptional_and_tax=11299, profit_before_tax=11299,
            current_tax=2323, deferred_tax=204, net_profit=8772),
    ],
}

ELECON_STANDALONE_OCR = {  # page 3: "Other income 1.702" (a comma read as a point), unit garbled
    "statement_basis": "standalone", "unit": "unknown", "currency": "INR",
    "columns": [
        col("30 Sep 2026", "2026-09-30", revenue_from_operations=53466, other_income=1.702, total_income=55168, total_expenses=45240,
            finance_costs=994, depreciation=2890, profit_before_exceptional_and_tax=9928, profit_before_tax=9928,
            current_tax=2517, deferred_tax=-64, net_profit=7475),
        col("30 Jun 2026", "2026-06-30", revenue_from_operations=39824, other_income=1960, total_income=41784, total_expenses=33915,
            finance_costs=780, depreciation=2609, profit_before_exceptional_and_tax=7869, profit_before_tax=7869,
            current_tax=2032, deferred_tax=-20, net_profit=5857),
        col("30 Sep 2025", "2025-09-30", revenue_from_operations=49618, other_income=1831, total_income=51449, total_expenses=41074,
            finance_costs=535, depreciation=2206, profit_before_exceptional_and_tax=10375, profit_before_tax=10375,
            current_tax=2282, deferred_tax=204, net_profit=7889),
    ],
}

INFY_STAMPED = {  # page 18: a stamp covers the revenue, other income and total income rows
    "statement_basis": "consolidated", "unit": "crore", "currency": "INR",
    "columns": [
        col("Sep 30, 2026", "2026-09-30", total_expenses=39029, finance_costs=115, depreciation=1359,
            profit_before_exceptional_and_tax=11063, profit_before_tax=11063, current_tax=3398, deferred_tax=-173, net_profit=7838),
        col("June 30, 2026", "2026-06-30", total_expenses=38167, finance_costs=119, depreciation=1246,
            profit_before_exceptional_and_tax=11028, profit_before_tax=11028, current_tax=3356, deferred_tax=-103, net_profit=7775),
        col("Sep 30, 2025", "2025-09-30", total_expenses=35243, finance_costs=106, depreciation=1182,
            profit_before_exceptional_and_tax=10229, profit_before_tax=10229, current_tax=3178, deferred_tax=-324, net_profit=7375),
    ],
}

HDFC_OCR = {  # page 2, as OCR'd: total income 97267.62 (true 97257.62), Jun PBT 26108.30 (25108.30),
    # Sep net profit 19609.96 (19509.96), Jun net profit 19069.72 (19059.72); the year-ago date
    # printed "39.09.2026" so the model repeats 2026-09-30
    "statement_basis": "standalone", "unit": "crore", "currency": "INR",
    "columns": [
        col("30.09.2026", "2026-09-30", True, interest_earned=83426.60, other_income=13831.02, total_income=97267.62,
            interest_expended=48807.42, operating_expenses=18966.78, operating_profit_before_provisions=29483.42,
            provisions=3573.62, profit_before_tax=25909.80, total_tax=6399.84, net_profit=19609.96),
        col("30.06.2026", "2026-06-30", True, interest_earned=79362.78, other_income=12821.60, total_income=92184.38,
            interest_expended=45828.83, operating_expenses=18187.49, operating_profit_before_provisions=28168.06,
            provisions=3059.76, profit_before_tax=26108.30, total_tax=6048.58, net_profit=19069.72),
        col("39.09.2026", "2026-09-30", True, interest_earned=76690.70, other_income=14350.02, total_income=91040.72,
            interest_expended=45139.20, operating_expenses=17977.92, operating_profit_before_provisions=27923.60,
            provisions=3500.53, profit_before_tax=24423.07, total_tax=5781.79, net_profit=18641.28),
    ],
}

NBFC = {  # Ind AS NBFC layout: no NII or PPOP line; impairment = provisions
    "statement_basis": "consolidated", "unit": "crore", "currency": "INR",
    "columns": [
        col("30.09.2026", "2026-09-30", True, interest_earned=21500, revenue_from_operations=24546, other_income=33, total_income=24579,
            interest_expended=8602, provisions=2200, profit_before_tax=8537, total_tax=2170, net_profit=6367),
        col("30.06.2026", "2026-06-30", True, interest_earned=20300, revenue_from_operations=23165, other_income=6, total_income=23171,
            interest_expended=7942, provisions=2100, profit_before_tax=8149, total_tax=2068, net_profit=6081),
        col("30.09.2025", "2025-09-30", True, interest_earned=17500, revenue_from_operations=19990, other_income=5, total_income=19995,
            interest_expended=7011, provisions=1900, profit_before_tax=6608, total_tax=1660, net_profit=4948),
    ],
}

STANDARD_CO = {"is_lender": False, "primary_view": "consolidated", "name": "Test"}
LENDER_CO = {"is_lender": True, "primary_view": "standalone", "name": "Test Bank"}


@pytest.mark.parametrize("extraction, lender", [(ELECON_CONSOLIDATED, False), (ELECON_STANDALONE_OCR, False),
                                                (INFY_STAMPED, False), (HDFC_OCR, True), (NBFC, True)])
def test_extractions_match_the_schema(extraction, lender):
    jsonschema.validate(extraction, extraction_schema(lender))


@pytest.mark.parametrize("sym, basis, page", [("ELECON", "consolidated", 9), ("INFY", "consolidated", 18), ("HDFCBANK", "standalone", 2)])
def test_page_choice(sym, basis, page):
    choice = choose_page(pages(sym), basis, 4)
    assert (choice.number, choice.basis, choice.note) == (page, basis, "")


def test_other_basis_is_used_with_a_note_and_summaries_are_skipped():
    choice = choose_page(pages("HDFCBANK"), "consolidated", 4)
    assert (choice.number, choice.basis) == (9, "consolidated")
    elecon_standalone_only = [(n, t) for n, t in pages("ELECON") if n == 3]
    choice = choose_page(elecon_standalone_only, "consolidated", 4)
    assert choice.number == 3 and "No consolidated statement" in choice.note
    bajaj = choose_page(pages("BAJFINANCE"), "consolidated", 4)  # the real 19 Oct results PDF
    assert (bajaj.number, bajaj.basis) == (14, "consolidated")
    highlights = "Annexure A\nHighlights of the consolidated financial results for H1 FY27 (in crore)\n" + "\n".join(
        ["Interest income 42,449", "Interest expenses 16,544", "Net interest income 25,905", "Profit before tax 16,686",
         "Profit after tax 12,447", "Other income 9", "Total income 31,198", "Quarter ended 30.09.2026"])
    assert choose_page([(7, highlights)], "consolidated", 4) is None  # a summary, not the statement


@pytest.mark.parametrize("sym", ["ELECON", "INFY", "HDFCBANK"])
def test_prompt_fits_groqs_per_minute_budget(sym):
    lender = sym == "HDFCBANK"
    choice = choose_page(pages(sym), "standalone" if lender else "consolidated", 4)
    system = system_prompt(lender) + json.dumps(extraction_schema(lender))
    tokens = estimate_tokens(system + user_prompt(sym, choice, RC["max_page_chars"]))
    assert tokens + 3000 <= 8000, tokens


def test_elecon_consolidated_lakhs_to_crore_all_verified():
    card = build_card("ELECON", STANDARD_CO, SCREENER["ELECON"], ELECON_CONSOLIDATED, RC)
    assert card["status"] == "verified" and card["periods"] == {"current": "Sep 2026", "previous": "Jun 2026", "year_ago": "Sep 2025"}
    rev, ebitda, margin = metric(card, "revenue"), metric(card, "ebitda"), metric(card, "ebitda_margin")
    assert (rev["current"], rev["previous"], rev["year_ago"]) == (638.94, 520.56, 578.13)
    assert (rev["qoq_pct"], rev["yoy_pct"]) == (22.7, 10.5)
    assert (ebitda["current"], ebitda["previous"], ebitda["year_ago"]) == (147.9, 109.12, 125.64)
    assert ebitda["screener"]["current"] == 148 and ebitda["check"]["current"] == "verified"
    assert round(margin["current"], 1) == 23.1 and margin["qoq_pp"] == 2.2
    assert metric(card, "pbt")["current"] == 124.76 and metric(card, "pat")["current"] == 96.35
    assert card["formula"].startswith("PBT before exceptional items")
    assert all(c["ok"] for checks in card["statement_checks"].values() for c in checks)


def test_comma_read_as_a_point_is_repaired_and_unit_is_inferred():
    card = build_card("ELECON", STANDARD_CO, SCREENER["ELECON"], ELECON_STANDALONE_OCR, RC)
    assert card["basis"] == "standalone" and card["screener_view"] == "standalone"
    assert any("'1.702' as 1702" in n for n in card["notes"])
    assert any("Unit taken as lakh" in n for n in card["notes"])
    assert metric(card, "other_income")["current"] == 17.02
    assert metric(card, "ebitda")["current"] == 121.1 and card["status"] == "verified"


def test_stamped_rows_are_rebuilt_from_the_statement_and_screener():
    card = build_card("INFY", STANDARD_CO, SCREENER["INFY"], INFY_STAMPED, RC)
    rev = metric(card, "revenue")
    # total income = total expenses + profit before exceptional items (from the PDF);
    # other income from screener; revenue = the difference, then checked against screener
    assert (rev["current"], rev["previous"], rev["year_ago"]) == (49244.0, 48211.0, 44490.0)
    assert rev["check"]["current"] == "verified" and (rev["qoq_pct"], rev["yoy_pct"]) == (2.1, 10.7)
    assert metric(card, "ebitda")["current"] == 11689.0 and metric(card, "ebitda")["check"]["current"] == "verified"
    assert any("taken from screener.in: other income" in n for n in card["notes"])
    assert card["status"] == "verified"


def test_bank_ocr_slips_are_caught_and_corrected():
    card = build_card("HDFCBANK", LENDER_CO, SCREENER["HDFCBANK"], HDFC_OCR, RC)
    assert card["layout"] == "lender" and card["status"] == "verified"
    assert card["periods"]["year_ago"] == "Sep 2025"  # repeated date -> standard column order
    nii, ppop, prov, pat = (metric(card, k) for k in ("nii", "ppop", "provisions", "pat"))
    assert (nii["current"], nii["previous"], nii["year_ago"]) == (34619.18, 33533.95, 31551.5)
    assert nii["yoy_pct"] == 9.7          # HDFC Bank's own press release: NII "grew by 9.7%"
    assert (ppop["current"], ppop["qoq_pct"], ppop["yoy_pct"]) == (29483.42, 4.7, 5.6)
    assert (prov["current"], prov["qoq_pct"], prov["yoy_pct"]) == (3573.62, 16.8, 2.1)
    assert (pat["current"], pat["previous"]) == (19509.96, 19059.72)   # both corrected
    assert all(metric(card, k)["check"]["current"] == "verified" for k in ("nii", "ppop", "provisions", "pat"))
    notes = " | ".join(card["notes"])
    assert "read profit before tax as 26,108.30" in notes and "25,108.30" in notes
    assert "read net profit as 19,609.96" in notes
    assert "total income (97,267.62)" in notes and "isn't used on the card" in notes
    assert "assumed the standard order" in notes


def test_nbfc_ppop_from_pbt_plus_provisions():
    card = build_card("BAJFINANCE", {"is_lender": True, "primary_view": "consolidated"}, SCREENER["BAJFINANCE"], NBFC, RC)
    ppop = metric(card, "ppop")
    assert (ppop["current"], ppop["check"]["current"]) == (10737.0, "verified")
    assert metric(card, "nii")["current"] == 12898.0
    assert metric(card, "nii")["check"]["current"] == "unchecked"  # screener has no NBFC interest-income line
    assert card["status"] == "partial"


def test_mismatch_against_screener_is_flagged():
    bad = json.loads(json.dumps(ELECON_CONSOLIDATED))
    for k in ("profit_before_exceptional_and_tax", "profit_before_tax"):
        bad["columns"][0]["values"][k] = 15476   # 3,000 lakh too high, consistently
    bad["columns"][0]["values"]["total_expenses"] = 50397
    bad["columns"][0]["values"]["net_profit"] = 12635
    card = build_card("ELECON", STANDARD_CO, SCREENER["ELECON"], bad, RC)
    assert card["status"] == "mismatch"
    assert metric(card, "pbt")["check"]["current"] == "mismatch" and metric(card, "pbt")["screener"]["current"] == 125


def test_declared_unit_wrong_is_corrected():
    wrong = dict(ELECON_CONSOLIDATED, unit="crore")
    card = build_card("ELECON", STANDARD_CO, SCREENER["ELECON"], wrong, RC)
    assert metric(card, "revenue")["current"] == 638.94 and any("Unit taken as lakh" in n for n in card["notes"])


def test_no_extraction_or_foreign_currency_falls_back_to_screener():
    card = build_card("ELECON", STANDARD_CO, SCREENER["ELECON"], None, RC)
    assert card["status"] == "screener_only" and metric(card, "revenue")["current"] == 639
    assert metric(card, "ebitda")["current"] == 148 and metric(card, "revenue")["yoy_pct"] == 10.6
    usd = dict(ELECON_CONSOLIDATED, currency="USD")
    assert build_card("ELECON", STANDARD_CO, SCREENER["ELECON"], usd, RC)["status"] == "screener_only"
    bank = screener_only_card("HDFCBANK", LENDER_CO, SCREENER["HDFCBANK"], None, RC, [])
    assert metric(bank, "nii")["current"] == 83427 - 48807
    assert build_card("NOPE", STANDARD_CO, {}, None, RC)["status"] == "unavailable"


def test_latest_results_card_prefers_the_statement_over_a_later_report():
    from datetime import datetime
    from ingest.common import IST
    from push.feed import Snapshot, score_snapshot

    def filing(fid, when, title, sub, detail=None):
        return {"id": fid, "symbol": "BAJFINANCE", "datetime": when, "title": title, "detail": detail, "more": None,
                "bse_category": "Result" if sub == "Financial Results" else "Company Update", "bse_subcategory": sub,
                "pdf_url": f"https://www.bseindia.com/stockinfo/AnnPdfOpen.aspx?Pname={fid}.pdf"}

    items = [
        filing("results", "2026-10-19T17:39:00+05:30", "Unaudited Standalone And Consolidated Financial Results For The Quarter",
               "Financial Results"),
        filing("deck", "2026-10-19T18:10:00+05:30", "Announcement under Regulation 30 (LODR)-Investor Presentation",
               "Investor Presentation", "Investor Presentation for the quarter ended 30 September 2026"),
        filing("halfyear", "2026-11-07T10:00:00+05:30", "Submission Of Half Yearly Report For FY2026-27", "General",
               "Submission of half-yearly report containing the Financial Performance of the Company"),
    ]
    scored = score_snapshot(Snapshot({}, items, {}, {}, datetime(2026, 11, 14, tzinfo=IST)), cfg(), llm_cache={})
    card = latest_results_card(scored, "BAJFINANCE", cfg())
    assert card.lead.item["datetime"].startswith("2026-10-19")
    from push.results import pdf_candidates
    assert [i["id"] for i in pdf_candidates(card)][0] == "results"
