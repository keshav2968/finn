"""Management card on four real filings (Titan, Federal Bank, KPIT, L&T) plus
synthetic ones for the warning flags. The extractions are what a correct model
returns; the tests check Python's grounding checks and flags."""

import json

import jsonschema
import pytest
from conftest import FIXTURES
from push_helpers import cfg

from llm.router import LLMError, LLMResult, estimate_tokens
from push.management import build_card, extract, management_settings, schema, source_text, system_prompt, user_prompt

FILINGS = {f["symbol"]: f for f in json.loads((FIXTURES / "management_filings.json").read_text("utf-8"))["filings"]}
MCFG = management_settings(cfg())


def person(name, role, level, change, effective=None, reason=None, prior=(), entity=None, tenure=None):
    return {"name": name, "role": role, "role_level": level, "change": change, "entity": entity,
            "effective_date": effective, "stated_reason": reason, "prior_roles": list(prior), "tenure": tenure}


ANSWERS = {
    "TITAN": {"summary": "Noel N. Tata retires as Non-Executive Director and Vice-Chairman from 12 November 2026.",
              "people": [person("Noel N. Tata", "Non-Executive, Non-Independent Director and Vice-Chairman", "chair", "retirement",
                                "2026-11-12", "In accordance with the Tata Group Governance Guidelines")]},
    "FEDERALBNK": {"summary": "Rajesh Varrier appointed Additional (Independent) Director for three years from 16 October 2026.",
                   "people": [person("Rajesh Varrier", "Additional Director (Non-Executive Independent Director)", "independent_director",
                                     "appointment", "2026-10-16", None,
                                     ["President, Global Operations, Cognizant", "EVP, Head of Global Services and Infosys Americas",
                                      "CIO and Digital Officer, Aditya Birla Sun Life Insurance"], tenure="3 years")]},
    "KPITTECH": {"summary": "Chairman Anant Talaulicar appointed to the board of material subsidiary KPIT Technologies Inc.",
                 "people": [person("Anant Talaulicar", "Independent Director", "independent_director", "appointment", "2026-10-28",
                                   "Pursuant to Regulation 24(1) of the SEBI Listing Regulations", entity="KPIT Technologies Inc.")]},
    "LT": {"summary": "Four officials promoted to Senior Vice President and categorised as senior management.",
           "people": [
               person("C Jayakumar", "Senior Vice President & Head - Corporate Human Resources", "senior_management", "promotion",
                      "2026-07-01", "Promoted as Senior Vice President", ["CHRO of L&T Ltd."]),
               person("Suresh Kumar Narang", "Senior Vice President & IC Head - CarbonLite Solutions IC", "senior_management",
                      "promotion", "2026-07-01", "Promoted as Senior Vice President",
                      ["Project Director – Nabha Power", "Chief Executive of Nabha Power Ltd (2021-2026)"]),
               person("S Ramkumar", "Senior Vice President & IC Head - Transportation Infrastructure IC", "senior_management",
                      "promotion", "2026-07-01", "Promoted as Senior Vice President"),
               person("Sriraman T", "Senior Vice President & IC Head - Residential, Commercial Buildings & Factories IC",
                      "senior_management", "promotion", "2026-07-01", "Promoted as Senior Vice President",
                      ["Graduate Engineer Trainee"]),
           ]},
}


def text_for(sym):
    f = FILINGS[sym]
    return source_text(f, f["pdf_text"], MCFG["max_text_chars"])


def card_for(sym, answer=None):
    return build_card(FILINGS[sym], answer or ANSWERS[sym], text_for(sym), MCFG)


@pytest.mark.parametrize("sym", list(ANSWERS))
def test_answers_match_the_schema_and_prompt_fits_groq(sym):
    jsonschema.validate(ANSWERS[sym], schema())
    tokens = estimate_tokens(system_prompt() + json.dumps(schema()) + user_prompt(FILINGS[sym], text_for(sym)))
    assert tokens + 1500 <= 8000, tokens


def test_titan_vice_chair_retires_no_red_flags():
    c = card_for("TITAN")
    [p] = c["people"]
    assert (p["name"], p["direction"], p["effective_date"], p["at_subsidiary"]) == ("Noel N. Tata", "leaving", "2026-11-12", False)
    assert p["stated_reason"].startswith("In accordance with the Tata Group")
    assert c["flags"] == [] and c["severity"] == "normal" and c["status"] == "ok"  # chair leaving: worth a look, not a red flag


def test_federal_bank_independent_director_with_prior_roles():
    c = card_for("FEDERALBNK")
    [p] = c["people"]
    assert p["direction"] == "joining" and p["tenure"] == "3 years"
    assert "CIO and Digital Officer, Aditya Birla Sun Life Insurance" in p["prior_roles"]
    assert c["severity"] == "low" and c["notes"] == []


def test_kpit_subsidiary_board_seat_is_marked_and_low():
    c = card_for("KPITTECH")  # OCR splits the name ("T alau li car") in the PDF; grounding still finds it
    [p] = c["people"]
    assert p["at_subsidiary"] and p["entity"] == "KPIT Technologies Inc." and c["severity"] == "low"


