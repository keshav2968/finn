# FINN against the ENAM brief

Checked on 15 Nov 2026 against *FINN: Financial Investment Agent – AI Engineer Build Challenge*
and the companion reference. **Done**, **Partial** or **Missing**, with where to see it.

| Brief asks for | Status | Where, and what's missing |
|---|---|---|
| Mobile-first prototype that's easy to try on a phone | Done | finn-eight-psi.vercel.app, installable PWA, checked at 320/360/390/430px in both themes |
| Portfolio of 15–20 NSE/BSE companies, mixed sectors and sizes | Done | 15 names, 11 sector families, large to small cap (`config/portfolio.yaml`) |
| 3–5 ad-hoc research companies | Done | INFY, POLYCAB, KPITTECH, ETERNAL, plus HCLTECH as an unseen ticker |
| Research works on any NSE ticker, not hard-wired | Done (engine) | `python scripts/build_research.py SYMBOL` on any symbol; HCLTECH ran with no code changes. In the deployed app, a ticker not yet run shows that command instead of running a model from the phone |
| Price and volume, end of day | Done | yfinance, about a year per holding; frozen snapshot to the 13 Nov close |
| NSE/BSE corporate announcements | Done | BSE filings, about 60 days |
| Fundamentals: annual reports and concall transcripts | Partial | Transcripts are read; annual reports only through screener.in's tables (the PDFs aren't parsed) |
| Push: windowed digest, default 24h, window picker | Done | 24h / 7d / 30d. Default is 7d on purpose: the snapshot is a Saturday and its last 24h holds 4 filings |
| Digest filtered and prioritised, routine collapsed | Done | Needs attention, Worth knowing, routine in one collapsed row; repeats grouped |
| The reference's 17 announcement categories | Done | All 17 in `config/push.yaml`; rules place 379 of 392 filings, a model the other 13 |
| Triggered alerts: material announcement of a chosen type | Done | Category toggles in Alerts, saved on the device |
| Triggered alerts: volume ~2× average, price ±X%, configurable | Done | Price ±%, volume × 20-day average, and a σ threshold; re-applied in the browser at once |
| "Tell me the moment" | Partial | Alerts show when the app opens. Real Web Push works on free infrastructure, but it's opt-in and sent by hand: the data is a snapshot and there's no server |
| Management change: background of the incoming person | Partial | Who, role, date, reason, prior roles and risk flags, all from the filing. No LinkedIn bio (not free, not allowed) |
| Results: Revenue, EBITDA, PBT, PAT, QoQ and YoY | Done | From the results PDF, each figure checked against the statement and screener.in and flagged if it doesn't reconcile (3 of 15 fully verified). Lenders show NII, PPOP, provisions and PAT |
| Other announcements: one-line summary or right priority | Done | Rank plus the reason ("Volume 3.4× its 20-day average", "CFO change") |
| Pull menu: business snapshot | Missing | Left out on purpose |
| Pull menu: financial snapshot | Done | Numbers tiles and tables on each research page |
| Pull menu: trajectory | Done | 8 quarters, 5 years and this year so far |
| Pull menu: balance sheet | Missing | Left out; inputs are in the seed |
| Pull menu: cash quality | Missing | Left out; inputs are in the seed |
| Pull menu: narrative vs numbers (the worked example) | Done | The promise ledger: guided ranges across calls, exact quotes, verdicts |
| Pull menu: guidance | Done | Every numeric guide with its quote and transcript link |
| Pull menu: bull vs bear | Missing | Left out on purpose |
| Primary sources only on the pull side | Done | screener.in tables and the transcripts it links; quotes must match the transcript |
| An interaction model with a point of view | Done | Inbox with your own rules, plus a ledger you can interrogate from any story's Ask buttons |
| Efficiency: model routing, caching, cost | Done | Cheap model extracts, stronger one judges, content-hash cache; 367k tokens, ₹0 |
| Deliverable: deployed prototype | Done | Shows the redesign once `redesign` is merged to main |
| Deliverable: GitHub repository | Done | github.com/keshav2968/finn |
| Deliverable: AI build history | Partial | Keshav adds the session share links to the email |
| Deliverable: short write-up in the covering email | Done | Draft ready; only the build-history link is left to fill |
