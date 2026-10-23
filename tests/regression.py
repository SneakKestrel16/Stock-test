"""Regression checks for bugs found 2026-10-22, on fake data. Runs in its own temp
folder, never your real ~/.stock_tracker. Opens a window for a few seconds.

    py tests/regression.py
"""
import os, sys, runpy, tempfile, threading
from datetime import date, datetime, timedelta
from pathlib import Path
os.environ["USERPROFILE"] = os.environ["HOME"] = tempfile.mkdtemp()   # before stock_tracker loads
import numpy as np
import pandas as pd
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
import fake_run  # noqa: F401  (patches yfinance and requests)
import stock_tracker as st


def chk(*a):
    np.random.seed(1)          # fake prices are random; same draw each call
    return st.check_ticker(*a)


# "seen" memory is capped but never forgets items still in the look-back window
state = {"contact": None, "watchlist": {"MSFT": {}}, "seen": {"MSFT": [f"aaa:{i:04d}" for i in range(700)]}}
chk("MSFT", state, 30, False)
now = {e["id"] for e in chk("MSFT", {**state, "seen": {}}, 30, True)["events"]}
kept = set(state["seen"]["MSFT"])
assert now <= kept and len(kept) <= 500, (len(now - kept), len(kept))
assert not chk("MSFT", state, 30, False)["events"], "seen items came back as new"
print("ok seen cap")

# analyst wording
class T:
    upgrades_downgrades = pd.DataFrame(
        {"Firm": ["UBS", "MS"], "ToGrade": ["Buy", "Sell"], "FromGrade": ["Buy", "Hold"], "Action": ["main", "down"]},
        index=pd.DatetimeIndex([pd.Timestamp.today()] * 2))
texts = [e["text"] for e in st.analyst_events(T(), "2000-01-01")]
assert texts == ["UBS kept its Buy rating", "MS DOWNGRADED from Hold to Sell"], texts
print("ok analyst wording")

# weights are checked before any download
for bad in (["value=-1"], ["value=0", "quality=0", "growth=0", "momentum=0"]):
    try:
        st.parse_weights(bad)
        raise SystemExit(f"no error for {bad}")
    except ValueError:
        pass
print("ok weights")

# damaged state file: trailing junk recovered; unreadable file kept, not silently wiped
st.HOME.mkdir(parents=True, exist_ok=True)
st.STATE_FILE.write_text('{"contact": "a@b.c", "watchlist": {"KO": {}}, "seen": {}}\n}, "news:a1"\n  ]\n}')
assert list(st.load_state()["watchlist"]) == ["KO"]
st.STATE_FILE.write_text('{"contact": "a@b.c", "watchl')
assert st.load_state()["watchlist"] == {} and list(st.HOME.glob("state.damaged-*.json"))
print("ok damaged state file")

# concurrent writers don't lose or corrupt anything
st.save_state({"contact": None, "watchlist": {}, "seen": {}})
ts = [threading.Thread(target=lambda p=p: [st.add_to_watchlist(f"{p}{i}") for i in range(40)]) for p in "AB"]
[t.start() for t in ts]
[t.join() for t in ts]
assert len(st.load_state()["watchlist"]) == 80
print("ok concurrent adds")

# one-year note only for a gain close to its first anniversary; junk dates ignored
flat = pd.DataFrame({"Close": [100.0] * 250})
near = str(pd.Timestamp.today().date() - pd.Timedelta(days=340))
assert any("One year held" in x for x in st.position_alerts("X", {"bought": 80, "added": near}, flat))
assert not any("One year" in x for x in st.position_alerts("X", {"bought": 120, "added": near}, flat))
assert len(st.position_alerts("X", {"bought": 80, "added": "x"}, flat)) == 1
print("ok holding period")

# day test: top 5 from today's ranking, ends today, each stop / take-profit sale's money
# goes to SPY (fake prices jump +-25%, so stops fire)
real_close = st.market_close_today
st.market_close_today = lambda: datetime.now() + timedelta(hours=1)
real_screen, st.screen = st.screen, lambda *a, **k: (pd.DataFrame(index=st.DEFAULT_TICKERS[:12]), [])
day = st.start_practice([], 10000, 1, 0.02, 0.03, day=True)
assert len(day["positions"]) == 5 and day["queue"] and day["end"][:10] == f"{date.today()}"
day = next(x for x in st.update_practice() if x["id"] == day["id"])
sells = [x for x in day["trades"] if x["side"] == "SELL"]
refills = [x for x in day["trades"] if x["reason"] == "parked in SPY"]     # DAY_RULES refill "spy"
assert sells and refills and day["cash"] >= 0
tr = day["trades"]
for i, b in enumerate(tr):                 # every refill follows the sale that paid for it
    if b["reason"] in ("next in ranking", "parked in SPY"):
        assert tr[i - 1]["side"] == "SELL"
