#!/usr/bin/env python3
"""
stock_screener.py - rank stocks on value, quality, growth and momentum.

This is a screener, NOT a predictor and NOT financial advice. It pulls current
fundamentals and price history from Yahoo Finance (via yfinance) and ranks a
list of stocks against each other. Use the output as a shortlist to research,
not a list of things to buy.

Setup (once):
    pip install yfinance pandas

Examples:
    python stock_screener.py                          # built-in list of ~60 large caps
    python stock_screener.py --top 15
    python stock_screener.py --tickers AAPL MSFT NVDA COST
    python stock_screener.py --file my_tickers.txt    # one ticker per line
    python stock_screener.py --weights value=2 quality=1 growth=1 momentum=0
    python stock_screener.py --min-mcap 10e9          # only companies over $10B
"""

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

try:
    import pandas as pd
    import yfinance as yf
except ImportError:
    sys.exit("Missing packages. Run:  pip install yfinance pandas")


DEFAULT_TICKERS = [
    # Tech / communication
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "AVGO", "ORCL", "CRM", "ADBE",
    "AMD", "INTC", "CSCO", "QCOM", "TXN", "IBM", "NFLX",
    # Financials
    "JPM", "BAC", "WFC", "GS", "MS", "V", "MA", "AXP", "BRK-B", "BLK",
    # Health care
    "JNJ", "UNH", "LLY", "PFE", "MRK", "ABBV", "TMO", "ABT", "AMGN",
    # Consumer
    "PG", "KO", "PEP", "WMT", "COST", "HD", "MCD", "NKE", "SBUX", "TGT",
    # Industrials / energy / materials / utilities
    "CAT", "DE", "HON", "GE", "UPS", "LMT", "XOM", "CVX", "COP", "LIN",
    "NEE", "DUK",
]

# factor -> list of (metric column, higher_is_better)
FACTORS = {
    "value":   [("forwardPE", False), ("priceToBook", False),
                ("evToEbitda", False), ("fcfYield", True)],
    "quality": [("returnOnEquity", True), ("profitMargins", True),
                ("debtToEquity", False)],
    "growth":  [("revenueGrowth", True), ("earningsGrowth", True)],
    "momentum": [("mom_12_1", True), ("ret_6m", True)],
}

# Ratios where a zero/negative value means "losing money", which should score
# worst rather than look artificially cheap.
POSITIVE_ONLY = {"forwardPE", "evToEbitda", "priceToBook"}


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
            print(f"\r  fundamentals {i}/{len(tickers)}", end="", flush=True)
            if not info:
                continue
            mcap = info.get("marketCap")
            fcf = info.get("freeCashflow")
            price = info.get("currentPrice") or info.get("regularMarketPrice")
            target = info.get("targetMeanPrice")
            rows.append({
                "ticker": t,
                "name": (info.get("shortName") or "")[:28],
                "sector": info.get("sector", ""),
                "price": price,
                "marketCap": mcap,
                "forwardPE": info.get("forwardPE"),
                "priceToBook": info.get("priceToBook"),
                "evToEbitda": info.get("enterpriseToEbitda"),
                "fcfYield": (fcf / mcap) if fcf and mcap else None,
                "returnOnEquity": info.get("returnOnEquity"),
                "profitMargins": info.get("profitMargins"),
                "debtToEquity": info.get("debtToEquity"),
                "revenueGrowth": info.get("revenueGrowth"),
                "earningsGrowth": info.get("earningsGrowth"),
                "dividendYield": info.get("dividendYield"),
                "analystUpside": (target / price - 1) if target and price else None,
            })
    print()
    return pd.DataFrame(rows).set_index("ticker") if rows else pd.DataFrame()


def get_momentum(tickers):
    print("  price history...")
    data = yf.download(tickers, period="13mo", auto_adjust=True,
                       progress=False, threads=True)
    close = data["Close"]
    if isinstance(close, pd.Series):
        close = close.to_frame(tickers[0])
    close = close.dropna(how="all")
    out = pd.DataFrame(index=close.columns)

    def ret(days_ago_start, days_ago_end=0):
        if len(close) <= days_ago_start:
            return pd.Series(index=close.columns, dtype=float)
        end = close.iloc[-1 - days_ago_end]
        start = close.iloc[-1 - days_ago_start]
        return end / start - 1

    # 12-1 momentum: return from ~12 months ago to ~1 month ago (skips the
    # most recent month, which tends to mean-revert).
    out["mom_12_1"] = ret(252, 21)
    out["ret_6m"] = ret(126)
    out["vol_1y"] = close.pct_change().tail(252).std() * (252 ** 0.5)
    return out


