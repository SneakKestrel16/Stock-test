# Stock Tracker

A personal, **buy-only** stock research tool. It finds a strong-looking stock to
research, shows its past performance, and watches the company for news, SEC
filings, analyst changes, earnings dates and big price moves.

> **Not financial advice.** It ranks stocks on measurable factors; it cannot
> predict prices. It never suggests shorting, margin or options, so the most
> you can lose is what you invest.

## Install (Windows PowerShell)

```powershell
py -m pip install -r requirements.txt
```

## Desktop app

Double-click **`Start Stock Tracker.bat`** once. The app opens and offers to put a
**Stock Tracker** shortcut on your desktop (also in its Settings tab). After that,
use the shortcut. Tabs: **Pick** (best buy candidate + ranked list), **History**
(returns, worst drop, chart, save CSV), **Watchlist** (your stocks, stop-loss
levels, news/filings/analyst changes; red rows need a closer look),
**Track record** (how your past picks did vs SPY), **Backtest** (the pick
replayed over past years) and **Settings** (SEC contact email, data folder,
shortcut).

If something goes wrong, the app shows a message and logs details to
`~/.stock_tracker/app_error.log`.

## Command line

```powershell
py stock_tracker.py pick --add               # best buy candidate (+ add to watchlist)
py stock_tracker.py history MSFT             # returns, worst drop, chart, CSV
py stock_tracker.py add MSFT --bought 410.50 --stop 0.15
py stock_tracker.py watch                    # what's new since last check
py stock_tracker.py list
py stock_tracker.py remove MSFT
py stock_tracker.py track                    # past picks vs SPY (--all adds runners-up)
py stock_tracker.py backtest --csv bt.csv    # replay the pick over 10 past years
py stock_tracker.py setup --contact you@example.com   # enables SEC filings
```

`stock_screener.py` is the earlier, simpler version: it ranks a list and prints
the top N.

## How the pick works

1. Pull company data for ~60 large US stocks (Yahoo Finance via `yfinance`).
2. Drop anything that fails a safety filter: under $10B, expected to lose money,
   negative free cash flow, below its 200-day average, or extreme debt.
3. Rank the rest on **value**, **quality**, **growth** and **momentum**
   (percentile ranks, equal weights by default; change with `--weights`).
4. Suggest a stop-loss (default 15% below the price) to cap the loss.

## Does the pick actually work?

Two ways to check, both against **SPY** (a fund holding the 500 largest US
companies, i.e. "just buy the market"):

- **Track record.** Every pick run is saved to `~/.stock_tracker/picks.csv`
  (top 5). `track` shows how each did since, and after 1, 3, 6 and 12 months.
  Picks with no price data are listed, not dropped, so a delisted pick can't
  quietly make the record look better.
- **Backtest.** Re-runs the pick at every month-end of the past 10 years using
  only facts that were public then (company figures from SEC filings, with the
  date each was filed), holds it for a month, and compares. Needs the SEC
  contact email. First run downloads ~64 companies' filing histories (cached
  30 days in `~/.stock_tracker/sec_facts/`). Main limits: the stock list is
  today's winners (hindsight), so compare with "all stocks, equal" too;
  trailing P/E instead of forecasts; no costs or taxes.

## Where data is stored

Watchlist, seen items, the SEC contact email and reports live in
`~/.stock_tracker/` on your computer. Nothing personal is stored in this repo.
