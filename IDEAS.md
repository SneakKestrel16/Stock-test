# Ideas: making the picks more consistent

Brainstorm from 2026-10-22. Nothing here is built yet. Every idea stays inside
the hard rules in `CLAUDE.md`: buy-only, no shorting/margin/options, and no
promise that anything predicts prices.

**The honest part first.** Adding more data does not by itself make the guesses
better. More inputs can also make the tool *fit the past* by accident and then
do worse in the future (called "overfitting"). The only way to know whether an
addition helps is to **measure it**. That is why idea 1 comes first: without
it, the other ideas are guesses about guesses.

Data sources were checked on 2026-10-22 from the user's PC: the yfinance 1.7.0
attributes listed exist; FRED's no-key CSV
(`fred.stlouisfed.org/graph/fredgraph.csv?id=...`) and SEC's
`data.sec.gov/api/xbrl/companyfacts/CIK##########.json` both returned HTTP 200.
Other sources are named but not checked yet.

## 1. Keep score (do this first) — built 2026-10-22

Built as `log_picks`, `track_record` and `backtest` in `stock_tracker.py`
(CLI `track`, `backtest`; app tabs Track record, Backtest). See README.

**First real backtest (run 2026-10-22, Sep 2016 to Oct 2026, $10,000 start):**

| | ended with | yearly avg | worst drop |
|---|---|---|---|
| Top pick | $48,502 | +17.0% | -41.0% |
| Top 5 average | $80,211 | +22.9% | -21.4% |
| SPY | $41,358 | +15.1% | -23.9% |
| All 64, equal | $65,448 | +20.5% | -20.3% |

What it says (inference, from one run):
- The **single top pick is close to a coin toss**: it beat SPY in 54 of 121
  months, swung from +132% (2017) to -38% (2018), and fixing a few data gaps
  moved its result from $147,676 to $48,502. Too fragile to trust alone.
- The **top 5 together** beat both SPY and the equal mix with a smaller worst
  drop. That points to idea 2 (spreading across several picks, stability).
- Everything beats SPY partly because the list is today's winners
  (hindsight). The fair yardstick is "all 64, equal": top 5 beat it by ~2.4
  points a year, which could still be luck. Running it with different `--years`
  or weights would show whether that edge holds.

- **Pick journal.** Each time `pick` runs, save the date, ticker, price, score
  and factor scores to `~/.stock_tracker/picks.csv`. A "Track record" tab then
  shows how each past pick did after 1, 3, 6 and 12 months **compared with just
  buying the whole market** (SPY, an index fund that holds the 500 largest US
  companies). If the picks don't beat SPY over time, the score isn't helping.
- **Backtest.** Re-run the scoring as if it were each month of the past 10
  years and see what it would have picked. Gotcha: yfinance `.info` only gives
  *today's* numbers, so a backtest built on it secretly uses the future
  ("lookahead bias"). SEC XBRL `companyfacts` has historical financials with the
  date each was filed, which fixes that for fundamentals. Prices come from
  `yf.download`.
- **Check every new idea below against the journal and backtest** before keeping it.

**Variants tested 2026-10-22** (same period, real data; `backtest --sector`,
`--market-filter`):

| variant | top pick | top 5 | worst drop (top 5) |
|---|---|---|---|
| plain (default) | $48,502 | **$80,211** | -21.4% |
| rank value/quality within sector | $47,653 | $50,654 | -22.7% |
| sector + cash when SPY < 200-day | $18,917 | $27,204 | -27.1% |

Both ideas made things worse here, so they stay off (kept as options). The
market filter hurt most: it sat in cash after drops and missed the rebounds
(2020, 2022-23). That matches what's commonly reported for simple trend
filters on monthly data, but this is one test on one list (inference).

## 2. Make the ranking itself steadier — built / tested 2026-10-22