def score(df, weights):
    factor_scores = pd.DataFrame(index=df.index)
    for factor, metrics in FACTORS.items():
        ranks = []
        for col, higher_better in metrics:
            if col not in df:
                continue
            s = pd.to_numeric(df[col], errors="coerce")
            bad = pd.Series(False, index=s.index)
            if col in POSITIVE_ONLY:
                bad = s <= 0
                s = s.where(~bad)
            r = s.rank(pct=True, ascending=higher_better)
            r[bad] = 0.0          # unprofitable -> worst
            ranks.append(r)
        if ranks:
            # average of available metric ranks; missing data -> neutral 0.5
            factor_scores[factor] = pd.concat(ranks, axis=1).mean(axis=1).fillna(0.5)

    total_w = sum(weights.get(f, 0) for f in factor_scores)
    if total_w == 0:
        sys.exit("All weights are zero.")
    composite = sum(factor_scores[f] * weights.get(f, 0) for f in factor_scores) / total_w
    factor_scores["score"] = composite
    return factor_scores


def parse_weights(pairs):
    w = {"value": 1.0, "quality": 1.0, "growth": 1.0, "momentum": 1.0}
    for p in pairs or []:
        k, _, v = p.partition("=")
        if k not in w:
            sys.exit(f"Unknown factor '{k}'. Use: {', '.join(w)}")
        w[k] = float(v)
    return w


def main():
    ap = argparse.ArgumentParser(description="Rank stocks on value, quality, growth, momentum.")
    ap.add_argument("--tickers", nargs="+", help="tickers to screen")
    ap.add_argument("--file", help="text file with one ticker per line")
    ap.add_argument("--top", type=int, default=10, help="how many to show (default 10)")
    ap.add_argument("--min-mcap", type=float, default=2e9,
                    help="minimum market cap in dollars (default 2e9)")
    ap.add_argument("--weights", nargs="+", metavar="FACTOR=W",
                    help="e.g. value=2 momentum=0 (default all 1)")
    args = ap.parse_args()

    if args.file:
        with open(args.file) as f:
            tickers = [l.strip().upper() for l in f if l.strip() and not l.startswith("#")]
    elif args.tickers:
        tickers = [t.upper() for t in args.tickers]
    else:
        tickers = DEFAULT_TICKERS
    weights = parse_weights(args.weights)

    print(f"Screening {len(tickers)} tickers...")
    fund = get_fundamentals(tickers)
    if fund.empty:
        sys.exit("No data returned. Check your internet connection or ticker symbols.")
    df = fund.join(get_momentum(list(fund.index)), how="left")
    df = df[pd.to_numeric(df["marketCap"], errors="coerce").fillna(0) >= args.min_mcap]
    if df.empty:
        sys.exit("Nothing left after the market-cap filter.")

    df = df.join(score(df, weights)).sort_values("score", ascending=False)

    show = df.head(args.top)[[
        "name", "sector", "price", "score", "value", "quality", "growth", "momentum",
        "forwardPE", "revenueGrowth", "mom_12_1", "vol_1y", "analystUpside",
    ]].copy()
    pct = ["revenueGrowth", "mom_12_1", "vol_1y", "analystUpside"]
    for c in pct:
        show[c] = show[c].map(lambda x: f"{x:+.0%}" if pd.notna(x) else "-")
    for c in ["score", "value", "quality", "growth", "momentum"]:
        show[c] = show[c].map(lambda x: f"{x:.2f}")
    show["price"] = show["price"].map(lambda x: f"{x:,.2f}" if pd.notna(x) else "-")
    show["forwardPE"] = show["forwardPE"].map(lambda x: f"{x:.1f}" if pd.notna(x) else "-")

    print(f"\nTop {len(show)} by composite score (weights: {weights})")
    print("Scores are 0-1 percentile ranks within the list you screened.\n")
    print(show.to_string())

    out = f"screen_{date.today().isoformat()}.csv"
    df.to_csv(out)
    print(f"\nFull results saved to {out}")
    print("\nReminder: a high score means 'looks good on these metrics right now',"
          " not 'will go up'. Research before buying; this is not financial advice.")


if __name__ == "__main__":
    main()
