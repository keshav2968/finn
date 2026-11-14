import json

import pytest

from llm.router import Budget, LLMError, Router, extract_json, schema_error

SCHEMA = {
    "type": "object",
    "required": ["category"],
    "additionalProperties": False,
    "properties": {"category": {"enum": ["results", "capex"]}},
}

CONFIG = {
    "providers": {
        "groq": {"kind": "openai_compatible", "base_url": "https://groq.test/v1", "api_key_env": "GROQ_API_KEY", "pdf_input": False},
        "gemini": {"kind": "gemini", "base_url": "https://gemini.test/v1beta", "api_key_env": "GOOGLE_API_KEY", "pdf_input": True},
    },
    "limits": {"groq/small": {"tpm": 3000, "rpm": 30, "tpd": 10000}, "gemini/flash": {"tpm": 100000, "rpm": 15, "tpd": 1000000}},
    "max_wait_seconds": 30,
    "timeout_seconds": 5,
    "tasks": {
        "classify": {
            "temperature": 0,
            "max_output_tokens": 200,
            "chain": [
                {"provider": "groq", "model": "small", "params": {"reasoning_effort": "low"}},
                {"provider": "gemini", "model": "flash", "params": {"thinking_budget": 0}},
            ],
        }
    },
    "paths": {"cache_dir": "cache/llm", "usage_log": "usage.jsonl"},
}
ENV = {"GROQ_API_KEY": "g", "GOOGLE_API_KEY": "k"}


def groq_reply(content, pt=100, ct=20):
    return 200, {}, {"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": pt, "completion_tokens": ct}}


def gemini_reply(content, pt=120, ct=25):
    return 200, {}, {"candidates": [{"content": {"parts": [{"text": content}]}}], "usageMetadata": {"promptTokenCount": pt, "candidatesTokenCount": ct}}


class FakeTransport:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append({"url": url, "headers": headers, "payload": payload})
        return self.replies.pop(0)


class Clock:
    def __init__(self):
        self.t = 1000.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def make(tmp_path, replies, env=ENV, config=CONFIG):
    clock = Clock()
    transport = FakeTransport(replies)
    r = Router(config, dict(env), root=tmp_path, transport=transport, clock=clock.now, sleep=clock.sleep, today=lambda: "2026-11-14")
    return r, transport, clock


def usage(tmp_path):
    return [json.loads(line) for line in (tmp_path / "usage.jsonl").read_text("utf-8").splitlines()]


def test_primary_success_payload_and_usage_log(tmp_path):
    r, t, _ = make(tmp_path, [groq_reply('{"category": "results"}')])
    res = r.complete_json("classify", "Classify.", "Filing text", SCHEMA, label="INFY:1")
    assert res.data == {"category": "results"} and (res.provider, res.model) == ("groq", "small")
    call = t.calls[0]
    assert call["url"] == "https://groq.test/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer g"
    p = call["payload"]
    assert p["response_format"] == {"type": "json_object"} and p["reasoning_effort"] == "low"
    assert p["max_completion_tokens"] == 200 and '"enum": ["results", "capex"]' in p["messages"][0]["content"]
    [u] = usage(tmp_path)
    assert (u["task"], u["provider"], u["input_tokens"], u["output_tokens"], u["cached"], u["label"]) == ("classify", "groq", 100, 20, False, "INFY:1")


def test_cache_answers_identical_requests_without_a_call(tmp_path):
    r, t, _ = make(tmp_path, [groq_reply('{"category": "capex"}')])
    r.complete_json("classify", "S", "U", SCHEMA)
    again = r.complete_json("classify", "S", "U", SCHEMA)
    assert again.cached and again.data == {"category": "capex"} and len(t.calls) == 1
    assert [u["cached"] for u in usage(tmp_path)] == [False, True]


def test_invalid_reply_gets_one_repair_on_the_same_model(tmp_path):
    r, t, _ = make(tmp_path, [groq_reply('{"category": "gossip"}'), groq_reply('```json\n{"category": "results"}\n```')])
    res = r.complete_json("classify", "S", "U", SCHEMA)
    assert res.data == {"category": "results"} and res.provider == "groq"
    repair = t.calls[1]["payload"]["messages"]
    assert repair[-2]["role"] == "assistant" and "invalid" in repair[-1]["content"] and "gossip" in repair[-1]["content"]
    assert res.input_tokens == 200  # both calls counted


