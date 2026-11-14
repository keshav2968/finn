"""Research pipeline, fully offline: real Infosys transcript excerpts and screener figures
as fixtures, and scripted model replies (good and bad) instead of network calls."""

from __future__ import annotations

import pytest

from research import ledger as L
from research import periods
from research import promises as P
from research import transcripts as T
from research.build import build_research
from research.numbers import actual_for, build_numbers, period_ended
from tests.research_helpers import FIX as FIXDIR
from tests.research_helpers import ScriptedModel, fixture_text, infy_record, research_cfg

GOOD_JUDGE = {
    "revenue_growth:FY27": {"verdict": "Goalposts moved", "evidence_ids": ["s1", "s3"],
                       "rationale": "FY27 guidance was cut from 1.5–3.5% to 1–2% over three calls.",
                       "actual_quote": "Our revenue growth for Q2 was 1.5% YoY and 1.2% sequentially in constant currency terms.",
                       "actual_evidence_id": None},
    "operating_margin:FY27": {"verdict": "Pending", "evidence_ids": [],
                         "rationale": "Operating margin so far is 21.03%, inside the 20–22% band."},
}


def _build(model=None, record=None, get_text=fixture_text):
    return build_research("INFY", record or infy_record(), research_cfg(), get_text, model)


def _entry(doc, metric, period="FY27"):
    return next(e for e in doc["ledger"] if e["metric"] == metric and e["period"] == period)


# ---------------------------------------------------------------- periods and numbers

def test_fiscal_periods():
    assert periods.fiscal_label("Sep 2026") == "Q2 FY27"
    assert periods.fiscal_label("Mar 2027") == "Q4 FY27"
    assert periods.quarters_of("FY27") == ["Jun 2026", "Sep 2026", "Dec 2026", "Mar 2027"]
    assert periods.quarters_of("H2FY27") == ["Dec 2026", "Mar 2027"]
    assert periods.quarters_of("Q1FY28") == ["Jun 2027"]
    assert periods.quarter_discussed("2026-10") == "Sep 2026"
    assert periods.quarter_discussed("2026-01") == "Dec 2025"
    assert periods.quarters_of("medium_term") == []


def test_numbers_are_computed_in_python_from_screener():
    rec = infy_record()
    n = build_numbers(rec)
    assert n["latest_quarter"] == "Sep 2026" and n["latest_fiscal"] == "Q2 FY27"
    last = n["quarters"][-1]
    assert last["revenue"] == 49244.0
    assert last["ebit_margin"] == round(100 * (11689 - 1359) / 49244, 2)  # (operating profit - depreciation) / sales
    assert last["revenue_yoy"] == round(100 * (49244 - 44490) / 44490, 2)
    ytd = n["fiscal_year_to_date"]["metrics"]["ebit_margin"]
    assert ytd["quarters"] == ["Jun 2026", "Sep 2026"] and not ytd["complete"]
    assert ytd["value"] == round(100 * ((11409 + 11689) - (1246 + 1359)) / (48211 + 49244), 2)


def test_period_status_follows_reported_quarters():
    rec = infy_record()
    assert period_ended("FY26", rec) and not period_ended("FY27", rec)
    assert actual_for("ebit_margin", "FY26", rec)["complete"]
    assert actual_for(None, "FY27", rec) is None
    assert actual_for("revenue_growth", "unspecified", rec) is None


# ---------------------------------------------------------------- transcripts

def test_roster_and_speakers_from_a_real_transcript_layout():
    cfg = research_cfg()
    t = T.read({"period": "Apr 2026", "month": "2026-04", "transcript_url": "https://example.test/infy-2026-04.pdf"}, "t3", cfg, fixture_text)
    assert t.error is None
    # The header misspells JOURNALISTS; the roster must still stop before the journalists.
    assert t.management == ["Salil Parekh", "Jayesh Sanghrajka", "Rishi Basu"]
    speakers = {p.speaker for p in t.passages}
    assert {"Salil Parekh", "Jayesh Sanghrajka", "Ritu Singh"} <= speakers
    assert not any(p.management for p in t.passages if p.speaker == "Ritu Singh")