Built: stability check (200 weight nudges, "Settled" column), top-5 basket.
Tested and rejected (worse in backtest): ranking within sector; capping the
basket at 2 per sector ($73,287 vs $80,211; cap of 1: $49,414). The app now
just warns when 3+ of the top 5 share a sector. Not built: staying power
(needs months of journal), bigger universe (see new ideas).

- **Stability check.** Wiggle the factor weights a little 100 times and count
  how often the same stock comes out on top. Show it as "Top pick in 83 of 100
  variations". A pick that flips with tiny changes is a coin toss.
- **Require staying power.** Only call something the top pick if it has stayed
  in the top 5 for several runs over a few weeks (needs the journal from idea 1).
- **Compare within sector.** A P/E of 30 is cheap for software and expensive
  for an oil company. Rank each metric against companies in the same sector.
- **Bigger universe.** Screen the whole S&P 500 instead of 64 hand-picked names.

## 3. Market conditions — built 2026-10-22 (as information only)

Built: Home tab panel and `market` command with all five signals below. As a
trading rule (cash when SPY < 200-day) it did worse in the backtest, and the
app says so next to the panel.

A "Market weather" panel, shown above the pick. All are free:

- **Market trend:** is SPY above its 200-day average? (yfinance)
- **Fear gauge:** VIX, `^VIX` in yfinance. High = nervous market, big swings.
- **Recession warning:** yield curve, 10-year minus 3-month Treasury rate
  (FRED series `T10Y3M`). Below zero has often come before recessions, with a
  long and uneven delay.
- **Credit stress:** high-yield bond spread (FRED `BAMLH0A0HYM2`). Rising =
  lenders getting worried.
- **Breadth:** what share of the screened stocks are above their 200-day
  average. A market rising on only a few stocks is fragile.

Use: when most signals are bad, say "consider waiting or buying smaller
amounts". It never suggests betting against the market.

## 4. More facts about each company — mostly built 2026-10-22

Built as the Checklist (`check TICKER`, Pick tab button): earnings surprises,
estimate changes, insider trades, analyst mood trend, short interest, share
count, dividend payout. Context only: Yahoo keeps no history, so the daily run
now saves snapshots (`check_snapshots.csv`) to test them later. Not built yet:
Piotroski / Altman scores, long-term track record.

From sources already in use (yfinance, SEC):

- **Earnings surprises** (`earnings_history`): does the company usually beat
  its own forecasts?
- **Estimate changes** (`eps_trend`, `eps_revisions`): are analysts raising or
  cutting next year's profit estimates? Rising estimates is one of the better-
  studied signals.
- **Insider buying** (`insider_transactions`, SEC Form 4): executives buying
  with their own money, especially several at once, is more telling than
  selling (they sell for many reasons).
- **Share count:** buying back shares vs. issuing new ones (dilution).
- **Health scores from SEC data:** Piotroski F-score (9 yes/no checks on
  profits, debt and efficiency) and Altman Z-score (bankruptcy risk).
- **Track record:** 10 years of revenue and profit from SEC XBRL. Steady
  growers vs. boom-and-bust. How far the stock fell in 2008, 2020 and 2022.
  Years of dividend increases.

## 5. Reading the news and what people say — not built

Skipped for now: weakest evidence for the effort; AI summary needs an API key
and costs per run.

- **Headline mood.** Score each headline positive/negative and show the trend.
  Simple word lists (e.g. the VADER library) are cheap; an AI model reads
  better. News mostly explains moves that already happened, so treat this as
  context, not a signal.
- **More news sources.** Google News RSS search for the company name (no key
  needed; not checked yet).
- **What changed in the annual report.** Compare this year's 10-K "Risk
  Factors" section with last year's and list new risks.
- **AI research summary.** For the top pick, ask Claude (with web search) to
  summarise recent news, the business, main risks and what critics say, with
  links. Costs a little per run and needs an API key. Clearly labelled as a
  summary, not advice.
- **Social media buzz** (Reddit, StockTwits): very noisy and easy to
  manipulate. Useful at most as a "lots of hype, be careful" warning.

