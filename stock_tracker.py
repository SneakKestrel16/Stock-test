#!/usr/bin/env python3
"""
stock_tracker.py - pick a stock to research, pull its history, and watch the
company for news, SEC filings, analyst changes, earnings dates and big moves.

LONG-ONLY BY DESIGN. This program only ever ranks stocks to BUY and tells you
when you might want to SELL shares you already own. It has no shorting, margin
or options features, so the most you can lose is what you put in.

This is a research tool, not financial advice, and it cannot predict prices.

Setup (once):
    pip install yfinance pandas requests matplotlib
    python stock_tracker.py setup --contact you@example.com
        (the SEC asks for a contact email in requests to its free filings API;
         it is only sent to sec.gov. Skip this and SEC filings are skipped.)

Commands:
    python stock_tracker.py pick                    # find the single best buy candidate
    python stock_tracker.py pick --add              # ...and add it to your watchlist
    python stock_tracker.py history MSFT            # past performance + chart + CSV
    python stock_tracker.py add MSFT --bought 410.50 --stop 0.15
    python stock_tracker.py watch                   # what's new for your watchlist
    python stock_tracker.py watch NVDA --all        # everything recent, not just new
    python stock_tracker.py list
    python stock_tracker.py remove MSFT
    python stock_tracker.py track                   # how past picks did vs the market
    python stock_tracker.py backtest                # replay the pick over 10 past years

Run `watch` once a day (or schedule it with Task Scheduler / cron) and it will
only show you things that happened since the last time you checked.
"""

import argparse
import io
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    import numpy as np
    import pandas as pd
    import requests
    import yfinance as yf
except ImportError:
    sys.exit("Missing packages. Run:  pip install yfinance pandas requests matplotlib")

HOME = Path.home() / ".stock_tracker"
STATE_FILE = HOME / "state.json"
CIK_FILE = HOME / "sec_tickers.json"
REPORTS = HOME / "reports"
PICKS_FILE = HOME / "picks.csv"
FACTS_DIR = HOME / "sec_facts"
BENCH = "SPY"   # S&P 500 index fund: "just buy the whole market"

DEFAULT_TICKERS = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "AVGO", "ORCL", "CRM", "ADBE",
    "AMD", "CSCO", "QCOM", "TXN", "IBM", "NFLX", "INTU", "NOW",
    "JPM", "BAC", "WFC", "GS", "MS", "V", "MA", "AXP", "BRK-B", "BLK", "SPGI",
    "JNJ", "UNH", "LLY", "MRK", "ABBV", "TMO", "ABT", "AMGN", "ISRG", "VRTX",
    "PG", "KO", "PEP", "WMT", "COST", "HD", "LOW", "MCD", "NKE", "TJX", "BKNG",
    "CAT", "DE", "HON", "GE", "UNP", "LMT", "RTX", "ETN", "XOM", "CVX", "COP",
    "LIN", "NEE", "DUK",
]

FACTORS = {
    "value":    [("forwardPE", False), ("priceToBook", False),
                 ("evToEbitda", False), ("fcfYield", True)],
    "quality":  [("returnOnEquity", True), ("profitMargins", True),
                 ("debtToEquity", False)],
    "growth":   [("revenueGrowth", True), ("earningsGrowth", True)],
    "momentum": [("mom_12_1", True), ("ret_6m", True)],
}
POSITIVE_ONLY = {"forwardPE", "evToEbitda", "priceToBook"}

SEC_FORMS = {
    "8-K": "Major event report", "10-K": "Annual report", "10-Q": "Quarterly report",
    "4": "Insider buy/sell", "SC 13D": "Activist/5%+ stake", "SC 13G": "Large passive stake",
    "SC 13D/A": "Activist stake update", "DEF 14A": "Proxy (shareholder vote)",
    "S-1": "New share registration", "S-3": "Shelf registration (may sell new shares)",
    "424B5": "Share offering prospectus",
}
EIGHT_K_ITEMS = {
    "1.01": "signed a major agreement", "1.02": "ended a major agreement",
    "1.03": "BANKRUPTCY", "2.01": "completed an acquisition or sale",
    "2.02": "quarterly results", "2.03": "took on new debt",
    "2.05": "restructuring / layoffs", "2.06": "wrote down asset values",
    "3.01": "DELISTING notice", "3.02": "sold unregistered shares",
    "4.01": "changed auditor", "4.02": "PAST FINANCIALS UNRELIABLE",
    "5.02": "executive or board change", "5.03": "changed bylaws",
    "5.07": "shareholder vote results", "7.01": "investor disclosure",
    "8.01": "other event", "9.01": "exhibits attached",
}
RED_FLAG_ITEMS = {"1.03", "3.01", "4.02", "2.06", "4.01"}


# ---------------------------------------------------------------- state ----

STATE_LOCK = threading.RLock()     # the desktop app reads/writes state from several threads


def load_state():
    with STATE_LOCK:
        try:
            text = STATE_FILE.read_text()
        except FileNotFoundError:
            return {"contact": None, "watchlist": {}, "seen": {}}
        try:
            return json.JSONDecoder().raw_decode(text.strip())[0]   # ignores junk after the data
        except json.JSONDecodeError:
            # Never silently start over: the next save would wipe the watchlist for good.
            STATE_FILE.replace(STATE_FILE.with_name(f"state.damaged-{datetime.now():%Y%m%d-%H%M%S}.json"))
            return {"contact": None, "watchlist": {}, "seen": {}}


def save_state(st):
    write_json(STATE_FILE, st)


def write_json(path, obj):
    HOME.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with STATE_LOCK:
        tmp.write_text(json.dumps(obj, indent=2, default=str))
        tmp.replace(path)              # swap in whole: never a half-written file


def money(x):
    if x is None or pd.isna(x):
        return "-"
    return f"-${-x:,.2f}" if x < 0 else f"${x:,.2f}"


def pct(x):
    return f"{x:+.1%}" if x is not None and pd.notna(x) else "-"


# --------------------------------------------------------------- pick -----

def fetch_info(ticker):
    for attempt in range(3):
        try:
            return ticker, yf.Ticker(ticker).info or {}
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    return ticker, {}


def print_progress(i, n):
    print(f"\r  company data {i}/{n}", end="" if i < n else "\n", flush=True)


def get_fundamentals(tickers, progress=print_progress):
    rows = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fetch_info, t) for t in tickers]
        for i, fut in enumerate(as_completed(futures), 1):
            t, info = fut.result()
            if progress:
                progress(i, len(tickers))
            if not info:
                continue
            mcap, fcf = info.get("marketCap"), info.get("freeCashflow")
            price = info.get("currentPrice") or info.get("regularMarketPrice")
            target = info.get("targetMeanPrice")
            rows.append({
                "ticker": t, "name": (info.get("shortName") or t)[:30],
                "sector": info.get("sector", ""), "price": price, "marketCap": mcap,
                "forwardPE": info.get("forwardPE"), "priceToBook": info.get("priceToBook"),
                "evToEbitda": info.get("enterpriseToEbitda"),
                "fcfYield": (fcf / mcap) if fcf and mcap else None,
                "returnOnEquity": info.get("returnOnEquity"),
                "profitMargins": info.get("profitMargins"),
                "debtToEquity": info.get("debtToEquity"),
                "revenueGrowth": info.get("revenueGrowth"),
                "earningsGrowth": info.get("earningsGrowth"),
                "analystUpside": (target / price - 1) if target and price else None,
                "recommendation": info.get("recommendationKey"),
            })
    return pd.DataFrame(rows).set_index("ticker") if rows else pd.DataFrame()


def get_price_signals(tickers):
    data = yf.download(tickers, period="13mo", auto_adjust=True, progress=False, threads=True)
    close = data["Close"]
    if isinstance(close, pd.Series):
        close = close.to_frame(tickers[0])
    close = close.dropna(how="all")
    out = pd.DataFrame(index=close.columns)

    def ret(start, end=0):
        if len(close) <= start:
            return pd.Series(index=close.columns, dtype=float)
        return close.iloc[-1 - end] / close.iloc[-1 - start] - 1

    out["mom_12_1"] = ret(252, 21)      # 12-month return, skipping the latest month
    out["ret_6m"] = ret(126)
    out["vol_1y"] = close.pct_change().tail(252).std() * (252 ** 0.5)
    out["ma200"] = close.tail(200).mean()
    out["last"] = close.ffill().iloc[-1]
    return out


def get_sectors(tickers):
    """Sector of each ticker (today's, from Yahoo). Cached for 90 days."""
    cache = HOME / "sectors.json"
    fresh = cache.exists() and time.time() - cache.stat().st_mtime < 90 * 86400
    have = json.loads(cache.read_text()) if fresh else {}
    missing = [t for t in tickers if not have.get(t)]
    if missing:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for t, info in pool.map(fetch_info, missing):
                have[t] = info.get("sector") or ""
        HOME.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(have))
    return {t: have.get(t, "") for t in tickers}


