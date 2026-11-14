"""The promise ledger: each promise joined with what actually happened, then a verdict.

Python builds the evidence (screener numbers it computed, and later-call passages where
management states an actual), works out which verdicts are possible, and checks the
verdict the model returns: evidence ids must exist, any quoted actual must match its
source, numbers in the rationale must come from the evidence, and a Delivered/Missed
that contradicts the arithmetic is overridden.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from . import numbers as nums
from . import periods
from .promises import numbers_in, quote_found
from .transcripts import Transcript, _sentences

VERDICTS = ["Delivered", "Missed", "Pending", "Goalposts moved", "Unverified"]
GROWTH = {"revenue_growth", "profit_growth"}


# ---------------------------------------------------------------- evidence

def _comparable(metric: str, basis: str) -> tuple[bool, str | None]:
    if metric in GROWTH and basis in ("constant_currency", "usd"):
        return False, f"guidance is in {basis.replace('_', ' ')} terms; screener reports ₹, so the two are not comparable"
    if metric in GROWTH and basis == "unspecified":
        return True, "basis not stated; compared with reported ₹ growth"
    return True, None


def build_evidence(group: dict[str, Any], record: dict[str, Any], transcripts: list[Transcript], cfg: dict[str, Any]) -> dict[str, Any]:
    metric, period = group["metric"], group["period"]
    mcfg = cfg["metrics"].get(metric) or {}
    latest = group["latest"]
    evidence: list[dict[str, Any]] = []
    notes: list[str] = []

    actual = nums.actual_for(mcfg.get("compute"), period, record)
    check = None
    if actual:
        evidence.append({"id": f"{group['id']}-n1", "kind": "screener", **actual})
        ok, why = _comparable(metric, latest.get("basis") or "unspecified")
        if why:
            notes.append(why)
        low, high = latest["target_low"], latest["target_high"]
        if ok and low is not None and (latest.get("unit") in (None, "%")):
            v = actual["value"]
            pos = "within" if low <= v <= high else ("above" if v > high else "below")
            check = {"comparable": True, "position": pos, "actual": v, "target_low": low, "target_high": high,
                     "complete": actual["complete"], "evidence_id": evidence[-1]["id"]}
        elif low is not None:
            check = {"comparable": False, "position": None, "actual": actual["value"], "target_low": low,
                     "target_high": high, "complete": actual["complete"], "evidence_id": evidence[-1]["id"]}

    # Later calls where management states an actual for this metric: the call right after
    # the period ends first (it reports the full year), then the newest calls.
    first_month = group["statements"][0]["call_month"]
    words = [w.lower() for w in (mcfg.get("aliases") or [])] or sorted(_words_of(group["metric_text"]))
    basis = latest.get("basis") or "unspecified"
    basis_rx = re.compile(r"constant currency|\bcc\b", re.I) if basis == "constant_currency" else None
    later = sorted((t for t in transcripts if t.month >= first_month and t.passages), key=lambda t: t.month, reverse=True)
    end_q = periods.quarters_of(period)[-1] if periods.is_valid(period) else None
    year_end_call = None
    if end_q:
        after = [t for t in later if t.kind == "earnings" and t.quarter == end_q]
        year_end_call = after[0] if after else None
    order = ([year_end_call] if year_end_call else []) + [t for t in later if t is not year_end_call]
    fy_cues = _period_cues(period)
    found = []
    for t in order:
        best, best_score = None, 0
        for p in t.passages:
            if not (p.management and p.has_number):
                continue
            low = p.text.lower()
            if not any(w in low for w in words):
                continue
            score = p.outcome_hits + (3 if basis_rx and basis_rx.search(p.text) else 0) + (2 if any(c in low for c in fy_cues) else 0)
            if (t is year_end_call and ("full year" in low or "for the year" in low)):
                score += 2
            if p.outcome_hits and score > best_score:
                best, best_score = p, score
        if best is not None:
            found.append((t, best))
        if len(found) >= int(cfg["transcripts"]["max_outcome_passages"]):
            break
    newest = max((t.month for t, _ in found), default=None)
    for k, (t, p) in enumerate(found, 1):
        evidence.append({
            "id": f"{group['id']}-q{k}",
            "kind": "transcript",
            "call": t.period,
            "call_month": t.month,
            "fiscal": t.fiscal,
            "latest": t.month == newest,
            "speaker": p.speaker,
            "passage_id": p.id,
            "text": _focus(p.text, words, basis_rx, int(cfg["transcripts"]["outcome_chars"])),
            "source_url": t.url,
        })

    # Which verdicts are possible, decided in Python.
    if period in ("unspecified", "medium_term"):
        allowed, status = ["Delivered", "Pending", "Unverified"], "no end date"
    elif nums.period_ended(period, record):
        # Once a period is over, the outcome is what counts; a revision shows in the path.
        allowed, status = ["Delivered", "Missed", "Unverified"], "period ended"
    else:
        reported = len(actual["quarters"]) if actual else None
        allowed = ["Pending"]
        status = f"in progress ({reported} of 4 quarters reported)" if reported and not period.startswith(("Q", "H")) else "in progress"
        if group["revised"] and group.get("direction") != "raised":
            allowed = ["Goalposts moved"] + allowed
    return {"evidence": evidence, "check": check, "allowed": allowed, "period_status": status, "notes": notes}


def _words_of(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{5,}", (text or "").lower()) if w not in {"target", "guidance", "approximately"}}


def _period_cues(period: str) -> list[str]:
    m = periods.PERIOD_RE.match(period or "")
    if not m:
        return []
    yy = int(m.group(2))
    return [f"fy{yy:02d}", f"fy {yy:02d}", f"financial year 20{yy:02d}", f"financial year '{yy:02d}", f"fy20{yy:02d}"]


NUMBER = re.compile(r"\d")


def _focus(text: str, words: list[str], basis_rx: re.Pattern | None, size: int) -> str:
    """The sentences of a passage that state a figure for the metric, up to `size` chars."""
    sents = _sentences(text)
    keep = [s for s in sents if NUMBER.search(s) and (any(w in s.lower() for w in words) or (basis_rx and basis_rx.search(s)))]
    out = ""
    for s in keep or sents:
        if len(out) + len(s) + 1 > size:
            break
        out = f"{out} {s}".strip()
    return out or text[:size]


# ---------------------------------------------------------------- verdicts

def rationale_for(verdict: str, group: dict[str, Any], ev: dict[str, Any]) -> str:
    """A plain, number-safe sentence for a verdict, built only from the evidence."""
    check, target = ev["check"], fmt_target(group["latest"])
    if verdict == "Goalposts moved":
        return f"Target for {group['period']} changed: {group['path']}."
    if verdict == "Pending":
        if check and check["comparable"]:
            return f"So far {check['actual']:g}% against a {target} target ({ev['period_status']})."
        return f"Period still running ({ev['period_status']})."
    if verdict in ("Delivered", "Missed") and check and check["comparable"]:
        return f"Actual {check['actual']:g}% against a {target} target."
    stated = ev.get("stated")
    if verdict in ("Delivered", "Missed") and stated:
        return f"Management stated {stated['actual']:g}% ({stated['call']}) against a {target} target."
    if verdict in ("Delivered", "Missed"):
        return "Judged on management's own stated actual in a later call."
    if check and not check["comparable"]:
        return "No figure on the guidance's basis: screener reports ₹ and no later call states the actual."
    return "No comparable actual in screener or in later calls."


def rules_verdict(group: dict[str, Any], ev: dict[str, Any]) -> tuple[str, str]:
    """The verdict Python can reach on its own (used when no model is available, and to
    overrule a model that contradicts the arithmetic)."""
    check = ev["check"]
    if "Goalposts moved" in ev["allowed"]:
        verdict = "Goalposts moved"
    elif "Pending" in ev["allowed"]:
        verdict = "Pending"
    elif check and check["comparable"] and check["complete"]:
        verdict = "Delivered" if check["position"] in ("within", "above") else "Missed"
    else:
        verdict = "Unverified"
    return verdict, rationale_for(verdict, group, ev)


def fmt_target(p: dict[str, Any]) -> str:
    return p.get("target_text") or "stated"


def judge_schema(ids: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["verdicts"],
        "properties": {
            "verdicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["group_id", "verdict", "evidence_ids", "rationale"],
                    "properties": {
                        "group_id": {"type": "string", "enum": ids},
                        "verdict": {"type": "string", "enum": VERDICTS},
                        "evidence_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
                        "actual_quote": {"type": ["string", "null"], "maxLength": 500},
                        "actual_evidence_id": {"type": ["string", "null"]},
                        "rationale": {"type": "string", "maxLength": 300},
                    },
                },
            }
        },
    }


JUDGE_SYSTEM = (
    "You check whether an Indian listed company's management delivered on its own promises, using only the "
    "evidence given (statements from its earnings calls and figures computed from its reported results). "
    "Do not use anything you know about the company from elsewhere.\n"
    "For each promise group:\n"
    "- verdict: pick one of that group's allowed verdicts. \"Goalposts moved\" means the target for the same "
    "period was changed after it was first given; use it only when the statements show that. \"Pending\" means "
    "the period has not ended. \"Unverified\" means the evidence cannot settle it.\n"
    "- evidence_ids: the ids (statements s1, s2 ... and evidence ids) that support the verdict.\n"
    "- actual_quote: if a later-call passage states the actual, copy that sentence exactly and give its id in "
    "actual_evidence_id; otherwise null.\n"
    "- rationale: one plain sentence, at most 30 words. Any number in it must appear in the evidence. Do no "
    "arithmetic: comparisons already computed are given as `check`.\n"
    "Judge figures on the same basis only: a constant-currency target cannot be judged on rupee growth. "
    "Delivered or Missed needs a figure on the same basis: a comparable screener figure, or a later call that "
    "states the actual (quote it). When several calls state a figure, use the one marked latest."
)


def judge_prompt(company: str, batch: list[tuple[dict[str, Any], dict[str, Any]]]) -> str:
    out = [f"Company: {company}", ""]
    for g, ev in batch:
        out.append(f"## Group {g['id']}: {g['metric_label']}{' — ' + g['metric_text'] if g['metric'] == 'other' else ''}, period {g['period']} ({ev['period_status']})")
        out.append(f"Allowed verdicts: {', '.join(ev['allowed'])}")
        if g["revised"]:
            out.append(f"Target path (oldest to newest): {g['path']} — {g.get('direction')}")
        for k, s in enumerate(g["statements"], 1):
            out.append(f"- s{k} [{s['call']}, {s['speaker']}] target {s.get('target_text') or 'none stated'} ({s['basis']}): \"{s['quote']}\"")
        for e in ev["evidence"]:
            if e["kind"] == "screener":
                out.append(f"- {e['id']} [screener, computed] {e['label']}: {e['value']:g}{e['unit']} ({e['basis']})")
            else:
                tag = ", latest" if e.get("latest") else ""
                out.append(f"- {e['id']} [{e['call']}{tag}, {e['speaker']}]: \"{e['text']}\"")
        if ev["check"]:
            c = ev["check"]
            out.append(f"- check: comparable={c['comparable']}, actual {c['actual']:g} vs target {c['target_low']:g}–{c['target_high']:g}, "
                       f"position={c['position']}, period complete={c['complete']}")
        for n in ev["notes"]:
            out.append(f"- note: {n}")
        out.append("")
    return "\n".join(out)


def _allowed_numbers(g: dict[str, Any], ev: dict[str, Any], actual_quote: str | None) -> set[float]:
    pool: set[float] = set()
    for s in g["statements"]:
        pool |= numbers_in(s["quote"])
    for e in ev["evidence"]:
        if e["kind"] == "screener":
            v = float(e["value"])
            pool |= {v, round(v, 1), round(v), float(f"{v:g}")}
            pool |= numbers_in(e["label"])
        else:
            pool |= numbers_in(e["text"])
    pool |= numbers_in(actual_quote or "")
    pool |= numbers_in(g["period"]) | numbers_in(ev["period_status"])
    for s in g["statements"]:
        pool |= numbers_in(s["call"])
    return pool


PCT = re.compile(r"(-?\d+(?:\.\d+)?)\s?(?:%|per ?cent)", re.I)


def stated_check(g: dict[str, Any], actual_quote: dict[str, Any]) -> dict[str, Any] | None:
    """Compare a quoted actual with the target, in Python, when the quote holds exactly one percentage."""
    latest = g["latest"]
    pcts = {float(x) for x in PCT.findall(actual_quote["text"])}
    if len(pcts) != 1:
        return None
    v = pcts.pop()
    low, high = latest["target_low"], latest["target_high"]
    pos = None
    if low is not None and latest.get("unit") in ("%", None):
        pos = "within" if low <= v <= high else ("above" if v > high else "below")
    return {"actual": v, "position": pos, "call": actual_quote["call"], "speaker": actual_quote["speaker"]}


def stale_numbers(g: dict[str, Any], ev: dict[str, Any], rationale: str) -> list[float]:
    """Numbers in the rationale that only appear in an older call's passage while a newer
    call (statement or evidence) exists: the rationale should use the latest figure."""
    months = [s["call_month"] for s in g["statements"]] + [e["call_month"] for e in ev["evidence"] if e["kind"] == "transcript"]
    if not months:
        return []
    newest = max(months)
    fresh: set[float] = set()
    for s in g["statements"]:
        fresh |= numbers_in(s["quote"])
    for e in ev["evidence"]:
        if e["kind"] == "screener":
            v = float(e["value"])
            fresh |= {v, round(v, 1), round(v)}
        elif e["call_month"] == newest:
            fresh |= numbers_in(e["text"])
    old: set[float] = set()
    for e in ev["evidence"]:
        if e["kind"] == "transcript" and e["call_month"] < newest:
            old |= numbers_in(e["text"])
    return [n for n in numbers_in(rationale) if n in old and n not in fresh]


def chart_data(g: dict[str, Any], ev: dict[str, Any]) -> dict[str, Any] | None:
    """What the research screen draws: each call's guided range as a band, the actual as a dot.
    Only percentage targets are charted; every value comes from a quote or from screener."""
    guides = [{"call": s["call"], "fiscal": s["fiscal"], "low": s["target_low"], "high": s["target_high"]}
              for s in g["statements"] if s["target_low"] is not None and s.get("unit") == "%"]
    if not guides:
        return None
    actual = None
    check, stated = ev["check"], ev.get("stated")
    if check and check["comparable"]:
        e = next(x for x in ev["evidence"] if x["id"] == check["evidence_id"])
        actual = {"value": check["actual"], "kind": "screener", "label": e["label"], "complete": check["complete"]}
    elif stated:
        actual = {"value": stated["actual"], "kind": "stated", "label": f"Stated by {stated['speaker']}, {stated['call']}", "complete": True}
    return {"unit": "%", "guides": guides, "actual": actual}


def finalise(g: dict[str, Any], ev: dict[str, Any], raw: dict[str, Any] | None, model: str | None, cfg: dict[str, Any]) -> dict[str, Any]:
    """Validate a model verdict (or fall back to the rules) and build the ledger entry."""
    notes = list(ev["notes"])
    rv, rr = rules_verdict(g, ev)
    stmt_ids = {f"s{k}" for k in range(1, len(g["statements"]) + 1)}
    ev_by_id = {e["id"]: e for e in ev["evidence"]}
    verdict, rationale, by, cited, actual_quote = rv, rr, "rules", [], None

    if raw is not None:
        verdict, by = raw.get("verdict"), model or "model"
        rationale = (raw.get("rationale") or "").strip()
        cited = [i for i in raw.get("evidence_ids") or [] if i in ev_by_id or i in stmt_ids]
        if verdict not in ev["allowed"]:
            notes.append(f"model chose \"{verdict}\", which the dates don't allow; used the rules instead")
            verdict, rationale, by = rv, rr, "rules"
        check = ev["check"]
        if by != "rules" and check and check["comparable"] and check["complete"] and verdict in ("Delivered", "Missed") and verdict != rv:
            notes.append(f"model said {verdict} but the figures say {rv}; the figures win")
            verdict, rationale = rv, rr
        q, qid = raw.get("actual_quote"), raw.get("actual_evidence_id")
        if q and qid in ev_by_id and ev_by_id[qid]["kind"] == "transcript":
            ok, _ = quote_found(q, ev_by_id[qid]["text"], cfg["quotes"]["min_score"], cfg["quotes"]["min_chars"])
            if ok:
                e = ev_by_id[qid]
                actual_quote = {"text": q.strip(), "speaker": e["speaker"], "call": e["call"], "source_url": e["source_url"]}
            else:
                notes.append("the model's quoted actual did not match the transcript; dropped")
        elif q:
            notes.append("the model's quoted actual had no valid source; dropped")

        # A stated actual with exactly one percentage is read and compared by Python.
        ev["stated"] = stated_check(g, actual_quote) if actual_quote else None
        check = ev["check"]
        comparable_done = bool(check and check["comparable"] and check["complete"])
        if by != "rules" and verdict in ("Delivered", "Missed"):
            if ev["stated"] and ev["stated"]["position"] is not None and not comparable_done:
                want = "Delivered" if ev["stated"]["position"] in ("within", "above") else "Missed"
                if verdict != want:
                    notes.append(f"model said {verdict} but the stated actual says {want}; the figures win")
                    verdict, rationale = want, rationale_for(want, g, ev)
            elif not comparable_done and not actual_quote and g["latest"]["target_low"] is not None:
                notes.append(f"model said {verdict} without a figure on the guidance's basis; marked Unverified")
                verdict = "Unverified" if "Unverified" in ev["allowed"] else rv
                rationale = rationale_for(verdict, g, ev)
        if by != "rules":
            stray = [n for n in numbers_in(rationale) if n not in _allowed_numbers(g, ev, actual_quote["text"] if actual_quote else None)]
            stale = stale_numbers(g, ev, rationale)
            if stray or stale or not rationale:
                notes.append("rationale replaced: it used numbers that are not in the evidence" if stray
                             else "rationale replaced: it used an older figure than the latest call" if stale
                             else "empty rationale replaced")
                rationale = rationale_for(verdict, g, ev)

    latest = g["latest"]
    return {
        "id": g["id"],
        "metric": g["metric"],
        "metric_label": g["metric_label"],
        "metric_text": g["metric_text"],
        "period": g["period"],
        "period_status": ev["period_status"],
        "target": {"text": latest.get("target_text"), "low": latest["target_low"], "high": latest["target_high"],
                   "unit": latest.get("unit"), "basis": latest.get("basis")},
        "revised": g["revised"],
        "revision_direction": g.get("direction"),
        "revision_path": g["path"],
        "statements": [
            {"id": f"s{k}", "call": s["call"], "call_label": s.get("call_label"), "fiscal": s["fiscal"], "speaker": s["speaker"], "quote": s["quote"],
             "target_text": s.get("target_text"), "basis": s["basis"], "quote_score": s["quote_score"], "source_url": s["source_url"]}
            for k, s in enumerate(g["statements"], 1)
        ],
        "evidence": ev["evidence"],
        "check": ev["check"],
        "verdict": verdict,
        "verdict_by": by,
        "rationale": rationale,
        "cited": cited,
        "actual_quote": actual_quote,
        "stated": ev.get("stated"),
        "chart": chart_data(g, ev),
        "notes": notes,
    }


def judge(
    company: str,
    groups: list[dict[str, Any]],
    record: dict[str, Any],
    transcripts: list[Transcript],
    cfg: dict[str, Any],
    complete: Callable[..., Any] | None,
    log: Callable[[str], None] = lambda _m: None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Ledger entries for every group. Without `complete` (or when it fails) the rules decide."""
    prepared = [(g, build_evidence(g, record, transcripts, cfg)) for g in groups]
    raw: dict[str, tuple[dict[str, Any], str]] = {}
    errors: list[str] = []
    size = int(cfg["judge"]["groups_per_call"])
    if complete is not None:
        for i in range(0, len(prepared), size):
            batch = prepared[i : i + size]
            try:
                res = complete("judge_promises", JUDGE_SYSTEM, judge_prompt(company, batch),
                               judge_schema([g["id"] for g, _ in batch]), label=f"{company} judge {i // size + 1}")
                for v in res.data.get("verdicts") or []:
                    raw[v["group_id"]] = (v, f"{res.provider}/{res.model}")
            except Exception as exc:  # noqa: BLE001 - fall back to the rules for this batch
                errors.append(f"judge batch {i // size + 1}: {type(exc).__name__}: {str(exc)[:160]}")
                log(errors[-1])
    entries = []
    for g, ev in prepared:
        v = raw.get(g["id"])
        entries.append(finalise(g, ev, v[0] if v else None, v[1] if v else None, cfg))
    return entries, errors
