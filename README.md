# FINN: a filter for a daily investor

FINN is a mobile-first investing assistant built for the ENAM AI Engineer build challenge.
It does two jobs:

- **Push:** what changed in your portfolio, ranked so the few things that matter come first.
- **Pull:** for any NSE company, what management promised on its earnings calls against
  what the reported numbers show.

**Try it on a phone:** https://finn-eight-psi.vercel.app (add it to your home screen; it
is a PWA). Data is a snapshot taken on **14 Nov 2026, 15:06 IST** (prices to the 13 Nov
close). Everything you see was built from that snapshot by the code in this repository.

| | |
|---|---|
| Portfolio | 15 NSE names across banks, NBFC, IT, FMCG, pharma, capital goods, consumer internet, chemicals, a conglomerate and a small cap (`config/portfolio.yaml`) |
| Research demo set | INFY, POLYCAB, KPITTECH, ETERNAL, plus HCLTECH run as an unseen ticker |
| Tests | 263 Python (offline, real fixtures) + 7 web (`node --test`) |
| Spend | ₹0. Free tiers only (Groq, then Gemini as fallback). Token log below |

---

## What it does

The app has four tabs in a bottom bar:

| Tab | What's there |
|---|---|
| **News** | The push feed: headline-first stories, each with a ticker chip showing the stock's move on the last session, an impact label (High impact, Notable, Routine) and category filter chips. Stories are read or unread: opening one marks it read, and "Mark all read" clears the lot. Top stories carry a price strip for the window with the filing's day marked. |
| **Markets** | A watchlist you choose from the 15 holdings: price, day change and a 30-session sparkline per row, plus top movers (up, down, volume) and an advance/decline bar. Each stock has its own page: a chart with 1M/3M/6M/1Y ranges, volume underneath and the snapshot's filings marked on the price line (tap one to open it; drag to read any session), plus key numbers, 52-week range, returns and the filing list. |
| **Research** | Search for any ticker, the researched companies with their track record and verdict mix, and the rest of the portfolio with the command that researches them. |
| **Alerts** | What crossed your rules (read/unread), the alert rules themselves, dark/light theme, and installing the app. |

Every tab ends with a footer that names the data sources in words (no logos), gives the
snapshot date, and says it isn't investment advice.

**Design system:**
- **Type:** one family (Plus Jakarta Sans) with tabular figures for every number; JetBrains
  Mono only for ticker symbols. An eight-step type scale and sentence-case section heads.
- **Colour:** teal only on things you can tap; green and red only on price moves (reported
  figures and research verdicts are ink, told apart by shape).
- **Layout:** 1px hairlines between rows instead of boxes inside boxes.
- **Charts:** label their own high, low, last close and filing dates on the line.

**Motion:** one entrance on the app's first screen (News, once a visit), a 120ms cross-fade
between tabs, and a hover and press layer: rows take a faint wash, buttons and chips step up
1px and sink when pressed, text actions draw an underline. Nothing animates because a page
opened or scrolled, and everything rests under "reduce motion".

**Installable app:**
- **Android/Chrome:** a manifest with 192/512 icons and maskable versions, `display:
  standalone` and a theme colour, plus a service worker. Chrome's installability check
  reports no errors. FINN shows its own install banner after your first tap; once dismissed
  or installed it never shows again.
- **iPhone/iPad:** there's no install API, so FINN shows a one-time sheet with the Share →
  Add to Home Screen steps, only in a browser and not once installed. It also sets the
  apple-touch-icon, the standalone meta tags and a translucent status bar.
- **Offline:** the service worker keeps the four tabs working offline. It caches only FINN's
  own public pages and hashed assets, never cross-origin filings, and there's no personal
  data in the app to cache.
- **Security headers:** CSP, HSTS, `X-Frame-Options: DENY`, nosniff, a referrer policy, a
  permissions policy and COOP are set in `web/next.config.ts`. The CSP allows inline scripts
  because statically generated Next.js pages need them; nothing loads from another origin.