def score(df, weights, sectors=None):
    """Percentile-rank each metric, average into factor scores, weight into one score.
    With `sectors` (ticker -> sector), value and quality metrics are ranked against the
    same sector (a P/E of 30 is cheap for software, dear for oil); sectors with fewer
    than 3 companies fall back to ranking against everyone."""
    fs = pd.DataFrame(index=df.index)
    groups = None
    if sectors is not None:
        groups = pd.Series(sectors).reindex(df.index).fillna("?")
        small = groups.map(groups.value_counts()) < 3
    for factor, metrics in FACTORS.items():
        ranks = []
        for col, higher in metrics:
            if col not in df:
                continue
            s = pd.to_numeric(df[col], errors="coerce")
            bad = (s <= 0) if col in POSITIVE_ONLY else pd.Series(False, index=s.index)
            r = s.where(~bad).rank(pct=True, ascending=higher)
            if groups is not None and factor in ("value", "quality"):
                r = s.where(~bad).groupby(groups).rank(pct=True, ascending=higher).where(~small, r)
            r[bad] = 0.0
            ranks.append(r)
        if ranks:
            fs[factor] = pd.concat(ranks, axis=1).mean(axis=1).fillna(0.5)
    total = sum(weights[f] for f in fs)
    if total == 0:
        raise ValueError("All weights are zero.")
    fs["score"] = sum(fs[f] * weights[f] for f in fs) / total
    return fs


def parse_weights(pairs):
    w = {"value": 1.0, "quality": 1.0, "growth": 1.0, "momentum": 1.0}
    for p in pairs or []:
        k, _, v = p.partition("=")
        if k not in w:
            raise ValueError(f"Unknown factor '{k}'. Use: {', '.join(w)}")
        w[k] = float(v)
        if w[k] < 0:
            raise ValueError(f"Weight for '{k}' can't be negative.")
    if not any(w.values()):        # check before downloading 64 companies, not after
        raise ValueError("All weights are zero.")
    return w


def screen(tickers, weights, min_mcap, progress=print_progress):
    """Rank tickers that pass the safety filters. Returns (ranked_df, filter_report),
    filter_report being [(label, removed_count)]. ranked_df is empty if none pass."""
    df = get_fundamentals(tickers, progress)
    if df.empty:
        raise RuntimeError("No data returned. Check your internet connection.")
    df = df.join(get_price_signals(list(df.index)), how="left")
    df, report = apply_filters(df, min_mcap)
    if df.empty:
        return df, report
    df = df.join(score(df, weights)).sort_values("score", ascending=False)
    return df.join(stability(df, weights)), report


BASKET_NOTE = """\
Spread it out: the top 5 together, split evenly. In the 10-year backtest the
top 5 grew more and fell less than the single top pick (see Backtest)."""


def stability(ranked, weights, runs=200, seed=0):
    """How settled the ranking is: nudge each factor weight to 50-150% of itself
    `runs` times and count how often each stock comes out #1 and in the top 5."""
    rng = np.random.default_rng(seed)
    factors = [f for f in FACTORS if f in ranked]
    scores, w = ranked[factors].to_numpy(), np.array([weights[f] for f in factors])
    top1 = pd.Series(0.0, index=ranked.index)
    top5 = pd.Series(0.0, index=ranked.index)
    for _ in range(runs):
        ww = w * rng.uniform(0.5, 1.5, len(w))
        order = ranked.index[np.argsort(-(scores @ ww), kind="stable")]
        top1[order[0]] += 1 / runs
        top5[order[:5]] += 1 / runs
    return pd.DataFrame({"stable1": top1, "stable5": top5})


def apply_filters(df, min_mcap):
    """Safety filters: only steady, profitable, uptrending companies qualify.
    Returns (passing_df, [(label, removed_count)])."""
    num = lambda c: pd.to_numeric(df[c], errors="coerce")
    checks = {
        f"market cap >= ${min_mcap/1e9:.0f}B": num("marketCap").fillna(0) >= min_mcap,
        "expected to be profitable (forward P/E > 0)": num("forwardPE") > 0,
        "generates cash (free cash flow > 0)": num("fcfYield") > 0,
        "in an uptrend (price above 200-day average)": num("last") > num("ma200"),
        "debt not extreme (debt/equity < 250%)": num("debtToEquity").fillna(0) < 250,
    }
    keep = pd.Series(True, index=df.index)
    report = []
    for label, ok in checks.items():
        ok = ok.fillna(False)
        report.append((label, int((keep & ~ok).sum())))
        keep &= ok
    return df[keep], report


def log_picks(ranked, top=5):
    """Append the top `top` of a pick run to the pick journal (picks.csv)."""
    if ranked.empty:
        return
    rows = ranked.head(top).rename_axis("ticker").reset_index()
    rows = rows[["ticker", "price", "score", "value", "quality", "growth", "momentum"]]
    rows.insert(0, "rank", range(1, len(rows) + 1))
    rows.insert(0, "date", f"{datetime.now():%Y-%m-%d %H:%M}")
    HOME.mkdir(parents=True, exist_ok=True)
    rows.to_csv(PICKS_FILE, mode="a", header=not PICKS_FILE.exists(), index=False,
                float_format="%.4f")


def add_to_watchlist(t, bought=None, stop=0.15, keep_existing=False):
    entry = {"added": str(date.today()), "bought": bought, "stop_pct": stop}
    with STATE_LOCK:
        st = load_state()
        if keep_existing:
            st["watchlist"].setdefault(t, entry)
        else:
            st["watchlist"][t] = entry
        save_state(st)


def cmd_pick(a):
    if a.file:
        tickers = [l.strip().upper() for l in open(a.file) if l.strip() and not l.startswith("#")]
    else:
        tickers = [t.upper() for t in a.tickers] if a.tickers else DEFAULT_TICKERS
    try:
        weights = parse_weights(a.weights)
        print(f"Screening {len(tickers)} stocks (buy-only)...")
        df, report = screen(tickers, weights, a.min_mcap)
    except (ValueError, RuntimeError) as e:
        sys.exit(str(e))

    print("\nSafety filters:")
    for label, removed in report:
        print(f"  - {label}: {removed} removed")
    if df.empty:
        sys.exit("No stock passed every filter right now. That itself is a signal to be patient.")
    log_picks(df)

    top = df.iloc[0]
    t = df.index[0]
    stop = top["price"] * (1 - a.stop) if pd.notna(top["price"]) else None

    print("\n" + "=" * 66)
    print(f"  TOP BUY CANDIDATE: {t}  ({top['name']}, {top['sector']})")
    print("=" * 66)
    print(f"  Price now:          {money(top['price'])}")
    print(f"  Overall score:      {top['score']:.2f} / 1.00  (rank among {len(df)} that passed)")
    print(f"    value {top['value']:.2f} | quality {top['quality']:.2f} | "
          f"growth {top['growth']:.2f} | momentum {top['momentum']:.2f}")
    print(f"  Forward P/E:        {top['forwardPE']:.1f}" if pd.notna(top["forwardPE"]) else "")
    print(f"  Revenue growth:     {pct(top['revenueGrowth'])}")
    print(f"  Profit margin:      {pct(top['profitMargins'])}")
    print(f"  12-month momentum:  {pct(top['mom_12_1'])}")
    print(f"  Yearly volatility:  {pct(top['vol_1y'])}  (typical yearly swing)")
    print(f"  Analyst target:     {pct(top['analystUpside'])} vs today "
          f"(consensus: {top['recommendation'] or 'n/a'})")
    print("\n  If you buy (whole shares, cash account, no margin):")
    print(f"    - Suggested stop-loss: {money(stop)} ({a.stop:.0%} below today).")
    print("      Selling there caps your loss; you can never lose more than you invest.")
    print("    - Keep any single stock to a small slice of your savings (many people use <=5%).")
    print(f"  How settled: #1 in {top['stable1']:.0%} of 200 small changes to the weights "
          f"(top 5 in {top['stable5']:.0%}).")

    print("\n  " + BASKET_NOTE.replace("\n", "\n  "))
    for rt, r in df.iloc[:5].iterrows():
        print(f"    {rt:6} {r['name'][:26]:26} score {r['score']:.2f}  price {money(r['price']):>10}"
              f"  top-5 in {r['stable5']:.0%} of variations")

    print(f"\n  Next: python stock_tracker.py history {t}")
    print("  A high score means 'looks strong on these measures today', not 'will go up'.")
    print("  Saved to your pick journal. See how past picks did: python stock_tracker.py track")

    if a.add:
        add_to_watchlist(t, stop=a.stop, keep_existing=True)
        print(f"  Added {t} to your watchlist.")


# ------------------------------------------------------------ history -----

RETURN_WINDOWS = [("1 month", 21), ("3 months", 63), ("6 months", 126),
                  ("1 year", 252), ("3 years", 756), ("5 years", 1260)]