def test_lt_four_promotions():
    c = card_for("LT")
    assert [p["name"] for p in c["people"]] == ["C Jayakumar", "Suresh Kumar Narang", "S Ramkumar", "Sriraman T"]
    assert all(p["direction"] == "joining" and p["effective_date"] == "2026-07-01" for p in c["people"])
    assert c["people"][1]["prior_roles"] == ["Project Director – Nabha Power", "Chief Executive of Nabha Power Ltd (2021-2026)"]
    assert c["flags"] == [] and c["severity"] == "low"


def test_made_up_names_reasons_and_roles_are_dropped():
    bad = json.loads(json.dumps(ANSWERS["TITAN"]))
    bad["people"][0]["stated_reason"] = "Disagreement with the board over strategy"
    bad["people"][0]["prior_roles"] = ["Chairman of Tata Sons"]
    bad["people"].append(person("Ratan Tata", "Chairman Emeritus", "chair", "retirement"))
    c = build_card(FILINGS["TITAN"], bad, text_for("TITAN"), MCFG)
    assert [p["name"] for p in c["people"]] == ["Noel N. Tata"]
    assert c["people"][0]["stated_reason"] is None and c["people"][0]["prior_roles"] == []
    notes = " | ".join(c["notes"])
    assert "Dropped 'Ratan Tata'" in notes and "isn't worded like that" in notes and "prior role 'Chairman of Tata Sons'" in notes


CFO_FILING = {"id": "cfo-1", "symbol": "ACME", "datetime": "2026-11-14T18:00:00+05:30",
              "title": "Announcement under Regulation 30 (LODR)-Resignation of Chief Financial Officer",
              "detail": "Mr. Arun Mehta, Chief Financial Officer, has resigned with effect from November 14, 2026 due to personal reasons.",
              "more": None, "pdf_url": None}


def test_cfo_resigning_mid_quarter_for_personal_reasons_raises_all_three_flags():
    answer = {"summary": "CFO Arun Mehta resigns.", "people": [
        person("Arun Mehta", "Chief Financial Officer", "cfo", "resignation", "2026-11-14", "personal reasons")]}
    c = build_card(CFO_FILING, answer, source_text(CFO_FILING, "", 9000), MCFG)
    assert [f["code"] for f in c["flags"]] == ["cfo_exit", "vague_reason", "mid_quarter"]
    assert c["severity"] == "high" and c["flags"][0]["name"] == "Arun Mehta"


def test_quarter_end_exit_with_a_reason_and_no_reason_cases():
    end = {"summary": "x", "people": [person("Arun Mehta", "Chief Financial Officer", "cfo", "resignation", "2026-12-31",
                                             "to take up the position of CFO at a larger group company")]}
    filing = dict(CFO_FILING, detail=CFO_FILING["detail"] + " He leaves to take up the position of CFO at a larger group company.")
    c = build_card(filing, end, source_text(filing, "", 9000), MCFG)
    assert [f["code"] for f in c["flags"]] == ["cfo_exit"]  # specific reason, at quarter end
    none_given = {"summary": "x", "people": [person("Arun Mehta", "Chief Financial Officer", "cfo", "resignation", None, None)]}
    c = build_card(CFO_FILING, none_given, source_text(CFO_FILING, "", 9000), MCFG)
    assert [f["code"] for f in c["flags"]] == ["cfo_exit", "vague_reason"]


def test_failures_give_an_unavailable_card():
    class Down:
        def complete_json(self, *a, **k):
            raise LLMError("extract_management", ["groq: 503", "gemini: 503"])

    with pytest.raises(LLMError):
        extract(FILINGS["LT"], text_for("LT"), Down().complete_json)
    c = build_card(FILINGS["LT"], None, text_for("LT"), MCFG, error="Extraction failed: groq: 503")
    assert c["status"] == "unavailable" and c["summary"] == "Changes in Senior Management" and c["notes"] == ["Extraction failed: groq: 503"]
    empty = build_card(FILINGS["LT"], {"people": [], "summary": "No changes."}, text_for("LT"), MCFG)
    assert empty["status"] == "no_people"


def test_extract_passes_the_task_and_schema():
    seen = {}

    def complete(task, system, user, sch, pdf=None, label=""):
        seen.update(task=task, user=user, label=label)
        jsonschema.validate(ANSWERS["KPITTECH"], sch)
        return LLMResult(ANSWERS["KPITTECH"], "groq", "openai/gpt-oss-20b", 900, 120, False, [])

    data, model = extract(FILINGS["KPITTECH"], text_for("KPITTECH"), complete)
    assert seen["task"] == "extract_management" and "Talaulicar" in seen["user"] and model == "groq/openai/gpt-oss-20b"
    assert seen["label"].startswith("KPITTECH:")


def test_letterhead_lines_are_trimmed():
    t = source_text({"title": "x", "detail": None}, "BSE Limited\nPhiroze Jeejeebhoy Towers\nMr. A B appointed\nYours faithfully,", 9000)
    assert "Phiroze" not in t and "Mr. A B appointed" in t