def test_keyword_filter_keeps_guidance_and_drops_small_talk():
    cfg = research_cfg()
    t = T.read({"period": "Oct 2026", "month": "2026-10", "transcript_url": "https://example.test/infy-2026-10.pdf"}, "t1", cfg, fixture_text)
    sent = T.forward_passages(t.passages, cfg)
    text = " ".join(p.text for p in sent)
    assert "revenue growth guidance is 1% to 2%" in text
    assert all(p.management for p in sent)
    assert sum(len(p.text) for p in sent) <= cfg["transcripts"]["max_chars_per_call"]
    assert len(sent) < len(t.passages)


def test_unreadable_or_missing_transcript_is_recorded_not_raised():
    cfg = research_cfg()

    def boom(_url):
        raise OSError("blocked")

    t = T.read({"period": "Oct 2026", "month": "2026-10", "transcript_url": "u"}, "t1", cfg, boom)
    assert t.error.startswith("OSError") and t.passages == []
    t = T.read({"period": "Oct 2026", "month": "2026-10", "transcript_url": "u"}, "t1", cfg, lambda _u: "  ")
    assert "no readable text" in t.error


# ---------------------------------------------------------------- quotes and promises

def test_quote_matching_tolerates_layout_but_not_paraphrase():
    source = "Our operating margin guidance for financial year '27 is 20%\nto 22%.\n With that"
    assert P.quote_score("Our operating margin guidance for financial year ’27 is 20% to 22%.", source) == 100
    assert P.quote_score("Our margin guidance this year is about 21%.", source) < 90


def test_extraction_checks_drop_invented_quotes_and_analyst_words():
    doc = _build(ScriptedModel(judge_replies=GOOD_JUDGE))
    reasons = [d["reason"] for d in doc["dropped"]]
    assert any(r.startswith("quote not found") for r in reasons)
    assert any("not management" in r for r in reasons)
    for e in doc["ledger"]:
        for s in e["statements"]:
            assert s["quote_score"] >= 90 and s["source_url"]


def test_a_target_number_not_in_the_quote_is_removed_not_kept():
    doc = _build(ScriptedModel(judge_replies=GOOD_JUDGE))
    margin = _entry(doc, "operating_margin")
    targets = [s["target_text"] for s in margin["statements"]]
    assert targets == ["20–22%", None, "20–22%"]  # the July reply claimed 20-25%
    assert not margin["revised"]


# ---------------------------------------------------------------- ledger

def test_ledger_on_infy_guidance_trail():
    doc = _build(ScriptedModel(judge_replies=GOOD_JUDGE))
    assert doc["status"] == "ok"
    rev = _entry(doc, "revenue_growth")
    assert rev["verdict"] == "Goalposts moved"
    assert rev["revision_path"] == "1.5–3.5% → 1.5–3% → 1–2%"
    assert [s["call"] for s in rev["statements"]] == ["Apr 2026", "Jul 2026", "Oct 2026"]
    # Constant-currency guidance is never judged on rupee growth.
    assert rev["check"]["comparable"] is False
    assert any("not comparable" in n for n in rev["notes"])
    margin = _entry(doc, "operating_margin")
    assert margin["verdict"] == "Pending" and margin["period_status"].startswith("in progress")
    assert margin["check"]["position"] == "within"
    assert margin["evidence"][0]["kind"] == "screener"


def test_quoted_actual_must_match_its_source():
    rev_id = _entry(_build(ScriptedModel(judge_replies=GOOD_JUDGE)), "revenue_growth")["id"]
    judge = {**GOOD_JUDGE, "revenue_growth:FY27": {**GOOD_JUDGE["revenue_growth:FY27"], "actual_evidence_id": f"{rev_id}-q1"}}
    doc = _build(ScriptedModel(judge_replies=judge))
    assert _entry(doc, "revenue_growth")["actual_quote"]["speaker"] == "Salil Parekh"
    judge["revenue_growth:FY27"] = {**judge["revenue_growth:FY27"], "actual_quote": "Revenue grew 9% in constant currency, our best year."}
    doc = _build(ScriptedModel(judge_replies=judge))
    rev = _entry(doc, "revenue_growth")
    assert rev["actual_quote"] is None and any("did not match" in n for n in rev["notes"])