def history_stats(ticker, period="5y"):
    """Returns (hist_df, stats, uptrend). Raises ValueError if there is no data."""
    t = ticker.upper()
    h = yf.Ticker(t).history(period=period, auto_adjust=True)
    if h.empty:
        raise ValueError(f"No price history for {t}. Check the ticker symbol.")
    c = h["Close"]
    last = c.iloc[-1]
    years = (c.index[-1] - c.index[0]).days / 365.25
    dd = c / c.cummax() - 1
    low_day = dd.idxmin()
    divs = h["Dividends"][h.index >= h.index[-1] - pd.Timedelta(days=365)].sum() if "Dividends" in h else 0
    yr = c.tail(252)
    stats = {
        "last": last, "last_date": c.index[-1],
        "returns": [(label, c.iloc[-1] / c.iloc[-1 - n] - 1)
                    for label, n in RETURN_WINDOWS if len(c) > n],
        "years": years,
        "cagr": (last / c.iloc[0]) ** (1 / years) - 1 if years > 0.5 else None,
        "low_52w": yr.min(), "high_52w": yr.max(),
        "volatility": c.pct_change().tail(252).std() * 252 ** 0.5,
        "worst_drop": dd.min(), "peak_day": c[:low_day].idxmax(), "low_day": low_day,
        "dividends": divs, "ma50": c.tail(50).mean(), "ma200": c.tail(200).mean(),
    }
    return h, stats, last > stats["ma200"]


def cmd_history(a):
    t = a.ticker.upper()
    print(f"Pulling {a.period} of history for {t}...")
    try:
        h, s, uptrend = history_stats(t, a.period)
    except ValueError as e:
        sys.exit(str(e))
    c, last, divs = h["Close"], s["last"], s["dividends"]

    print(f"\n{t}  last close {money(last)}  ({s['last_date']:%Y-%m-%d})")
    print("-" * 50)
    for label, r in s["returns"]:
        print(f"  Return {label:9}  {pct(r)}")
    print(f"  Yearly avg (CAGR)  {pct(s['cagr'])} over {s['years']:.1f} years")
    print(f"  52-week range      {money(s['low_52w'])} - {money(s['high_52w'])}")
    print(f"  Volatility         {pct(s['volatility'])} per year")
    print(f"  Worst drop         {pct(s['worst_drop'])} ({s['peak_day']:%b %Y} to {s['low_day']:%b %Y})")
    print(f"  Dividends (1 yr)   {money(divs)}  (yield {pct(divs / last) if divs else '-'})")
    print(f"  50-day average     {money(s['ma50'])}")
    print(f"  200-day average    {money(s['ma200'])}  -> "
          f"{'price ABOVE: uptrend' if uptrend else 'price BELOW: downtrend, be cautious'}")
    print("\n  Worst drop is a useful gut check: could you hold through that again?")

    csv = Path(f"{t}_history.csv")
    h.to_csv(csv)
    print(f"\n  Daily data saved to {csv.resolve()}")

    if not a.no_chart:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(figsize=(11, 5.5))
            ax.plot(c.index, c, label="Price", linewidth=1.4, color="#2563eb")
            ax.plot(c.index, c.rolling(50).mean(), label="50-day avg", linewidth=1, color="#f59e0b")
            ax.plot(c.index, c.rolling(200).mean(), label="200-day avg", linewidth=1, color="#6b7280")
            ax.set_title(f"{t} - {a.period} price history")
            ax.set_ylabel("Price ($)")
            ax.grid(alpha=0.3)
            ax.legend()
            fig.tight_layout()
            png = Path(f"{t}_chart.png")
            fig.savefig(png, dpi=120)
            print(f"  Chart saved to {png.resolve()}")
        except ImportError:
            print("  (pip install matplotlib to also get a chart)")


# -------------------------------------------------------------- watch -----

def iso_day(x):
    if x is None:
        return ""
    if isinstance(x, (int, float)):
        return datetime.fromtimestamp(x, timezone.utc).strftime("%Y-%m-%d")
    if hasattr(x, "strftime"):
        return x.strftime("%Y-%m-%d")
    return str(x)[:10]


def news_events(tk):
    out = []
    try:
        items = tk.news or []
    except Exception:
        items = []
    for n in items:
        c = n.get("content") or n
        title = c.get("title")
        if not title:
            continue
        url = (c.get("canonicalUrl") or {}).get("url") or c.get("link") or ""
        src = (c.get("provider") or {}).get("displayName") or c.get("publisher") or ""
        when = c.get("pubDate") or c.get("providerPublishTime")
        out.append({"id": "news:" + str(n.get("id") or c.get("id") or url or title),
                    "date": iso_day(when), "kind": "News",
                    "text": f"{title}" + (f"  [{src}]" if src else ""), "url": url})
    return out


def analyst_events(tk, since):
    out = []
    try:
        ud = tk.upgrades_downgrades
    except Exception:
        return out
    if ud is None or getattr(ud, "empty", True):
        return out
    words = {"up": "UPGRADED", "down": "DOWNGRADED", "init": "started coverage",
             "main": "kept rating", "reit": "reiterated"}
    for when, r in ud.iterrows():
        d = iso_day(when)
        if d < since:
            continue
        action = words.get(str(r.get("Action", "")).lower(), r.get("Action", ""))
        frm, to = r.get("FromGrade"), r.get("ToGrade")
        text = (f"{r.get('Firm')} kept its {to} rating" if frm == to
                else f"{r.get('Firm')} {action}" + (f" from {frm}" if frm else "") + f" to {to}")
        out.append({"id": f"analyst:{d}:{r.get('Firm')}:{to}", "date": d,
                    "kind": "Analyst", "text": text,
                    "url": "", "flag": action == "DOWNGRADED"})
    return out


def calendar_events(tk):
    out = []
    try:
        cal = tk.calendar or {}
    except Exception:
        return out
    dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
    for d in dates or []:
        d = iso_day(d)
        if d >= str(date.today()):
            out.append({"id": f"earnings:{d}", "date": d, "kind": "Earnings",
                        "text": f"Next earnings report scheduled {d} (expect a big price move)",
                        "url": ""})
            break
    return out


def price_events(tk, since, move=0.05):
    out = []
    try:
        h = tk.history(period="3mo", auto_adjust=False)
    except Exception:
        return out, None
    if h.empty:
        return out, None
    chg = h["Close"].pct_change()
    for when, r in chg.items():
        d = iso_day(when)
        if d >= since and pd.notna(r) and abs(r) >= move:
            out.append({"id": f"move:{d}", "date": d, "kind": "Big move",
                        "text": f"Stock {'jumped' if r > 0 else 'fell'} {pct(r)} in one day "
                                f"(close {money(h['Close'][when])})",
                        "url": "", "flag": r < 0})
    for col, label in [("Dividends", "Dividend paid"), ("Stock Splits", "Stock split")]:
        if col in h:
            for when, v in h[col].items():
                d = iso_day(when)
                if v and d >= since:
                    out.append({"id": f"{col}:{d}", "date": d, "kind": "Corporate action",
                                "text": f"{label}: {v:g}" + (" per share" if col == "Dividends" else ""),
                                "url": ""})
    return out, h


def sec_cik(ticker, headers):
    fresh = CIK_FILE.exists() and time.time() - CIK_FILE.stat().st_mtime < 7 * 86400
    if not fresh:
        r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=headers, timeout=20)
        r.raise_for_status()
        HOME.mkdir(parents=True, exist_ok=True)
        CIK_FILE.write_text(r.text)
    data = json.loads(CIK_FILE.read_text())
    want = ticker.upper().replace(".", "-")
    for row in data.values():
        if row["ticker"].upper() == want:
            return int(row["cik_str"])
    return None


def sec_events(ticker, contact, since):
    if not contact:
        return [], "SEC filings skipped: no SEC contact email set (Settings tab, or: setup --contact)"
    headers = {"User-Agent": f"stock_tracker personal research {contact}"}
    try:
        cik = sec_cik(ticker, headers)
        if cik is None:
            return [], f"No SEC filer found for {ticker} (may be a foreign company or fund)"
        r = requests.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json",
                         headers=headers, timeout=20)
        r.raise_for_status()
        rec = r.json()["filings"]["recent"]
    except Exception as e:
        return [], f"SEC lookup failed: {e}"

    out, insider = [], 0
    for i, form in enumerate(rec["form"]):
        d = rec["filingDate"][i]
        if d < since:
            break
        if form not in SEC_FORMS:
            continue
        acc = rec["accessionNumber"][i]
        url = (f"https://www.sec.gov/Archives/edgar/data/{cik}/"
               f"{acc.replace('-', '')}/{rec['primaryDocument'][i]}")
        if form == "4":                       # show at most 5 insider filings
            insider += 1
            if insider > 5:
                continue
        text, flag = SEC_FORMS[form], False
        if form == "8-K":
            items = [x.strip() for x in (rec.get("items", [""] * len(rec["form"]))[i] or "").split(",") if x.strip()]
            desc = [EIGHT_K_ITEMS.get(x, x) for x in items if x != "9.01"]
            flag = any(x in RED_FLAG_ITEMS for x in items)
            if desc:
                text += ": " + "; ".join(desc)
        out.append({"id": f"sec:{acc}", "date": d, "kind": f"SEC {form}",
                    "text": text, "url": url, "flag": flag})
    return out, None


