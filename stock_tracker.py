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
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
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
    HOME.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    with STATE_LOCK:
        tmp.write_text(json.dumps(st, indent=2, default=str))
        tmp.replace(STATE_FILE)        # swap in whole: never a half-written state.json


def money(x):
    return f"${x:,.2f}" if x is not None and pd.notna(x) else "-"


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


def score(df, weights):
    fs = pd.DataFrame(index=df.index)
    for factor, metrics in FACTORS.items():
        ranks = []
        for col, higher in metrics:
            if col not in df:
                continue
            s = pd.to_numeric(df[col], errors="coerce")
            bad = (s <= 0) if col in POSITIVE_ONLY else pd.Series(False, index=s.index)
            r = s.where(~bad).rank(pct=True, ascending=higher)
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
    return df.join(score(df, weights)).sort_values("score", ascending=False), report


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

    print("\n  Runners-up:")
    for rt, r in df.iloc[1:6].iterrows():
        print(f"    {rt:6} {r['name'][:26]:26} score {r['score']:.2f}  price {money(r['price'])}")

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


def backtest(tickers=None, years=10, min_mcap=10e9, weights=None, contact=None, progress=None):
    """Replay `pick` at every month-end of the past `years`, using only data public
    at the time, and hold the pick for one month. Returns (monthly_df, summary, info)."""
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
            df = df.join(score(df, weights)).sort_values("score", ascending=False)
        top = list(df.index[:5])
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
                                    contact=load_state().get("contact"))
    except ValueError as e:
        sys.exit(str(e))
    print()
    for line in backtest_lines(summary, info):
        print("  " + line)
    print("\n" + BACKTEST_CAVEATS)
    if a.csv:
        m.to_csv(a.csv)
        print(f"\n  Monthly detail saved to {Path(a.csv).resolve()}")


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
    p.set_defaults(func=cmd_backtest)

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