### Push: how the feed is built

- **Windowed digest.** Pick 24h, 7d or 30d. Every BSE filing in the window across the
  portfolio is classified into the 17 reference categories, scored and tiered:
  - **Needs attention** and **Worth knowing** are cards.
  - Routine paperwork is one collapsed row that isn't counted in your queue.
  - Repeats (the same filing re-sent, everything filed on results day) collapse into one card.
- **Your alert rules.** The Alerts tab sets:
  - a price move threshold (±%);
  - a volume spike threshold (× the 20-day average);
  - an optional "unusual for this stock" threshold (σ of its own daily moves);
  - which filing categories ping you.

  Choices are saved on the device. The browser re-runs the same alert rules the pipeline
  uses on the stored metrics, so the badge and the list change immediately. Defaults are
  in `config/push.yaml`; the choices offered are in `config/app.yaml`.
- **Results card.** Revenue, EBITDA, PBT and PAT for the quarter, QoQ and YoY.
  - Lenders show NII, PPOP, provisions and PAT instead.
  - Figures are read off the results PDF, then checked against the statement's own totals
    and against screener.in. Each figure carries its check: ✓ verified, ⚠ mismatch (with
    screener's figure underneath), ? not checked.
  - A story headline only ever uses a checked figure.
- **Management change.** From the filing itself:
  - who is joining or leaving, the role, the effective date, the stated reason and prior roles;
  - flags for a CEO or CFO exit, a vague reason, or an exit far from a quarter end.
- **Everything else** gets its rank and the reason for it ("Volume 3.4× its 20-day
  average", "CFO change", "rating downgrade").
- **Ask buttons.** Each card has two or three questions. They open the company's research
  page with the question carried over.

### Pull: promises vs delivery (`/research/SYMBOL`)

1. **Numbers** (Python only, from screener.in): the last 8 quarters, 5 years, and this fiscal
   year so far.
2. **Track record line,** counted in Python, e.g. "2 checkable promises: 2 delivered · 4 still
   running, 1 with goalposts moved".
3. **The ledger.** Each promise shows:
   - every guided range across calls as a band, with the actual as a dot;
   - the exact quotes with links to the transcript PDF;
   - a verdict: Delivered, Missed, Pending, Goalposts moved or Unverified.

   A "guidance has gone quiet" note appears when a metric was guided earlier and on none
   of the last three calls. For KPIT: 21% EBITDA margin guided in Nov 2025, nothing in
   four calls since, 15.6% so far this year.
4. **Any ticker.** The search box opens a pre-built company. For one that hasn't been run,
   it shows the one command that builds it.

The pull side uses primary sources only: the company's screener.in tables and the
earnings-call transcripts it links. No news, no broker notes, no model memory.

---

## Architecture

```
                    config/*.yaml  (tickers, thresholds, model chains: no tickers or thresholds in code)
                          │
  Yahoo Finance ──┐       ▼
  BSE filings ────┼─► ingest/ ──► data/seed/ (committed JSON snapshot)
  screener.in ────┘                 │
                                    ├─► push/      classify → score/tier → group → alerts      (rules, no LLM)
                                    │      └─ LLM only for: filings no rule can place, results PDFs, management filings
                                    ├─► research/  numbers → transcript filter → extract → join → judge
                                    │      └─ LLM only for: extracting promises (cheap), verdicts (strong), labels (cheap)
                                    ▼
                      data/seed/push/*.json, data/seed/research/SYMBOL.json
                                    │  read at build time
                                    ▼
                      web/ (Next.js, static pages) ──► Vercel, rebuilt on every push
```

- **The app needs no server and no keys.** `web/` reads the committed JSON at build time
  and ships static pages. The browser re-applies window and alert-rule choices to the
  stored metrics.
- **Models never do arithmetic.** They classify, copy figures off a page, extract quotes
  and pick a verdict. Every sum, margin, growth rate, comparison and count is Python.
- **Every model output is checked:**
  - A quote must fuzzy-match the transcript (rapidfuzz ≥ 90/100) and be spoken by management.
  - A target number must appear in its own quote.
  - Names in a management card must appear in the filing.
  - Results figures must reconcile with the statement or screener.
  - A verdict must be one the dates allow, and Python's arithmetic overrules a model that
    contradicts it.
- **One failing ticker, PDF or model call never stops a run.** It is logged, the previous
  file is kept, and the output carries a `status` and notes.

```
config/        portfolio, settings, push rules, research rules, model chains, app settings
ingest/        prices (yfinance), BSE announcements, screener.in parser, PDF download + text
push/          classify.py, priority.py, alerts.py, results.py, management.py, llm_classify.py
research/      numbers.py, transcripts.py, promises.py, ledger.py, build.py, periods.py
llm/           router.py (chains, budgets, JSON-schema validation, cache, usage log), env.py
scripts/       build_seed, build_push, classify_pending, build_results_cards,
               build_management_cards, build_research, llm_check
web/           Next.js app: app/ (news, markets, research, alerts, sw.js), components/, lib/ (loaders, feed logic)
tests/         offline tests with real-markup and real-transcript fixtures
docs/          data-contract.md: the JSON the app reads
```

---

## Run it

### The app only (no keys, no Python)

```bash
cd web
npm install
npm run dev        # http://localhost:3000
npm test           # the browser-side inbox reproduces the pipeline's alerts.json
npm run build
```

**Deploy:** import the repo in Vercel and set **Root Directory = `web`**. No environment
variables are needed. The build reads `../data/seed` and `../config`. A fresh clone builds
as is; this was checked on a clean clone with no `.env`.

### The pipeline

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env     # add free GROQ_API_KEY and GOOGLE_API_KEY (only the LLM steps need them)

pytest -q                                   # 263 offline tests, no keys, no network
python scripts/llm_check.py --ping          # one tiny call per model in config/models.yaml

python scripts/build_seed.py                # prices + filings + screener for the portfolio (~3 min)
python scripts/build_push.py                # classify, rank, alert → data/seed/push/
python scripts/classify_pending.py          # LLM for filings the rules couldn't place
python scripts/build_results_cards.py       # results PDFs → checked Revenue/EBITDA/PBT/PAT
python scripts/build_management_cards.py    # management-change filings → people cards

python scripts/build_research.py HCLTECH    # any NSE symbol, in the portfolio or not
python scripts/build_research.py INFY --no-llm     # numbers and transcript filtering only
python scripts/build_research.py INFY --dry-run    # print exactly what the extractor is sent
```

Commit `data/seed` and push; Vercel redeploys with the new data.

`.github/workflows/ingest.yml` can run the push pipeline daily at 17:05 IST: seed, feed, classification, results and management cards. The schedule
is **paused** during review so the demo stays on the tested snapshot; it can still be run
by hand. BSE sometimes blocks cloud IPs, so local runs are the reliable path.

---

## Phone notifications (optional, free)

FINN has no server, so by default nothing reaches a phone while the app is closed. The Alerts
tab shows what works on this device:
- the notification permission;
- whether it's installed (iPhone needs this, iOS 16.4+);
- the service worker and HTTPS;
- whether a sender is set up.

It also offers a local test notification.

To get real Web Push to your own phone at no cost:

1. `cd web && npx web-push generate-vapid-keys`.
2. In Vercel, add `NEXT_PUBLIC_VAPID_PUBLIC_KEY` = the public key, then redeploy. It's public by
   design, and the only key in the app.
3. On the phone, open FINN (on iPhone: from the Home Screen). In Alerts, tap **Allow
   notifications**, then **Subscribe this phone**, then **Copy subscription for the sender**.
4. In GitHub → Settings → Secrets → Actions, add:
   - `VAPID_PUBLIC_KEY`
   - `VAPID_PRIVATE_KEY`
   - `VAPID_SUBJECT` (a `mailto:` address)
   - `PUSH_SUBSCRIPTIONS` (the copied JSON, or a JSON array of several)
5. Actions → **push-alerts** → Run workflow. It sends the current alerts as one notification
   (`web/scripts/send-push.mjs`, which uses the `web-push` library). It's manual only and never
   touches the deployed site. `node scripts/send-push.mjs --dry-run` shows the message first.

## Model routing

Each task has a chain in `config/models.yaml`: the first model is tried, then the next. The
router (`llm/router.py`) moves down the chain when:

- a key is missing;
- the input is a PDF the provider can't read;
- the request is over the model's tokens-per-minute;
- the daily budget is used;
- a call fails or stays rate-limited past 65 s;
- the reply fails its JSON schema after one repair attempt.

Replies are cached by content hash (`data/cache/llm`), so a re-run only pays for what changed.

| Task | Input | First choice | Fallback | Why this model |
|---|---|---|---|---|
| `classify_filing` | headline + first PDF page, only for the 13 of 392 filings rules couldn't place | Groq gpt-oss-20b (low) | Gemini 3.5 Flash-Lite | Short, closed-set label |
| `extract_management` | one filing | gpt-oss-20b (low) | 3.5 Flash-Lite | Copying names and roles; checked against the text |
| `extract_results` | only the P&L page(s) of the results PDF | gpt-oss-120b (low) | Gemini 3.8 Flash (reads scanned PDFs) | Dense tables with many columns; mistakes are costly |
| `extract_promises` | ~9,000 chars per call of management passages with a metric, a number and a forward cue, filtered in Python from ~100–180 passages | gpt-oss-20b (low) | 3.5 Flash-Lite | Bulk extraction; quotes are verified afterwards |
| `judge_promises` | grouped promises + Python-computed actuals + outcome passages | gpt-oss-120b (medium) | 3.8 Flash | The one step that needs reasoning |
| `label_promises` | descriptions of "other" promises | gpt-oss-20b (low) | 3.5 Flash-Lite | 5-word display labels; Python clips them and falls back |

Most of the saving comes from what never reaches a model:

- Rules classify 379 of 392 filings.
- Python picks the one P&L page out of a results PDF.
- Python cuts a 30-page transcript of 100–180 passages to the ~10 worth reading.

---

## Cost log (real numbers)

Every call is appended to `data/seed/llm_usage.jsonl`. The table covers every model call
from the router's first run (14 Nov 16:50 IST) to the HCLTECH run (15 Nov 14:02 IST). That
includes all development re-runs of the research pipeline, not one clean pass.

| Task | Model | Paid calls | Input tokens | Output tokens | Cache hits | Failed attempts |
|---|---|---:|---:|---:|---:|---:|
| classify_filing | gpt-oss-20b | 18 | 25,831 | 2,376 | – | – |
| classify_filing | Gemini 3.5 Flash-Lite | 1 | 1,097 | 63 | – | 2 (Gemini 2.5 retired, 404) |
| extract_management | gpt-oss-20b | 18 | 31,720 | 4,722 | – | 1 (Gemini 2.5, 404) |
| extract_results | gpt-oss-120b | 15 | 40,186 | 10,121 | – | 5 (2 network; fallbacks: 503, network, Gemini 2.5 retired) |
| extract_promises | gpt-oss-20b | 54 | 112,564 | 23,932 | 100 | – |
| judge_promises | gpt-oss-120b | 48 | 73,408 | 38,768 | 13 | – |
| label_promises | gpt-oss-20b | 4 | 1,966 | 401 | – | – |
| **Total** | | **158** | **286,772** | **80,383** | **113** | **8** |

- **Actual spend: ₹0.** All of it ran on free tiers.
- **At Groq's paid list prices** (Oct 2026: gpt-oss-20b $0.075 / $0.30, gpt-oss-120b
  $0.15 / $0.60 per million input / output tokens), the whole build would have cost about
  **$0.07**.
- **One research run for an unseen company** (HCLTECH: 6 transcripts, 10 calls) used
  18,348 input + 4,969 output tokens, about **$0.004** at paid prices.
- **Cache:** 113 of 271 successful requests were answered from cache.

`python scripts/llm_check.py --usage` prints the running totals.

---

## Key decisions

- **Filter first, model last.** Most of the job is deciding what not to show or send, and
  rules and arithmetic do that cheaply and repeatably. The model handles only what rules
  can't: unplaceable filings, reading a P&L page, pulling promises out of speech, weighing
  evidence.
- **A promise ledger instead of a summary.** The brief's "promised vs delivered" example is
  the one place an AI adds signal over a screener page. Each promise is tracked across calls,
  so a cut target shows as 1.5–3.5% → 1.5–3% → 1–2% rather than a fresh Delivered.
  "Unverified" is a first-class verdict: a constant-currency target is never judged on
  rupee growth.
- **Static app, committed snapshot.** No backend to fall over during review. The data, the
  code that made it and the app are in one repo, and a data commit redeploys the site.
- **Thresholds are data, not code.** Tickers, alert defaults, research cues, windows and
  model chains are in `config/`. The user's own alert rules live in the browser.

## Honest limits

- **It's a snapshot, not live.** The data is from 14 Nov 2026. The window counts back from
  the snapshot time, and the default window is 7d rather than the brief's 24h: the snapshot
  is a Saturday, and its last 24h holds 4 filings, 1 of them worth knowing. 24h is one tap
  away.
- **Research is pre-built.** A ticker that hasn't been run needs
  `python scripts/build_research.py SYMBOL` with free keys, then a push. The app says so
  rather than calling a model from the phone.
- **Ask buttons don't write answers yet.** They open the company's evidence page with the
  question shown.
- **The pull side is narrow on purpose.** It covers numbers and promises vs delivery. There
  is no business snapshot, balance-sheet, cash-quality or bull/bear view, and annual reports
  aren't parsed (screener's tables come from them).
- **Results cards:** 3 of 15 are fully verified, 11 have at least one flagged figure, and 1
  comes from screener only. Flagged figures include:
  - HUL's revenue (the wrong line was read);
  - Marksans' EBITDA;
  - L&T's EBITDA (a definition gap with screener);
  - unchecked lender lines such as Bajaj Finance's NII.

  These are shown flagged with screener's figure, and are never used as a story headline.
- **Ledger misses.** Known, visible cases:
  - POLYCAB's export goal is filed under FY26 (the quote names no year; the model guessed).
  - Some labels are generic (HCLTECH's "Guidance range").
  - The extractor can miss an open-ended line (KPIT's "30% plus" for solution products).
  - Screener's margin can differ from the company's own definition (KPIT FY26: 18.9% vs
    the stated 20.8%). The verdict uses the company's stated figure when it gives one.
- **No phone notifications yet.** Alerts show when you open the app; nothing is pushed to
  the phone. On iOS, web push only works for apps added to the home screen (iOS 16.4+).
- **Charts are end of day.** One close per session from the snapshot. Filing markers only
  go back as far as the snapshot's filings (about 60 days), so the 1Y chart has markers in
  its last two months only.
- **Management background comes from the filing only.** A LinkedIn-style bio of the incoming
  person isn't scraped; that isn't free or allowed.

## Where I'd take it next

1. Answer the ask buttons with a grounded, quote-cited reply from the same transcripts and
   tables, via a small serverless function.
2. Add the cash-quality and balance-sheet views; the inputs are already in the seed.
3. Run research on demand from the search box (queue → build → redeploy), so an unseen
   ticker needs no terminal.
4. Fix the results-card misreads above, and add a person-background step for management
   changes from public sources.
5. Run ingestion on a schedule from a machine the exchanges don't block, with push
   notifications for alerts.