def position_alerts(t, pos, hist):
    if hist is None or hist.empty:
        return []
    c = hist["Close"]
    last = c.iloc[-1]
    lines = []
    if pos.get("bought"):
        gain = last / pos["bought"] - 1
        stop = pos["bought"] * (1 - pos.get("stop_pct", 0.15))
        lines.append(f"Your position: bought {money(pos['bought'])}, now {money(last)} ({pct(gain)})."
                     f" Stop-loss level {money(stop)}.")
        if last <= stop:
            lines.append("!! PRICE IS AT/BELOW YOUR STOP-LOSS. Consider selling to cap the loss.")
        elif gain >= 0.5:
            lines.append("Up 50%+. Consider selling part to lock in gains, or raising your stop.")
    long = yf.Ticker(t).history(period="1y")["Close"] if len(c) < 200 else c
    ma200 = long.tail(200).mean() if len(long) else None
    if ma200 and last < ma200:
        lines.append(f"Price {money(last)} is below its 200-day average {money(ma200)}: downtrend.")
    return lines


def check_ticker(ticker, state, days=30, show_all=False):
    """Gather events for one ticker. Returns {alerts, events, note, price}; events are
    only the new ones unless show_all. Marks everything found as seen in state."""
    t = ticker.upper()
    since = str(date.today() - timedelta(days=days))
    tk = yf.Ticker(t)
    news = [e for e in news_events(tk) if e["date"] >= since]
    events = news + analyst_events(tk, since) + calendar_events(tk)
    moves, hist = price_events(tk, since)
    events += moves
    filings, note = sec_events(t, state.get("contact"), since)
    events += filings

    alerts = position_alerts(t, state["watchlist"].get(t, {}), hist)
    seen = set(state["seen"].get(t, []))
    new = events if show_all else [e for e in events if e["id"] not in seen]
    new.sort(key=lambda e: e["date"], reverse=True)
    # Cap the memory, but never forget what's still in the look-back window, or it
    # would show up as "new" again. Older IDs can't reappear unless --days grows.
    now = {e["id"] for e in events}
    state["seen"][t] = sorted(now | set(sorted(seen - now)[:max(0, 500 - len(now))]))
    price = hist["Close"].iloc[-1] if hist is not None and not hist.empty else None
    return {"alerts": alerts, "events": new, "note": note, "price": price}


def watch_all(days=30, show_all=False, progress=None):
    """Check every watchlist stock and save what was seen. Safe to run while the app
    edits the watchlist: only the 'seen' memory of checked stocks is merged back.
    Returns (results, report_path or None)."""
    state = load_state()
    results = {}
    for i, t in enumerate(state["watchlist"], 1):
        if progress:
            progress(f"Checking {t} ({i}/{len(state['watchlist'])})...")
        results[t] = check_ticker(t, state, days, show_all)
    with STATE_LOCK:
        fresh = load_state()
        fresh["seen"].update({t: state["seen"][t] for t in results if t in fresh["watchlist"]})
        save_state(fresh)
    return results, save_report(results) if results else None


def cmd_daily(a):
    """Unattended run for Task Scheduler: save today's pick to the journal, check the
    watchlist, update practice tests. Writes a line per step to daily.log."""
    lines = [f"--- {datetime.now():%Y-%m-%d %H:%M}"]
    for label, step in (
            ("pick", lambda: log_picks(screen(DEFAULT_TICKERS, parse_weights(None), 10e9, None)[0])
             or "saved to journal"),
            ("watch", lambda: f"report {watch_all()[1]}"),
            ("practice", lambda: f"{len(update_practice())} tests updated")):
        try:
            lines.append(f"{label}: {step()}")
        except Exception as e:
            lines.append(f"{label}: FAILED {e!r}")
    HOME.mkdir(parents=True, exist_ok=True)
    with (HOME / "daily.log").open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


def save_report(results):
    """results: {ticker: check_ticker() result}. Writes Markdown, returns its path."""
    report = [f"# Stock watch {date.today()}\n"]
    for t, r in results.items():
        report.append(f"\n## {t}\n")
        report += [f"- **{line}**" for line in r["alerts"]]
        if not r["events"]:
            report.append("- Nothing new.")
        for e in r["events"]:
            report.append(f"- {'**RED FLAG** ' if e.get('flag') else ''}{e['date']} {e['kind']}: "
                          f"{e['text']}" + (f" ([link]({e['url']}))" if e["url"] else ""))
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"watch_{datetime.now():%Y-%m-%d_%H%M}.md"
    out.write_text("\n".join(report))
    return out


def cmd_watch(a):
    st = load_state()
    tickers = [t.upper() for t in a.tickers] if a.tickers else list(st["watchlist"])
    if not tickers:
        sys.exit("Watchlist is empty. Add one with:  python stock_tracker.py add MSFT")
    results = {}

    for t in tickers:
        print(f"\n{'=' * 66}\n  {t}\n{'=' * 66}")
        r = results[t] = check_ticker(t, st, a.days, a.all)
        for line in r["alerts"]:
            print("  " + line)
        if not r["events"]:
            print("  Nothing new since your last check.")
        for e in r["events"]:
            mark = "!!" if e.get("flag") else "  "
            print(f"  {mark} {e['date']}  {e['kind']:16} {e['text']}")
            if e["url"]:
                print(f"     {'':10}  {e['url']}")
        if r["note"]:
            print(f"  ({r['note']})")

    save_state(st)
    out = save_report(results)
    print(f"\nLines marked !! are worth a closer look. Report saved to {out}")


# ------------------------------------------------ track record / backtest -

HORIZONS = [("1 mo", 21), ("3 mo", 63), ("6 mo", 126), ("1 yr", 252)]

BACKTEST_CAVEATS = """\
Read this before trusting the numbers:
- Hindsight in the stock list: these are today's big, successful companies.
  Choosing among known winners flatters every line, so compare the pick with
  "all stocks, equal" (a random choice from the same list) more than with SPY.
- Simplified data: trailing P/E instead of forecasts, yearly sales and profit
  figures (up to ~15 months old), no EV/EBITDA, no trading costs or taxes.
- Past results don't predict future results. A method can beat the market for
  years and then stop."""


def naive(df):
    """Drop the timezone from a price index so dates compare plainly."""
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)
    return df


def track_record(top_only=True):
    """Each journal pick vs SPY over the same trading days (first run per day counts).
    Returns (table, summary); summary rows are (horizon, n, avg_pick, avg_spy, n_beat)."""
    if not PICKS_FILE.exists():
        return pd.DataFrame(), []
    p = pd.read_csv(PICKS_FILE)
    if top_only:
        p = p[p["rank"] == 1]
    p["day"] = pd.to_datetime(p["date"]).dt.normalize()
    p = p.drop_duplicates(["day", "ticker"])
    if p.empty:
        return pd.DataFrame(), []
    tickers = sorted(set(p["ticker"]) - {BENCH}) + [BENCH]
    close = yf.download(tickers, start=p["day"].min() - pd.Timedelta(days=10),
                        auto_adjust=True, progress=False)["Close"]
    close = naive(close).ffill()

    rows = []
    for _, r in p.iterrows():
        t = r["ticker"]
        i0 = close.index.searchsorted(r["day"], side="right") - 1   # last close on/before pick day
        if i0 < 0 or t not in close or pd.isna(close[t].iloc[i0]):
            # Keep it visible: silently dropping a pick that got delisted would flatter the record.
            rows.append({"date": r["day"].date(), "ticker": t, "rank": r["rank"], "score": r["score"],
                         "days": float("nan"), "so far": float("nan"), "SPY so far": float("nan")})
            continue
        ret = lambda col, j: close[col].iloc[j] / close[col].iloc[i0] - 1
        row = {"date": r["day"].date(), "ticker": t, "rank": r["rank"], "score": r["score"],
               "days": len(close) - 1 - i0, "so far": ret(t, -1), "SPY so far": ret(BENCH, -1)}
        for label, n in HORIZONS:
            if i0 + n < len(close):
                row[label], row[f"SPY {label}"] = ret(t, i0 + n), ret(BENCH, i0 + n)
        rows.append(row)
    table = pd.DataFrame(rows).sort_values(["date", "rank"]).reset_index(drop=True)

    summary = []
    for label in ["so far"] + [h for h, _ in HORIZONS]:
        if label not in table:
            continue
        d = table.dropna(subset=[label])
        if label == "so far":
            d = d[d["days"] > 0]
        spy = d["SPY so far" if label == "so far" else f"SPY {label}"]
        if len(d):
            summary.append((label, len(d), d[label].mean(), spy.mean(), int((d[label] > spy).sum())))
    return table, summary


