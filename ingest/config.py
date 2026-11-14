"""Load and validate config/portfolio.yaml and config/settings.yaml."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .common import REPO_ROOT

SIZES = {"large", "mid", "small"}
VIEWS = {"consolidated", "standalone"}
SYMBOL_RE = re.compile(r"^[A-Z0-9&\-]{1,20}$")
BSE_CODE_RE = re.compile(r"^\d{6}$")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Company:
    symbol: str
    name: str
    sector: str
    size: str | None
    is_lender: bool | None
    bse_code: str | None = None
    primary_view: str = "consolidated"
    # True for symbols passed on the command line that are not in portfolio.yaml.
    # Their name/sector/size/lender flag are filled from screener.in during the build.
    ad_hoc: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "sector": self.sector,
            "size": self.size,
            "is_lender": self.is_lender,
            "bse_code": self.bse_code,
            "primary_view": self.primary_view,
            "ad_hoc": self.ad_hoc,
        }


@dataclass(frozen=True)
class ResearchPick:
    symbol: str
    focus: str


@dataclass
class Config:
    companies: dict[str, Company]
    portfolio: list[str]
    research: list[ResearchPick]
    settings: dict[str, Any]
    warnings: list[str] = field(default_factory=list)

    def universe(self) -> list[Company]:
        """Portfolio first, then research picks not already held, in config order."""
        seen: list[str] = []
        for sym in self.portfolio + [r.symbol for r in self.research]:
            if sym not in seen:
                seen.append(sym)
        return [self.companies[s] for s in seen]

    def setting(self, *keys: str, default: Any = None) -> Any:
        node: Any = self.settings
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def path(self, key: str) -> Path:
        rel = self.setting("paths", key)
        if not rel:
            raise ConfigError(f"settings.yaml: paths.{key} is missing")
        p = Path(rel)
        return p if p.is_absolute() else REPO_ROOT / p


def _read_yaml(path: Path) -> Any:
    if not path.exists():
        raise ConfigError(f"{path} not found")
    with open(path, encoding="utf-8") as fh:
        try:
            return yaml.safe_load(fh)
        except yaml.YAMLError as exc:
            raise ConfigError(f"{path}: invalid YAML: {exc}") from exc


def parse_config(raw: Any, settings: Any) -> Config:
    """Validate the parsed YAML; collects every problem before raising."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(raw, dict):
        raise ConfigError("portfolio.yaml must be a mapping with companies, portfolio and research")
    if not isinstance(settings, dict):
        raise ConfigError("settings.yaml must be a mapping")

    companies: dict[str, Company] = {}
    for i, entry in enumerate(raw.get("companies") or []):
        where = f"companies[{i}]"
        if not isinstance(entry, dict):
            errors.append(f"{where}: must be a mapping")
            continue
        sym = str(entry.get("symbol", "")).strip().upper()
        where = f"companies[{i}] ({sym or '?'})"
        if not SYMBOL_RE.match(sym):
            errors.append(f"{where}: symbol must be an NSE symbol like INFY or M&M")
            continue
        if sym in companies:
            errors.append(f"{where}: duplicate symbol")
            continue
        name = str(entry.get("name") or "").strip()
        sector = str(entry.get("sector") or "").strip()
        size = str(entry.get("size") or "").strip().lower()
        is_lender = entry.get("is_lender")
        bse_code = entry.get("bse_code")
        view = str(entry.get("primary_view") or "consolidated").strip().lower()
        if not name:
            errors.append(f"{where}: name is required")
        if not sector:
            errors.append(f"{where}: sector is required")
        if size not in SIZES:
            errors.append(f"{where}: size must be one of {sorted(SIZES)}")
        if not isinstance(is_lender, bool):
            errors.append(f"{where}: is_lender must be true or false")
        if bse_code is not None:
            bse_code = str(bse_code).strip()
            if not BSE_CODE_RE.match(bse_code):
                errors.append(f"{where}: bse_code must be 6 digits (quote it in YAML)")
        if view not in VIEWS:
            errors.append(f"{where}: primary_view must be one of {sorted(VIEWS)}")
        companies[sym] = Company(sym, name, sector, size, is_lender, bse_code, view)

    portfolio: list[str] = []
    for item in raw.get("portfolio") or []:
        sym = str(item).strip().upper()
        if sym not in companies:
            errors.append(f"portfolio: {sym} is not defined under companies")
        elif sym in portfolio:
            errors.append(f"portfolio: {sym} listed twice")
        else:
            portfolio.append(sym)

    research: list[ResearchPick] = []
    for i, item in enumerate(raw.get("research") or []):
        if isinstance(item, str):
            item = {"symbol": item}
        if not isinstance(item, dict):
            errors.append(f"research[{i}]: must be a symbol or a mapping")
            continue
        sym = str(item.get("symbol", "")).strip().upper()
        if sym not in companies:
            errors.append(f"research[{i}]: {sym or '?'} is not defined under companies")
            continue
        research.append(ResearchPick(sym, str(item.get("focus") or "").strip()))

    if not portfolio:
        errors.append("portfolio: at least one symbol is required")
    elif not 15 <= len(portfolio) <= 20:
        warnings.append(f"portfolio has {len(portfolio)} names; the brief asks for 15-20")

    if errors:
        raise ConfigError("Config problems:\n  - " + "\n  - ".join(errors))
    return Config(companies, portfolio, research, settings, warnings)


def load_config(config_dir: Path | None = None) -> Config:
    config_dir = config_dir or REPO_ROOT / "config"
    return parse_config(
        _read_yaml(config_dir / "portfolio.yaml"),
        _read_yaml(config_dir / "settings.yaml"),
    )


def ad_hoc_company(symbol: str) -> Company:
    """A company passed on the command line that is not in portfolio.yaml."""
    sym = symbol.strip().upper()
    if not SYMBOL_RE.match(sym):
        raise ConfigError(f"{symbol!r} is not a valid NSE symbol")
    return Company(sym, name=sym, sector="", size=None, is_lender=None, ad_hoc=True)