def test_verdicts_the_dates_forbid_and_invented_numbers_are_overruled():
    judge = {"operating_margin:FY27": {"verdict": "Delivered", "evidence_ids": [], "rationale": "Margin hit 23.5%."},
             "revenue_growth:FY27": {"verdict": "Pending", "evidence_ids": [], "rationale": "Growth will reach 7% by March."}}
    doc = _build(ScriptedModel(judge_replies=judge))
    margin = _entry(doc, "operating_margin")
    assert margin["verdict"] == "Pending" and margin["verdict_by"] == "rules"  # FY27 has not ended
    rev = _entry(doc, "revenue_growth")
    assert rev["verdict"] == "Pending" and "7%" not in rev["rationale"]
    assert rev["rationale"].startswith("Period still running")  # matches the verdict it explains
    assert any("rationale replaced" in n for n in rev["notes"])


def test_arithmetic_beats_the_model_once_a_period_has_ended():
    group = {"id": "g1", "metric": "operating_margin", "metric_label": "Operating (EBIT) margin", "metric_text": "operating margin",
             "period": "FY26", "revised": False, "path": None,
             "statements": [{"call": "Apr 2025", "call_month": "2025-04", "fiscal": "Q4 FY25", "speaker": "CFO", "quote": "Margin of 22% to 24% for FY26.",
                             "target_text": "22–24%", "target_low": 22, "target_high": 24, "unit": "%", "basis": "unspecified",
                             "quote_score": 100, "source_url": "u", "metric_label": "Operating (EBIT) margin", "metric_text": "operating margin"}]}
    group["latest"] = group["statements"][0]
    ev = L.build_evidence(group, infy_record(), [], research_cfg())
    assert ev["check"]["complete"] and ev["check"]["position"] == "below"  # FY26 EBIT margin was ~20.9%
    entry = L.finalise(group, ev, {"verdict": "Delivered", "evidence_ids": [], "rationale": "Delivered."}, "m", research_cfg())
    assert entry["verdict"] == "Missed" and any("figures win" in n for n in entry["notes"])


def test_model_outage_falls_back_to_rules_and_still_writes_a_ledger():
    doc = _build(ScriptedModel(fail_tasks={"judge_promises"}))
    assert doc["status"] == "ok" and doc["ledger"]
    assert all(e["verdict_by"] == "rules" for e in doc["ledger"])
    assert _entry(doc, "revenue_growth")["verdict"] == "Goalposts moved"
    assert any("judge batch" in n for n in doc["notes"])
    doc = _build(ScriptedModel(fail_tasks={"extract_promises"}))
    assert doc["status"] == "no_promises"
    assert all("extraction failed" in t["error"] for t in doc["transcripts"] if t["sent"])


def test_company_without_transcripts_gets_numbers_and_a_clear_status():
    rec = infy_record()
    rec["documents"] = {"concalls": [], "annual_reports": []}
    doc = _build(ScriptedModel(), record=rec)
    assert doc["status"] == "no_transcripts" and doc["ledger"] == []
    assert doc["numbers"]["latest_quarter"] == "Sep 2026"


def test_numbers_only_run_makes_no_model_calls():
    doc = _build(None)
    assert doc["status"] == "numbers_only" and doc["ledger"] == []
    assert all(t["sent"] > 0 for t in doc["transcripts"] if t["fiscal"] != "FY26" or t["call"] != "Feb 2026")


@pytest.mark.parametrize("raw,expected", [("FY27", "FY27"), ("FY 2027", "FY27"), ("fy'27", "FY27"), ("H2 FY27", "H2FY27"),
                                          ("FY27Q3", "Q3FY27"), ("medium_term", "medium_term"), ("next few years", "unspecified")])
def test_period_labels_are_normalised(raw, expected):
    t = T.Transcript("Oct 2026", "2026-10", "Sep 2026", "u", [], [], "")
    assert P.normalise_period(raw, t) == expected


def test_rosters_of_both_calls_in_one_file_are_merged():
    cfg = research_cfg()["transcripts"]
    text = fixture_text("https://example.test/infy-2026-10.pdf") + (
        "\n Q2 FY27 Earnings Conference Call\n CORPORATE PARTICIPANTS:\n Salil Parekh\n Chief Executive Officer\n"
        " Sandeep Mahindroo\n Financial Controller and Head Investor Relations\n ANALYSTS\n Kumar Rakesh\n"
        " BNP Paribas Mutual Fund\n Moderator\n Ladies and gentlemen, welcome.\n")
    names, start = T.management_roster(text, cfg["roster_start"], cfg["roster_end"])
    assert names == ["Salil Parekh", "Jayesh Sanghrajka", "Rishi Basu", "Sandeep Mahindroo"]
    assert 0 < start < 20