# XBRL tags in SEC "companyfacts". Several per item because companies renamed
# them over the years (e.g. SalesRevenueNet became RevenueFromContract... in 2018,
# MA/CAT moved profit to ProfitLoss). First tag wins when several give the same period.
FACT_TAGS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
    "net_income": ["NetIncomeLoss", "NetIncomeLossAvailableToCommonStockholdersBasic", "ProfitLoss"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "op_cash": ["NetCashProvidedByUsedInOperatingActivities",
                "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "debt": ["LongTermDebt", "LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"],
    "shares": ["dei:EntityCommonStockSharesOutstanding",
               "WeightedAverageNumberOfDilutedSharesOutstanding", "CommonStockSharesOutstanding"],
}
# The ticker now points at a new parent company whose SEC history is short, so
# also read the old filer. Found by hand (SEC "company_tickers.json", 2026-10).
PREDECESSOR_CIKS = {"XOM": [34088],     # ExxonMobil Holdings Corp (2026) <- Exxon Mobil Corp
                    "BLK": [1364742]}   # BlackRock, Inc. (2024) <- now "BlackRock Finance, Inc."
FLOWS = {"revenue", "net_income", "op_cash", "capex"}    # amounts over a period, not a point in time


def company_facts(ticker, contact):
    """Reported figures from SEC XBRL, each with the date it was filed, so a
    backtest only uses what was public at the time. Cached for 30 days.
    Returns {item: [[start, end, value, filed], ...]}."""
    FACTS_DIR.mkdir(parents=True, exist_ok=True)
    cache = FACTS_DIR / f"{ticker}.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < 30 * 86400:
        return json.loads(cache.read_text())
    headers = {"User-Agent": f"stock_tracker personal research {contact}"}
    cik = sec_cik(ticker, headers)
    out = {item: [] for item in FACT_TAGS}
    for c in ([cik] if cik is not None else []) + PREDECESSOR_CIKS.get(ticker, []):
        r = requests.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{c:010d}.json",
                         headers=headers, timeout=60)
        time.sleep(0.15)      # SEC allows at most 10 requests a second
        if r.status_code == 404:
            continue
        r.raise_for_status()
        facts = r.json().get("facts", {})
        for item, tags in FACT_TAGS.items():
            for tag in reversed(tags):     # preferred tag last: fact_asof takes the last of equals
                ns, _, name = tag.rpartition(":")
                for vals in facts.get(ns or "us-gaap", {}).get(name, {}).get("units", {}).values():
                    out[item] += [[v.get("start"), v["end"], v["val"], v["filed"]]
                                  for v in vals if str(v.get("form", "")).startswith("10-")]
    out = {k: v for k, v in out.items() if v}
    cache.write_text(json.dumps(out))
    return out


def fact_frames(raw, splits=None):
    """One DataFrame per item. Flows keep full-year figures only. Share counts are
    restated on today's split basis to match yfinance's split-adjusted prices."""
    split_days = splits[splits > 0] if splits is not None else pd.Series(dtype=float)
    out = {}
    for item, rows in raw.items():
        f = pd.DataFrame(rows, columns=["start", "end", "val", "filed"])
        if f.empty:
            continue
        for c in ("start", "end", "filed"):
            f[c] = pd.to_datetime(f[c])
        if item in FLOWS:
            f = f[(f["end"] - f["start"]).dt.days.between(350, 380)]
        if item == "shares":
            f["val"] = [v * split_days[split_days.index > e].prod() for v, e in zip(f["val"], f["end"])]
        out[item] = f.sort_values("filed", kind="stable")
    return out


def fact_asof(f, day, years_back=0):
    """Latest figure that had been filed by `day`; years_back=1 gives the one a year before it."""
    if f is None:
        return float("nan")
    f = f[f["filed"] <= day]
    if f.empty:
        return float("nan")
    end = f["end"].max()
    if (day - end).days > 550:               # company stopped reporting this figure
        return float("nan")
    if years_back:
        end -= pd.DateOffset(years=years_back)
        f = f[(f["end"] - end).abs() <= pd.Timedelta(days=20)]
    else:
        f = f[f["end"] == end]
    return f["val"].iloc[-1] if len(f) else float("nan")


def backtest(tickers=None, years=10, min_mcap=10e9, weights=None, contact=None, progress=None,
             sector_neutral=False, market_filter=False):
    """Replay `pick` at every month-end of the past `years`, using only data public
    at the time, and hold the pick for one month. Returns (monthly_df, summary, info).
    market_filter: hold cash for the month when SPY is below its 200-day average."""
    if not contact:
        raise ValueError("The backtest needs old company reports from the SEC. Set your SEC "
                         "contact email first (Settings tab, or: setup --contact you@example.com).")
    tickers = tickers or DEFAULT_TICKERS
    weights = weights or parse_weights(None)
    say = progress or (lambda msg: print("  " + msg))
    say("Downloading price history...")
    start = pd.Timestamp.today().normalize() - pd.DateOffset(years=years, months=14)
    data = naive(yf.download(tickers + [BENCH], start=start, auto_adjust=False, actions=True,
                             progress=False, threads=True))
    close, adj = data["Close"], data["Adj Close"]     # Close: for company value; Adj: for returns
    splits = data["Stock Splits"] if "Stock Splits" in data.columns.get_level_values(0) else None

    frames = {}
    for i, t in enumerate(tickers, 1):
        say(f"SEC report history {i}/{len(tickers)} ({t})...")
        try:
            frames[t] = fact_frames(company_facts(t, contact),
                                    splits[t] if splits is not None and t in splits else None)
        except Exception:
            frames[t] = {}      # counted below as "couldn't be valued"

    sectors = get_sectors(tickers) if sector_neutral else None
    mom = adj.shift(21) / adj.shift(252) - 1
    ret6 = adj / adj.shift(126) - 1
    ma200 = adj.rolling(200).mean()
    month_ends = adj.groupby(adj.index.to_period("M")).tail(1).index
    month_ends = month_ends[month_ends >= adj.index[0] + pd.DateOffset(months=13)]
    nan = float("nan")

    rows, unvalued = [], {}
    for k, (d, d2) in enumerate(zip(month_ends[:-1], month_ends[1:]), 1):
        say(f"Replaying month {k}/{len(month_ends) - 1} ({d:%Y-%m})...")
        feats = []
        for t in tickers:
            fr = frames.get(t, {})
            get = lambda item, back=0: fact_asof(fr.get(item), d, back)
            mcap = close.at[d, t] * get("shares")
            ni, ni0, rev, eq = get("net_income"), get("net_income", 1), get("revenue"), get("equity")
            feats.append({
                "ticker": t, "marketCap": mcap,
                "forwardPE": mcap / ni,       # trailing P/E stands in: old forecasts aren't public
                # ponytail: a missing yearly capex row counts as 0 (overstates free cash a
                # little); some filers skip it in certain years (e.g. NVDA FY2019).
                "priceToBook": mcap / eq,
                "fcfYield": (get("op_cash") - (0 if pd.isna(get("capex")) else get("capex"))) / mcap,
                "returnOnEquity": ni / eq, "profitMargins": ni / rev,
                "debtToEquity": get("debt") / eq * 100,
                "revenueGrowth": rev / get("revenue", 1) - 1,
                "earningsGrowth": ni / ni0 - 1 if ni0 > 0 else nan,
                "mom_12_1": mom.at[d, t], "ret_6m": ret6.at[d, t],
                "last": adj.at[d, t], "ma200": ma200.at[d, t]})
        df = pd.DataFrame(feats).set_index("ticker")
        for t in df.index[df["marketCap"].isna() | df["forwardPE"].isna()]:
            unvalued[t] = unvalued.get(t, 0) + 1
        df, _ = apply_filters(df, min_mcap)
        if len(df):
            df = df.join(score(df, weights, sectors)).sort_values("score", ascending=False)
        top = list(df.index[:5])
        if market_filter and adj.at[d, BENCH] < ma200.at[d, BENCH]:
            top = []                     # market in a downtrend: sit in cash this month
        fwd = (adj.loc[d2] / adj.loc[d] - 1).fillna(0.0)
        rows.append({"date": d, "pick": top[0] if top else "(cash)", "passed": len(df),
                     "pick_ret": fwd[top[0]] if top else 0.0,
                     "top5_ret": fwd[top].mean() if top else 0.0,
                     "spy_ret": fwd[BENCH], "all_ret": fwd[tickers].mean()})
    m = pd.DataFrame(rows).set_index("date")

    def perf(r):
        g = pd.concat([pd.Series([1.0]), (1 + r).cumprod()], ignore_index=True)
        return {"growth": g.iloc[-1], "cagr": g.iloc[-1] ** (12 / len(r)) - 1,
                "worst": (g / g.cummax() - 1).min()}
    lines = [("Top pick", "pick_ret"), ("Top 5 average", "top5_ret"),
             (f"{BENCH} (whole market)", "spy_ret"), (f"All {len(tickers)} stocks, equal", "all_ret")]
    summary = {name: {**perf(m[col]), "col": col} for name, col in lines}
    info = {"months": len(m), "beat_spy": int((m["pick_ret"] > m["spy_ret"]).sum()),
            "beat_all": int((m["pick_ret"] > m["all_ret"]).sum()),
            "cash": int((m["passed"] == 0).sum()), "start": m.index[0], "end": month_ends[-1],
            "unvalued": dict(sorted(unvalued.items(), key=lambda kv: -kv[1]))}
    return m, summary, info


