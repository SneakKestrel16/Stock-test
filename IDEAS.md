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

## 2. Make the ranking itself steadier

- **Stability check.** Wiggle the factor weights a little 100 times and count
  how often the same stock comes out on top. Show it as "Top pick in 83 of 100
  variations". A pick that flips with tiny changes is a coin toss.
- **Require staying power.** Only call something the top pick if it has stayed
  in the top 5 for several runs over a few weeks (needs the journal from idea 1).
- **Compare within sector.** A P/E of 30 is cheap for software and expensive
  for an oil company. Rank each metric against companies in the same sector.
- **Bigger universe.** Screen the whole S&P 500 instead of 64 hand-picked names.

## 3. Market conditions ("is now a good time at all?")

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

## 4. More facts about each company

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

## 5. Reading the news and what people say

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

## 6. Protecting against mistakes

- **Stop-loss sized to the stock.** Use the stock's normal daily swing (ATR,
  "average true range") instead of a flat 15%, so calm stocks get tighter
  stops and jumpy ones don't get sold on ordinary noise.
- **Earnings warning.** Flag "earnings in 5 days" on the pick card: prices
  often jump or drop on that day.
- **Diversification check.** Warn when the pick is in the same sector as, or
  moves closely with, stocks already on the watchlist.
- **Data sanity checks.** Flag missing or odd numbers (yfinance sometimes
  returns glitches) and lower the confidence instead of quietly scoring 0.5.

## 7. Automation

- Run `pick` and `watch` each morning with Windows Task Scheduler, so the pick
  journal fills up on its own and the track record grows.

## Suggested order

1 (journal + backtest), then 3 (market weather), then 2 (stability + sector
ranking), then 4, then 5. Each step is checked against the journal from 1
before it's kept.
