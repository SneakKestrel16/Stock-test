# CLAUDE.md: Stock Tracker

Handoff notes for Claude Code. Read this first; it carries the context from the
conversation where this project started.

## About the user

- New to investing and to Python. Explain things plainly; avoid jargon or define it.
- Windows, PowerShell. Use `py` (Python launcher) in instructions, e.g.
  `py -m pip install -r requirements.txt`, `py stock_tracker.py watch`.
  Fall back to `python` if `py` isn't recognized.
- Hasn't put real money in yet. Plans to set the SEC contact email once they do.
- A copy of `stock_tracker.py` was also saved to their Downloads folder before
  this repo existed; the repo is now the source of truth.

## Hard rules (the user asked for these)

1. **Long-only. Never shorting, margin, options, or anything where losses can
   exceed the money invested.** The tool only suggests stocks to BUY and when
   to consider SELLING shares already owned. Don't add short signals, "sell
   short" suggestions, leverage, or options features, even as optional flags.
2. **Be honest about prediction.** It's a screener/research aid, not a price
   predictor. Keep the "not financial advice" reminders. Never promise returns.
3. **Privacy.** The SEC contact email goes only to sec.gov (it's required in
   the User-Agent by SEC's API) and is stored in `~/.stock_tracker/state.json`.
   Never commit personal data. The repo is currently **public**.

## What exists

- `stock_tracker.py`: main CLI (single file). Commands: `pick`, `history`,
  `watch`, `add`, `remove`, `list`, `setup`.
  - Data: `yfinance` (`.info`, `yf.download`, `.history`, `.news`,
    `.upgrades_downgrades`, `.calendar`) and SEC EDGAR
    (`company_tickers.json` → CIK → `data.sec.gov/submissions/CIK##########.json`).
  - `pick`: safety filters (mcap ≥ $10B, fwd P/E > 0, FCF > 0, price > 200-day MA,
    D/E < 250) → percentile-rank scoring on value/quality/growth/momentum →
    top pick + 15% stop-loss + 5 runners-up.
  - `watch`: news, analyst up/downgrades, next earnings, ±5% days, dividends/
    splits, SEC filings (8-K items decoded; red-flag items 1.03/3.01/4.02/2.06/4.01
    marked `!!`). Remembers seen item IDs so only new things show. Position alerts:
    stop-loss hit, +50% gain, below 200-day MA. Writes a Markdown report to
    `~/.stock_tracker/reports/`.
  - yfinance news has two shapes (old flat dict vs new `{"content": {...}}`);
    both are handled in `news_events`.
  - `track` / `backtest` (added 2026-10-22): `log_picks` appends the top 5 of
    every pick run to `~/.stock_tracker/picks.csv`; `track_record` compares each
    with SPY over the same trading days. `backtest` replays the pick monthly
    using SEC XBRL `companyfacts` (cached in `~/.stock_tracker/sec_facts/`),
    taking only figures filed by each date. Trailing P/E goes in the
    `forwardPE` column so `apply_filters`/`score` are reused unchanged. Share
    counts are multiplied by later splits to match yfinance's split-adjusted
    `Close`; returns use `Adj Close`. Gotcha: never drop picks with no price
    data from the track record (a delisted pick would vanish and flatter it).
    Status: track checked on real Yahoo data; backtest checked only on fake
    data (`tests/fake_run.py backtest`), because the real run needs the user's
    SEC contact email. First real run: check that few tickers are "skipped" and
    that market caps / P/Es look sane in `--csv` output.
- `stock_screener.py`: earlier, simpler ranker (prints top N). Kept for reference.
- `tests/fake_run.py`: monkeypatches yfinance + requests with fake data so every
  command runs offline. Cloud sandboxes usually can't reach Yahoo or sec.gov,
  so use this to test there. All commands passed with it.

## Desktop app + desktop shortcut (done 2026-10-22)

Built as planned below: `StockTracker.pyw`, `Start Stock Tracker.bat`,
`tests/fake_gui.py`. The shortcut was created on the user's PC (Desktop is under
OneDrive). Gotcha: running a test script from `%TEMP%` breaks `import numpy`
(something there shadows a module), so run drivers from a clean folder.
Original design:

1. **Refactor `stock_tracker.py`** so the logic returns data instead of printing,
   keeping the CLI working on top of it:
   - `screen(tickers, weights, min_mcap, progress=None) -> (ranked_df, filter_report)`
   - `history_stats(ticker, period) -> (hist_df, stats, uptrend)`
   - `check_ticker(ticker, state, days, show_all) -> {alerts, events, note, price}`
     (updates `state["seen"]`)
   - `get_fundamentals` takes an optional `progress(i, n)` callback.
2. **`StockTracker.pyw`**: tkinter + ttk window (no extra installs; ships with
   python.org Python), `matplotlib` `FigureCanvasTkAgg` for charts. Tabs:
   - **Pick**: "Find best buy candidate" button, min market cap + stop-loss %
     inputs, result card (ticker, name, price, score, factor scores, key metrics,
     stop-loss), runners-up table (click a row to show it in the card),
     "Add to watchlist" and "View history" buttons, filter summary.
   - **History**: ticker + period (1y/2y/5y/10y/max), stats panel (returns,
     CAGR, 52-week range, volatility, worst drop, dividends, 50/200-day MA),
     embedded price chart with 50/200-day averages, "Save CSV" (file dialog).
   - **Watchlist**: positions table (ticker, bought, price, gain, stop level,
     status), add/update form (ticker, bought price optional, stop %), remove,
     "Check for updates" (+ "show everything" checkbox, look-back days), events
     table with red rows for `!!` items; double-click opens the link.
   - **Settings**: SEC contact email, open data/reports folder, "Create desktop
     shortcut", reminder that it's buy-only and not advice.
   - All network work in background threads; results passed back to the UI via a
     `queue.Queue` polled with `after(100, ...)` (don't touch tk from threads).
     Status bar with an indeterminate progress bar.
   - On launch, check for missing packages and offer to `pip install` them
     (`sys.executable -m pip`, `CREATE_NO_WINDOW` on Windows).
   - `.pyw` errors are silent, so set `report_callback_exception`/`sys.excepthook`
     to show a messagebox and log to `~/.stock_tracker/app_error.log`.
3. **Desktop shortcut**: from the app (first launch prompt + Settings button),
   create `Stock Tracker.lnk` via PowerShell `WScript.Shell`, targeting
   `pythonw.exe` (swap from `python.exe` if needed) with the `.pyw` as the
   argument, working dir = repo folder, and Desktop path from
   `[Environment]::GetFolderPath('Desktop')` (may be OneDrive). Also add
   `Start Stock Tracker.bat` as a fallback launcher (tries `pyw`, then
   `pythonw`, else tells them to install Python with "Add to PATH").
4. Test the GUI with fake data (Xvfb + screenshots if in a Linux sandbox; the
   python3.12 there had tkinter after `apt-get install python3-tk`).
5. Update README (remove the roadmap item) and tell the user, in plain words,
   how to get it on their computer (`git clone` or GitHub's "Download ZIP"),
   then double-click `Start Stock Tracker.bat` once to make the shortcut.

## Possible later ideas (only if the user asks)

See `IDEAS.md` for the full brainstorm on making picks more consistent
(pick journal + backtest first, then market conditions, more factors, news).


- Run `watch` automatically each morning (Windows Task Scheduler).
- Package as a single `.exe` with PyInstaller.