def cmd_track(a):
    table, summary = track_record(top_only=not a.all)
    if table.empty:
        sys.exit("No picks in your journal yet. Each `pick` run is saved; check back in a few weeks.")
    print(f"Your past {'picks' if a.all else 'top picks'} vs {BENCH} (the whole market) "
          f"over the same days:\n")
    print(f"  {'date':10}  {'ticker':6}  {'so far':>8}  {BENCH + ' so far':>11}  ahead by")
    for _, r in table.iterrows():
        print(f"  {r['date']}  {r['ticker']:6}  {pct(r['so far']):>8}  {pct(r['SPY so far']):>11}"
              f"  {pct(r['so far'] - r['SPY so far'])}")
    print()
    for line in track_lines(summary, table):
        print("  " + line)


def track_lines(summary, table):
    lines = [f"{'So far' if label == 'so far' else 'After ' + label}: {n} picks, average "
             f"{pct(avg)} vs {BENCH} {pct(spy)}; beat {BENCH} {beat} of {n} times"
             for label, n, avg, spy, beat in summary]
    missing = sorted(set(table.loc[table["so far"].isna(), "ticker"]))
    if missing:
        lines += [f"No price data for {', '.join(missing)} (left out above). Try again later;",
                  "if it stays missing, the company may have been bought out or delisted."]
    return lines + ["", "A handful of picks proves little either way; luck dominates until there are dozens."]


def backtest_lines(summary, info):
    lines = [f"Backtest {info['start']:%Y-%m} to {info['end']:%Y-%m}: {info['months']} months,",
             "pick re-run every month-end and held one month.", "",
             f"{'':24} {'$10,000 became':>14} {'yearly avg':>10} {'worst drop':>10}"]
    lines += [f"{name:24} {money(10000 * s['growth']):>14} {pct(s['cagr']):>10} {pct(s['worst']):>10}"
              for name, s in summary.items()]
    lines += ["", f"Top pick beat {BENCH} in {info['beat_spy']} of {info['months']} months,",
              f"and the equal mix in {info['beat_all']}."]
    if info["cash"]:
        lines.append(f"No stock passed the filters in {info['cash']} months (held cash).")
    if info["unvalued"]:
        lines += ["Too little SEC data to value these, so they sat out (months):",
                  ", ".join(f"{t} ({n})" for t, n in info["unvalued"].items())]
    return lines


def cmd_backtest(a):
    try:
        m, summary, info = backtest(years=a.years, min_mcap=a.min_mcap,
                                    contact=load_state().get("contact"),
                                    sector_neutral=a.sector, market_filter=a.market_filter)
    except ValueError as e:
        sys.exit(str(e))
    print()
    for line in backtest_lines(summary, info):
        print("  " + line)
    print("\n" + BACKTEST_CAVEATS)
    if a.csv:
        m.to_csv(a.csv)
        print(f"\n  Monthly detail saved to {Path(a.csv).resolve()}")


# ------------------------------------------------ market weather / checks -
# Each check returns (name, result, mood, why); mood is "good", "warn", "bad" or "info".

def fred_last(series_id, months_back=0):
    """Latest value of a FRED series (no key needed), or the value `months_back` ago."""
    # Gotcha: FRED stalls (no reply) for some custom User-Agents, so send requests' default.
    r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}", timeout=15)
    r.raise_for_status()
    s = pd.read_csv(io.StringIO(r.text), index_col=0, parse_dates=True).iloc[:, 0]
    s = pd.to_numeric(s, errors="coerce").dropna()
    if months_back:
        s = s[s.index <= s.index[-1] - pd.DateOffset(months=months_back)]
    return s.iloc[-1]


def market_weather(signals=None, breadth=True):
    """Signals about the market as a whole. `signals`: get_price_signals() of the stock
    list, if already downloaded (for breadth). Returns (checks, summary_line)."""
    out = []

    def safe(fn):
        try:
            out.append(fn())
        except Exception:
            pass

    def trend():
        c = naive(yf.download([BENCH, "^VIX"], period="13mo", auto_adjust=True, progress=False)["Close"])
        last, ma = c[BENCH].dropna().iloc[-1], c[BENCH].dropna().tail(200).mean()
        vix_now[0] = c["^VIX"].dropna().iloc[-1]
        return ("Market trend", f"{BENCH} {pct(last / ma - 1)} vs its 200-day average",
                "good" if last > ma else "bad",
                "Above = market rising overall. Below = falling; drops tend to bunch together.")

    vix_now = [None]

    def vix():
        v = vix_now[0]
        return ("Fear gauge (VIX)", f"{v:.1f}", "good" if v < 20 else "warn" if v < 30 else "bad",
                "Under 20 calm, 20-30 nervous, over 30 fearful. High = big daily swings.")

    def curve():
        v = fred_last("T10Y3M")
        return ("Recession warning (yield curve)", f"{v:+.2f} points", "good" if v > 0 else "bad",
                "10-year minus 3-month Treasury rate. Below zero has often come before "
                "recessions, with a long and uneven delay (6-24 months).")

    def credit():
        v, before = fred_last("BAMLH0A0HYM2"), fred_last("BAMLH0A0HYM2", 3)
        mood = "bad" if v > 6 else "warn" if v - before > 0.75 else "good"
        return ("Credit stress", f"{v:.2f}% (3 months ago {before:.2f}%)", mood,
                "Extra interest risky companies pay to borrow. Rising fast = lenders worried.")

    def breadth_check():
        s = signals if signals is not None else get_price_signals(DEFAULT_TICKERS)
        share = (s["last"] > s["ma200"]).mean()
        return ("Breadth", f"{share:.0%} of {len(s)} big stocks above their 200-day average",
                "good" if share > 0.6 else "warn" if share > 0.4 else "bad",
                "A rise carried by only a few stocks is fragile.")

    for fn in (trend, vix, curve, credit) + ((breadth_check,) if breadth else ()):
        safe(fn)
    bad = sum(c[2] == "bad" for c in out)
    warn = sum(c[2] == "warn" for c in out)
    summary = ("Mostly calm." if bad == 0 and warn <= 1 else
               "Mixed: some warning signs." if bad <= 1 else "Stormy: several warning signs.")
    summary += (" These describe today; they don't predict. In the backtest, sitting in cash "
                "when the trend turned down did WORSE (missed rebounds), so use this for "
                "patience and smaller amounts, not for jumping in and out.")
    return out, summary


def atr_stop(hist, mult=3.0):
    """Stop-loss sized to the stock's normal daily swing: `mult` x the 14-day average
    true range below the last close. Returns (stop_price, pct_below)."""
    h, c = hist.tail(60), hist["Close"].tail(60)
    tr = pd.concat([h["High"] - h["Low"], (h["High"] - c.shift()).abs(),
                    (h["Low"] - c.shift()).abs()], axis=1).max(axis=1)
    stop = c.iloc[-1] - mult * tr.tail(14).mean()
    return stop, 1 - stop / c.iloc[-1]


