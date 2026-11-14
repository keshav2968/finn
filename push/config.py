"""Load and validate config/push.yaml.

Every regex is compiled up front and every category reference is checked, so a
typo in the config fails loudly at startup instead of silently mis-classifying.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ingest.common import REPO_ROOT, parse_hhmm

TIERS = ("needs_attention", "worth_knowing", "routine")
TIER_LABELS = {"needs_attention": "Needs attention", "worth_knowing": "Worth knowing", "routine": "Routine"}
RULE_FIELDS = ("subcategory", "bse_category", "title", "text", "also", "unless")


class PushConfigError(ValueError):
    pass


def _rx(pattern: Any, where: str, errors: list[str]) -> re.Pattern | None:
    if pattern is None:
        return None
    try:
        return re.compile(str(pattern), re.IGNORECASE)
    except re.error as exc:
        errors.append(f"{where}: bad regex {pattern!r}: {exc}")
        return None


@dataclass(frozen=True)
class Category:
    id: str
    label: str
    base: int
    notice: int
    description: str = ""


@dataclass(frozen=True)
class Rule:
    id: str
    category: str
    subcategory: re.Pattern | None = None
    bse_category: re.Pattern | None = None
    title: re.Pattern | None = None
    text: re.Pattern | None = None
    also: re.Pattern | None = None
    unless: re.Pattern | None = None


@dataclass(frozen=True)
class Modifier:
    category: str
    text: re.Pattern
    delta: int
    reason: str
    unless: re.Pattern | None = None


@dataclass
class PushConfig:
    categories: dict[str, Category]
    rules: list[Rule]
    notice_title: re.Pattern
    context_text: re.Pattern
    context_category: str
    context_override: set[str]
    context_window_hours: float
    pending_score: int
    pending_label: str
    llm_min_confidence: float
    llm_cache: Path
    tiers: dict[str, int]
    modifiers: list[Modifier]
    reaction: dict[str, Any]
    same_day_categories: set[str]
    digest_window_hours: float
    alerts: dict[str, Any]
    generic_title: re.Pattern
    boilerplate_prefix: re.Pattern
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    def label(self, category: str) -> str:
        cat = self.categories.get(category)
        return cat.label if cat else category

    def tier_for(self, score: float) -> str:
        if score >= self.tiers["needs_attention"]:
            return "needs_attention"
        if score >= self.tiers["worth_knowing"]:
            return "worth_knowing"
        return "routine"

    def public_rules(self) -> dict[str, Any]:
        """What the app needs to show labels and re-apply thresholds client-side."""
        return {
            "categories": {k: {"label": c.label} for k, c in self.categories.items()},
            "tiers": dict(self.tiers),
            "tier_labels": TIER_LABELS,
            "alerts": dict(self.alerts),
            "digest_window_hours": self.digest_window_hours,
        }


def parse_push_config(raw: Any) -> PushConfig:
    errors: list[str] = []
    if not isinstance(raw, dict):
        raise PushConfigError("push.yaml must be a mapping")

    categories: dict[str, Category] = {}
    for cid, spec in (raw.get("categories") or {}).items():
        spec = spec or {}
        try:
            categories[str(cid)] = Category(
                str(cid), str(spec["label"]), int(spec["base"]), int(spec.get("notice", 0)), str(spec.get("description", ""))
            )
        except (KeyError, TypeError, ValueError):
            errors.append(f"categories.{cid}: needs label, base (int) and optional notice (int)")
    if "unclassified" not in categories:
        errors.append("categories: 'unclassified' is required (it is where routine filings go)")

    def check_cat(cat: Any, where: str) -> str:
        cat = str(cat)
        if cat not in categories:
            errors.append(f"{where}: unknown category {cat!r}")
        return cat

    cl = raw.get("classifier") or {}
    rules: list[Rule] = []
    seen_ids: set[str] = set()
    for i, spec in enumerate(cl.get("rules") or []):
        where = f"classifier.rules[{i}]"
        if not isinstance(spec, dict) or "id" not in spec or "category" not in spec:
            errors.append(f"{where}: needs id and category")
            continue
        rid = str(spec["id"])
        if rid in seen_ids:
            errors.append(f"{where}: duplicate rule id {rid!r}")
        seen_ids.add(rid)
        unknown = set(spec) - set(RULE_FIELDS) - {"id", "category"}
        if unknown:
            errors.append(f"{where} ({rid}): unknown keys {sorted(unknown)}")
        conds = {k: _rx(spec.get(k), f"{where}.{k}", errors) for k in RULE_FIELDS}
        if not any(conds[k] for k in ("subcategory", "bse_category", "title", "text")):
            errors.append(f"{where} ({rid}): needs at least one of subcategory, bse_category, title, text")
        rules.append(Rule(rid, check_cat(spec["category"], where), **conds))

    ctx = cl.get("context") or {}
    modifiers: list[Modifier] = []
    for i, spec in enumerate(raw.get("modifiers") or []):
        where = f"modifiers[{i}]"
        try:
            modifiers.append(
                Modifier(
                    check_cat(spec["category"], where),
                    _rx(spec["text"], f"{where}.text", errors) or re.compile("$^"),
                    int(spec["delta"]),
                    str(spec["reason"]),
                    _rx(spec.get("unless"), f"{where}.unless", errors),
                )
            )
        except (KeyError, TypeError, ValueError):
            errors.append(f"{where}: needs category, text, delta (int) and reason")

    tiers = raw.get("tiers") or {}
    try:
        tiers = {"needs_attention": float(tiers["needs_attention"]), "worth_knowing": float(tiers["worth_knowing"])}
        if tiers["worth_knowing"] >= tiers["needs_attention"]:
            errors.append("tiers: worth_knowing must be below needs_attention")
    except (KeyError, TypeError, ValueError):
        errors.append("tiers: needs numeric needs_attention and worth_knowing")
        tiers = {"needs_attention": 70.0, "worth_knowing": 40.0}

    reaction = dict(raw.get("reaction") or {})
    try:
        parse_hhmm(str(reaction.get("market_close_ist", "15:30")))
    except ValueError:
        errors.append("reaction.market_close_ist must look like 15:30")
    for c in reaction.get("skip_categories") or []:
        check_cat(c, "reaction.skip_categories")

    grouping = raw.get("grouping") or {}
    same_day = {check_cat(c, "grouping.same_day_categories") for c in grouping.get("same_day_categories") or []}

    alerts = dict(raw.get("alerts") or {})
    for c in alerts.get("filing_categories") or []:
        check_cat(c, "alerts.filing_categories")
    for key in ("price_move_pct", "volume_ratio", "filing_min_score"):
        if not isinstance(alerts.get(key), (int, float)):
            errors.append(f"alerts.{key} must be a number")

    notice = _rx(cl.get("notice_title"), "classifier.notice_title", errors)
    context_text = _rx(ctx.get("text"), "classifier.context.text", errors)
    context_category = check_cat(ctx.get("category", "results"), "classifier.context.category")
    context_override = {check_cat(c, "classifier.context.override") for c in ctx.get("override") or []}
    generic_title = _rx((raw.get("display") or {}).get("generic_title"), "display.generic_title", errors)
    boilerplate = _rx((raw.get("display") or {}).get("boilerplate_prefix"), "display.boilerplate_prefix", errors)

    if errors:
        raise PushConfigError("push.yaml problems:\n  - " + "\n  - ".join(errors))

    llm_cache = Path(cl.get("llm_cache") or "data/seed/push/llm_classifications.json")
    return PushConfig(
        categories=categories,
        rules=rules,
        notice_title=notice or re.compile("$^"),
        context_text=context_text or re.compile("$^"),
        context_category=context_category,
        context_override=context_override,
        context_window_hours=float(ctx.get("window_hours", 24)),
        pending_score=int(cl.get("pending_score", 40)),
        pending_label=str(cl.get("pending_label", "Unclassified")),
        llm_min_confidence=float(cl.get("llm_min_confidence", 0.5)),
        llm_cache=llm_cache if llm_cache.is_absolute() else REPO_ROOT / llm_cache,
        tiers=tiers,
        modifiers=modifiers,
        reaction=reaction,
        same_day_categories=same_day,
        digest_window_hours=float((raw.get("digest") or {}).get("default_window_hours", 24)),
        alerts=alerts,
        generic_title=generic_title or re.compile("$^"),
        boilerplate_prefix=boilerplate or re.compile("$^"),
        raw=raw,
    )


def load_push_config(path: Path | None = None) -> PushConfig:
    path = path or REPO_ROOT / "config" / "push.yaml"
    if not path.exists():
        raise PushConfigError(f"{path} not found")
    with open(path, encoding="utf-8") as fh:
        try:
            raw = yaml.safe_load(fh)
        except yaml.YAMLError as exc:
            raise PushConfigError(f"{path}: invalid YAML: {exc}") from exc
    return parse_push_config(raw)
