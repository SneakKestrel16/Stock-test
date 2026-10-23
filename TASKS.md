# Tasks (overnight solo run, started 2026-10-22 23:55)

User asked (verbatim intent): work solo all night, auto-accept everything, keep
**weekly usage under 20%** of the weekly limit (was 5% at start; check
`get_usage` between steps and stop at ~19%). Commit + push each step.

## Queue

1. [in progress] Hindsight-free backtest: `backtest(universe="sp500")` uses
   Wikipedia page history (old revisions of "List of S&P 500 companies") as
   point-in-time members, CIK -> today's ticker. Code patched in; still to do:
   CLI flag `--universe sp500`, run it (first run fetches ~700 SEC files, slow;
   run in background), record coverage + results in IDEAS.md, compare with list.
2. Bug tests: `tests/regression.py`, offline smoke over every CLI command
   (fake_run), GUI tour with screenshots (driver pattern: runpy StockTracker.pyw,
   patch messagebox, PIL ImageGrab), real-data smoke in an isolated HOME.
   (Done in module: `web_news()` with NEWS_FILLER regex, `stock_detail()`,
   `detail_facts()`, CLI `lookup TICKER`. GUI: Stock tab, web news in Pick
   checklist window, Settings > Look (THEMES/ACCENTS/TEXT_SIZES, restart) written,
   NOT yet run/screenshotted.)
3. "Web search" for candidates: news from the web per stock (Google News RSS,
   no key) in the checklist / detail view.
4. Convenience settings: colour theme (light/dark + accent), text size; saved
   in state.json "prefs"; Settings tab.
5. Detail search: new "Stock" tab: type any ticker -> overview (name, sector,
   description, price, market cap, P/E, 52w range, dividend), price chart,
   news (Yahoo + web), checklist, SEC filings, analyst data, add to watchlist /
   practice buttons.
6. Compare with other stock apps (Yahoo Finance, Finviz, Morningstar, Seeking
   Alpha, Robinhood, Stock Rover): list what to add/remove in IDEAS.md, build
   cheap useful ones.
7. Final full test pass, docs (README, CLAUDE.md, IDEAS.md), push.

Rules still apply: long-only, no predictions promised, SEC email only to
sec.gov (Wikipedia/Google get a plain UA), no personal data in repo.
Gotcha: bash heredocs in this environment mangle backslashes and quotes; write
patch scripts with the Write tool instead.