def test_still_invalid_falls_back_to_the_next_model(tmp_path):
    r, t, _ = make(tmp_path, [groq_reply("not json"), groq_reply('{"category": 1}'), gemini_reply('{"category": "capex"}')])
    res = r.complete_json("classify", "S", "U", SCHEMA)
    assert (res.provider, res.data) == ("gemini", {"category": "capex"})
    gem = t.calls[2]
    assert gem["url"] == "https://gemini.test/v1beta/models/flash:generateContent" and gem["headers"]["x-goog-api-key"] == "k"
    assert gem["payload"]["generationConfig"]["responseMimeType"] == "application/json"
    assert gem["payload"]["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}
    assert any("failed the schema twice" in a for a in res.attempts)


def test_rate_limit_retries_after_the_header_then_falls_back(tmp_path):
    r, t, clock = make(tmp_path, [(429, {"Retry-After": "7"}, {"error": {"message": "slow down"}}), groq_reply('{"category": "results"}')])
    assert r.complete_json("classify", "S", "U1", SCHEMA).provider == "groq"
    assert clock.slept == [7.0]
    r2, t2, _ = make(tmp_path, [(429, {"Retry-After": "600"}, {}), gemini_reply('{"category": "results"}')])
    assert r2.complete_json("classify", "S", "U2", SCHEMA).provider == "gemini"  # too long to wait
    failed = [u for u in usage(tmp_path) if not u["ok"]]
    assert failed and "HTTP 429" in failed[0]["error"]


def test_missing_key_pdf_and_oversized_inputs_skip_to_gemini(tmp_path):
    r, t, _ = make(tmp_path, [gemini_reply('{"category": "results"}')], env={"GOOGLE_API_KEY": "k"})
    assert r.complete_json("classify", "S", "U", SCHEMA).provider == "gemini"
    r, t, _ = make(tmp_path, [gemini_reply('{"category": "results"}')])
    res = r.complete_json("classify", "S", "U", SCHEMA, pdf=b"%PDF-1.4 scan")
    assert res.provider == "gemini" and "cannot read PDFs" in res.attempts[0]
    assert t.calls[0]["payload"]["contents"][0]["parts"][0]["inline_data"]["mime_type"] == "application/pdf"
    r, t, _ = make(tmp_path, [gemini_reply('{"category": "results"}')])
    res = r.complete_json("classify", "S", "x" * 20000, SCHEMA)  # ~5000 tokens > groq's 3000/min
    assert res.provider == "gemini" and "exceeds its 3000 tokens/min" in res.attempts[0]


def test_daily_budget_counts_todays_log(tmp_path):
    (tmp_path / "usage.jsonl").write_text(
        json.dumps({"date": "2026-11-14", "provider": "groq", "model": "small", "input_tokens": 9900, "output_tokens": 50, "cached": False}) + "\n",
        encoding="utf-8",
    )
    r, t, _ = make(tmp_path, [gemini_reply('{"category": "results"}')])
    res = r.complete_json("classify", "S", "U", SCHEMA)
    assert res.provider == "gemini" and "daily token budget used" in res.attempts[0]


def test_all_failing_raises_with_reasons(tmp_path):
    r, _, _ = make(tmp_path, [(400, {}, {"error": {"message": "bad model"}}), (500, {}, "oops"), (500, {}, "oops")])
    with pytest.raises(LLMError) as exc:
        r.complete_json("classify", "S", "U", SCHEMA)
    assert "HTTP 400: bad model" in exc.value.attempts[0] and "HTTP 500" in exc.value.attempts[1]


def test_only_restricts_the_chain(tmp_path):
    r, t, _ = make(tmp_path, [gemini_reply('{"category": "results"}')])
    assert r.complete_json("classify", "S", "U", SCHEMA, only="gemini/flash").provider == "gemini"
    assert len(t.calls) == 1


def test_budget_waits_for_the_window():
    clock = Clock()
    b = Budget(tpm=1000, rpm=2, tpd=None, used_today=0, clock=clock.now)
    assert b.wait_needed(600) == 0
    b.record(600)
    clock.t += 10
    assert b.wait_needed(600) == pytest.approx(50)   # first event leaves at +60
    assert b.wait_needed(300) == 0
    b.record(300)
    assert b.wait_needed(10) == pytest.approx(50)    # rpm=2 reached
    clock.t += 60
    assert b.wait_needed(1000) == 0
    assert not b.fits_at_all(1001)


def test_json_helpers():
    assert extract_json('Sure! {"a": 1} hope this helps') == {"a": 1}
    assert extract_json('```json\n{"a": 2}\n```') == {"a": 2}
    assert schema_error({"category": "results"}, SCHEMA) is None
    assert "category" in schema_error({"category": "x"}, SCHEMA)


def test_gemini_3_thinking_level_is_sent_instead_of_a_budget(tmp_path):
    cfg = json.loads(json.dumps(CONFIG))
    cfg["tasks"]["classify"]["chain"][1]["params"] = {"thinking_level": "low"}
    r, t, _ = make(tmp_path, [gemini_reply('{"category": "results"}')], config=cfg)
    assert r.complete_json("classify", "S", "U", SCHEMA, only="gemini/flash").provider == "gemini"
    assert t.calls[0]["payload"]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}


def test_network_error_on_one_provider_falls_back(tmp_path):
    from llm.router import ProviderError

    class Flaky(FakeTransport):
        def __call__(self, url, headers, payload, timeout):
            if "groq" in url:
                self.calls.append({"url": url})
                raise ProviderError("network error: ConnectionError", status=599)
            return super().__call__(url, headers, payload, timeout)

    clock = Clock()
    t = Flaky([gemini_reply('{"category": "results"}')])
    r = Router(CONFIG, dict(ENV), root=tmp_path, transport=t, clock=clock.now, sleep=clock.sleep, today=lambda: "2026-11-14")
    res = r.complete_json("classify", "S", "U", SCHEMA)
    assert res.provider == "gemini" and "network error" in res.attempts[0]
