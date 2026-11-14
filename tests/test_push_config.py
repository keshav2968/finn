import copy

import pytest
import yaml
from conftest import ROOT

from push.config import PushConfigError, parse_push_config

REFERENCE_CATEGORIES = {
    "results", "M&A", "fund_raise", "management_change", "litigation", "insider_trading",
    "earnings_call", "investor_meetings", "credit_rating", "dividend", "bonus_split", "capex",
    "press_release", "postal_ballot", "agm_egm", "pledging", "unclassified",
}


def raw_config():
    return yaml.safe_load((ROOT / "config" / "push.yaml").read_text(encoding="utf-8"))


def test_real_config_has_the_17_reference_categories():
    cfg = parse_push_config(raw_config())
    assert set(cfg.categories) == REFERENCE_CATEGORIES
    assert all(r.category in cfg.categories for r in cfg.rules)
    assert cfg.tier_for(70) == "needs_attention" and cfg.tier_for(69.9) == "worth_knowing" and cfg.tier_for(39) == "routine"


def test_public_rules_carry_labels_tiers_and_alert_defaults():
    pub = parse_push_config(raw_config()).public_rules()
    assert pub["categories"]["M&A"]["label"] == "M&A"
    assert pub["alerts"]["price_move_pct"] == 4.0 and pub["alerts"]["volume_ratio"] == 2.0
    assert pub["tier_labels"]["needs_attention"] == "Needs attention"


def test_every_problem_is_reported_at_once():
    raw = raw_config()
    bad = copy.deepcopy(raw)
    bad["classifier"]["rules"].append({"id": "x1", "text": "([unclosed", "category": "results"})
    bad["classifier"]["rules"].append({"id": "x2", "text": "ok", "category": "news"})
    bad["classifier"]["rules"].append({"id": "x3", "category": "results"})
    bad["classifier"]["rules"].append({"id": "x4", "text": "ok", "category": "results", "colour": "red"})
    bad["modifiers"].append({"category": "results", "text": "x"})
    bad["alerts"]["filing_categories"].append("gossip")
    bad["tiers"] = {"needs_attention": 40, "worth_knowing": 70}
    with pytest.raises(PushConfigError) as exc:
        parse_push_config(bad)
    msg = str(exc.value)
    for fragment in ["bad regex", "unknown category 'news'", "needs at least one of", "unknown keys ['colour']",
                     "modifiers[", "unknown category 'gossip'", "worth_knowing must be below"]:
        assert fragment in msg, fragment


def test_duplicate_rule_ids_rejected():
    raw = raw_config()
    raw["classifier"]["rules"].append(dict(raw["classifier"]["rules"][0]))
    with pytest.raises(PushConfigError, match="duplicate rule id"):
        parse_push_config(raw)
