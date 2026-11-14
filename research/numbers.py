"""Numbers from screener.in tables, computed in Python only (no model sees a sum).

Two jobs:
- `build_numbers`: the company's recent record (quarters, years, this fiscal year so far)
  for the research screen.
- `actual_for`: the actual for one promise (a metric over a fiscal period), as evidence
  the judge can cite by id. Every value carries its period, the quarters it used and
  where it came from.
"""

from __future__ import annotations

from typing import Any

from . import periods

UNIT = "₹ crore"


def _view(record: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    name = record.get("primary_view") or "consolidated"
    view = (record.get("views") or {}).get(name) or {}
    return name, view


def series(record: dict[str, Any], table: str) -> tuple[list[str], dict[str, list[float | None]]]:
    """(periods, {stable key: values}) for a screener table, via its `fields` map."""
    _, view = _view(record)
    tab = (view.get("tables") or {}).get(table) or {}
    fields = (view.get("fields") or {}).get(table) or {}
    rows = tab.get("rows") or {}
    out = {key: list(rows.get(lbl) or []) for key, lbl in fields.items() if lbl in rows}
    return list(tab.get("periods") or []), out


def _pct(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den == 0:
        return None
    return round(100.0 * num / den, 2)


def _growth(cur: float | None, prev: float | None) -> float | None:
    if cur is None or prev is None or prev <= 0:
        return None  # growth off a loss or zero base means nothing
    return round(100.0 * (cur - prev) / prev, 2)


def _sum(values: list[float | None]) -> float | None:
    if not values or any(v is None for v in values):
        return None
    return float(sum(values))  # type: ignore[arg-type]


def _pick(ps: list[str], rows: dict[str, list], key: str, labels: list[str]) -> list[float | None]:
    col = rows.get(key) or []
    idx = {p: i for i, p in enumerate(ps)}
    return [col[idx[lbl]] if lbl in idx and idx[lbl] < len(col) else None for lbl in labels]


# ---------------------------------------------------------------- metric calculations

def compute(kind: str, record: dict[str, Any], quarter_labels: list[str]) -> dict[str, Any] | None:
    """One metric over the given quarters (summed), with the inputs used."""
    ps, rows = series(record, "quarters")
    have = [q for q in quarter_labels if q in ps]
    if not have:
        return None
    prev = [periods.year_earlier(q) for q in have]
    rev, rev_prev = _sum(_pick(ps, rows, "revenue", have)), _sum(_pick(ps, rows, "revenue", prev))  # type: ignore[arg-type]
    op = _sum(_pick(ps, rows, "operating_profit", have))
    dep = _sum(_pick(ps, rows, "depreciation", have))
    pat, pat_prev = _sum(_pick(ps, rows, "net_profit", have)), _sum(_pick(ps, rows, "net_profit", prev))  # type: ignore[arg-type]

    if kind == "revenue_growth":
        value, inputs = _growth(rev, rev_prev), {"revenue": rev, "revenue_year_earlier": rev_prev}
    elif kind == "ebit_margin":
        ebit = None if op is None or dep is None else op - dep
        value, inputs = _pct(ebit, rev), {"operating_profit": op, "depreciation": dep, "revenue": rev}
    elif kind == "ebitda_margin":
        value, inputs = _pct(op, rev), {"operating_profit": op, "revenue": rev}
    elif kind == "profit_growth":
        value, inputs = _growth(pat, pat_prev), {"net_profit": pat, "net_profit_year_earlier": pat_prev}
    else:
        return None
    if value is None:
        return None
    return {"value": value, "quarters": have, "inputs": inputs}


COMPUTE_LABEL = {
    "revenue_growth": "Revenue growth YoY (reported ₹)",
    "ebit_margin": "Operating (EBIT) margin",
    "ebitda_margin": "EBITDA margin",
    "profit_growth": "Net profit growth YoY",
}


def actual_for(kind: str | None, period: str, record: dict[str, Any]) -> dict[str, Any] | None:
    """The actual for a fiscal period, or None when screener can't give it.
    `complete` says whether every quarter of the period has been reported."""
    if not kind or not periods.is_valid(period):
        return None
    wanted = periods.quarters_of(period)
    got = compute(kind, record, wanted)
    if not got:
        return None
    view_name, view = _view(record)
    n, total = len(got["quarters"]), len(wanted)
    span = period if n == total else f"{period} so far ({n} of {total} quarters)"
    return {
        "label": f"{COMPUTE_LABEL[kind]}, {span}",
        "value": got["value"],
        "unit": "%",
        "period": period,
        "quarters": got["quarters"],
        "complete": n == total,
        "basis": "reported, ₹",
        "inputs": got["inputs"],
        "source": f"screener.in {view_name} quarterly results",
        "url": view.get("url"),
    }


def latest_quarter(record: dict[str, Any]) -> str | None:
    ps, rows = series(record, "quarters")
    rev = rows.get("revenue") or []
    filled = [p for i, p in enumerate(ps) if i < len(rev) and rev[i] is not None]
    return filled[-1] if filled else None


def period_ended(period: str, record: dict[str, Any]) -> bool:
    """True once the period's last quarter has been reported on screener."""
    qs = periods.quarters_of(period)
    last = latest_quarter(record)
    return bool(qs and last) and periods.sort_key(qs[-1]) <= periods.sort_key(last)  # type: ignore[arg-type]


# ---------------------------------------------------------------- the record, for the screen

def build_numbers(record: dict[str, Any], quarters: int = 8, years: int = 5) -> dict[str, Any]:
    view_name, view = _view(record)
    layout = view.get("layout") or record.get("layout") or "standard"
    qp, qr = series(record, "quarters")
    yp, yr = series(record, "profit_loss")
    rp, rr = series(record, "ratios")

    def q_row(i: int) -> dict[str, Any]:
        p = qp[i]
        prev = periods.year_earlier(p)
        j = qp.index(prev) if prev in qp else None
        get = lambda k, idx: (qr.get(k) or [None] * len(qp))[idx] if idx is not None and idx < len(qr.get(k) or []) else None  # noqa: E731
        rev, op, dep, pat = get("revenue", i), get("operating_profit", i), get("depreciation", i), get("net_profit", i)
        row = {
            "period": p,
            "fiscal": periods.fiscal_label(p),
            "revenue": rev,
            "revenue_yoy": _growth(rev, get("revenue", j)),
            "net_profit": pat,
            "net_profit_yoy": _growth(pat, get("net_profit", j)),
        }
        if layout == "standard":
            row["ebitda"] = op
            row["ebitda_margin"] = _pct(op, rev)
            row["ebit_margin"] = _pct(None if op is None or dep is None else op - dep, rev)
        else:
            row["financing_profit"] = get("financing_profit", i)
            row["gross_npa_pct"] = get("gross_npa_pct", i)
            row["net_npa_pct"] = get("net_npa_pct", i)
        return row

    filled = [i for i, _ in enumerate(qp) if i < len(qr.get("revenue") or []) and qr["revenue"][i] is not None]
    q_rows = [q_row(i) for i in filled[-quarters:]]

    y_idx = [i for i, p in enumerate(yp) if periods.parse_label(p) and i < len(yr.get("revenue") or []) and yr["revenue"][i] is not None]
    ratio_key = "ROCE %" if layout == "standard" else "ROE %"
    ratio_rows = ((view.get("tables") or {}).get("ratios") or {}).get("rows") or {}
    y_rows = []
    for k, i in enumerate(y_idx[-years:]):
        p = yp[i]
        prev_i = y_idx[y_idx.index(i) - 1] if y_idx.index(i) > 0 else None
        val = lambda key, idx: (yr.get(key) or [])[idx] if idx is not None and idx < len(yr.get(key) or []) else None  # noqa: E731
        rev, op, pat = val("revenue", i), val("operating_profit", i), val("net_profit", i)
        ratio = None
        if p in rp and ratio_key in ratio_rows:
            col = ratio_rows[ratio_key]
            ratio = col[rp.index(p)] if rp.index(p) < len(col) else None
        y = {"period": p, "fiscal": f"FY{periods.fiscal_year(*periods.parse_label(p)):02d}", "revenue": rev,
             "revenue_growth": _growth(rev, val("revenue", prev_i)), "net_profit": pat,
             "net_profit_growth": _growth(pat, val("net_profit", prev_i)), ratio_key.replace(" %", "").lower() + "_pct": ratio}
        if layout == "standard":
            y["ebitda_margin"] = _pct(op, rev)
        y_rows.append(y)

    last = latest_quarter(record)
    ytd = None
    if last:
        fy = periods.fiscal_year(*periods.parse_label(last))
        period = f"FY{fy:02d}"
        kinds = ["revenue_growth", "profit_growth"] + (["ebitda_margin", "ebit_margin"] if layout == "standard" else [])
        ytd = {"period": period, "metrics": {k: actual_for(k, period, record) for k in kinds}}

    return {
        "basis": view_name,
        "layout": layout,
        "unit": UNIT,
        "latest_quarter": last,
        "latest_fiscal": periods.fiscal_label(last) if last else None,
        "quarters": q_rows,
        "years": y_rows,
        "fiscal_year_to_date": ytd,
        "source": {"name": f"screener.in ({view_name})", "url": view.get("url"), "fetched_at": view.get("fetched_at")},
    }
