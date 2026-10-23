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
use the shortcut. Tabs:

- **Home**: how-to steps, your alerts and practice tests at a glance, and
  "market weather" (market trend, fear gauge, recession and credit warnings).
- **Stock**: type any US ticker to see its key numbers (P/E, dividend and
  payout, short interest, insider ownership...), returns next to the S&P 500
  over the same periods, a price chart, news from Yahoo and the web (Google
  News), SEC filings and the checklist. Buttons add it to the watchlist or
  start a practice test.
- **Pick**: ranks big US companies; the top 5 is the suggested basket. Each
  stock has a **Checklist** (forecast changes, insider buying, earnings date,
  dividend safety, share buybacks, a stop-loss sized to the stock, overlap
  with your watchlist) and recent web headlines.
- **Practice**: try stocks with pretend money at live prices for N days, with
  automatic stop-loss / take-profit and your own buys and sells. When it
  ends you get a results list vs SPY. **Day trade** runs for today only:
  it buys today's top 5, sells any stock at -2% or +3%, moves that money into
  the next-ranked stock (SPY once the list runs out, so no cash sits idle),
  and sells everything 5 minutes before the close. It knows the NYSE
  holidays and 1 pm early closes; the Home tab shows whether the market is
  open now and when it next opens.
  **Replay result** (30 trading days, 2026-09-14 to 2026-10-23, no peeking
  ahead): $10,000 became $9,553 (-4.5%). Holding the same top 5 all day with
  no auto-sells: -3.7%. SPY over the same hours: -0.6%. The 2% stop-loss fired
  27 times, the 3% take-profit only 6, so the auto-sells mostly locked in small
  losses. Day trading these picks lost money in this test.
  **Tuning (2026-10-24):** 144 rule sets chosen on the first 30 of Yahoo's 60
  days, judged on the last 30. Kept, because each won on both halves: a
  trailing stop (2% below the day's high), no take-profit, and sale money into
  SPY. Together: +$76 per $10,000 on the unseen days, still -3.7%. Dropped:
  stops sized to volatility and wider fixed stops (lost on unseen days). The
  best set overall held overnight (5% trailing stop, no take-profit):
  $10,831 on the unseen days vs SPY $10,016, but that is swing trading, not
  day trading, and 30 days is a small test.
- **Watchlist**, **History**, **Track record** (your past picks vs SPY),
  **Backtest** (the pick replayed over 10 past years) and **Settings** (SEC
  email, shortcut, light/dark colours, accent colour, text size, and an
  optional automatic weekday run).

If something goes wrong, the app shows a message and logs details to
`~/.stock_tracker/app_error.log`.

## Command line

```powershell
py stock_tracker.py pick --add               # top candidates (+ add #1 to watchlist)
py stock_tracker.py lookup MSFT              # everything about one stock (numbers, news, filings)
py stock_tracker.py check MSFT               # extra checklist for one company
py stock_tracker.py market                   # market weather
py stock_tracker.py practice start MSFT KO --days 30 --take-profit 0.3
py stock_tracker.py practice day             # trade today's top 5 until the close (market hours)
py stock_tracker.py practice replay --days 30  # replay day trading on past 5-minute prices
py stock_tracker.py practice                 # update and show practice tests
py stock_tracker.py history MSFT             # returns, worst drop, chart, CSV
py stock_tracker.py add MSFT --bought 410.50 --stop 0.15
py stock_tracker.py watch                    # what's new since last check
py stock_tracker.py list
py stock_tracker.py remove MSFT
py stock_tracker.py track                    # past picks vs SPY (--all adds runners-up)
py stock_tracker.py backtest --csv bt.csv    # replay the pick over 10 past years
py stock_tracker.py backtest --universe sp500  # same, choosing from the S&P 500 as it was then
py stock_tracker.py daily                    # what the automatic run does
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
4. Suggest the top 5 as a basket (split evenly) and a stop-loss (default 15%
   below the price) to cap the loss. "Settled" shows how often a stock stays
   in the top 5 when the weights are nudged.

Ideas tested in the backtest and **rejected** because they did worse (still
available as options): ranking within sectors (`--sector`), sitting in cash
when the market trends down (`--market-filter`), capping sectors in the
basket (`--sector-cap`). Details in `IDEAS.md`.

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
  `--universe sp500` removes most of that hindsight: it chooses from the
  S&P 500 as it stood at each month-end (from Wikipedia's page history).

**Results, Sep 2016 to Oct 2026, $10,000 start, held one month, re-picked
monthly** (real data, run 2026-10-23):

| | Today's 64-stock list | S&P 500 as it was then |
|---|---|---|
| Top 5 basket | $80,211 | **$55,375** (+18.5%/yr, worst drop -26.2%) |
| Top pick alone | $48,502 | $12,048 (+1.9%/yr, worst drop -52.3%) |
| SPY | $41,358 | $41,358 (+15.1%/yr, worst drop -23.9%) |
| Every stock, equal | $65,448 | $32,681 |

The hindsight-free top 5 still beat SPY, but by much less than the 64-stock
list suggested. **Buying only the top pick did badly**: one stock is too much
luck. Use the basket. About 8% of past members had no Yahoo price data
(bought out or delisted), so a little hindsight remains. Past results don't
promise future ones.

## Where data is stored

Watchlist, seen items, the SEC contact email and reports live in
`~/.stock_tracker/` on your computer. Nothing personal is stored in this repo.