# ---------------------------------------------------------------- review fixes (cases from the INFY run)

def _t(period, month, quarter, kind="earnings"):
    return T.Transcript(period, month, quarter, "u", [], [], "", kind=kind)


def test_full_year_means_the_calls_own_fiscal_year_unless_the_quote_names_another():
    oct25, oct26, apr26 = _t("Oct 2025", "2025-10", "Sep 2025"), _t("Oct 2026", "2026-10", "Sep 2026"), _t("Apr 2026", "2026-04", "Mar 2026")
    quote = "The new guidance is growth between 2% and 3% in constant currency terms for the full year."
    assert P.resolve_period("FY27", quote, oct25)[0] == "FY26"          # the model said FY27
    assert P.resolve_period("FY27", "contribute over 1% revenue growth in the coming financial year.", oct26)[0] == "FY28"
    assert P.resolve_period("FY26", "Our operating margin guidance for financial year '27 is 20% to 22%.", apr26)[0] == "FY27"
    assert P.resolve_period("FY27", "guidance of 2% to 3% for FY2026-27", oct25)[0] == "FY27"
    assert P.resolve_period("FY27", "margin of 20% to 22% for the full year", apr26)[0] == "FY27"  # a Q4 call talks about the year ahead


def test_oct_2025_guidance_lands_in_fy26_and_the_fy27_path_starts_in_fy27():
    doc = _build(ScriptedModel(judge_replies=GOOD_JUDGE))
    fy26_margin = _entry(doc, "operating_margin", "FY26")
    assert [s["call"] for s in fy26_margin["statements"]] == ["Oct 2025", "Jan 2026"]
    fy27_rev = _entry(doc, "revenue_growth", "FY27")
    assert fy27_rev["revision_path"] == "1.5–3.5% → 1.5–3% → 1–2%" and fy27_rev["revision_direction"] == "cut"
    assert "Oct 2025" not in [s["call"] for s in fy27_rev["statements"]]
    fy26_rev = _entry(doc, "revenue_growth", "FY26")
    assert fy26_rev["revision_path"] == "2–3% → 3–3.5%" and fy26_rev["revision_direction"] == "raised"


def _without_stated_cc(url):
    text = fixture_text(url)
    return text.replace("We had growth of 3.1% for the full year in constant currency\nterms.", "")


def test_constant_currency_guide_is_not_delivered_on_rupee_growth():
    judge = {**GOOD_JUDGE, "revenue_growth:FY26": {"verdict": "Delivered", "evidence_ids": [], "rationale": "Revenue grew 9.61% YoY."}}
    doc = _build(ScriptedModel(judge_replies=judge), get_text=_without_stated_cc)
    e = _entry(doc, "revenue_growth", "FY26")
    assert all(s["basis"] == "constant_currency" for s in e["statements"])  # from the quote, not the model
    assert e["check"]["comparable"] is False and e["verdict"] == "Unverified"
    assert not any("basis not stated" in n for n in e["notes"])


def test_constant_currency_guide_is_delivered_on_the_stated_cc_actual():
    # The judge says Unverified, Missed or Delivered: the year-end call's own sentence decides.
    for said in ("Unverified", "Missed", "Delivered"):
        judge = {**GOOD_JUDGE, "revenue_growth:FY26": {"verdict": said, "evidence_ids": [], "rationale": "As stated."}}
        e = _entry(_build(ScriptedModel(judge_replies=judge)), "revenue_growth", "FY26")
        assert e["verdict"] == "Delivered" and e["stated"]["actual"] == 3.1
        assert e["actual_quote"]["call"] == "Apr 2026" and e["actual_quote"]["found_by"] == "python"
        assert "constant currency" in e["actual_quote"]["text"]
        assert e["chart"]["actual"] == {"value": 3.1, "kind": "stated", "label": "Stated by Salil Parekh, Apr 2026", "complete": True}


