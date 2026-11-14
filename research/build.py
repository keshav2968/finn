"""One company's research file: numbers (Python only) + the promise ledger.

Every stage records its own failure and the run carries on: no transcripts, an unreadable
PDF, a model that is down or a ticker with no guidance all produce a valid file with a
`status` and notes, never an exception.
"""

from __future__ import annotations

from typing import Any, Callable

from ingest.common import iso_ist, now_ist

from . import ledger as L
from . import promises as P
from . import transcripts as T
from .numbers import build_numbers

SCHEMA_VERSION = 1


def build_research(
    symbol: str,
    record: dict[str, Any],
    cfg: dict[str, Any],
    get_text: Callable[[str], str],
    complete: Callable[..., Any] | None,
    log: Callable[[str], None] = lambda _m: None,
) -> dict[str, Any]:
    company = record.get("name") or symbol
    out: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "symbol": symbol,
        "name": company,
        "generated_at": iso_ist(now_ist()),
        "status": "ok",
        "notes": [],
        "numbers": None,
        "transcripts": [],
        "ledger": [],
        "dropped": [],
        "models": [],
        "sources": {"screener": None, "transcripts": []},
    }

    try:
        out["numbers"] = build_numbers(record)
        out["sources"]["screener"] = out["numbers"]["source"]
    except Exception as exc:  # noqa: BLE001
        out["notes"].append(f"numbers unavailable: {type(exc).__name__}: {exc}"[:200])

    calls = T.select(record.get("documents") or {}, int(cfg["transcripts"]["count"]))
    if not calls:
        out["status"] = "no_transcripts"
        out["notes"].append("screener.in lists no earnings-call transcripts for this company, so there is no promise ledger.")
        return out

    transcripts: list[T.Transcript] = []
    seen: dict[str, str] = {}
    for i, call in enumerate(calls, 1):
        log(f"transcript {call.get('period')}: reading")
        t = T.read(call, f"t{i}", cfg, get_text)
        # screener sometimes lists the same transcript twice under different links.
        fp = T.fingerprint(t)
        if fp and fp in seen:
            t.error, t.passages = f"duplicate of the {seen[fp]} transcript", []
        elif fp:
            seen[fp] = t.period
        transcripts.append(t)

    promises: list[dict[str, Any]] = []
    for t in transcripts:
        sent = T.forward_passages(t.passages, cfg) if not t.error else []
        info = {"call": t.period, "kind": t.kind, "label": t.label, "quarter": t.quarter, "fiscal": t.fiscal, "url": t.url, "error": t.error,
                "management": t.management, "passages": len(t.passages), "sent": len(sent),
                "sent_chars": sum(len(p.text) for p in sent), "promises": 0}
        if not t.error and sent and complete is not None:
            try:
                found, dropped, model = P.extract(company, t, sent, cfg, complete)
                promises += found
                out["dropped"] += dropped
                info["promises"] = len(found)
                if model not in out["models"]:
                    out["models"].append(model)
                log(f"transcript {t.period}: {len(sent)} passages sent, {len(found)} promises kept, {len(dropped)} dropped")
            except Exception as exc:  # noqa: BLE001 - one transcript must never stop the run
                info["error"] = f"extraction failed: {type(exc).__name__}: {str(exc)[:160]}"
                log(info["error"])
        elif not t.error and not sent:
            info["error"] = "no forward-looking passages found"
        out["transcripts"].append(info)
        out["sources"]["transcripts"].append({"call": t.period, "url": t.url})

    if complete is None:
        out["status"] = "numbers_only"
        out["notes"].append("run without a model: numbers and transcript filtering only.")
        return out
    if not promises:
        out["status"] = "no_promises"
        readable = sum(1 for t in transcripts if not t.error)
        out["notes"].append(f"no measurable forward-looking promises found in {readable} readable transcript(s).")
        return out

    groups = P.group(promises)
    entries, errors = L.judge(company, groups, record, transcripts, cfg, complete, log)
    out["ledger"] = entries
    out["notes"] += errors
    for e in entries:
        if e["verdict_by"] not in ("rules",) and e["verdict_by"] not in out["models"]:
            out["models"].append(e["verdict_by"])
    out["summary"] = {v: sum(1 for e in entries if e["verdict"] == v) for v in L.VERDICTS}
    out["track_record"] = track_record(entries, sum(1 for t in out["transcripts"] if t["promises"]))
    return out


def _n(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def track_record(entries: list[dict[str, Any]], calls: int) -> dict[str, Any]:
    """Counts of verdicts, in Python. "Checkable" means the period has ended (or has no end
    date) and a verdict on the outcome was possible; nothing is weighted or scored."""
    count = {v: sum(1 for e in entries if e["verdict"] == v) for v in L.VERDICTS}
    ended = [e for e in entries if e["period_status"] == "period ended"]
    checkable = len(ended)
    outcome_count = {v: sum(1 for e in ended if e["verdict"] == v) for v in ("Delivered", "Missed", "Unverified")}
    open_ended = sum(1 for e in entries if e["period_status"] == "no end date")
    revised = sum(1 for e in entries if e["revised"])
    parts = []
    if checkable:
        outcome = ", ".join(f"{outcome_count[v]} {v.lower()}" for v in ("Delivered", "Missed", "Unverified") if outcome_count[v])
        parts.append(f"{_n(checkable, 'checkable promise')}: {outcome}")
    else:
        parts.append("No checkable promises yet")
    running = sum(1 for e in entries if e["period_status"].startswith("in progress"))
    if running:
        extra = f", {count['Goalposts moved']} with goalposts moved" if count["Goalposts moved"] else ""
        parts.append(f"{running} still running{extra}")
    if open_ended:
        parts.append(f"{open_ended} open-ended")
    if revised:
        parts.append(f"{_n(revised, 'target')} revised along the way")
    return {"promises": len(entries), "calls": calls, "checkable": checkable, "open_ended": open_ended, "revised": revised,
            "counts": count, "text": " · ".join(parts)}
