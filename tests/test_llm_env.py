import os

from llm.env import load_env, parse_env


def test_parse_tolerates_real_world_shapes():
    text = (
        "﻿GROQ_API_KEY = gsk_abc123\r\n"
        "GOOGLE_API_KEY=\"AIza-quoted\"\r\n"
        "export EXTRA='single'\n"
        "# comment\n\nNO_EQUALS_LINE\n"
        "WITH_COMMENT=value # trailing note\n"
    )
    assert parse_env(text) == {
        "GROQ_API_KEY": "gsk_abc123",
        "GOOGLE_API_KEY": "AIza-quoted",
        "EXTRA": "single",
        "WITH_COMMENT": "value",
    }


def test_existing_environment_wins(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("FINN_TEST_A = from_file\nFINN_TEST_B=from_file\n", encoding="utf-8")
    monkeypatch.setenv("FINN_TEST_A", "from_ci")
    monkeypatch.delenv("FINN_TEST_B", raising=False)
    load_env(f)
    assert os.environ["FINN_TEST_A"] == "from_ci"
    assert os.environ["FINN_TEST_B"] == "from_file"
    assert load_env(tmp_path / "missing.env") == {}
