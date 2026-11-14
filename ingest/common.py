"""Small shared helpers: IST time, number parsing, JSON writing, logging."""

from __future__ import annotations

import json
import logging
import math
import os
import re
import tempfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

# India has no daylight saving, so a fixed offset is exact and needs no tz database
# (Windows ships without one).
IST = timezone(timedelta(hours=5, minutes=30), "IST")

REPO_ROOT = Path(__file__).resolve().parents[1]


def now_ist() -> datetime:
    return datetime.now(IST)


def iso_ist(dt: datetime) -> str:
    """ISO-8601 with +05:30 offset, second precision. Naive datetimes are taken as IST."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(IST).replace(microsecond=0).isoformat()


def parse_hhmm(value: str) -> time:
    hours, minutes = value.strip().split(":")
    return time(int(hours), int(minutes))


_NUMBER_JUNK = re.compile(r"[,\s ₹%+]|Cr\.?|Rs\.?", re.IGNORECASE)


def parse_number(text: str | None) -> float | None:
    """Parse screener-style numbers: '1,23,456', '-5', '+12%', '₹ 1,142', '24.5 %'.

    Returns None for blanks and dashes. Indian digit grouping is handled by
    dropping every comma.
    """
    if text is None:
        return None
    cleaned = _NUMBER_JUNK.sub("", str(text))
    cleaned = cleaned.replace("−", "-")  # unicode minus
    if cleaned in {"", "-", "--", "—", "–", "NA", "N/A"}:
        return None
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def clean_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.replace(" ", " ")).strip()


def json_safe(value: Any) -> Any:
    """Recursively replace NaN/inf with None so the output is valid JSON for browsers."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    # numpy scalars without importing numpy here
    if hasattr(value, "item") and callable(value.item):
        try:
            return json_safe(value.item())
        except (TypeError, ValueError):
            return value
    return value


def write_json(path: Path, obj: Any, compact: bool = False) -> None:
    """Atomic UTF-8 JSON write: a crash never leaves a half-written seed file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json_safe(obj)
    if compact:
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    else:
        text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"finn.{name}")


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Third-party chatter (yfinance logs every failed ticker at ERROR level)
    for noisy in ("yfinance", "urllib3", "peewee", "curl_cffi"):
        logging.getLogger(noisy).setLevel(logging.CRITICAL)
