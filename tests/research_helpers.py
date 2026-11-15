"""Offline stand-ins for the research pipeline: transcript text from fixtures and scripted
model replies (what a model might return, good and bad), so tests never touch the network."""

from __future__ import annotations

import re

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "research"


def research_cfg() -> dict[str, Any]:
    cfg = yaml.safe_load((ROOT / "config" / "research.yaml").read_text(encoding="utf-8"))
    cfg["transcripts"]["min_text_chars"] = 300  # fixtures are condensed excerpts
    return cfg


def infy_record() -> dict[str, Any]:
    return json.loads((FIX / "screener_infy.json").read_text(encoding="utf-8"))


def fixture_text(url: str) -> str:
    month = url.rsplit("infy-", 1)[1].removesuffix(".pdf")
    return (FIX / f"INFY_{month}.txt").read_text(encoding="utf-8")


@dataclass
class Result:
    data: dict[str, Any]
    provider: str = "fake"
    model: str = "scripted"


# What an extractor might return for each call: real guidance, plus the mistakes the
# checks must catch (an invented quote, an analyst's words, a number not in the quote).
EXTRACTIONS = {
    "2026-04": [
        {"metric": "revenue_growth", "metric_text": "revenue growth in constant currency", "target_low": 1.5, "target_high": 3.5,
         "unit": "%", "basis": "constant_currency", "period": "FY27", "passage_id": "t3-p4",
         "quote": "Our revenue growth guidance for the financial year 2027 is 1.5% to 3.5% growth year-on-year in constant currency terms."},
        {"metric": "operating_margin", "metric_text": "operating margin", "target_low": 20, "target_high": 22,
         "unit": "%", "basis": "unspecified", "period": "FY 2027", "passage_id": "t3-p4",
         "quote": "Our operating margin guidance for financial year '27 is 20% to 22%."},
        {"metric": "revenue_growth", "metric_text": "invented", "target_low": 5, "target_high": 6, "unit": "%",
         "basis": "constant_currency", "period": "FY27", "passage_id": "t3-p4",
         "quote": "We are confident of double-digit growth of 5% to 6% next year across all verticals."},
        {"metric": "revenue_growth", "metric_text": "analyst", "target_low": 1.5, "target_high": 3.5, "unit": "%",
         "basis": "constant_currency", "period": "FY27", "passage_id": "t3-p6",
         "quote": "Salil, first on your guidance itself, 1.5% to 3.5%, if you could break up for us"},
    ],
    "2026-07": [
        {"metric": "revenue_growth", "metric_text": "revenue growth in constant currency", "target_low": 1.5, "target_high": 3,
         "unit": "%", "basis": "constant_currency", "period": "FY27", "passage_id": "t2-p3",
         "quote": "we are changing our revenue growth guidance to 1.5% to 3% Y-on-Y growth in constant currency terms."},
        {"metric": "other", "metric_text": "Recruitment plan for college graduates", "target_low": 20000, "target_high": 20000,
         "unit": "20,000", "basis": "unspecified", "period": "FY27", "passage_id": "t2-p3",
         "quote": "This year, we have a plan to recruit 20,000 college graduates."},
        {"metric": "operating_margin", "metric_text": "operating margin", "target_low": 20, "target_high": 25,
         "unit": "%", "basis": "unspecified", "period": "FY27", "passage_id": "t2-p3",
         "quote": "Our operating margin guidance remains the same at 20% to 22% operating margin."},
    ],
    # Oct 2025 (Q2 FY26): "for the full year" guidance the model filed under FY27.
    "2025-10": [
        {"metric": "revenue_growth", "metric_text": "Revenue growth guidance", "target_low": 2, "target_high": 3,
         "unit": "%", "basis": "constant_currency", "period": "FY27", "passage_id": "t6-p3",
         "quote": "The new guidance is growth between 2% and 3% in constant currency terms for the full year."},
        {"metric": "operating_margin", "metric_text": "Operating margin guidance", "target_low": 20, "target_high": 22,
         "unit": "%", "basis": "constant_currency", "period": "FY27", "passage_id": "t6-p3",
         "quote": "And our operating margin guidance remains the same as in the past quarter at 20% to 22% for the full year."},
    ],
    # Jan 2026 (Q3 FY26): the quote says constant currency, the model said "unspecified".
    "2026-01": [
        {"metric": "revenue_growth", "metric_text": "Revenue growth guidance for FY26", "target_low": 3, "target_high": 3.5,
         "unit": "%", "basis": "unspecified", "period": "FY26", "passage_id": "t5-p3",
         "quote": "The new revenue growth guidance for this financial year is 3% to 3.5% growth in constant currency."},
        {"metric": "operating_margin", "metric_text": "Operating margin guidance for FY26", "target_low": 20, "target_high": 22,
         "unit": "%", "basis": "unspecified", "period": "FY26", "passage_id": "t5-p3",
         "quote": "Our operating margin guidance for the financial year remains the same at 20% to 22%."},
    ],
    "2026-10": [
        {"metric": "revenue_growth", "metric_text": "revenue growth in constant currency", "target_low": 1, "target_high": 2,
         "unit": "%", "basis": "constant_currency", "period": "FY27", "passage_id": "t1-p5",
         "quote": "our revenue growth guidance is 1% to 2% YoY.in constant currency terms."},
        {"metric": "operating_margin", "metric_text": "operating margin", "target_low": 20, "target_high": 22,
         "unit": "%", "basis": "unspecified", "period": "FY27", "passage_id": "t1-p5",
         "quote": "Our operating margin guidance remains at 20% to 22% for the year."},
        # A reported actual, not a promise; and a headcount target with a garbage unit.
        {"metric": "other", "metric_text": "DSO target", "target_low": 77, "target_high": 77, "unit": "days",
         "basis": "unspecified", "period": "FY27", "passage_id": "t1-p12",
         "quote": "DSO, including unbilled net of unearned was 77 days, down by 10 days as compared to last year."},
        {"metric": "other", "metric_text": "Net headcount target", "target_low": 20000, "target_high": 20000, "unit": "mn",
         "basis": "unspecified", "period": "FY27", "passage_id": "t1-p12",
         "quote": "We hired about 13,000 freshers in H1 in line with our target of approximately 20,000 for FY27."},
        {"metric": "other", "metric_text": "mega deal revenue contribution", "target_low": 1, "target_high": 1,
         "unit": "%", "basis": "unspecified", "period": "FY28", "passage_id": "t1-p4",
         "quote": "This deal is expected to contribute over 1% revenue growth in the coming financial year."},
    ],
}