def test_reported_actual_is_not_a_promise_and_targets_parse_cleanly():
    doc = _build(ScriptedModel(judge_replies=GOOD_JUDGE))
    assert any(d["quote"].startswith("DSO") and "reported result" in d["reason"] for d in doc["dropped"])
    hiring = [e for e in doc["ledger"] if e["metric"] == "other" and e["period"] == "FY27"]
    assert len(hiring) == 1  # "net headcount" and "college graduates" are the same 20,000 target
    assert [s["target_text"] for s in hiring[0]["statements"]] == ["20,000", "20,000"]
    assert hiring[0]["target"]["unit"] is None


def test_rationale_must_use_the_latest_figure():
    g = {"statements": [{"call_month": "2026-07", "quote": "This year, we have a plan to recruit 20,000 college graduates."},
                        {"call_month": "2026-10", "quote": "We hired about 13,000 freshers in H1 in line with our target of approximately 20,000 for FY27."}]}
    ev = {"evidence": [{"kind": "transcript", "call_month": "2026-07", "text": "We have hired about 8,000 graduates so far."}]}
    assert L.stale_numbers(g, ev, "Only 8,000 hired so far, against 20,000.") == [8000.0]
    assert L.stale_numbers(g, ev, "13,000 hired in H1 against a 20,000 target.") == []


def test_investor_day_is_dated_not_a_second_q3_call():
    doc = _build(ScriptedModel(judge_replies=GOOD_JUDGE))
    calls = {t["call"]: t for t in doc["transcripts"]}
    assert calls["Feb 2026"]["kind"] == "event" and calls["Feb 2026"]["fiscal"] == "FY26" and calls["Feb 2026"]["quarter"] is None
    q3 = [t for t in doc["transcripts"] if t["fiscal"] == "Q3 FY26"]
    assert [t["call"] for t in q3] == ["Jan 2026"]


def test_track_record_is_counted_in_python():
    doc = _build(ScriptedModel(judge_replies=GOOD_JUDGE))
    tr = doc["track_record"]
    assert tr["counts"]["Delivered"] == sum(1 for e in doc["ledger"] if e["verdict"] == "Delivered")
    assert tr["checkable"] == tr["counts"]["Delivered"] + tr["counts"]["Missed"] + tr["counts"]["Unverified"]
    assert tr["text"].startswith(f"{tr['checkable']} checkable promise")
    assert "revised along the way" in tr["text"]


# ---------------------------------------------------------------- other transcript layouts (POLYCAB, KPIT, ETERNAL runs)

def _chorus(cfg=None):
    cfg = cfg or research_cfg()
    text = (FIXDIR / "chorus_style.txt").read_text(encoding="utf-8")
    return T.read({"period": "Oct 2026", "month": "2026-10", "transcript_url": "u"}, "t1", cfg, lambda _u: text)


def test_chorus_layout_roster_header_and_speakers():
    t = _chorus()
    assert t.error is None
    assert t.management == ["NIKHIL JAISINGHANI", "NIYANT MARU", "SHASHANK YAGNICK"]  # not the company, not "MR.SHASHANK"
    speakers = {p.speaker for p in t.passages}
    assert "Polycab India Limited" not in speakers  # the running page header is not a speaker
    mgmt = {p.speaker for p in t.passages if p.management}
    assert mgmt == {"Niyant Maru", "Nikhil Jaisinghani", "Shashank Yagnick"}
    # The broker host, "CA Garvit" (introduced with a title) and "Shrenik B" (an initial) are not the company.
    assert not ({"Rahul Jain", "Garvit", "Shrenik B"} & mgmt)


def test_analyst_words_are_never_a_promise():
    t = _chorus()
    analyst = next(p for p in t.passages if p.speaker == "Garvit")
    raw = {"promises": [{"metric": "operating_margin", "metric_text": "aspiration", "target_low": 22, "target_high": 24,
                         "unit": "%", "basis": "unspecified", "period": "FY29", "passage_id": analyst.id,
                         "quote": "During the Analyst Day, you spoke about an aspiration of achieving 22% to 24% by FY '29."}]}
    kept, dropped = P.check_promises(raw, t, t.passages, research_cfg())
    assert kept == [] and "not management" in dropped[0]["reason"]
    # Even if the transcript mislabelled the speaker, "you spoke about..." is reported speech.
    for p in t.passages:
        p.management = True
    kept, dropped = P.check_promises(raw, t, t.passages, research_cfg())
    assert kept == [] and "analyst" in dropped[0]["reason"]