def company_checks(ticker, watchlist=None):
    """Extra facts about one company, as a checklist. Context, not part of the score:
    Yahoo keeps no history of most of these, so they can't be backtested."""
    t = ticker.upper()
    tk = yf.Ticker(t)
    out = []

    def check(fn):
        try:
            r = fn()
            if r:
                out.append(r)
        except Exception:
            pass

    info = {}
    check(lambda: info.update(tk.info or {}))

    def surprises():
        e = tk.earnings_history.dropna(subset=["epsActual", "epsEstimate"]).tail(4)
        beats = int((e["epsActual"] > e["epsEstimate"]).sum())
        return ("Earnings vs forecasts", f"beat forecasts {beats} of last {len(e)} quarters",
                "good" if beats >= 3 else "warn" if beats >= 2 else "bad",
                "Companies that keep beating forecasts tend to be well run (or forecast low).")

    def revisions():
        r = tk.eps_revisions.loc["0y"]
        up, down = int(r["upLast30days"]), int(r["downLast30days"])
        tr = tk.eps_trend.loc["0y"]
        chg = tr["current"] / tr["90daysAgo"] - 1
        return ("Profit forecasts", f"{up} analysts raised, {down} cut this year's estimate in 30 days; "
                f"estimate {pct(chg)} over 90 days", "good" if up > down and chg >= 0 else
                "bad" if down > up and chg < 0 else "warn",
                "Rising estimates is one of the better-studied signals.")

    def insiders():
        it = tk.insider_transactions
        it = it[pd.to_datetime(it["Start Date"]) >= pd.Timestamp.today() - pd.DateOffset(months=6)]
        buys = it["Text"].str.contains("Purchase", case=False, na=False).sum()
        sells = it["Text"].str.contains("Sale", case=False, na=False).sum()
        return ("Insider trades (6 months)", f"{buys} buys, {sells} sales",
                "good" if buys else "info",
                "Executives buying with their own money is telling; selling is common "
                "(taxes, diversifying) and says less.")

    def analysts():
        r = tk.recommendations.set_index("period")
        share = lambda p: (r.loc[p, ["strongBuy", "buy"]].sum() / r.loc[p, ["strongBuy", "buy", "hold",
                                                                           "sell", "strongSell"]].sum())
        now, before = share("0m"), share("-3m")
        return ("Analyst mood", f"{now:.0%} say buy (3 months ago {before:.0%})",
                "good" if now >= before else "warn", "Direction matters more than level: most "
                "analysts say buy most of the time.")

    def short():
        v = info.get("shortPercentOfFloat")
        if v is None:
            return None
        return ("Bets against it (short interest)", f"{v:.1%} of shares",
                "good" if v < 0.05 else "warn" if v < 0.15 else "bad",
                "High = many traders expect a fall. Information only; this app never shorts.")

    def earnings_soon():
        dates = (tk.calendar or {}).get("Earnings Date") or []
        d = min((pd.Timestamp(x) for x in dates if pd.Timestamp(x) >= pd.Timestamp.today().normalize()),
                default=None)
        if d is None:
            return None
        days = (d - pd.Timestamp.today().normalize()).days
        return ("Next earnings report", f"{d:%Y-%m-%d} (in {days} days)", "warn" if days <= 7 else "info",
                "Prices often jump or drop on that day; buying right before is a gamble.")

    def dividend():
        pr = info.get("payoutRatio")
        if not pr:
            return None
        return ("Dividend safety", f"pays out {pr:.0%} of profit", "good" if pr < 0.7 else
                "warn" if pr < 1 else "bad", "Over 100% means paying more than it earns: "
                "a dividend cut is more likely.")

    def share_count():
        s = tk.get_shares_full(start=pd.Timestamp.today() - pd.DateOffset(months=13)).dropna()
        chg = s.iloc[-1] / s.iloc[0] - 1
        return ("Share count (1 year)", pct(chg), "good" if chg <= 0.005 else
                "warn" if chg < 0.03 else "bad",
                "Shrinking = buying back shares (good for owners). Growing = new shares dilute you.")

    def stop():
        p, frac = atr_stop(tk.history(period="3mo", auto_adjust=True))
        return ("Stop-loss sized to the stock", f"{money(p)} ({frac:.0%} below)", "info",
                "3x its normal daily swing (ATR). Calm stocks get tighter stops, jumpy ones "
                "wider, so ordinary noise doesn't sell you out.")

    def overlap():
        others = [x for x in (watchlist or []) if x != t]
        if not others:
            return None
        c = yf.download([t] + others, period="1y", auto_adjust=True, progress=False)["Close"]
        corr = c.pct_change().corr()[t].drop(t).dropna()
        close = corr[corr > 0.7]
        return ("Overlap with your watchlist", ", ".join(f"{k} {v:.2f}" for k, v in close.items())
                or f"low (max {corr.max():.2f})" if len(corr) else "n/a",
                "warn" if len(close) else "good",
                "Stocks that move together don't spread your risk. Above 0.7 = move a lot alike.")

    def quality():
        need = ["forwardPE", "freeCashflow", "returnOnEquity", "profitMargins", "revenueGrowth",
                "earningsGrowth", "debtToEquity", "marketCap"]
        missing = [k for k in need if info.get(k) is None]
        return ("Data completeness", "all key numbers present" if not missing else
                f"missing: {', '.join(missing)}", "good" if not missing else "warn",
                "Missing numbers get a middle score, which can flatter or hide a company.")

    for fn in (surprises, revisions, insiders, analysts, short, earnings_soon, dividend,
               share_count, stop, overlap, quality):
        check(fn)
    return out


def cmd_market(a):
    checks, summary = market_weather()
    print_checks("Market weather", checks, summary)


def cmd_check(a):
    checks = company_checks(a.ticker, list(load_state()["watchlist"]))
    print_checks(f"Checklist for {a.ticker.upper()}", checks,
                 "Context only: these aren't in the score (no history to test them on).")


def print_checks(title, checks, note):
    marks = {"good": " ok ", "warn": "WARN", "bad": " !! ", "info": "    "}
    print(f"{title}\n")
    for name, result, mood, why in checks:
        print(f"  [{marks[mood]}] {name}: {result}\n           {why}")
    print("\n  " + note)


# ------------------------------------------------------ practice trading --
# Pretend money, live prices. Long-only like everything else: buys can't exceed
# cash (no margin) and sells can't exceed shares owned (no shorting).

PRACTICE_FILE = HOME / "practice.json"


def load_practice():
    with STATE_LOCK:
        try:
            return json.loads(PRACTICE_FILE.read_text())
        except FileNotFoundError:
            return {"tests": []}


def live_prices(tickers):
    """Latest price per ticker (Yahoo; can be ~15 minutes behind)."""
    def one(t):
        try:
            return t, float(yf.Ticker(t).fast_info["last_price"])
        except Exception:
            return t, float("nan")
    with ThreadPoolExecutor(max_workers=8) as pool:
        return dict(pool.map(one, tickers))


def _trade(test, t, side, shares, price, reason):
    pos = test["positions"].get(t, {"shares": 0, "cost": 0.0})
    if side == "BUY":
        if shares * price > test["cash"] + 1e-6:
            raise ValueError(f"Not enough cash: {shares} x {money(price)} = {money(shares * price)}, "
                             f"cash {money(test['cash'])}. (No borrowing in a cash account.)")
        pos["cost"] = (pos["cost"] * pos["shares"] + price * shares) / (pos["shares"] + shares)
        pos["shares"] += shares
        test["cash"] -= shares * price
        pnl = None
    else:
        if shares > pos["shares"]:
            raise ValueError(f"You own {pos['shares']} {t}; you can't sell more than that.")
        pos["shares"] -= shares
        test["cash"] += shares * price
        pnl = (price - pos["cost"]) * shares
    if pos["shares"]:
        test["positions"][t] = pos
    else:
        test["positions"].pop(t, None)
    test["trades"].append({"time": f"{datetime.now():%Y-%m-%d %H:%M}", "ticker": t, "side": side,
                           "shares": shares, "price": round(price, 4), "reason": reason,
                           "pnl": None if pnl is None else round(pnl, 2)})