@dataclass
class ScriptedModel:
    """Plays the extractor and the judge. `judge_replies` maps "metric:period" (or just the
    metric) to the verdict dict the judge returns for that group."""

    judge_replies: dict[str, dict[str, Any]] = field(default_factory=dict)
    fail_tasks: set[str] = field(default_factory=set)
    calls: list[str] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)  # "other" description -> label the model returns

    def __call__(self, task: str, system: str, user: str, schema: dict, **_: Any) -> Result:
        self.calls.append(task)
        if task in self.fail_tasks:
            raise RuntimeError(f"{task} unavailable")
        if task == "label_promises":
            ids = schema["properties"]["labels"]["items"]["properties"]["id"]["enum"]
            out = []
            for ln in user.splitlines():
                m = re.match(r"- id (\S+): description: (.*?) \| quote:", ln)
                if m and m.group(1) in ids:
                    out.append({"id": m.group(1), "label": self.labels.get(m.group(2), "Scripted label")})
            return Result({"labels": out})
        if task == "extract_promises":
            month = next((m for m in EXTRACTIONS if f"quarter reported: {self._quarter(m)}" in user), None)
            return Result({"promises": EXTRACTIONS.get(month, [])})
        verdicts = []
        for gid in schema["properties"]["verdicts"]["items"]["properties"]["group_id"]["enum"]:
            metric, period = self._metric_of(gid, user)
            default = {"verdict": "Pending", "evidence_ids": [], "rationale": "Still running."}
            reply = dict(self.judge_replies.get(f"{metric}:{period}") or self.judge_replies.get(metric) or default)
            reply["group_id"] = gid
            verdicts.append(reply)
        return Result({"verdicts": verdicts})

    @staticmethod
    def _quarter(month: str) -> str:
        return {"2025-10": "Sep 2025", "2026-01": "Dec 2025", "2026-04": "Mar 2026", "2026-07": "Jun 2026", "2026-10": "Sep 2026"}[month]

    @staticmethod
    def _metric_of(gid: str, user: str) -> tuple[str, str]:
        line = next(ln for ln in user.splitlines() if ln.startswith(f"## Group {gid}:"))
        period = line.split(", period ", 1)[1].split(" ", 1)[0]
        for metric, label in (("revenue_growth", "Revenue growth"), ("operating_margin", "Operating (EBIT) margin"), ("other", "Other")):
            if label in line:
                return metric, period
        return "?", period