starts = [x for x in tr if x["reason"] == "start"]
assert day["cash0"] - sum(x["shares"] * x["price"] for x in starts) < min(x["price"] for x in starts)
st.update_practice(end_now=day["id"])     # a running test would make the GUI check below refresh it

# swing: trailing stop, sale money buys the next-ranked stock, each new trading morning
# re-ranks and spends spare cash on top-5 stocks not held
sw = st.start_practice([], 10000, 30, 0.05, None, swing=True)
assert sw["swing"] and sw["trail"] and sw["queue"] and sw["end"][:10] > f"{date.today()}"
with st.STATE_LOCK:
    p = st.load_practice()
    x = next(x for x in p["tests"] if x["id"] == sw["id"])
    x["ranked_on"] = "2000-01-01"                        # pretend it's a new morning
    st.write_json(st.PRACTICE_FILE, p)
real_status, st.market_status = st.market_status, lambda now=None: (True, "open")
sw = next(x for x in st.update_practice() if x["id"] == sw["id"])
st.market_status = real_status
assert sw["ranked_on"] == f"{date.today()}" and sw["status"] == "running"
assert {"stop-loss", "next in ranking"} <= {x["reason"] for x in sw["trades"]}
st.update_practice(end_now=sw["id"])
print("ok swing test")
st.market_close_today, st.screen = real_close, real_screen
print("ok day test")

# refill: a stock with no price waits its turn instead of being dropped; nothing
# buyable left -> cash parks in SPY
t = {"positions": {}, "cash": 1000.0, "trades": [], "queue": ["AAA", "BBB"]}
st._refill(t, {"AAA": float("nan"), "BBB": 100.0, "SPY": 500.0})
assert list(t["positions"]) == ["BBB"] and t["queue"] == ["AAA"] and t["cash"] == 0
t["cash"] = 1000.0
st._refill(t, {"AAA": float("nan"), "SPY": 500.0})
assert t["positions"]["SPY"]["shares"] == 2 and t["queue"] == ["AAA"]
print("ok refill")

# NYSE calendar (2026 dates from NYSE's published schedule)
from datetime import date as D
h = st.market_holidays(2026)
assert h[D(2026, 4, 3)] == "Good Friday" and h[D(2026, 7, 3)] == "Independence Day" and D(2026, 7, 4) not in h
assert st.market_hours(D(2026, 11, 27))[1] == "13:00" and st.market_hours(D(2026, 12, 24))[1] == "13:00"
assert st.market_hours(D(2026, 11, 26)) is None and st.market_hours(D(2026, 10, 24)) is None
assert D(2021, 12, 31) not in st.market_holidays(2021) and D(2022, 1, 1) not in st.market_holidays(2022)
ny = lambda t: pd.Timestamp(t, tz="America/New_York")
assert not st.market_status(ny("2026-11-26 11:00"))[0] and "Thanksgiving" in st.market_status(ny("2026-11-26 11:00"))[1]
assert st.market_status(ny("2026-11-27 12:59"))[0] and not st.market_status(ny("2026-11-27 13:00"))[0]
print("ok market calendar")

# day replay: trades only between 09:35 and 15:55, nothing held overnight, money compounds
st.save_state({**st.load_state(), "contact": "a@b.c"})
rdata = st.replay_data("a@b.c", say=lambda m: None)
rd, rt, rs = st.day_replay(5, 10000, None, data=rdata, say=lambda m: None)
fdata = st.replay_data("a@b.c", say=lambda m: None, universe="sp500")      # fake Wikipedia: 40 members
assert all(len(v["order"]) <= st.FUNNEL_SIZE and set(v["top"]) <= set(v["order"]) for v in fdata.values())

# live funnel: ranked once a day, then served from the cache
st.FUNNEL_FILE.unlink(missing_ok=True)
f1 = st.funnel("a@b.c", None, lambda m: None)
real_screen, st.screen = st.screen, lambda *a, **k: (_ for _ in ()).throw(AssertionError("re-ranked"))
assert st.funnel("a@b.c", None, lambda m: None) == f1 and f1["source"].startswith("S&P 500")
st.screen = real_screen
print("ok funnel")

