"""Collects per-source, per-symbol outcomes so one failure never stops the run."""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator

from .common import get_logger

log = get_logger("report")

OK, FAILED, SKIPPED = "ok", "failed", "skipped"


@dataclass
class Outcome:
    source: str
    symbol: str
    status: str
    detail: str = ""
    seconds: float = 0.0


@dataclass
class RunReport:
    outcomes: list[Outcome] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add(self, source: str, symbol: str, status: str, detail: str = "", seconds: float = 0.0) -> None:
        self.outcomes.append(Outcome(source, symbol, status, detail, seconds))

    def warn(self, message: str) -> None:
        log.warning(message)
        self.warnings.append(message)

    @contextmanager
    def track(self, source: str, symbol: str) -> Iterator[dict]:
        """Wrap one unit of work. Any exception is logged as a failure and swallowed.

        The body can set ctx["detail"] for the success message.
        """
        ctx: dict = {"detail": ""}
        start = time.monotonic()
        try:
            yield ctx
        except Exception as exc:  # noqa: BLE001 - isolating failures is the point
            msg = f"{type(exc).__name__}: {exc}"
            log.error("%s %s failed: %s", source, symbol, msg)
            self.add(source, symbol, FAILED, msg[:300], time.monotonic() - start)
        else:
            self.add(source, symbol, OK, ctx["detail"], time.monotonic() - start)

    def status(self, source: str, symbol: str) -> Outcome | None:
        for o in reversed(self.outcomes):
            if o.source == source and o.symbol == symbol:
                return o
        return None

    def counts(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for o in self.outcomes:
            bucket = out.setdefault(o.source, {OK: 0, FAILED: 0, SKIPPED: 0})
            bucket[o.status] = bucket.get(o.status, 0) + 1
        return out

    def any_success(self) -> bool:
        return any(o.status == OK for o in self.outcomes)

    def any_failure(self) -> bool:
        return any(o.status == FAILED for o in self.outcomes)

    def render(self) -> str:
        lines = ["", "=" * 72, "SEED BUILD SUMMARY", "=" * 72]
        for source, c in self.counts().items():
            lines.append(f"{source:<14} ok={c[OK]:<3} failed={c[FAILED]:<3} skipped={c[SKIPPED]}")
        failures = [o for o in self.outcomes if o.status != OK]
        if failures:
            lines.append("-" * 72)
            for o in failures:
                detail = o.detail if len(o.detail) <= 140 else o.detail[:137] + "..."
                lines.append(f"{o.status.upper():<8} {o.source:<13} {o.symbol:<12} {detail}")
        if self.warnings:
            lines.append("-" * 72)
            lines.append("WARNINGS")
            lines.extend(f"  - {w}" for w in self.warnings)
        lines.append("=" * 72)
        return "\n".join(lines)
