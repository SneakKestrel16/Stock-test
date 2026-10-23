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
# buys the next-ranked stock (fake prices jump +-25%, so both fire)
real_close = st.market_close_today
st.market_close_today = lambda: datetime.now() + timedelta(hours=1)
real_screen, st.screen = st.screen, lambda *a, **k: (pd.DataFrame(index=st.DEFAULT_TICKERS[:12]), [])
day = st.start_practice([], 10000, 1, 0.02, 0.03, day=True)
assert len(day["positions"]) == 5 and day["queue"] and day["end"][:10] == f"{date.today()}"
day = next(x for x in st.update_practice() if x["id"] == day["id"])
sells = [x for x in day["trades"] if x["side"] == "SELL"]
refills = [x for x in day["trades"] if x["reason"] == "next in ranking"]
assert sells and refills and day["cash"] >= 0
tr = day["trades"]
for i, b in enumerate(tr):                 # a refill spends only the sale just before it
    if b["reason"] == "next in ranking":
        s = tr[i - 1]
        assert s["side"] == "SELL" and b["shares"] * b["price"] <= s["shares"] * s["price"] + 1e-6
st.market_close_today, st.screen = real_close, real_screen
print("ok day test")

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