# self-tuning: saves bars, puts a challenger on trial, and only after FORWARD_DAYS
# later sessions promotes or drops it; compares with random baskets and other strategies
lines = st.self_improve("a@b.c", lambda m: None)
assert list(st.BARS_DIR.glob("*.csv.gz")) and st.SELF_FILE.exists()
tune = st.json.loads(st.SELF_FILE.read_text())
for mode in st.MODES:
    rep_ = tune[mode]["report"]
    assert 0 <= rep_["beat_random"] <= 1 and set(rep_["others"]) == set(st.ALT_STRATEGIES)
    assert rep_["random_worst"] <= rep_["random_median"] <= rep_["random_best"]
on_trial = [m for m in st.MODES if tune[m].get("challenger")]
for m in on_trial:                         # pretend 10+ new sessions have passed since
    tune[m]["since"] = "2000-01-01"
st.write_json(st.SELF_FILE, tune)
st.self_improve("a@b.c", lambda m: None)
after = st.json.loads(st.SELF_FILE.read_text())
for m in on_trial:
    ev = [x["event"] for x in after["log"] if x["mode"] == m][-1]
    assert ev.startswith(("PROMOTED", "challenger dropped")), ev
    if ev.startswith("PROMOTED"):
        assert st.active_rules(m) == {**st.MODES[m][1], **tune[m]["challenger"]}
print(f"ok self-tune ({len(on_trial)} challenger(s) judged)")
assert len(rd) == 5 and rt["time"].str[11:].between("09:35", "15:55").all()
assert abs(10000 * (1 + rd["day_ret"]).prod() - rs["end"]) < 0.01
last = rt.groupby(rt["time"].str[:10])
assert all((g["side"] == "SELL").iloc[-1] for _, g in last)
for rules in ({"atr": 2, "trail": True, "tp": None, "refill": "spy"}, {"overnight": True, "refill": "none"}):
    vd, vt, vs = st.day_replay(5, 10000, rules, data=rdata, say=lambda m: None)
    assert abs(10000 * (1 + vd["day_ret"]).prod() - vs["end"]) < 0.01 and (vt["side"] == "BUY").any()
assert "next in ranking" not in set(vt["reason"])
print("ok day replay")

# GUI: an error in a result callback must not stop later results; a stock added while
# "Check for updates" runs must survive; removing a stock clears its events
g = runpy.run_path(str(REPO / "StockTracker.pyw"), run_name="lib")
G = g["App"].__init__.__globals__
G["st"] = st
G["log_error"] = lambda t: None
for n in ("showinfo", "showwarning", "showerror"):
    setattr(G["messagebox"], n, lambda *a, n=n: print(f"  [{n}] {a[1][:80]}"))
G["messagebox"].askyesno = lambda *a: True
import tkinter as tk
root = tk.Tk()
root.report_callback_exception = lambda *e: None      # the forced error below lands here
s = st.load_state()
s.update(shortcut_offered=True, watchlist={"MSFT": {"added": "x", "bought": None, "stop_pct": .15}})
st.save_state(s)
app = g["App"](root)
out, failed = {}, []


def boom(_):
    raise RuntimeError("forced")


def check():
    if app.busy:
        return root.after(200, check)
    try:
        assert out.get("second") == 2, "polling stopped after a callback error"
        assert "KO" in st.load_state()["watchlist"], "add made during check was lost"
        app.pos_tv.selection_set("MSFT")
        app.watch_remove()
        assert "MSFT" not in {app.ev_tv.item(i, "values")[0] for i in app.ev_tv.get_children()}
        print("ok GUI")
    except AssertionError as e:
        failed.append(str(e))
    root.quit()


def start_watch():
    app.do_watch()
    app.w_ticker.set("KO"); app.w_bought.set(""); app.w_stop.set("15")
    app.watch_add()                                    # while the check is running
    root.after(300, check)


app.run_bg("x", lambda: 1, boom)
root.after(500, lambda: app.run_bg("y", lambda: 2, lambda v: out.setdefault("second", v)))
root.after(1500, start_watch)
root.mainloop()
if failed:
    raise SystemExit("FAILED: " + "; ".join(failed))
print("all regression checks passed")