def test_segment_target_is_never_judged_on_company_figures():
    t = _chorus()
    p = next(x for x in t.passages if "this business" in x.text.replace("\n", " "))
    raw = {"promises": [{"metric": "operating_margin", "metric_text": "margin guidance", "target_low": 11, "target_high": 13,
                         "unit": "%", "basis": "unspecified", "period": "medium_term", "passage_id": p.id, "scope": "company",
                         "quote": "We continue to maintain our medium- to long-term margin guidance of 11% to 13% for this business."}]}
    kept, _ = P.check_promises(raw, t, t.passages, research_cfg())
    assert kept[0]["scope"] == "a business segment"
    g = P.group(kept)[0]
    ev = L.build_evidence(g, infy_record(), [t], research_cfg())
    assert ev["allowed"] == ["Pending", "Unverified"]  # an ongoing range has no moment of delivery
    entry = L.finalise(g, ev, {"verdict": "Delivered", "evidence_ids": [], "rationale": "13.3% beats it."}, "m", research_cfg())
    assert entry["verdict"] == "Pending" and entry["verdict_by"] == "rules"


def test_screener_figure_far_outside_the_range_is_not_used():
    # ETERNAL: "a 15% sort of year-on-year growth" for FY26 against 168% reported revenue growth.
    st = {"call": "Oct 2025", "call_month": "2025-10", "fiscal": "Q2 FY26", "speaker": "CFO", "quote": "we're expecting a 15% sort of year-on-year growth",
          "target_text": "15%", "target_low": 15.0, "target_high": 15.0, "unit": "%", "basis": "unspecified", "scope": "company",
          "quote_score": 100, "source_url": "u", "metric_label": "Revenue growth", "metric_text": "growth"}
    g = {"id": "g1", "metric": "revenue_growth", "metric_label": "Revenue growth", "metric_text": "growth", "scope": "company",
         "period": "FY26", "revised": False, "path": None, "direction": None, "statements": [st], "latest": st}
    rec = infy_record()
    rows = rec["views"]["consolidated"]["tables"]["quarters"]["rows"]["Sales"]
    rec["views"]["consolidated"]["tables"]["quarters"]["rows"]["Sales"] = [v * (2.7 if i >= 4 else 1) for i, v in enumerate(rows)]
    ev = L.build_evidence(g, rec, [], research_cfg())
    assert ev["check"]["comparable"] is False and any("far outside" in n for n in ev["notes"])
    entry = L.finalise(g, ev, {"verdict": "Delivered", "evidence_ids": [], "rationale": "Beat it."}, "m", research_cfg())
    assert entry["verdict"] == "Unverified"


def test_quoted_actual_about_another_period_is_dropped():
    doc = _build(ScriptedModel(judge_replies=GOOD_JUDGE))
    gid = _entry(doc, "operating_margin", "FY26")["id"]
    ev_id = next(e["id"] for e in _entry(doc, "operating_margin", "FY26")["evidence"] if e["kind"] == "transcript" and e["call"] == "Oct 2026")
    judge = {**GOOD_JUDGE, "operating_margin:FY26": {"verdict": "Delivered", "evidence_ids": [ev_id], "rationale": "Margin 21%.",
                                                     "actual_quote": "Operating margin was stable at 21%.", "actual_evidence_id": ev_id}}
    e = _entry(_build(ScriptedModel(judge_replies=judge)), "operating_margin", "FY26")
    assert gid and any("different period" in n for n in e["notes"])
    assert e["actual_quote"] is None or e["actual_quote"]["call"] == "Apr 2026"


def test_duplicate_transcript_is_skipped():
    rec = infy_record()
    rec["documents"]["concalls"].append({"period": "Jan 2026", "month": "2026-01", "transcript_url": "https://example.test/infy-2026-01.pdf?copy=1"})
    cfg = research_cfg()
    cfg["transcripts"]["count"] = 7
    doc = build_research("INFY", rec, cfg, lambda u: fixture_text(u.split("?")[0]), ScriptedModel(judge_replies=GOOD_JUDGE))
    dups = [t for t in doc["transcripts"] if (t["error"] or "").startswith("duplicate of")]
    assert [t["call"] for t in dups] == ["Jan 2026"] and dups[0]["error"] == "duplicate of the Jan 2026 transcript"
    assert len(doc["transcripts"]) == 7
