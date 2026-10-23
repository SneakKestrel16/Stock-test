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

Run `watch` once a day (or schedule it with Task Scheduler / cron) and it will
only show you things that happened since the last time you checked.
"""

import argparse
import json
import sys
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

def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"contact": None, "watchlist": {}, "seen": {}}


def save_state(st):
    HOME.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(st, indent=2, default=str))


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


def get_fundamentals(tickers):
    rows = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fetch_info, t) for t in tickers]
        for i, fut in enumerate(as_completed(futures), 1):
            t, info = fut.result()
            print(f"\r  company data {i}/{len(tickers)}", end="", flush=True)
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
    print()
    return pd.DataFrame(rows).set_index("ticker") if rows else pd.DataFrame()


def get_price_signals(tickers):
    print("  price history...")
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
        sys.exit("All weights are zero.")
    fs["score"] = sum(fs[f] * weights[f] for f in fs) / total
    return fs


def parse_weights(pairs):
    w = {"value": 1.0, "quality": 1.0, "growth": 1.0, "momentum": 1.0}
    for p in pairs or []:
        k, _, v = p.partition("=")
        if k not in w:
            sys.exit(f"Unknown factor '{k}'. Use: {', '.join(w)}")
        w[k] = float(v)
    return w


def cmd_pick(a):
    if a.file:
        tickers = [l.strip().upper() for l in open(a.file) if l.strip() and not l.startswith("#")]
    else:
        tickers = [t.upper() for t in a.tickers] if a.tickers else DEFAULT_TICKERS
    weights = parse_weights(a.weights)

    print(f"Screening {len(tickers)} stocks (buy-only)...")
    df = get_fundamentals(tickers)
    if df.empty:
        sys.exit("No data returned. Check your internet connection.")
    df = df.join(get_price_signals(list(df.index)), how="left")

    # Safety filters: only steady, profitable, uptrending companies qualify.
    num = lambda c: pd.to_numeric(df[c], errors="coerce")
    checks = {
        f"market cap >= ${a.min_mcap/1e9:.0f}B": num("marketCap").fillna(0) >= a.min_mcap,
        "expected to be profitable (forward P/E > 0)": num("forwardPE") > 0,
        "generates cash (free cash flow > 0)": num("fcfYield") > 0,
        "in an uptrend (price above 200-day average)": num("last") > num("ma200"),
        "debt not extreme (debt/equity < 250%)": num("debtToEquity").fillna(0) < 250,
    }
    keep = pd.Series(True, index=df.index)
    print("\nSafety filters:")
    for label, ok in checks.items():
        ok = ok.fillna(False)
        print(f"  - {label}: {int((keep & ~ok).sum())} removed")
        keep &= ok
    df = df[keep]
    if df.empty:
        sys.exit("No stock passed every filter right now. That itself is a signal to be patient.")

    df = df.join(score(df, weights)).sort_values("score", ascending=False)
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

    if a.add:
        st = load_state()
        st["watchlist"].setdefault(t, {"added": str(date.today()), "bought": None, "stop_pct": a.stop})
        save_state(st)
        print(f"  Added {t} to your watchlist.")


# ------------------------------------------------------------ history -----

def cmd_history(a):
    t = a.ticker.upper()
    print(f"Pulling {a.period} of history for {t}...")
    h = yf.Ticker(t).history(period=a.period, auto_adjust=True)
    if h.empty:
        sys.exit(f"No price history for {t}. Check the ticker symbol.")
    c = h["Close"]
    last = c.iloc[-1]

    def back(n):
        return c.iloc[-1] / c.iloc[-1 - n] - 1 if len(c) > n else None

    years = (c.index[-1] - c.index[0]).days / 365.25
    cagr = (last / c.iloc[0]) ** (1 / years) - 1 if years > 0.5 else None
    dd = c / c.cummax() - 1
    low_day = dd.idxmin()
    peak_day = c[:low_day].idxmax()
    divs = h["Dividends"][h.index >= h.index[-1] - pd.Timedelta(days=365)].sum() if "Dividends" in h else 0
    ma50, ma200 = c.tail(50).mean(), c.tail(200).mean()
    yr = c.tail(252)

    print(f"\n{t}  last close {money(last)}  ({c.index[-1]:%Y-%m-%d})")
    print("-" * 50)
    for label, n in [("1 month", 21), ("3 months", 63), ("6 months", 126),
                     ("1 year", 252), ("3 years", 756), ("5 years", 1260)]:
        r = back(n)
        if r is not None:
            print(f"  Return {label:9}  {pct(r)}")
    print(f"  Yearly avg (CAGR)  {pct(cagr)} over {years:.1f} years")
    print(f"  52-week range      {money(yr.min())} - {money(yr.max())}")
    print(f"  Volatility         {pct(c.pct_change().tail(252).std() * 252 ** 0.5)} per year")
    print(f"  Worst drop         {pct(dd.min())} ({peak_day:%b %Y} to {low_day:%b %Y})")
    print(f"  Dividends (1 yr)   {money(divs)}  (yield {pct(divs / last) if divs else '-'})")
    print(f"  50-day average     {money(ma50)}")
    print(f"  200-day average    {money(ma200)}  -> "
          f"{'price ABOVE: uptrend' if last > ma200 else 'price BELOW: downtrend, be cautious'}")
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
        frm = f" from {r['FromGrade']}" if r.get("FromGrade") else ""
        out.append({"id": f"analyst:{d}:{r.get('Firm')}:{r.get('ToGrade')}", "date": d,
                    "kind": "Analyst", "text": f"{r.get('Firm')} {action}{frm} to {r.get('ToGrade')}",
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
        return [], "SEC filings skipped (run: setup --contact you@example.com)"
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


def cmd_watch(a):
    st = load_state()
    tickers = [t.upper() for t in a.tickers] if a.tickers else list(st["watchlist"])
    if not tickers:
        sys.exit("Watchlist is empty. Add one with:  python stock_tracker.py add MSFT")
    since = str(date.today() - timedelta(days=a.days))
    report = [f"# Stock watch {date.today()}\n"]

    for t in tickers:
        print(f"\n{'=' * 66}\n  {t}\n{'=' * 66}")
        report.append(f"\n## {t}\n")
        tk = yf.Ticker(t)
        news = [e for e in news_events(tk) if e["date"] >= since]
        events = news + analyst_events(tk, since) + calendar_events(tk)
        moves, hist = price_events(tk, since)
        events += moves
        filings, note = sec_events(t, st.get("contact"), since)
        events += filings

        for line in position_alerts(t, st["watchlist"].get(t, {}), hist):
            print("  " + line)
            report.append(f"- **{line}**")

        seen = set(st["seen"].get(t, []))
        new = events if a.all else [e for e in events if e["id"] not in seen]
        new.sort(key=lambda e: e["date"], reverse=True)
        if not new:
            print("  Nothing new since your last check.")
            report.append("- Nothing new.")
        for e in new:
            mark = "!!" if e.get("flag") else "  "
            print(f"  {mark} {e['date']}  {e['kind']:16} {e['text']}")
            if e["url"]:
                print(f"     {'':10}  {e['url']}")
            report.append(f"- {'**RED FLAG** ' if e.get('flag') else ''}{e['date']} {e['kind']}: "
                          f"{e['text']}" + (f" ([link]({e['url']}))" if e["url"] else ""))
        if note:
            print(f"  ({note})")
        st["seen"][t] = sorted(seen | {e["id"] for e in events})[-500:]

    save_state(st)
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"watch_{datetime.now():%Y-%m-%d_%H%M}.md"
    out.write_text("\n".join(report))
    print(f"\nLines marked !! are worth a closer look. Report saved to {out}")


# ----------------------------------------------------------- watchlist ----

def cmd_add(a):
    if a.bought is not None and a.bought <= 0:
        sys.exit("--bought must be the positive price you paid per share.")
    if not 0 < a.stop < 1:
        sys.exit("--stop is a fraction, e.g. 0.15 for 15% below your buy price.")
    st = load_state()
    t = a.ticker.upper()
    st["watchlist"][t] = {"added": str(date.today()), "bought": a.bought, "stop_pct": a.stop}
    save_state(st)
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
