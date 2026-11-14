# FINN: financial investment agent

Mobile-first investing assistant for the ENAM AI Engineer build challenge.
**Push** tells you what changed in your portfolio and why it matters; **pull**
researches any NSE company from primary sources (annual reports, call transcripts).

This repository is being built in phases. Phase 1 is the data snapshot; Phase 2
(in progress) is the push logic. Steps a–c below use no LLM.

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

## Phase 2 (a–c): classify, rank, alert

```
config/push.yaml        categories, classifier rules, scoring, alert defaults (no code changes to tune)
push/classify.py        BSE filing -> one of the 17 reference categories
push/priority.py        score, tier, collapse repeats, windowed digest
push/alerts.py          price/volume and filing alerts with stored reasons
scripts/build_push.py   writes data/seed/push/feed.json and alerts.json, prints a digest
```

```bash
python scripts/build_push.py                 # last 24h to the snapshot time
python scripts/build_push.py --window 7d --show-routine
python scripts/build_push.py --price-move 3 --volume 1.5 --no-write
```

- **Classifier.** Ordered rules, first match wins: unambiguous BSE subcategories,
  then routine paperwork (ESOPs, newspaper ads, trading-window notices, ESG), then
  keywords on title + detail, then a same-day pass (a generic "Outcome of Board
  Meeting" on results day is results). On the 14 Nov snapshot rules place 379 of
  392 filings; the 13 left say nothing beyond "Disclosure under Regulation 30" and
  go to the LLM in step d (cached by filing id in `data/seed/push/llm_classifications.json`).
- **Score** = category base (or its lower advance-notice score) + text modifiers
  (CEO/CFO change +, re-appointment −, routine debt paperwork −, rating downgrade +)
  + the market reaction in the first session that could react. A move is credited to
  one filing per session (results beat a board change on results day). Tiers: ≥70
  Needs attention, ≥40 Worth knowing, else Routine (collapsed to a count).
- **Repeats** collapse into one card: same company, category and title with dates and
  numbers removed; everything filed on results day is one card.
- **Alerts** fire on |move| ≥ 4%, volume ≥ 2× its 20-day average, optionally a σ
  threshold, and on filings in chosen categories at or above "Worth knowing". Each
  stores its reasons ("Volume 3.4× its 20-day average"). The defaults are written into
  both JSON files so the app re-applies the user's own thresholds to stored metrics.

## Phase 2 (d): LLM router

```
config/models.yaml        providers, per-task model chains, free-tier budgets
llm/router.py             Groq -> Gemini fallback, JSON-schema validation, cache, usage log
llm/env.py                .env loader (keys never leave .env; .env is git-ignored)
ingest/pdfs.py            PDF download (cached) and text extraction in Python
push/llm_classify.py      classifies filings no rule could place
scripts/llm_check.py      keys, model availability, --ping, --usage (the cost log)
scripts/classify_pending.py
```

Each task has a chain of models. The router moves to the next one when a key is
missing, the input is a PDF the provider can't read, the request exceeds the
model's tokens/minute, its daily budget is used, the call fails or is rate-limited
for too long, or the reply still fails the JSON schema after one repair attempt.
Models are asked for categories, text and copied figures only; every number FINN
shows is computed in Python. Every call is logged to `data/seed/llm_usage.jsonl`.

## Phase 2 (e): results card

```
push/results.py                 page choice, extraction schema, statement checks, metrics
scripts/build_results_cards.py  writes data/seed/push/results_cards.json
scripts/fetch_results_pdfs.py   saves a company's statement pages as test input
```

This quarter vs last quarter vs the same quarter last year. Standard companies show
Revenue, EBITDA (+ margin), PBT and PAT; lenders show NII, PPOP, provisions and PAT.

1. **Page.** The newest results card holding the statements (not a half-yearly report
   or a deck); in its PDF, the best-scoring P&L page on the company's primary basis.
   Cash-flow, segment, balance-sheet, highlights and US-dollar pages are skipped.
2. **Copy.** The model copies the quarter columns' line items into a JSON schema. It
   does no arithmetic.
3. **Check.** Python checks the statement's own sums, works out the unit (lakh vs crore,
   confirmed against screener.in), rebuilds unreadable rows from the other lines and
   screener.in, then computes every derived figure and compares each with screener.in.
   A figure is corrected only when the statement's own sums *and* screener.in agree on
   a different value (HDFC Bank's OCR'd June-quarter PBT "26,108.30" → 25,108.30).
4. **Status.** `verified` (all main figures match screener.in), `partial` (some can't be
   checked), `mismatch` (shown with screener's figure), `screener_only` (PDF unreadable).

`EBITDA = PBT before exceptional items + finance costs + depreciation − other income`
(and before share of associates), which equals screener's "Operating Profit".

## Phase 2 (f): management card

`push/management.py`, `scripts/build_management_cards.py` → `data/seed/push/management_cards.json`
(keyed by filing id). From the filing only: each person's name, role, joining/leaving,
effective date, stated reason, prior roles, and whether the role is at a subsidiary.
Every name, reason and prior role the model returns must appear in the filing text,
or it is dropped with a note. Flags: CEO/MD exit, CFO exit, a resignation with a vague
or missing reason, an executive leaving more than 10 days from a quarter end.

## Phase 3: the app (`web/`)

Next.js PWA that reads only the committed seed (`data/seed/`) at build time, so every
data commit redeploys it. App settings (time windows, default window, which results
figures reach the inbox) are in `config/app.yaml`; alert thresholds and tiers come from
`push.yaml` via `feed.json`.

```bash
cd web
npm install
npm run dev        # http://localhost:3000
npm test           # node --test: browser-side inbox reproduces alerts.json
npm run build
```

- **Inbox:** price alerts, then "Needs attention" and "Worth knowing" cards (repeats
  collapsed), routine filings folded into one line. Marking done is stored per device
  (localStorage); the bell filters to alerts. Window chips re-run the same grouping and
  alert rules as `push/priority.py` and `push/alerts.py`, in the browser.
- **Design tokens** in `web/app/globals.css`: ink, ivory, teal (interactive only), muted
  green/red for price moves only, each with an arrow and sign. IBM Plex Sans is
  self-hosted via `next/font/local`; its digits are tabular.
- **Deploy:** Vercel project with Root Directory `web`; files outside it (seed, config)
  are read during the build.