## 6. Protecting against mistakes — built 2026-10-22

All four are in the Checklist (ATR stop, earnings warning, watchlist overlap,
missing-data warning).

- **Stop-loss sized to the stock.** Use the stock's normal daily swing (ATR,
  "average true range") instead of a flat 15%, so calm stocks get tighter
  stops and jumpy ones don't get sold on ordinary noise.
- **Earnings warning.** Flag "earnings in 5 days" on the pick card: prices
  often jump or drop on that day.
- **Diversification check.** Warn when the pick is in the same sector as, or
  moves closely with, stocks already on the watchlist.
- **Data sanity checks.** Flag missing or odd numbers (yfinance sometimes
  returns glitches) and lower the confidence instead of quietly scoring 0.5.

## 7. Automation — built 2026-10-22

Settings > Automatic daily run (Task Scheduler, weekdays): journal a pick,
check the watchlist, update practice tests, save checklist snapshots.
Not yet verified by actually creating the task on this PC.

- Run `pick` and `watch` each morning with Windows Task Scheduler, so the pick
  journal fills up on its own and the track record grows.

## New ideas (2026-10-22, from building the above)

Ranked by expected value for effort. Same rule: measure before keeping.

1. **BUILT** (`practice start --follow`, Practice tab checkbox). **Practice "follow the picks" mode.** A practice test that re-buys the
   current top 5 every month. The honest real-time test of the exact strategy
   the backtest measures, without hindsight in the stock list going forward.
2. **BUILT and run 2026-10-23** (`backtest --universe sp500`). Top 5 $55,375
   (+18.5%/yr, worst drop -26.2%) vs SPY $41,358 and equal-weight members
   $32,681; top pick alone $12,048 (-52.3% worst drop). So the edge shrinks a
   lot without hindsight but the basket still led; the single top pick is not
   usable. Coverage per month: ~501 members, 461 priced, 453 valued (missing =
   mostly bought out / delisted, Yahoo drops them: some survivorship left).
   Rejected options rerun on this list, top 5: `--every 3` $33,948 (worst
   -36.4%), `--sector-cap 2` $34,483 (-28.4%), `--market-filter` $32,682
   (-35.1%). All worse than plain monthly, so defaults stay. Warning sign:
   capping sectors cuts the result from $55k to $34k, so much of the edge
   came from piling into one sector that happened to win. Inference; the
   monthly CSV's picks would show which sector. Treat the sector warning on
   the Pick tab seriously.
   **Hindsight-free stock list.** Use S&P 500 membership as of each backtest
   date (Wikipedia keeps a table of changes; unverified source) so the backtest
   stops choosing among today's winners. Biggest known flaw in the numbers.
3. **Out-of-sample check.** Before trusting any weight change, tune on
   2016-2021 and test on 2021-2026. A tweak that only wins in-sample is luck.
4. **TESTED: monthly is best.** Top 5: monthly $80,211 (worst drop -21.4%),
   quarterly $64,556 (-26.4%), every 6 months $75,883 (-31.8%); `backtest --every N`.
   **Rebalance less often.** Test quarterly vs monthly: fewer trades means
   lower costs and taxes in real life, possibly similar returns.
5. **Test the snapshots.** After ~12 months of `check_snapshots.csv`, check
   whether "analysts raising estimates" or "insider buying" picked better stocks.
6. **BUILT** (Budget box on the Pick tab). **Position-size helper.** "How many shares for $X, staying under 5% of
   savings" on the Pick card.
7. **BUILT** (watchlist alert in the 45 days before). **Holding-period note.** On the watchlist, show when a position passes one
   year (US long-term capital gains are taxed lower; inference, check local rules).
8. **Desktop notification** when the daily run finds a stop-loss hit or red flag.
9. Piotroski F-score from SEC data, then backtest it as a quality factor.


## Compared with other stock apps (2026-10-23)

From general knowledge of each app's public features, not a fresh survey;
check their sites before relying on a detail.