def start_practice(tickers, cash=10000.0, days=30, stop_pct=0.15, take_profit=None, name=None):
    """Start a test: split `cash` evenly over `tickers`, whole shares, at live prices."""
    tickers = [t.upper() for t in tickers]
    if not tickers or cash <= 0 or days < 1:
        raise ValueError("Give at least one ticker, cash above 0 and at least 1 day.")
    prices = live_prices(tickers + [BENCH])
    bad = [t for t in tickers if not prices[t] > 0]
    if bad:
        raise ValueError(f"No live price for {', '.join(bad)}. Check the ticker symbols.")
    now = datetime.now()
    test = {"id": f"{now:%Y%m%d-%H%M%S}", "name": name or ", ".join(tickers),
            "start": f"{now:%Y-%m-%d %H:%M}", "end": f"{now + timedelta(days=days):%Y-%m-%d %H:%M}",
            "cash0": cash, "cash": cash, "stop_pct": stop_pct, "take_profit": take_profit,
            "positions": {}, "trades": [], "spy_start": prices[BENCH], "status": "running",
            "history": []}
    each = cash / len(tickers)
    for t in tickers:
        shares = int(each // prices[t])
        if shares:
            _trade(test, t, "BUY", shares, prices[t], "start")
    _mark(test, prices)
    with STATE_LOCK:
        p = load_practice()
        p["tests"].append(test)
        write_json(PRACTICE_FILE, p)
    return test


def _mark(test, prices):
    # A manual trade only fetches that one stock's price: keep the others' last known.
    last = test.get("last_prices", {})
    last.update({t: p for t, p in prices.items() if p == p})          # p == p: not NaN
    last = test["last_prices"] = {t: last[t] for t in test["positions"] if t in last}
    value = test["cash"] + sum(pos["shares"] * last.get(t, pos["cost"])
                               for t, pos in test["positions"].items())
    test["value"] = value
    test["spy_now"] = prices.get(BENCH, test.get("spy_now", test["spy_start"]))
    test["history"].append([f"{datetime.now():%Y-%m-%d %H:%M}", round(value, 2),
                            round(test["cash0"] * test["spy_now"] / test["spy_start"], 2)])
    test["history"] = test["history"][-2000:]


def practice_trade(test_id, ticker, side, shares):
    """Manual buy or sell at the live price."""
    if shares < 1 or int(shares) != shares:
        raise ValueError("Shares must be a whole number, 1 or more.")
    t = ticker.upper()
    prices = live_prices([t, BENCH])
    if not prices[t] > 0:
        raise ValueError(f"No live price for {t}.")
    with STATE_LOCK:
        p = load_practice()
        test = next(x for x in p["tests"] if x["id"] == test_id)
        if test["status"] != "running":
            raise ValueError("That test has ended.")
        _trade(test, t, side, int(shares), prices[t], "you")
        _mark(test, prices)
        write_json(PRACTICE_FILE, p)
    return test


def update_practice(end_now=None):
    """Refresh running tests: apply stop-loss / take-profit, record value, and end
    tests whose time is up (or `end_now`, a test id). Returns all tests."""
    with STATE_LOCK:
        p = load_practice()
    running = [x for x in p["tests"] if x["status"] == "running"]
    if not running:
        return p["tests"]
    prices = live_prices(sorted({t for x in running for t in x["positions"]} | {BENCH}))
    with STATE_LOCK:
        p = load_practice()                 # re-read: a trade may have happened meanwhile
        for test in p["tests"]:
            if test["status"] != "running":
                continue
            for t, pos in list(test["positions"].items()):
                price = prices.get(t)
                if not price or pd.isna(price):
                    continue
                if price <= pos["cost"] * (1 - test["stop_pct"]):
                    _trade(test, t, "SELL", pos["shares"], price, "stop-loss")
                elif test.get("take_profit") and price >= pos["cost"] * (1 + test["take_profit"]):
                    _trade(test, t, "SELL", pos["shares"], price, "take-profit")
            _mark(test, prices)
            if test["id"] == end_now or datetime.now() >= datetime.strptime(test["end"], "%Y-%m-%d %H:%M"):
                for t, pos in list(test["positions"].items()):
                    if prices.get(t) and not pd.isna(prices[t]):
                        _trade(test, t, "SELL", pos["shares"], prices[t], "test ended")
                _mark(test, prices)
                test["status"] = "ended"
                test["ended"] = f"{datetime.now():%Y-%m-%d %H:%M}"
        write_json(PRACTICE_FILE, p)
    return p["tests"]


def practice_lines(test):
    """Plain-language result summary for one test (works while running too)."""
    value, spy = test.get("value", test["cash0"]), test.get("spy_now", test["spy_start"])
    ret, spy_ret = value / test["cash0"] - 1, spy / test["spy_start"] - 1
    sells = [x for x in test["trades"] if x["side"] == "SELL" and x["pnl"] is not None]
    wins = [x for x in sells if x["pnl"] > 0]
    state = "ENDED " + test.get("ended", "") if test["status"] == "ended" else f"running until {test['end']}"
    lines = [f"{test['name']}  ({test['start']} -> {state})",
             f"Started with {money(test['cash0'])}; now worth {money(value)} ({pct(ret)}).",
             f"Same money in {BENCH}: {money(test['cash0'] * (1 + spy_ret))} ({pct(spy_ret)}). "
             f"{'Ahead' if ret >= spy_ret else 'Behind'} by {pct(abs(ret - spy_ret))[1:]}.",
             f"Cash {money(test['cash'])}; {len(test['positions'])} stocks held; "
             f"{len(test['trades'])} trades."]
    if sells:
        lines.append(f"Closed sales: {len(wins)} of {len(sells)} made money; realised "
                     f"{money(sum(x['pnl'] for x in sells))}.")
        best = max(sells, key=lambda x: x["pnl"])
        worst = min(sells, key=lambda x: x["pnl"])
        lines.append(f"Best sale {best['ticker']} {money(best['pnl'])}; worst {worst['ticker']} "
                     f"{money(worst['pnl'])}.")
    return lines


def cmd_practice(a):
    try:
        if a.action == "start":
            test = start_practice(a.args, a.cash, a.days, a.stop, a.take_profit)
            print(f"Started practice test {test['id']}.")
            tests = [test]
        elif a.action in ("buy", "sell"):
            test_id, t, n = a.args
            tests = [practice_trade(test_id, t, a.action.upper(), float(n))]
        else:
            tests = update_practice(end_now=a.args[0] if a.action == "end" and a.args else None)
    except (ValueError, StopIteration) as e:
        sys.exit(str(e) or "No test with that id.")
    if not tests:
        sys.exit("No practice tests yet. Start one:  py stock_tracker.py practice start MSFT KO --days 30")
    for test in tests:
        print(f"\n[{test['id']}]")
        for line in practice_lines(test):
            print("  " + line)
        for x in test["trades"][-10:]:
            print(f"    {x['time']}  {x['side']:4} {x['shares']:>5} {x['ticker']:6} @ {money(x['price']):>10}"
                  f"  {x['reason']}" + (f"  P/L {money(x['pnl'])}" if x["pnl"] is not None else ""))
    print("\n  Practice uses pretend money and live prices; real results also include costs and taxes.")


# ----------------------------------------------------------- watchlist ----

def cmd_add(a):
    if a.bought is not None and a.bought <= 0:
        sys.exit("--bought must be the positive price you paid per share.")
    if not 0 < a.stop < 1:
        sys.exit("--stop is a fraction, e.g. 0.15 for 15% below your buy price.")
    t = a.ticker.upper()
    add_to_watchlist(t, a.bought, a.stop)
    extra = f", bought at {money(a.bought)}, stop {a.stop:.0%} below" if a.bought else ""
    print(f"Watching {t}{extra}.")


def cmd_remove(a):
    st = load_state()
    t = a.ticker.upper()
    st["watchlist"].pop(t, None)
    st["seen"].pop(t, None)
    save_state(st)
    print(f"Stopped watching {t}.")


def cmd_list(a):
    st = load_state()
    if not st["watchlist"]:
        print("Watchlist is empty.")
    for t, p in st["watchlist"].items():
        b = f"bought {money(p['bought'])}, stop {p['stop_pct']:.0%}" if p.get("bought") else "not bought"
        print(f"  {t:6} added {p['added']}  ({b})")
    print(f"SEC contact: {st.get('contact') or 'not set'}")


def cmd_setup(a):
    st = load_state()
    st["contact"] = a.contact
    save_state(st)
    print(f"Saved. SEC filings will be requested with contact {a.contact}.")


# ---------------------------------------------------------------- main -----

def main():
    ap = argparse.ArgumentParser(description="Long-only stock picker, history and company tracker.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("pick", help="find the single best buy candidate")
    p.add_argument("--tickers", nargs="+")
    p.add_argument("--file", help="text file, one ticker per line")
    p.add_argument("--min-mcap", type=float, default=10e9, help="minimum market cap (default 10e9)")
    p.add_argument("--weights", nargs="+", metavar="FACTOR=W")
    p.add_argument("--stop", type=float, default=0.15, help="stop-loss fraction (default 0.15)")
    p.add_argument("--add", action="store_true", help="add the pick to your watchlist")
    p.set_defaults(func=cmd_pick)

    p = sub.add_parser("history", help="past performance, chart and CSV")
    p.add_argument("ticker")
    p.add_argument("--period", default="5y", help="1y, 5y, 10y, max (default 5y)")
    p.add_argument("--no-chart", action="store_true")
    p.set_defaults(func=cmd_history)

    p = sub.add_parser("watch", help="news, filings, analyst changes, earnings, big moves")
    p.add_argument("tickers", nargs="*")
    p.add_argument("--days", type=int, default=30, help="look-back window (default 30)")
    p.add_argument("--all", action="store_true", help="show everything, not just new items")
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("track", help="how past picks did vs the whole market (SPY)")
    p.add_argument("--all", action="store_true", help="include runners-up, not just top picks")
    p.set_defaults(func=cmd_track)

    p = sub.add_parser("backtest", help="replay the pick over past years using old SEC reports")
    p.add_argument("--years", type=int, default=10, help="how many years back (default 10)")
    p.add_argument("--min-mcap", type=float, default=10e9, help="minimum market cap (default 10e9)")
    p.add_argument("--csv", help="also save month-by-month detail to this CSV file")
    p.add_argument("--sector", action="store_true",
                   help="rank value/quality within each sector (tested 2026-10: did worse)")
    p.add_argument("--market-filter", action="store_true",
                   help="hold cash when SPY is below its 200-day average (tested 2026-10: did worse)")
    p.set_defaults(func=cmd_backtest)

    sub.add_parser("daily", help="unattended: journal a pick, check watchlist, update practice"
                   ).set_defaults(func=cmd_daily)

    sub.add_parser("market", help="market weather: trend, fear, recession and credit signals"
                   ).set_defaults(func=cmd_market)

    p = sub.add_parser("check", help="extra checklist for one company (forecasts, insiders...)")
    p.add_argument("ticker")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("practice", help="practice trading with pretend money at live prices")
    p.add_argument("action", nargs="?", default="status", choices=["status", "start", "buy", "sell", "end"])
    p.add_argument("args", nargs="*", help="start: TICKERS | buy/sell: TEST_ID TICKER SHARES | end: TEST_ID")
    p.add_argument("--cash", type=float, default=10000.0, help="pretend starting cash (default 10000)")
    p.add_argument("--days", type=int, default=30, help="how long the test runs (default 30)")
    p.add_argument("--stop", type=float, default=0.15, help="auto-sell this far below cost (default 0.15)")
    p.add_argument("--take-profit", type=float, help="auto-sell this far above cost, e.g. 0.3")
    p.set_defaults(func=cmd_practice)

    p = sub.add_parser("add", help="add a stock to your watchlist")
    p.add_argument("ticker")
    p.add_argument("--bought", type=float, help="price you paid per share")
    p.add_argument("--stop", type=float, default=0.15, help="stop-loss fraction (default 0.15)")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("remove", help="stop watching a stock")
    p.add_argument("ticker")
    p.set_defaults(func=cmd_remove)

    sub.add_parser("list", help="show your watchlist").set_defaults(func=cmd_list)

    p = sub.add_parser("setup", help="save contact email for SEC filings")
    p.add_argument("--contact", required=True)
    p.set_defaults(func=cmd_setup)

    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
