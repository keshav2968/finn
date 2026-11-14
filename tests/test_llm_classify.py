import json

from pdf_maker import make_pdf
from push_helpers import cfg, filings, find

from llm.router import LLMError, LLMResult, schema_error
from push.classify import classify_all, load_llm_cache
from push.llm_classify import classification_schema, classify_items, merge_into_cache, system_prompt, user_prompt


class FakeRouter:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def complete_json(self, task, system, user, schema, pdf=None, label=""):
        self.calls.append({"task": task, "system": system, "user": user, "schema": schema, "pdf": pdf, "label": label})
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        assert schema_error(a, schema) is None  # the real router guarantees this
        return LLMResult(a, "groq", "openai/gpt-oss-20b", 10, 5, False, [])


def pending_items():
    items = [
        find("FEDERALBNK", "Disclosure Under Regulation 30 Of SEBI (LODR) Regulations 2015", "2026-11-13"),
        find("BAJFINANCE", "Regulation 8 of SEBI PIT"),
    ]
    for i, it in enumerate(items):
        it["pdf_url"] = it.get("pdf_url") or f"https://www.bseindia.com/stockinfo/AnnPdfOpen.aspx?Pname=test{i}.pdf"
    return items


def test_schema_and_prompts_are_built_from_config():
    schema = classification_schema(cfg())
    assert set(schema["properties"]["category"]["enum"]) == set(cfg().categories)
    sp = system_prompt(cfg())
    assert "- litigation: Lawsuits" in sp and "never calculate" in sp
    up = user_prompt(pending_items()[0], "page text here")
    assert "FEDERALBNK" in up and "page text here" in up


def test_pdf_text_goes_in_the_prompt_and_scans_go_as_bytes():
    text_pdf = make_pdf([["Intimation of acquisition of 26% stake in a solar SPV"]])
    scan_pdf = make_pdf([[""]])
    pdfs = iter([text_pdf, scan_pdf])
    router = FakeRouter([
        {"category": "M&A", "kind": "event", "confidence": 0.9, "summary": "Acquires 26% of a solar SPV."},
        {"category": "press_release", "kind": "event", "confidence": 0.7, "summary": "Quarterly business update."},
    ])
    out = classify_items(pending_items(), cfg(), router.complete_json, lambda url: next(pdfs))
    assert "26% stake in a solar SPV" in router.calls[0]["user"] and router.calls[0]["pdf"] is None
    assert router.calls[1]["pdf"] == scan_pdf
    assert [o.entry["source"] for o in out] == ["filing text + PDF", "scanned PDF"]
    assert out[0].entry["model"] == "groq/openai/gpt-oss-20b" and out[0].entry["category"] == "M&A"


def test_one_failure_does_not_stop_the_rest_and_missing_pdf_is_noted():
    router = FakeRouter([LLMError("classify_filing", ["groq: down", "gemini: down"]),
                         {"category": "press_release", "kind": "event", "confidence": 0.8, "summary": "Business update."}])

    def broken_pdf(url):
        from ingest.pdfs import PdfError
        raise PdfError("404")

    out = classify_items(pending_items(), cfg(), router.complete_json, broken_pdf)
    assert out[0].entry is None and "failed" in out[0].note
    assert out[1].entry["source"].startswith("filing text (PDF unavailable")


def test_answers_flow_into_the_feed_and_low_confidence_is_ignored(tmp_path):
    fed, baj = pending_items()
    router = FakeRouter([
        {"category": "capex", "kind": "event", "confidence": 0.85, "summary": "Board approves a new data centre."},
        {"category": "press_release", "kind": "event", "confidence": 0.3, "summary": "Unclear disclosure."},
    ])
    path = tmp_path / "llm.json"
    out = classify_items([fed, baj], cfg(), router.complete_json, None)
    assert merge_into_cache(path, out) == 2
    stored = json.loads(path.read_text("utf-8"))["items"]
    assert set(stored) == {fed["id"], baj["id"]}
    cache = load_llm_cache(path, cfg())
    classes = classify_all(filings(), cfg(), cache)
    assert (classes[fed["id"]].category, classes[fed["id"]].method, classes[fed["id"]].summary) == ("capex", "llm", "Board approves a new data centre.")
    assert classes[baj["id"]].pending  # 0.3 < llm_min_confidence


def test_merge_keeps_earlier_answers(tmp_path):
    path = tmp_path / "llm.json"
    path.write_text(json.dumps({"items": {"old-id": {"category": "results"}}}), encoding="utf-8")
    merge_into_cache(path, [])
    assert "old-id" in json.loads(path.read_text("utf-8"))["items"]