| App | What it does well | Taken here? |
|---|---|---|
| Yahoo Finance | Quote page, chart vs index, key stats, news | **Built**: Stock tab with S&P 500 same-period returns line |
| Finviz | Screener filters, short interest, insider trades, heat map | **Built**: short interest, insider ownership; insider trades already in checklist. Heat map skipped (decoration, no decision value) |
| Morningstar | Fair value estimate, moat rating, dividend safety | **Built**: payout ratio. Fair value / moat skipped: analyst judgement we can't reproduce or test |
| Seeking Alpha | Quant factor grades (value, growth, profitability, momentum) | Already the score's four parts. Idea: grade a looked-up stock against the list |
| Robinhood | Simple buy flow, price alerts | Stop-loss alerts exist; buying stays out (research tool only) |
| Stock Rover | Peer comparison tables, portfolio vs benchmark | Track record vs SPY exists. Idea: peers table on the Stock tab |

**Not adding** (on purpose): social-media sentiment and "trending" lists
(noise, no point-in-time history to test), price predictions or targets of our
own, options/margin anything (long-only rule), real-time streaming quotes
(this ranks monthly; seconds don't matter).

**Remove?** Nothing removed. The weakest feature is the analyst target line:
targets lag price and the backtest can't test them. It stays as context only.

## Day-trade rule tuning (2026-10-24)

`practice replay` on Yahoo's 60 days of 5-minute bars (2026-07-31 to 2026-10-23),
64-stock list, $10,000. 144 rule sets ranked on the first 30 sessions (train),
then run once on the last 30 (test). Only the best-on-train set's test number is
a fair out-of-sample result; the rest are context.

| Rules | Train | Test |
|---|---|---|
| Old day rules (2% stop, 3% take-profit, refill next-ranked) | $9,929 | $9,553 |
| New day rules (2% trailing stop, no take-profit, refill SPY) | $9,953 | $9,629 |
| Top 5 held 9:35-15:55, no auto-sell | $9,947 | $9,629 |
| SPY same hours / held throughout | $10,041 / $10,250 | $9,943 / $10,016 |
| Best on train: 5% trailing stop, no take-profit, refill next, **hold overnight** | $10,781 | **$10,831** |

One fix at a time (setting chosen on train): volatility stop (1x ATR) +29 / -142,
wider 3% stop +9 / -100, trailing +2 / +16, no take-profit +70 / +37, refill SPY
+34 / +67, hold overnight -224 / +960 (train / test, vs old rules). Kept the
three that won both. Selection bias: 144 sets tried on 30 days, so the train
winner's edge is partly luck; its test result is the honest number.

**BUILT 2026-10-23** (`practice swing`, Practice tab). A "swing" practice mode with the best-on-train rules (hold overnight,
5% trailing stop), tested forward in real time before trusting it.

## S&P 500 funnel vs fixed 64 list (2026-10-24)

Funnel: rank the S&P 500 (members as of that month) from the day before's close,
keep the top 64, trade from that. Same 60 sessions and split as the rule tuning.

| | Train (Jul 31 - Sep 11) | Test (Sep 14 - Oct 23) |
|---|---|---|
| Day trade, fixed 64 list | $9,953 | $9,629 |
| **Day trade, funnel** | **$10,270** | **$9,685** |
| Swing, fixed 64 list | $10,781 | $10,831 |
| Swing, funnel | $10,021 | $9,574 |
| Top 5 held 9:35-15:55: list / funnel | | $9,629 / $10,206 |
| SPY held throughout | $10,250 | $10,016 |

Kept for day trade only (won both halves; still loses money on the unseen days).
Swing stays on the list (lost both; note its rules were tuned on the list, which
favours the list on train but not on test). The funnel's picks held all day
beat SPY on the test half while the day rules turned them into a loss: the
selling rules, not the stocks, are what lose. Funnel picks lean to memory chips
and oil (MU, SNDK, APA, EOG) on these dates: a sector bet, see the sector warning.
