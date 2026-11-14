# FINN: financial investment agent

Mobile-first investing assistant for the ENAM AI Engineer build challenge.
**Push** tells you what changed in your portfolio and why it matters; **pull**
researches any NSE company from primary sources (annual reports, call transcripts).

This repository is being built in phases. **Phase 1 (this commit) is data only:**
no LLM calls, no UI.

## Phase 1: data snapshot

```
config/portfolio.yaml   the only place tickers live (15 holdings + 4 research picks)
config/settings.yaml    windows, throttles, cache TTL
ingest/                 fetchers and parsers
scripts/build_seed.py   builds data/seed/ (committed; the app reads only this)
data/cache/             raw screener.in pages (git-ignored)
```

| Source | What | Stored as |
|---|---|---|
| Yahoo Finance (yfinance) | ~1 year of daily OHLCV; % move, volume vs 20-day average, volatility-scaled move (z), 52-week range, returns | `data/seed/prices/SYMBOL.json` |
| BSE announcements API | last 60 days of filings: title, detail, BSE category, PDF link, timestamp | `data/seed/filings/SYMBOL.json` |
| screener.in | consolidated **and** standalone tables (quarterly, P&L, balance sheet, cash flow, ratios, shareholding), annual report and transcript links | `data/seed/fundamentals/SYMBOL.json` |
| all | per-company status (ok / stale / missing), warnings, `as_of` | `data/seed/manifest.json` |

### Run it

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt

pytest -q                                  # offline tests against real-markup fixtures
python scripts/build_seed.py               # full build, ~3 minutes
python scripts/build_seed.py --symbols TCS # any NSE symbol, in the config or not
python scripts/build_seed.py --only prices,filings
python scripts/build_seed.py --offline     # re-parse cached screener pages, no network
```

A failing ticker or source never stops the run. It is logged, the previous seed
file is kept and marked `stale` in the manifest, and a summary prints at the end.

### Design notes

- **Numbers, not alerts.** Prices store raw derived metrics; the user's thresholds
  are applied when the app reads them, so changing a slider re-evaluates instantly.
- **Volatility-aware moves.** `move_z` = today's % move / std-dev of the previous
  60 sessions. A 3% day is routine for a small cap and rare for HUL.
- **Lenders.** Screener uses a different table layout for banks and NBFCs; the parser
  detects it and maps both layouts to stable keys (`fields`), so later phases never
  depend on label spelling. HDFC Bank and Federal Bank use the standalone view:
  HDFC Bank's consolidated view includes its insurance subsidiaries.
- **EBITDA** is PBT + finance cost + depreciation − other income, which equals
  screener's "Operating Profit". That gives Phase 2 a free cross-check on numbers
  extracted from results PDFs.
- **BSE quirk.** Errors come back as HTTP 200 with an HTML page, and a failing URL can
  stay failed for a while; the fetcher validates JSON and retries with a different
  spelling of the same query.
- **Scheduling.** `.github/workflows/ingest.yml` runs the build at 17:05 IST on
  weekdays and commits `data/seed`. Exchanges sometimes block cloud IPs; if that
  happens, run the build locally and push.
