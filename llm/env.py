"""Minimal .env loader (no extra dependency).

Tolerates the shapes people actually write: `KEY=value`, `KEY = value`,
`export KEY=value`, quoted values, CRLF line endings, comments. Variables already
set in the environment win, so CI secrets override a local file.
"""

from __future__ import annotations

import os
from pathlib import Path

from ingest.common import REPO_ROOT


def parse_env(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip().lstrip("﻿")
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if key:
            out[key] = value
    return out


def load_env(path: Path | None = None) -> dict[str, str]:
    """Read .env into os.environ (without overwriting) and return what the file held."""
    path = path or REPO_ROOT / ".env"
    if not path.exists():
        return {}
    values = parse_env(path.read_text(encoding="utf-8-sig"))
    for k, v in values.items():
        os.environ.setdefault(k, v)
    return values
