"""
StockTracker.pyw - desktop window for stock_tracker.py (double-click to run).

Tabs: Pick, History, Watchlist, Settings. Same buy-only logic as the command
line; nothing here shorts, uses margin or trades options. Not financial advice.

    pythonw StockTracker.pyw              # open the app
    pythonw StockTracker.pyw --shortcut   # just create the desktop shortcut
"""

import os
import queue
import subprocess
import sys
import threading
import traceback
import webbrowser
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_DIR = Path(__file__).resolve().parent
LOG = Path.home() / ".stock_tracker" / "app_error.log"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PACKAGES = {"yfinance": "yfinance", "pandas": "pandas", "requests": "requests",
            "matplotlib": "matplotlib"}


THEMES = {
    "Light": {"bg": "#f4f6fb", "card": "#ffffff", "text": "#111827", "muted": "#6b7280",
              "line": "#dfe3ec", "stripe": "#f7f9fc", "tab": "#e6eaf2", "head": "#eef1f7",
              "hover": "#e8eefc", "sel": "#dbe7fe", "flagbg": "#fee2e2",
              "good": "#15803d", "warn": "#b45309", "bad": "#b91c1c", "info": "#6b7280"},
    "Dark": {"bg": "#111827", "card": "#1f2937", "text": "#f3f4f6", "muted": "#9ca3af",
             "line": "#374151", "stripe": "#18212f", "tab": "#1b2433", "head": "#273244",
             "hover": "#2b3a52", "sel": "#1e3a8a", "flagbg": "#3f1d1d",
             "good": "#4ade80", "warn": "#fbbf24", "bad": "#f87171", "info": "#9ca3af"},
}
ACCENTS = {"Blue": ("#2563eb", "#1d4ed8"), "Green": ("#059669", "#047857"),
           "Purple": ("#7c3aed", "#6d28d9"), "Orange": ("#ea580c", "#c2410c"),
           "Pink": ("#db2777", "#be185d")}
TEXT_SIZES = {"Normal": 10, "Large": 12, "Extra large": 14}
PALETTE = {}


def apply_style(root, prefs=None):
    """Flat theme on ttk's 'clam' (ships with Python; no extra installs). prefs:
    {"theme": Light/Dark, "accent": a key of ACCENTS, "size": a key of TEXT_SIZES}."""
    prefs = prefs or {}
    PALETTE.clear()
    PALETTE.update(THEMES.get(prefs.get("theme"), THEMES["Light"]))
    PALETTE["accent"], PALETTE["accent_dark"] = ACCENTS.get(prefs.get("accent"), ACCENTS["Blue"])
    n = TEXT_SIZES.get(prefs.get("size"), 10)
    PALETTE["size"] = n
    p = PALETTE
    s = ttk.Style(root)
    s.theme_use("clam")
    root.configure(background=p["bg"])
    root.option_add("*TCombobox*Listbox.background", p["card"])
    root.option_add("*TCombobox*Listbox.foreground", p["text"])
    base, bold = ("Segoe UI", n), ("Segoe UI Semibold", n)
    s.configure(".", background=p["bg"], foreground=p["text"], font=base, bordercolor=p["line"],
                lightcolor=p["bg"], darkcolor=p["bg"], troughcolor=p["line"],
                fieldbackground=p["card"], insertcolor=p["text"], selectbackground=p["sel"],
                selectforeground=p["text"])
    s.configure("TLabelframe", background=p["bg"], bordercolor=p["line"], relief="solid")
    s.configure("TLabelframe.Label", background=p["bg"], foreground=p["accent"],
                font=("Segoe UI Semibold", n + 1))
    s.configure("TNotebook", background=p["bg"], borderwidth=0, tabmargins=(0, 4, 0, 0))
    s.configure("TNotebook.Tab", padding=(14, 7), background=p["tab"], foreground=p["muted"],
                font=bold, borderwidth=0)
    s.map("TNotebook.Tab", background=[("selected", p["bg"])], foreground=[("selected", p["accent"])])
    s.configure("TButton", padding=(10, 5), background=p["card"], foreground=p["text"], relief="flat")
    s.map("TButton", background=[("active", p["hover"]), ("disabled", p["bg"])],
          foreground=[("disabled", p["muted"])])
    for name in ("Accent.TButton", "Big.TButton"):
        s.configure(name, background=p["accent"], foreground="white", padding=(16, 8),
                    font=("Segoe UI Semibold", n + 1))
        s.map(name, background=[("active", p["accent_dark"]), ("disabled", p["line"])],
              foreground=[("disabled", "white")])
    s.configure("TCheckbutton", background=p["bg"], foreground=p["text"])
    s.configure("TRadiobutton", background=p["bg"], foreground=p["text"])
    s.configure("TEntry", fieldbackground=p["card"], foreground=p["text"], padding=4)
    s.configure("TCombobox", fieldbackground=p["card"], foreground=p["text"], padding=3,
                arrowcolor=p["text"])
    s.map("TCombobox", fieldbackground=[("readonly", p["card"])], foreground=[("readonly", p["text"])])
    s.configure("TSpinbox", fieldbackground=p["card"], foreground=p["text"], padding=3, arrowcolor=p["text"])
    s.configure("Treeview", background=p["card"], fieldbackground=p["card"], foreground=p["text"],
                rowheight=int(n * 2.6), bordercolor=p["line"], font=base)
    s.configure("Treeview.Heading", background=p["head"], foreground=p["text"], relief="flat",
                font=bold, padding=(4, 5))
    s.map("Treeview", background=[("selected", p["sel"])], foreground=[("selected", p["text"])])
    s.map("Treeview.Heading", background=[("active", p["hover"])])
    s.configure("Title.TLabel", font=("Segoe UI Semibold", n + 7), foreground=p["text"])
    s.configure("Muted.TLabel", foreground=p["muted"])
    s.configure("Bold.TLabel", font=bold)
    s.configure("Step.TLabel", font=("Segoe UI Semibold", n + 2), foreground=p["accent"])
    s.configure("Card.TLabel", font=("Consolas", n), background=p["bg"])
    for mood in ("good", "warn", "bad", "info"):
        s.configure(f"{mood.title()}.TLabel", foreground=p[mood])
    s.configure("Status.TFrame", background=p["tab"])
    s.configure("Status.TLabel", background=p["tab"], foreground=p["muted"])
    s.configure("TProgressbar", background=p["accent"])
    s.configure("Vertical.TScrollbar", background=p["tab"], arrowcolor=p["muted"])
    import matplotlib
    matplotlib.rcParams.update({
        "figure.facecolor": p["card"], "axes.facecolor": p["card"], "savefig.facecolor": p["card"],
        "text.color": p["text"], "axes.labelcolor": p["text"], "axes.edgecolor": p["line"],
        "xtick.color": p["muted"], "ytick.color": p["muted"], "grid.color": p["line"],
        "legend.facecolor": p["card"], "legend.edgecolor": p["line"], "font.size": n - 1})


def text_widget_colors():
    """Options for plain tk.Text widgets so they follow the theme."""
    p = PALETTE
    return {"background": p["card"], "foreground": p["text"], "insertbackground": p["text"],
            "highlightthickness": 1, "highlightbackground": p["line"],
            "font": ("Consolas", p["size"])}


def log_error(text):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"\n--- {datetime.now():%Y-%m-%d %H:%M:%S}\n{text}")


def show_error(exc_type, exc, tb):
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    log_error(text)
    messagebox.showerror("Stock Tracker error", f"{exc}\n\nDetails were saved to:\n{LOG}")


def ensure_packages():
    """.pyw has no console, so offer to install missing packages in a dialog."""
    missing = []
    for mod, pkg in PACKAGES.items():
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if not missing:
        return True
    root = tk.Tk()
    root.withdraw()
    if not messagebox.askyesno("Stock Tracker", "Some free add-ons this app needs are missing:\n  "
                               + ", ".join(missing) + "\n\nInstall them now? (takes a minute)"):
        return False
    r = subprocess.run([sys.executable, "-m", "pip", "install", *missing],
                       capture_output=True, text=True, creationflags=NO_WINDOW)
    if r.returncode != 0:
        log_error(r.stdout + r.stderr)
        messagebox.showerror("Stock Tracker", f"Install failed. Details saved to:\n{LOG}")
        return False
    root.destroy()
    return True


def desktop_shortcut_path():
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "[Environment]::GetFolderPath('Desktop')"],
                       capture_output=True, text=True, creationflags=NO_WINDOW)
    return Path(r.stdout.strip()) / "Stock Tracker.lnk"


def create_shortcut():
    """Desktop shortcut that runs this file with pythonw.exe (no console window).
    Returns the .lnk path. Desktop may be inside OneDrive, so ask Windows for it."""
    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe" and exe.with_name("pythonw.exe").exists():
        exe = exe.with_name("pythonw.exe")
    q = lambda p: str(p).replace("'", "''")          # PowerShell single-quote escape
    script = APP_DIR / "StockTracker.pyw"
    ps = ("$d=[Environment]::GetFolderPath('Desktop');"
          "$p=Join-Path $d 'Stock Tracker.lnk';"
          "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($p);"
          f"$s.TargetPath='{q(exe)}';"
          f"$s.Arguments='\"{q(script)}\"';"
          f"$s.WorkingDirectory='{q(APP_DIR)}';"
          "$s.Description='Stock Tracker (buy-only research tool)';"
          "$s.Save();Write-Output $p")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "PowerShell could not create the shortcut.")
    return Path(r.stdout.strip())


DAILY_TASK = "Stock Tracker daily"


def pythonw():
    exe = Path(sys.executable)
    return exe.with_name("pythonw.exe") if exe.with_name("pythonw.exe").exists() else exe


def daily_task_exists():
    r = subprocess.run(["schtasks", "/Query", "/TN", DAILY_TASK], capture_output=True,
                       creationflags=NO_WINDOW)
    return r.returncode == 0


def set_daily_task(on, at="17:30"):
    """Weekday Task Scheduler job running `stock_tracker.py daily` without a window."""
    if on:
        datetime.strptime(at, "%H:%M")          # ValueError on a bad time
        cmd = ["schtasks", "/Create", "/F", "/TN", DAILY_TASK, "/SC", "WEEKLY",
               "/D", "MON,TUE,WED,THU,FRI", "/ST", at,
               "/TR", f'"{pythonw()}" "{APP_DIR / "stock_tracker.py"}" daily']
    else:
        if not daily_task_exists():
            return
        cmd = ["schtasks", "/Delete", "/F", "/TN", DAILY_TASK]
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or r.stdout.strip())


class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.busy = False
        self.ranked = None
        self.prices = {}
        self.event_urls = {}
        self.hist = None

        self.statuses = {}
        root.title("Stock Tracker")
        root.geometry("1220x780")
        root.minsize(980, 620)
        apply_style(root, st.load_state().get("prefs"))

        head = ttk.Frame(root, padding=(14, 10, 14, 0))
        head.pack(fill="x")
        ttk.Label(head, text="Stock Tracker", style="Title.TLabel").pack(side="left")
        ttk.Label(head, text="   Buy-only research tool. It can't predict prices. Not financial advice.",
                  style="Muted.TLabel").pack(side="left", pady=(6, 0))

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=10, pady=(6, 0))
        self.nb = nb
        self.tabs = {}
        for name, build in (("Home", self.build_home), ("Stock", self.build_stock), ("Pick", self.build_pick),
                            ("Practice", self.build_practice), ("Watchlist", self.build_watch),
                            ("History", self.build_history), ("Track record", self.build_track),
                            ("Backtest", self.build_backtest), ("Settings", self.build_settings)):
            self.tabs[name] = ttk.Frame(nb, padding=12)
            build(self.tabs[name])
        self.settings_tab = self.tabs["Settings"]

        bar = ttk.Frame(root, padding=(12, 4), style="Status.TFrame")
        bar.pack(fill="x")
        self.status = tk.StringVar(value="Ready.")
        ttk.Label(bar, textvariable=self.status, style="Status.TLabel").pack(side="left")
        self.spinner = ttk.Progressbar(bar, mode="indeterminate", length=160)

        self.refresh_watchlist()
        root.after(100, self.poll)
        root.after(400, self.offer_shortcut)
        root.after(700, lambda: self.do_weather(breadth=False))
        root.after(3000, self.prepare_funnel)

    def go(self, tab):
        self.nb.select(self.tabs[tab])

    def make_tree(self, parent, cols, heads, widths, height=None, stretch_last=False):
        """Table with a scrollbar and striped rows."""
        box = ttk.Frame(parent)
        box.pack(fill="both", expand=True)
        tv = ttk.Treeview(box, columns=cols, show="headings", selectmode="browse",
                          **({"height": height} if height else {}))
        for i, (c, h, w) in enumerate(zip(cols, heads, widths)):
            tv.heading(c, text=h)
            tv.column(c, width=w, anchor="w" if w >= 150 else "center",
                      stretch=stretch_last and i == len(cols) - 1 or not stretch_last)
        tv.tag_configure("odd", background=PALETTE["stripe"])
        sb = ttk.Scrollbar(box, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        return tv

    def fill_tree(self, tv, rows):
        """rows: values tuples, or (values, tags) pairs."""
        tv.delete(*tv.get_children())
        for i, row in enumerate(rows):
            values, tags = row if len(row) == 2 and isinstance(row[1], tuple) else (row, ())
            tv.insert("", "end", values=values, tags=tags + (("odd",) if i % 2 else ()))

    # ------------------------------------------------------------- home tab
    def build_home(self, f):
        self.nb.add(f, text="Home")
        left = ttk.Frame(f)
        left.pack(side="left", fill="both", expand=True)
        steps = ttk.LabelFrame(left, text="How to use it", padding=12)
        steps.pack(fill="x")
        for i, (text, tab) in enumerate((
                ("Find a stock worth researching (about a minute)", "Pick"),
                ("Read its checklist: forecasts, insiders, risks", "Pick"),
                ("Try it with pretend money at live prices", "Practice"),
                ("Watch it: news, filings, alerts", "Watchlist"),
                ("See whether the picks have actually worked", "Track record")), 1):
            row = ttk.Frame(steps)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=f"{i}.", width=3, style="Step.TLabel").pack(side="left")
            ttk.Label(row, text=text).pack(side="left")
            ttk.Button(row, text=f"Open {tab}", command=lambda t=tab: self.go(t)).pack(side="right")

        glance = ttk.LabelFrame(left, text="At a glance", padding=12)
        glance.pack(fill="both", expand=True, pady=(10, 0))
        self.glance = tk.StringVar()
        ttk.Label(glance, textvariable=self.glance, justify="left", wraplength=520).pack(anchor="w")
        self.update_glance()

        right = ttk.LabelFrame(f, text="Market weather (today, not a forecast)", padding=12)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        self.market_line = tk.StringVar()
        ttk.Label(right, textvariable=self.market_line, style="Step.TLabel", wraplength=520,
                  justify="left").pack(anchor="w", pady=(0, 8))
        self.update_market_line()
        bar = ttk.Frame(right)
        bar.pack(fill="x")
        ttk.Button(bar, text="Refresh", command=lambda: self.do_weather(True)).pack(side="left")
        ttk.Label(bar, text="  Includes breadth (slower, ~40 s).", style="Muted.TLabel").pack(side="left")
        self.weather_box = ttk.Frame(right)
        self.weather_box.pack(fill="both", expand=True, pady=(8, 0))
        ttk.Label(self.weather_box, text="Loading...", style="Muted.TLabel").pack(anchor="w")

    def update_glance(self):
        s = st.load_state()
        tests = st.load_practice()["tests"]
        running = [x for x in tests if x["status"] == "running"]
        alerts = [f"{t}: {msg}" for t, msg in self.statuses.items() if msg != "OK"]
        picks = st.PICKS_FILE.exists() and len(st.pd.read_csv(st.PICKS_FILE).query("rank == 1"))
        lines = [f"Watchlist: {len(s['watchlist'])} stocks"
                 + (f" ({', '.join(s['watchlist'])})" if s["watchlist"] else " (add some on the Pick tab)")]
        lines += ["Alerts from your last check:"] + [f"  - {a}" for a in alerts] if alerts else \
            ["Alerts: none yet (Watchlist > Check for updates)."]
        lines.append(f"Practice tests running: {len(running)}" + "".join(
            f"\n  - {x['name']}: {st.money(x.get('value'))} ({st.pct(x.get('value', x['cash0']) / x['cash0'] - 1)})"
            for x in running))
        lines.append(f"Picks saved in your journal: {picks or 0} runs")
        lines.append("SEC contact email: " + ("set" if s.get("contact") else "not set (Settings)"))
        self.glance.set("\n".join(lines))

    def prepare_funnel(self):
        """On a trading day, rank the S&P 500 in the background (~2 min) so a day test
        can start at once. Cached for the day; quiet unless it fails."""
        contact = st.load_state().get("contact")
        if not contact or not st.market_hours(st.date.today()):
            return

        def work():
            try:
                st.funnel(contact, None, lambda m: None)
            except Exception:
                log_error(traceback.format_exc())
        threading.Thread(target=work, daemon=True).start()

    def update_market_line(self):
        """Open / closed / holiday / early close, from the NYSE calendar; every minute."""
        self.market_line.set(st.market_status()[1])
        self.root.after(60 * 1000, self.update_market_line)

    def do_weather(self, breadth=True):
        if self.busy:
            return
        self.run_bg("Checking market weather...", lambda: st.market_weather(breadth=breadth),
                    self.weather_done)

    def weather_done(self, result):
        checks, summary = result
        for w in self.weather_box.winfo_children():
            w.destroy()
        for name, res, mood, why in checks:
            row = ttk.Frame(self.weather_box)
            row.pack(fill="x", pady=4)
            ttk.Label(row, text="●", style=f"{mood.title()}.TLabel", font=("Segoe UI", 14)).pack(side="left")
            txt = ttk.Frame(row)
            txt.pack(side="left", fill="x", padx=6)
            ttk.Label(txt, text=f"{name}: {res}", style="Bold.TLabel").pack(anchor="w")
            ttk.Label(txt, text=why, style="Muted.TLabel", wraplength=470).pack(anchor="w")
        ttk.Label(self.weather_box, text=summary, wraplength=500, justify="left").pack(anchor="w", pady=(8, 0))
        self.update_glance()

    # ------------------------------------------------------------ stock tab
    def build_stock(self, f):
        self.nb.add(f, text="Stock")
        top = ttk.Frame(f)
        top.pack(fill="x")
        ttk.Label(top, text="Ticker:").pack(side="left")
        self.look_ticker = tk.StringVar()
        e = ttk.Entry(top, textvariable=self.look_ticker, width=10)
        e.pack(side="left", padx=4)
        e.bind("<Return>", lambda ev: self.do_lookup())
        ttk.Button(top, text="Look up", style="Accent.TButton", command=self.do_lookup).pack(side="left")
        ttk.Label(top, text="  Chart:").pack(side="left")
        self.look_period = tk.StringVar(value="5y")
        ttk.Combobox(top, textvariable=self.look_period, values=["6mo", "1y", "2y", "5y", "10y", "max"],
                     width=5, state="readonly").pack(side="left", padx=4)
        self.look_btns = []
        for text, cmd in (("Add to watchlist", self.look_to_watch), ("Practice with it", self.look_to_practice),
                          ("Open on Yahoo Finance", self.look_open_web)):
            b = ttk.Button(top, text=text, command=cmd, state="disabled")
            b.pack(side="left", padx=(6, 0))
            self.look_btns.append(b)
        ttk.Label(f, text="Type any US ticker (e.g. AAPL, KO, BRK-B) for its numbers, history, news from "
                  "Yahoo and the web, SEC filings and the checklist. ~15 seconds.",
                  style="Muted.TLabel").pack(anchor="w", pady=(4, 6))

        body = ttk.Frame(f)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=False)
        self.look_text = tk.Text(left, width=58, wrap="word", relief="flat", padx=10, pady=8,
                                 **text_widget_colors())
        self.look_text.pack(fill="both", expand=True)
        for mood in ("good", "warn", "bad", "info"):
            self.look_text.tag_configure(mood, foreground=PALETTE[mood])
        self.look_text.tag_configure("h", font=("Segoe UI Semibold", PALETTE["size"] + 3))
        self.look_text.tag_configure("muted", foreground=PALETTE["muted"])
        self.look_text.insert("1.0", "Look up a stock to see its details here.")
        self.look_text.configure(state="disabled")

        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        self.look_fig = Figure(figsize=(6, 3.2), dpi=100)
        self.look_ax = self.look_fig.add_subplot(111)
        self.look_canvas = FigureCanvasTkAgg(self.look_fig, master=right)
        self.look_canvas.get_tk_widget().pack(fill="x")
        tabs = ttk.Notebook(right)
        tabs.pack(fill="both", expand=True, pady=(8, 0))
        self.look_trees, self.look_urls = {}, {}
        for key, title, heads in (("web", "News from the web", ("Date", "Source", "Headline")),
                                  ("yahoo", "Yahoo news", ("Date", "Source", "Headline")),
                                  ("sec", "SEC filings", ("Date", "Form", "What"))):
            fr = ttk.Frame(tabs, padding=4)
            tabs.add(fr, text=title)
            tv = self.make_tree(fr, ("date", "src", "text"), heads, (90, 120, 520), stretch_last=True)
            tv.tag_configure("flag", foreground=PALETTE["bad"])
            tv.bind("<Double-1>", lambda ev, k=key: self.look_open(k))
            self.look_trees[key] = tv
        ttk.Label(right, text="Double-click a row to open it.", style="Muted.TLabel").pack(anchor="w")
        self.look_data = None

    def do_lookup(self):
        t = self.look_ticker.get().strip().upper()
        if not t:
            return
        s = st.load_state()
        period = self.look_period.get()
        self.run_bg(f"Looking up {t}...", lambda: st.stock_detail(t, s.get("contact"), list(s["watchlist"]),
                                                                    period), self.lookup_done)

    def lookup_done(self, d):
        self.look_data = d
        info, s = d["info"], d["stats"]
        w = self.look_text
        w.configure(state="normal")
        w.delete("1.0", "end")
        w.insert("end", f"{d['ticker']}  {d['name']}\n", "h")
        for label, text in st.detail_facts(info):
            w.insert("end", f"{label:24}", "muted")
            w.insert("end", f"{text}\n")
        w.insert("end", "\nReturns  ", "muted")
        w.insert("end", "  ".join(f"{k} {st.pct(v)}" for k, v in s["returns"]) + "\n")
        if d.get("spy_returns"):
            w.insert("end", "S&P 500  ", "muted")
            w.insert("end", "  ".join(f"{k} {st.pct(d['spy_returns'].get(k))}" for k, _ in s["returns"]) + "\n", "muted")
        w.insert("end", "Worst drop ", "muted")
        w.insert("end", f"{st.pct(s['worst_drop'])}   ")
        w.insert("end", "uptrend\n" if d["uptrend"] else "downtrend\n", "good" if d["uptrend"] else "bad")
        if info.get("longBusinessSummary"):
            w.insert("end", "\n" + info["longBusinessSummary"][:700] + "\n", "muted")
        w.insert("end", "\nChecklist\n", "h")
        for name, res, mood, why in d["checks"]:
            w.insert("end", "● ", mood)
            w.insert("end", f"{name}: {res}\n")
            w.insert("end", f"   {why}\n", "muted")
        w.configure(state="disabled")

        h = d["hist"]["Close"]
        ax = self.look_ax
        ax.clear()
        ax.plot(h.index, h, color=PALETTE["accent"], linewidth=1.4, label="Price")
        ax.plot(h.index, h.rolling(50).mean(), color="#f59e0b", linewidth=1, label="50-day avg")
        ax.plot(h.index, h.rolling(200).mean(), color=PALETTE["muted"], linewidth=1, label="200-day avg")
        ax.set_title(f"{d['ticker']} price ({self.look_period.get()})")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
        self.look_fig.tight_layout()
        self.look_canvas.draw()

        self.look_urls.clear()
        for key, rows in (("web", [(n["date"], n["source"], n["title"], n["url"], False) for n in d["web_news"]]),
                          ("yahoo", [(e["date"], e["text"].rsplit("[", 1)[-1].rstrip("]") if "[" in e["text"] else "",
                                      e["text"].rsplit("  [", 1)[0], e["url"], False) for e in d["yahoo_news"]]),
                          ("sec", [(e["date"], e["kind"], e["text"], e["url"], e.get("flag"))
                                   for e in d["filings"]] or [("", "", d["filings_note"] or "None in the last year.",
                                                                "", False)])):
            tv = self.look_trees[key]
            tv.delete(*tv.get_children())
            for i, (dt, src, text, url, flag) in enumerate(rows):
                iid = tv.insert("", "end", values=(dt, src, text),
                                tags=(("flag",) if flag else ()) + (("odd",) if i % 2 else ()))
                if url:
                    self.look_urls[(key, iid)] = url
        for b in self.look_btns:
            b.configure(state="normal")

    def look_open(self, key):
        sel = self.look_trees[key].selection()
        if sel and (key, sel[0]) in self.look_urls:
            webbrowser.open(self.look_urls[(key, sel[0])])

    def look_to_watch(self):
        if self.look_data:
            st.add_to_watchlist(self.look_data["ticker"], keep_existing=True)
            self.refresh_watchlist()
            self.status.set(f"{self.look_data['ticker']} added to your watchlist.")

    def look_to_practice(self):
        if self.look_data:
            self.p_tickers.set(self.look_data["ticker"])
            self.p_follow.set(False)
            self.go("Practice")

    def look_open_web(self):
        if self.look_data:
            webbrowser.open(f"https://finance.yahoo.com/quote/{self.look_data['ticker']}")

    def show_checklist(self, ticker, checks, news=()):
        win = tk.Toplevel(self.root)
        win.title(f"Checklist: {ticker}")
        win.geometry("1240x780" if news else "760x780")
        win.configure(background=PALETTE["bg"])
        box = ttk.Frame(win, padding=14)
        box.pack(side="left", fill="both", expand=True)
        if news:
            side = ttk.LabelFrame(win, text="News from the web (last 14 days)", padding=10)
            side.pack(side="left", fill="both", expand=True, padx=(0, 14), pady=14)
            for n in news[:12]:
                link = ttk.Label(side, text=f"{n['date']}  {n['title']}", wraplength=420,
                                 cursor="hand2", style="Bold.TLabel" if n is news[0] else "TLabel")
                link.pack(anchor="w", pady=3)
                link.bind("<Button-1>", lambda e, u=n["url"]: webbrowser.open(u))
            ttk.Label(side, text="From Google News; click a headline to open it. Headlines mostly "
                      "explain moves that already happened.", style="Muted.TLabel",
                      wraplength=420).pack(anchor="w", pady=(8, 0))
        ttk.Label(box, text=f"{ticker} checklist", style="Title.TLabel").pack(anchor="w")
        ttk.Label(box, text="Extra facts, not part of the score (Yahoo keeps no history of most, so "
                  "they can't be backtested).", style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
        for name, res, mood, why in checks:
            row = ttk.Frame(box)
            row.pack(fill="x", pady=4)
            ttk.Label(row, text="●", style=f"{mood.title()}.TLabel", font=("Segoe UI", 14)).pack(side="left")
            txt = ttk.Frame(row)
            txt.pack(side="left", fill="x", padx=6)
            ttk.Label(txt, text=f"{name}: {res}", style="Bold.TLabel", wraplength=620).pack(anchor="w")
            ttk.Label(txt, text=why, style="Muted.TLabel", wraplength=620).pack(anchor="w")
        legend = ttk.Frame(box)
        legend.pack(anchor="w", pady=(10, 0))
        for mood, text in (("good", "good"), ("warn", "worth a look"), ("bad", "warning"), ("info", "info")):
            ttk.Label(legend, text="●", style=f"{mood.title()}.TLabel").pack(side="left")
            ttk.Label(legend, text=text + "    ", style="Muted.TLabel").pack(side="left")

    # ------------------------------------------------------ background work
    def run_bg(self, label, fn, done):
        """Run fn() in a thread; done(result) runs back on the tk thread."""
        if self.busy:
            messagebox.showinfo("Stock Tracker", "Still working on the last request, please wait.")
            return
        self.busy = True
        self.status.set(label)
        self.spinner.pack(side="right")
        self.spinner.start(12)

        def work():
            try:
                self.q.put(("done", done, fn()))
            except Exception as e:
                self.q.put(("error", e, traceback.format_exc()))
        threading.Thread(target=work, daemon=True).start()

    def progress(self, text):
        """Safe to call from worker threads."""
        self.q.put(("status", text, None))

    def poll(self):
        try:
            while True:
                kind, a, b = self.q.get_nowait()
                if kind == "status":
                    self.status.set(a)
                    continue
                self.busy = False
                self.spinner.stop()
                self.spinner.pack_forget()
                if kind == "done":
                    self.status.set("Ready.")
                    a(b)
                else:
                    log_error(b)
                    self.status.set("Something went wrong.")
                    messagebox.showerror("Stock Tracker", str(a))
        except queue.Empty:
            pass
        finally:    # an error in a callback must not stop polling, or every later result is lost
            self.root.after(100, self.poll)

    # ------------------------------------------------------------- pick tab
    def build_pick(self, f):
        self.nb.add(f, text="Pick")
        top = ttk.Frame(f)
        top.pack(fill="x")
        ttk.Button(top, text="Find best buy candidates", style="Accent.TButton",
                   command=self.do_pick).pack(side="left")
        ttk.Label(top, text="   Min company size ($ billions):").pack(side="left")
        self.min_mcap = tk.StringVar(value="10")
        ttk.Entry(top, textvariable=self.min_mcap, width=6).pack(side="left")
        ttk.Label(top, text="   Stop-loss %:").pack(side="left")
        self.pick_stop = tk.StringVar(value="15")
        ttk.Entry(top, textvariable=self.pick_stop, width=5).pack(side="left")
        ttk.Label(top, text="   Budget $:").pack(side="left")
        self.budget = tk.StringVar(value="1000")
        ttk.Entry(top, textvariable=self.budget, width=7).pack(side="left")
        self.budget.trace_add("write", lambda *a: self.show_candidate())
        ttk.Label(top, text=f"   Screens {len(st.DEFAULT_TICKERS)} large US companies (~1 minute).",
                  style="Muted.TLabel").pack(side="left")

        body = ttk.Frame(f)
        body.pack(fill="both", expand=True, pady=10)
        left = ttk.LabelFrame(body, text="Selected stock", padding=10)
        left.pack(side="left", fill="both", expand=True)
        self.card = tk.Text(left, width=62, height=20, wrap="word", relief="flat", padx=10, pady=8,
                            **text_widget_colors())
        self.card.pack(fill="both", expand=True)
        self.set_card("Press \"Find best buy candidates\".\n\n"
                      "It ranks big US companies on value, quality, growth and momentum,\n"
                      "after dropping any that fail basic safety checks.\n\n"
                      "A high score means 'looks strong on these measures today',\n"
                      "not 'will go up'.")
        btns = ttk.Frame(left)
        btns.pack(fill="x", pady=(8, 0))
        self.pick_btns = []
        for text, cmd in (("Checklist", self.pick_checklist), ("Add to watchlist", self.pick_to_watch),
                          ("View history", self.pick_to_history),
                          ("Practice with top 5", self.pick_to_practice)):
            b = ttk.Button(btns, text=text, command=cmd, state="disabled")
            b.pack(side="left", padx=(0, 6))
            self.pick_btns.append(b)

        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        ttk.Label(right, text="Ranked (click a row). 'Settled' = how often it stays in the top 5 when "
                  "the weights are nudged.", style="Muted.TLabel", wraplength=480).pack(anchor="w")
        cols = ("rank", "ticker", "name", "score", "settled", "price")
        self.rank_tv = self.make_tree(right, cols, ("#", "Ticker", "Company", "Score", "Settled", "Price"),
                                      (40, 65, 190, 60, 70, 85), height=10)
        self.rank_tv.tag_configure("basket", font=("Segoe UI Semibold", 10))
        self.rank_tv.bind("<<TreeviewSelect>>", lambda e: self.show_candidate())
        ttk.Label(right, text=st.BASKET_NOTE.replace("\n", " "), wraplength=480,
                  style="Bold.TLabel").pack(anchor="w", pady=(8, 0))
        self.sector_note = tk.StringVar()
        ttk.Label(right, textvariable=self.sector_note, wraplength=480, style="Warn.TLabel").pack(anchor="w")
        ttk.Label(right, text="Safety filters (stocks removed):", style="Muted.TLabel").pack(anchor="w", pady=(8, 0))
        self.filters = tk.StringVar()
        ttk.Label(right, textvariable=self.filters, justify="left", style="Muted.TLabel").pack(anchor="w")

    def set_card(self, text):
        self.card.configure(state="normal")
        self.card.delete("1.0", "end")
        self.card.insert("1.0", text)
        self.card.configure(state="disabled")

    def do_pick(self):
        try:
            mcap = float(self.min_mcap.get()) * 1e9
            self.stop_frac = float(self.pick_stop.get()) / 100
            assert 0 < self.stop_frac < 1
        except (ValueError, AssertionError):
            messagebox.showwarning("Stock Tracker", "Enter numbers, e.g. 10 and 15.")
            return
        weights = st.parse_weights(None)
        self.run_bg("Downloading company data...",
                    lambda: st.screen(st.DEFAULT_TICKERS, weights, mcap,
                                      lambda i, n: self.progress(f"Company data {i}/{n}...")),
                    self.pick_done)

    def pick_done(self, result):
        df, report = result
        st.log_picks(df)
        self.sector_note.set(st.sector_warning(df) if not df.empty else "")
        self.filters.set("\n".join(f"  {label}: {n}" for label, n in report))
        self.rank_tv.delete(*self.rank_tv.get_children())
        self.ranked = df
        if df.empty:
            self.set_card("No stock passed every safety filter right now.\n"
                          "That itself is a signal to be patient.")
            return
        for i, (t, r) in enumerate(df.iterrows(), 1):
            tags = (("basket",) if i <= 5 else ()) + (("odd",) if i % 2 == 0 else ())
            self.rank_tv.insert("", "end", iid=t, tags=tags, values=(
                i, t, r["name"], f"{r['score']:.2f}", f"{r['stable5']:.0%}", st.money(r["price"])))
        self.rank_tv.selection_set(df.index[0])
        self.update_glance()

    def selected_ticker(self):
        sel = self.rank_tv.selection()
        return sel[0] if sel else None

    def show_candidate(self):
        t = self.selected_ticker()
        if not t or self.ranked is None:
            return
        r = self.ranked.loc[t]
        rank = list(self.ranked.index).index(t) + 1
        stop = r["price"] * (1 - self.stop_frac) if st.pd.notna(r["price"]) else None
        pe = f"{r['forwardPE']:.1f}" if st.pd.notna(r["forwardPE"]) else "-"
        head = "TOP BUY CANDIDATE" if rank == 1 else f"CANDIDATE #{rank}"
        self.set_card(
            f"{head}: {t}\n{r['name']}  ({r['sector']})\n\n"
            f"Price now:          {st.money(r['price'])}\n"
            f"Overall score:      {r['score']:.2f} / 1.00  (#{rank} of {len(self.ranked)})\n"
            f"  value {r['value']:.2f} | quality {r['quality']:.2f}\n"
            f"  growth {r['growth']:.2f} | momentum {r['momentum']:.2f}\n\n"
            f"Forward P/E:        {pe}   (price vs expected profit; lower = cheaper)\n"
            f"Revenue growth:     {st.pct(r['revenueGrowth'])}\n"
            f"Profit margin:      {st.pct(r['profitMargins'])}\n"
            f"12-month momentum:  {st.pct(r['mom_12_1'])}\n"
            f"Yearly volatility:  {st.pct(r['vol_1y'])}  (typical yearly swing)\n"
            f"Analyst target:     {st.pct(r['analystUpside'])} vs today "
            f"(consensus: {r['recommendation'] or 'n/a'})\n\n"
            f"How settled: #1 in {r['stable1']:.0%}, top 5 in {r['stable5']:.0%} of 200\n"
            f"  small changes to the weights. Low = a coin toss between close scores.\n\n"
            f"If you buy (whole shares, cash account, no margin):\n"
            f"  Suggested stop-loss: {st.money(stop)} ({self.stop_frac:.0%} below today).\n"
            f"  The Checklist also gives one sized to this stock's normal swings.\n"
            f"  Selling there caps your loss; you can never lose more than you invest.\n"
            f"  Keep any single stock to a small slice of your savings (many use <=5%).\n\n"
            f"{self.budget_line(r['price'])}")
        for b in self.pick_btns:
            b.configure(state="normal")

    def budget_line(self, price):
        """Whole shares a budget buys: for this stock alone, and per stock in the top-5 basket."""
        try:
            budget = float(self.budget.get())
            assert budget > 0 and price > 0
        except (ValueError, AssertionError, TypeError):
            return "Budget: enter an amount above to see how many shares it buys."
        one = int(budget // price)
        each = int(budget / 5 // price)
        line = f"With {st.money(budget)}: {one} share(s) of this stock ({st.money(one * price)})."
        if each:
            line += f"\n  As one fifth of a top-5 basket: {each} share(s) ({st.money(each * price)})."
        else:
            line += (f"\n  A fifth of it ({st.money(budget / 5)}) doesn't buy one share; a top-5 "
                     f"basket needs a bigger budget.")
        return line

    def pick_checklist(self):
        t = self.selected_ticker()
        if t:
            wl = list(st.load_state()["watchlist"])
            self.run_bg(f"Checking {t} (forecasts, insiders, risks)...",
                        lambda: (st.company_checks(t, wl), self.safe_news(t)),
                        lambda r: self.show_checklist(t, *r))

    def safe_news(self, t):
        try:
            name = self.ranked.at[t, "name"] if self.ranked is not None and t in self.ranked.index else t
            return st.web_news(f'"{st.short_name(name)}" stock')
        except Exception:
            return []

    def pick_to_practice(self):
        self.practice_use_top5()
        self.go("Practice")

    def pick_to_watch(self):
        t = self.selected_ticker()
        if t:
            st.add_to_watchlist(t, stop=self.stop_frac, keep_existing=True)
            self.refresh_watchlist()
            self.status.set(f"{t} added to your watchlist.")

    def pick_to_history(self):
        t = self.selected_ticker()
        if t:
            self.hist_ticker.set(t)
            self.go("History")
            self.do_history()

    # ---------------------------------------------------------- history tab
    def build_history(self, f):
        self.nb.add(f, text="History")
        top = ttk.Frame(f)
        top.pack(fill="x")
        ttk.Label(top, text="Ticker:").pack(side="left")
        self.hist_ticker = tk.StringVar(value="MSFT")
        e = ttk.Entry(top, textvariable=self.hist_ticker, width=10)
        e.pack(side="left")
        e.bind("<Return>", lambda ev: self.do_history())
        ttk.Label(top, text="  Period:").pack(side="left")
        self.period = tk.StringVar(value="5y")
        ttk.Combobox(top, textvariable=self.period, values=["1y", "2y", "5y", "10y", "max"],
                     width=6, state="readonly").pack(side="left")
        ttk.Button(top, text="Show history", command=self.do_history).pack(side="left", padx=6)
        self.save_csv_btn = ttk.Button(top, text="Save CSV...", command=self.save_csv,
                                       state="disabled")
        self.save_csv_btn.pack(side="left")

        body = ttk.Frame(f)
        body.pack(fill="both", expand=True, pady=8)
        self.hist_stats = tk.StringVar(value="Type a ticker (e.g. MSFT) and press Show history.")
        ttk.Label(body, textvariable=self.hist_stats, style="Card.TLabel", justify="left",
                  width=46, anchor="nw").pack(side="left", fill="y")

        from matplotlib.figure import Figure
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        self.fig = Figure(figsize=(7, 4.5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=body)
        self.canvas.get_tk_widget().pack(side="left", fill="both", expand=True)

    def do_history(self):
        t = self.hist_ticker.get().strip().upper()
        if not t:
            return
        p = self.period.get()
        self.run_bg(f"Downloading {p} of history for {t}...",
                    lambda: (t, p, *st.history_stats(t, p)), self.history_done)

    def history_done(self, result):
        t, p, h, s, uptrend = result
        self.hist = (t, h)
        last, divs = s["last"], s["dividends"]
        lines = [f"{t}  last close {st.money(last)}  ({s['last_date']:%Y-%m-%d})", "-" * 44]
        lines += [f"Return {label:9}   {st.pct(r)}" for label, r in s["returns"]]
        lines += [
            f"Yearly avg (CAGR)  {st.pct(s['cagr'])} over {s['years']:.1f} yrs",
            f"52-week range      {st.money(s['low_52w'])} - {st.money(s['high_52w'])}",
            f"Volatility         {st.pct(s['volatility'])} per year",
            f"Worst drop         {st.pct(s['worst_drop'])}",
            f"                   ({s['peak_day']:%b %Y} to {s['low_day']:%b %Y})",
            f"Dividends (1 yr)   {st.money(divs)}"
            + (f"  (yield {st.pct(divs / last)})" if divs else ""),
            f"50-day average     {st.money(s['ma50'])}",
            f"200-day average    {st.money(s['ma200'])}",
            "",
            "Price ABOVE 200-day average: uptrend." if uptrend
            else "Price BELOW 200-day average:\ndowntrend, be cautious.",
            "",
            "Worst drop is a useful gut check:\ncould you hold through that again?",
        ]
        self.hist_stats.set("\n".join(lines))
        c = h["Close"]
        ax = self.ax
        ax.clear()
        ax.plot(c.index, c, label="Price", linewidth=1.4, color=PALETTE["accent"])
        ax.plot(c.index, c.rolling(50).mean(), label="50-day avg", linewidth=1, color="#f59e0b")
        ax.plot(c.index, c.rolling(200).mean(), label="200-day avg", linewidth=1, color="#6b7280")
        ax.set_title(f"{t} - {p} price history")
        ax.set_ylabel("Price ($)")
        ax.grid(alpha=0.3)
        ax.legend()
        self.fig.tight_layout()
        self.canvas.draw()
        self.save_csv_btn.configure(state="normal")

    def save_csv(self):
        if not self.hist:
            return
        t, h = self.hist
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                                            initialfile=f"{t}_history.csv",
                                            filetypes=[("CSV (opens in Excel)", "*.csv")])
        if path:
            h.to_csv(path)
            self.status.set(f"Saved {path}")

    # -------------------------------------------------------- watchlist tab
    def build_watch(self, f):
        self.nb.add(f, text="Watchlist")
        cols = ("ticker", "bought", "price", "gain", "stop", "status")
        heads = ("Ticker", "Bought at", "Price", "Gain", "Stop-loss level", "Status")
        self.pos_tv = ttk.Treeview(f, columns=cols, show="headings", height=6, selectmode="browse")
        for c, h, w in zip(cols, heads, (70, 90, 90, 80, 110, 360)):
            self.pos_tv.heading(c, text=h)
            self.pos_tv.column(c, width=w, anchor="w" if c == "status" else "center")
        self.pos_tv.tag_configure("bad", foreground=PALETTE["bad"])
        self.pos_tv.pack(fill="x")
        self.pos_tv.bind("<<TreeviewSelect>>", lambda e: self.fill_form())

        form = ttk.Frame(f)
        form.pack(fill="x", pady=6)
        ttk.Label(form, text="Ticker:").pack(side="left")
        self.w_ticker = tk.StringVar()
        ttk.Entry(form, textvariable=self.w_ticker, width=8).pack(side="left")
        ttk.Label(form, text="  Bought at $ (blank if not bought):").pack(side="left")
        self.w_bought = tk.StringVar()
        ttk.Entry(form, textvariable=self.w_bought, width=9).pack(side="left")
        ttk.Label(form, text="  Stop-loss %:").pack(side="left")
        self.w_stop = tk.StringVar(value="15")
        ttk.Entry(form, textvariable=self.w_stop, width=5).pack(side="left")
        ttk.Button(form, text="Add / update", command=self.watch_add).pack(side="left", padx=6)
        ttk.Button(form, text="Remove selected", command=self.watch_remove).pack(side="left")

        chk = ttk.Frame(f)
        chk.pack(fill="x", pady=(4, 6))
        ttk.Button(chk, text="Check for updates", style="Big.TButton",
                   command=self.do_watch).pack(side="left")
        self.show_all = tk.BooleanVar()
        ttk.Checkbutton(chk, text="Show everything (not just new)",
                        variable=self.show_all).pack(side="left", padx=8)
        ttk.Label(chk, text="Look back days:").pack(side="left")
        self.days = tk.StringVar(value="30")
        ttk.Spinbox(chk, from_=1, to=365, textvariable=self.days, width=5).pack(side="left")
        ttk.Label(chk, text="   Red rows are worth a closer look. Double-click a row to open it.",
                  style="Muted.TLabel").pack(side="left")

        ev = ttk.Frame(f)
        ev.pack(fill="both", expand=True)
        cols = ("ticker", "date", "kind", "text")
        self.ev_tv = ttk.Treeview(ev, columns=cols, show="headings")
        for c, w in zip(cols, (70, 90, 130, 760)):
            self.ev_tv.heading(c, text=c.title() if c != "text" else "What happened")
            self.ev_tv.column(c, width=w, anchor="w", stretch=c == "text")
        self.ev_tv.tag_configure("flag", foreground=PALETTE["bad"], background=PALETTE["flagbg"])
        sb = ttk.Scrollbar(ev, orient="vertical", command=self.ev_tv.yview)
        self.ev_tv.configure(yscrollcommand=sb.set)
        self.ev_tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.ev_tv.bind("<Double-1>", self.open_event)

    def refresh_watchlist(self, statuses=None):
        statuses = statuses or {}
        self.pos_tv.delete(*self.pos_tv.get_children())
        for t, p in st.load_state()["watchlist"].items():
            bought, price = p.get("bought"), self.prices.get(t)
            gain = price / bought - 1 if bought and price else None
            stop = bought * (1 - p.get("stop_pct", 0.15)) if bought else None
            status = statuses.get(t, "Press 'Check for updates'" if price is None else "OK")
            bad = status.startswith("!!") or "below" in status
            self.pos_tv.insert("", "end", iid=t, tags=("bad",) if bad else (), values=(
                t, st.money(bought), st.money(price), st.pct(gain),
                f"{st.money(stop)} ({p.get('stop_pct', 0.15):.0%})" if stop else "-", status))

    def fill_form(self):
        sel = self.pos_tv.selection()
        if not sel:
            return
        p = st.load_state()["watchlist"].get(sel[0], {})
        self.w_ticker.set(sel[0])
        self.w_bought.set(f"{p['bought']:g}" if p.get("bought") else "")
        self.w_stop.set(f"{p.get('stop_pct', 0.15) * 100:g}")

    def watch_add(self):
        t = self.w_ticker.get().strip().upper()
        try:
            bought = float(self.w_bought.get()) if self.w_bought.get().strip() else None
            stop = float(self.w_stop.get()) / 100
            assert t and (bought is None or bought > 0) and 0 < stop < 1
        except (ValueError, AssertionError):
            messagebox.showwarning("Stock Tracker", "Enter a ticker, the positive price you paid "
                                   "(or leave it blank), and a stop-loss % between 1 and 99.")
            return
        st.add_to_watchlist(t, bought, stop)
        self.refresh_watchlist()
        self.status.set(f"Watching {t}.")

    def watch_remove(self):
        sel = self.pos_tv.selection()
        if sel and messagebox.askyesno("Stock Tracker", f"Stop watching {sel[0]}?"):
            with st.STATE_LOCK:
                s = st.load_state()
                s["watchlist"].pop(sel[0], None)
                s["seen"].pop(sel[0], None)
                st.save_state(s)
            self.refresh_watchlist()
            for iid in self.ev_tv.get_children():
                if self.ev_tv.item(iid, "values")[0] == sel[0]:
                    self.ev_tv.delete(iid)

    def do_watch(self):
        try:
            days = int(self.days.get())
        except ValueError:
            days = 30
        show_all = self.show_all.get()

        def work():
            return st.watch_all(days, show_all, self.progress)

        if not st.load_state()["watchlist"]:
            messagebox.showinfo("Stock Tracker", "Your watchlist is empty. Add a ticker first.")
            return
        self.run_bg("Checking your watchlist...", work, self.watch_done)

    def watch_done(self, result):
        results, report = result
        self.ev_tv.delete(*self.ev_tv.get_children())
        self.event_urls.clear()
        statuses = {}
        for t, r in results.items():
            self.prices[t] = r["price"]
            short = []
            for line in r["alerts"]:
                if line.startswith("!!"):
                    short.append("!! STOP-LOSS HIT: consider selling")
                elif line.startswith("Up 50%"):
                    short.append("Up 50%+: consider taking some profit")
                elif "below its 200-day" in line:
                    short.append("below 200-day average (downtrend)")
                if not line.startswith("Your position"):
                    self.ev_tv.insert("", "end", values=(t, "", "Alert", line),
                                      tags=("flag",) if line.startswith("!!") else ())
            statuses[t] = "; ".join(short) or "OK"
            if not r["events"]:
                self.ev_tv.insert("", "end", values=(t, "", "", "Nothing new since your last check."))
            for e in r["events"]:
                iid = self.ev_tv.insert("", "end", values=(t, e["date"], e["kind"], e["text"]),
                                        tags=("flag",) if e.get("flag") else ())
                if e["url"]:
                    self.event_urls[iid] = e["url"]
            if r["note"]:
                self.ev_tv.insert("", "end", values=(t, "", "Note", r["note"]))
        self.statuses = statuses
        self.refresh_watchlist(statuses)
        self.update_glance()
        if report:
            self.status.set(f"Done. Report saved to {report}")

    def open_event(self, _):
        sel = self.ev_tv.selection()
        if sel and sel[0] in self.event_urls:
            webbrowser.open(self.event_urls[sel[0]])

    # --------------------------------------------------------- practice tab
    def build_practice(self, f):
        self.nb.add(f, text="Practice")
        new = ttk.LabelFrame(f, text="Start a practice test (pretend money, live prices)", padding=8)
        new.pack(fill="x")
        self.p_tickers = tk.StringVar()
        self.p_cash, self.p_days = tk.StringVar(value="10000"), tk.StringVar(value="30")
        self.p_stop, self.p_tp = tk.StringVar(value="15"), tk.StringVar(value="")
        row = ttk.Frame(new)
        row.pack(fill="x")
        ttk.Label(row, text="Stocks:").pack(side="left")
        ttk.Entry(row, textvariable=self.p_tickers, width=28).pack(side="left", padx=(2, 4))
        ttk.Button(row, text="Use today's top 5", command=self.practice_use_top5).pack(side="left")
        for label, var, w in (("  Cash $", self.p_cash, 8), ("  Days", self.p_days, 4),
                              ("  Auto-sell if down %", self.p_stop, 4),
                              ("  Auto-sell if up % (optional)", self.p_tp, 4)):
            ttk.Label(row, text=label).pack(side="left")
            entry = ttk.Entry(row, textvariable=var, width=w)
            entry.pack(side="left", padx=2)
            if var is self.p_days:
                self.p_days_entry = entry
        ttk.Button(row, text="Start test", style="Accent.TButton",
                   command=self.practice_start).pack(side="left", padx=8)
        self.p_follow = tk.BooleanVar()
        self.p_follow_cb = ttk.Checkbutton(new, variable=self.p_follow, text=(
            "Follow the picks: every 30 days switch to the new top 5 (leave Stocks empty to start "
            "with today's). This is the backtested strategy, tested forward in real time."))
        self.p_follow_cb.pack(anchor="w", pady=(6, 0))
        self.p_day = tk.BooleanVar()
        ttk.Checkbutton(new, variable=self.p_day, command=self.practice_day_toggle, text=(
            "Day trade: ends at today's close. With Stocks empty it buys the top 5 of today's S&P 500 ranking; sells a stock "
            "that falls 2% below its highest price today and puts that money in SPY. Market hours only.")
        ).pack(anchor="w", pady=(2, 0))
        self.p_swing = tk.BooleanVar()
        ttk.Checkbutton(new, variable=self.p_swing, command=lambda: self.practice_day_toggle("swing"), text=(
            "Swing: holds overnight for the Days above. Sells a stock 5% below its highest price since "
            "buying; that money buys the next-ranked stock. Re-ranks each trading morning.")
        ).pack(anchor="w", pady=(2, 0))
        ttk.Label(new, style="Muted.TLabel", text=(
            "Money is split evenly over the stocks (whole shares). Prices update every 5 minutes "
            "while the app is open; you can also buy and sell yourself. Results list appears when it ends.")
        ).pack(anchor="w", pady=(4, 0))

        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=(8, 4))
        ttk.Label(bar, text="Test:").pack(side="left")
        self.p_choice = tk.StringVar()
        self.p_combo = ttk.Combobox(bar, textvariable=self.p_choice, state="readonly", width=60)
        self.p_combo.pack(side="left", padx=4)
        self.p_combo.bind("<<ComboboxSelected>>", lambda e: self.practice_show())
        ttk.Button(bar, text="Refresh prices", command=self.practice_refresh).pack(side="left")
        ttk.Button(bar, text="End test now", command=self.practice_end).pack(side="left", padx=4)

        body = ttk.Frame(f)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True)
        self.p_summary = tk.StringVar(value="No practice tests yet. Start one above.")
        ttk.Label(left, textvariable=self.p_summary, style="Card.TLabel", justify="left",
                  wraplength=560).pack(anchor="w", pady=(0, 6))
        cols = ("ticker", "shares", "cost", "price", "value", "gain")
        self.p_hold = self.make_tree(left, cols, ("Stock", "Shares", "Paid (avg)", "Price now", "Value",
                                                  "Gain"), (70, 60, 90, 90, 100, 70), height=6)
        trade = ttk.Frame(left)
        trade.pack(fill="x", pady=6)
        self.p_t_ticker, self.p_t_shares = tk.StringVar(), tk.StringVar(value="1")
        ttk.Label(trade, text="Stock:").pack(side="left")
        ttk.Entry(trade, textvariable=self.p_t_ticker, width=8).pack(side="left", padx=2)
        ttk.Label(trade, text="  Shares:").pack(side="left")
        ttk.Entry(trade, textvariable=self.p_t_shares, width=6).pack(side="left", padx=2)
        ttk.Button(trade, text="Buy", command=lambda: self.practice_trade("BUY")).pack(side="left", padx=4)
        ttk.Button(trade, text="Sell", command=lambda: self.practice_trade("SELL")).pack(side="left")
        cols = ("time", "side", "shares", "ticker", "price", "reason", "pnl")
        self.p_trades = self.make_tree(left, cols, ("Time", "Buy/Sell", "Shares", "Stock", "Price",
                                                    "Why", "Profit/loss"), (120, 60, 55, 60, 80, 85, 85))
        self.p_trades.tag_configure("win", foreground=PALETTE["good"])
        self.p_trades.tag_configure("loss", foreground=PALETTE["bad"])

        from matplotlib.figure import Figure
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        self.p_fig = Figure(figsize=(5, 4), dpi=100)
        self.p_ax = self.p_fig.add_subplot(111)
        self.p_canvas = FigureCanvasTkAgg(self.p_fig, master=body)
        self.p_canvas.get_tk_widget().pack(side="left", fill="both", expand=True, padx=(8, 0))
        self.p_tests = []
        self.root.after(1500, self.practice_auto)

    def practice_use_top5(self):
        if self.ranked is None or self.ranked.empty:
            messagebox.showinfo("Stock Tracker", "Run 'Find best buy candidate' on the Pick tab first.")
            return
        self.p_tickers.set(" ".join(self.ranked.index[:5]))

    def practice_day_toggle(self, clicked="day"):
        if clicked == "swing" and self.p_swing.get():
            self.p_day.set(False)
        elif self.p_day.get():
            self.p_swing.set(False)
        day, swing = self.p_day.get(), self.p_swing.get()
        self.p_stop.set("2" if day else "5" if swing else "15")
        self.p_tp.set("")
        if day or swing:
            self.p_follow.set(False)
        self.p_days_entry.configure(state="disabled" if day else "normal")   # a day test ends today
        self.p_follow_cb.configure(state="disabled" if day or swing else "normal")

    def practice_start(self):
        tickers = self.p_tickers.get().replace(",", " ").split()
        try:
            cash, days = float(self.p_cash.get()), int(self.p_days.get())
            stop = float(self.p_stop.get()) / 100
            tp = float(self.p_tp.get()) / 100 if self.p_tp.get().strip() else None
            follow, day, swing = self.p_follow.get(), self.p_day.get(), self.p_swing.get()
            assert (tickers or follow or day or swing) and cash > 0 and days >= 1 and 0 < stop < 1 and (tp is None or tp > 0)
        except (ValueError, AssertionError):
            messagebox.showwarning("Stock Tracker", "Enter stocks (e.g. MSFT KO), cash, days, and the "
                                   "auto-sell % (between 1 and 99).")
            return
        self.run_bg("Starting practice test at live prices...",
                    lambda: (st.start_practice(tickers, cash, days, stop, tp, follow=follow and not (day or swing),
                                               day=day, swing=swing),
                             st.update_practice())[1],
                    self.practice_done)

    def practice_refresh(self, quiet=False):
        if quiet and self.busy:
            return
        self.run_bg("Updating practice prices...", st.update_practice, self.practice_done)

    def practice_auto(self):
        if any(x["status"] == "running" for x in st.load_practice()["tests"]):
            self.practice_refresh(quiet=True)
        self.root.after(5 * 60 * 1000, self.practice_auto)

    def practice_end(self):
        test = self.practice_selected()
        if test and test["status"] == "running" and messagebox.askyesno(
                "Stock Tracker", "End this test now and sell everything at today's prices?"):
            self.run_bg("Ending test...", lambda: st.update_practice(end_now=test["id"]), self.practice_done)

    def practice_trade(self, side):
        test = self.practice_selected()
        if not test:
            return
        t = self.p_t_ticker.get().strip().upper()
        try:
            n = float(self.p_t_shares.get())
        except ValueError:
            n = 0
        self.run_bg(f"{side.title()}ing {t} at the live price...",
                    lambda: (st.practice_trade(test["id"], t, side, n), st.load_practice()["tests"])[1],
                    self.practice_done)

    def practice_selected(self):
        i = self.p_combo.current()
        return self.p_tests[i] if 0 <= i < len(self.p_tests) else None

    def practice_done(self, tests):
        before = {x["id"]: x["status"] for x in self.p_tests}
        keep = self.practice_selected()
        self.p_tests = sorted(tests, key=lambda x: (x["status"] != "running", x["id"]), reverse=False)
        self.p_combo["values"] = [f"{'RUNNING' if x['status'] == 'running' else 'ended'}  {x['name']}  "
                                  f"(started {x['start']})" for x in self.p_tests]
        ids = [x["id"] for x in self.p_tests]
        if self.p_tests:
            self.p_combo.current(ids.index(keep["id"]) if keep and keep["id"] in ids else 0)
        self.practice_show()
        self.update_glance()
        for x in self.p_tests:
            if before.get(x["id"]) == "running" and x["status"] == "ended":
                messagebox.showinfo("Practice test ended", "\n".join(st.practice_lines(x)))

    def practice_show(self):
        test = self.practice_selected()
        if not test:
            return
        self.p_summary.set("\n".join(st.practice_lines(test)))
        prices = test.get("last_prices", {})
        rows = []
        for t, pos in test["positions"].items():
            p = prices.get(t)
            gain = p / pos["cost"] - 1 if p else None
            rows.append(((t, pos["shares"], st.money(pos["cost"]), st.money(p),
                          st.money(p * pos["shares"]) if p else "-", st.pct(gain)),
                         ("win",) if (gain or 0) > 0 else ("loss",) if (gain or 0) < 0 else ()))
        self.fill_tree(self.p_hold, rows)
        self.p_hold.tag_configure("win", foreground=PALETTE["good"])
        self.p_hold.tag_configure("loss", foreground=PALETTE["bad"])
        self.fill_tree(self.p_trades, [
            ((x["time"], x["side"], x["shares"], x["ticker"], st.money(x["price"]), x["reason"],
              st.money(x["pnl"]) if x["pnl"] is not None else ""),
             ("win",) if (x["pnl"] or 0) > 0 else ("loss",) if (x["pnl"] or 0) < 0 else ())
            for x in reversed(test["trades"])])
        ax = self.p_ax
        ax.clear()
        if len(test["history"]) > 1:
            h = st.pd.DataFrame(test["history"], columns=["time", "value", "spy"])
            h["time"] = st.pd.to_datetime(h["time"])
            short = h["time"].iloc[-1] - h["time"].iloc[0] < st.pd.Timedelta(days=1)
            x = range(len(h)) if short else h["time"]      # dates look silly within one day
            ax.plot(x, h["value"], color=PALETTE["accent"], linewidth=2, label="Your test")
            ax.plot(x, h["spy"], color="#6b7280", linewidth=1.2, label=f"Same money in {st.BENCH}")
            ax.legend(fontsize=8)
            ax.set_xlabel("price updates" if short else "")
            if not short:
                self.p_fig.autofmt_xdate()
        else:
            ax.text(0.5, 0.5, "Chart fills in as prices update", ha="center", va="center",
                    transform=ax.transAxes, color="gray")
        ax.set_title("Value over time")
        ax.grid(alpha=0.3)
        self.p_fig.tight_layout()
        self.p_canvas.draw()

    # ----------------------------------------------------- track record tab
    def build_track(self, f):
        self.nb.add(f, text="Track record")
        top = ttk.Frame(f)
        top.pack(fill="x")
        ttk.Button(top, text="Refresh", style="Big.TButton", command=self.do_track).pack(side="left")
        self.track_all = tk.BooleanVar()
        ttk.Checkbutton(top, text="Include runners-up (top 5 of each run)",
                        variable=self.track_all).pack(side="left", padx=8)
        ttk.Label(top, text="Every 'Find best buy candidate' result is saved here automatically.",
                  style="Muted.TLabel").pack(side="left")
        self.track_sum = tk.StringVar(value=(
            "Press Refresh to see how your past picks did compared with SPY, a fund that holds the\n"
            "500 largest US companies. If the picks don't beat SPY over time, the score isn't helping."))
        ttk.Label(f, textvariable=self.track_sum, style="Card.TLabel",
                  justify="left").pack(anchor="w", pady=8)

        cols = ("date", "ticker", "rank", "sofar", "spy", "ahead") + tuple(h for h, _ in st.HORIZONS)
        heads = ("Picked on", "Ticker", "Rank", "Pick so far", "SPY so far", "Ahead by") + tuple(
            f"Ahead after {h}" for h, _ in st.HORIZONS)
        tv = self.track_tv = ttk.Treeview(f, columns=cols, show="headings")
        for c, h in zip(cols, heads):
            tv.heading(c, text=h)
            tv.column(c, width=100, anchor="center")
        tv.tag_configure("good", foreground=PALETTE["good"])
        tv.tag_configure("bad", foreground=PALETTE["bad"])
        tv.pack(fill="both", expand=True)

    def do_track(self):
        top_only = not self.track_all.get()
        self.run_bg("Fetching prices for your past picks...",
                    lambda: st.track_record(top_only), self.track_done)

    def track_done(self, result):
        table, summary = result
        self.track_tv.delete(*self.track_tv.get_children())
        if table.empty:
            self.track_sum.set("No picks saved yet. Use the Pick tab now and then; check back in a "
                               "few weeks.")
            return
        self.track_sum.set("\n".join(st.track_lines(summary, table)))
        for _, r in table.sort_values(["date", "rank"], ascending=[False, True]).iterrows():
            ahead = r["so far"] - r["SPY so far"]
            later = [st.pct(r[h] - r[f"SPY {h}"]) if h in r and st.pd.notna(r[h]) else "-"
                     for h, _ in st.HORIZONS]
            self.track_tv.insert("", "end", tags=("good" if ahead > 0 else "bad" if ahead < 0 else "",),
                                 values=(r["date"], r["ticker"], r["rank"], st.pct(r["so far"]),
                                         st.pct(r["SPY so far"]), st.pct(ahead), *later))

    # --------------------------------------------------------- backtest tab
    def build_backtest(self, f):
        self.nb.add(f, text="Backtest")
        top = ttk.Frame(f)
        top.pack(fill="x")
        ttk.Button(top, text="Run backtest", style="Big.TButton",
                   command=self.do_backtest).pack(side="left")
        ttk.Label(top, text="   Years back:").pack(side="left")
        self.bt_years = tk.StringVar(value="10")
        ttk.Spinbox(top, from_=3, to=15, textvariable=self.bt_years, width=4).pack(side="left")
        ttk.Label(top, text="   Stocks:").pack(side="left")
        self.bt_universe = tk.StringVar(value="S&P 500 as it was")
        ttk.Combobox(top, textvariable=self.bt_universe, state="readonly", width=17,
                     values=["S&P 500 as it was", "Today's list (faster)"]).pack(side="left")
        self.bt_csv_btn = ttk.Button(top, text="Save monthly CSV...", command=self.save_bt_csv,
                                     state="disabled")
        self.bt_csv_btn.pack(side="left", padx=6)
        ttk.Label(top, text="First S&P 500 run downloads ~700 companies' SEC reports (up to an hour); later runs reuse them.",
                  style="Muted.TLabel").pack(side="left")

        body = ttk.Frame(f)
        body.pack(fill="both", expand=True, pady=8)
        self.bt_text = tk.StringVar(value=(
            "Replays 'Find best buy candidate' at the end of\nevery month in the past, using only "
            "facts that\nwere public then, and checks how the pick did\nover the following month.\n\n"
            + st.BACKTEST_CAVEATS))
        ttk.Label(body, textvariable=self.bt_text, style="Card.TLabel", justify="left",
                  anchor="nw", width=82).pack(side="left", fill="y")

        from matplotlib.figure import Figure
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        self.bt_fig = Figure(figsize=(6, 4.5), dpi=100)
        self.bt_ax = self.bt_fig.add_subplot(111)
        self.bt_canvas = FigureCanvasTkAgg(self.bt_fig, master=body)
        self.bt_canvas.get_tk_widget().pack(side="left", fill="both", expand=True)
        self.bt_monthly = None

    def do_backtest(self):
        contact = st.load_state().get("contact")
        if not contact:
            messagebox.showinfo("Stock Tracker", "The backtest reads old company reports from the "
                                "SEC, which asks for a contact email.\nAdd yours in Settings, "
                                "then try again.")
            self.nb.select(self.settings_tab)
            return
        try:
            years = int(self.bt_years.get())
        except ValueError:
            years = 10
        self.run_bg("Starting backtest...",
                    lambda: st.backtest(years=years, contact=contact, progress=self.progress,
                                        universe="sp500" if self.bt_universe.get().startswith("S&P") else "list"),
                    self.backtest_done)

    def backtest_done(self, result):
        m, summary, info = result
        self.bt_monthly = m
        self.bt_text.set("\n".join(st.backtest_lines(summary, info)) + "\n\n" + st.BACKTEST_CAVEATS)
        ax = self.bt_ax
        ax.clear()
        colors = [PALETTE["accent"], "#a855f7", PALETTE["text"], PALETTE["muted"]]
        for (name, s), color in zip(summary.items(), colors):
            ax.plot(m.index, 10000 * (1 + m[s["col"]]).cumprod(), label=name, color=color,
                    linewidth=2 if color == colors[0] else 1.2)
        ax.set_title("Growth of $10,000 (past results, not a forecast)")
        ax.set_ylabel("$")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
        self.bt_fig.tight_layout()
        self.bt_canvas.draw()
        self.bt_csv_btn.configure(state="normal")

    def save_bt_csv(self):
        if self.bt_monthly is None:
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="backtest.csv",
                                            filetypes=[("CSV (opens in Excel)", "*.csv")])
        if path:
            self.bt_monthly.to_csv(path)
            self.status.set(f"Saved {path}")

    # --------------------------------------------------------- settings tab
    def build_settings(self, f):
        self.nb.add(f, text="Settings")
        box = ttk.LabelFrame(f, text="SEC filings", padding=10)
        box.pack(fill="x")
        ttk.Label(box, text="The SEC's free filings service asks for a contact email. It is "
                  "sent only to sec.gov and stored on this computer.\nLeave it blank to skip "
                  "SEC filings.", justify="left").pack(anchor="w")
        row = ttk.Frame(box)
        row.pack(anchor="w", pady=(6, 0))
        ttk.Label(row, text="Contact email:").pack(side="left")
        self.contact = tk.StringVar(value=st.load_state().get("contact") or "")
        ttk.Entry(row, textvariable=self.contact, width=36).pack(side="left", padx=4)
        ttk.Button(row, text="Save", command=self.save_contact).pack(side="left")

        box = ttk.LabelFrame(f, text="This computer", padding=10)
        box.pack(fill="x", pady=10)
        ttk.Button(box, text="Create desktop shortcut",
                   command=self.make_shortcut).pack(side="left")
        ttk.Button(box, text="Open data & reports folder",
                   command=self.open_data).pack(side="left", padx=6)

        box = ttk.LabelFrame(f, text="Look", padding=10)
        box.pack(fill="x", pady=(0, 10))
        prefs = st.load_state().get("prefs") or {}
        self.pref_vars = {}
        for key, label, choices, default in (("theme", "Colours", list(THEMES), "Light"),
                                             ("accent", "Accent", list(ACCENTS), "Blue"),
                                             ("size", "Text size", list(TEXT_SIZES), "Normal")):
            ttk.Label(box, text=f"{label}:").pack(side="left")
            var = self.pref_vars[key] = tk.StringVar(value=prefs.get(key, default))
            ttk.Combobox(box, textvariable=var, values=choices, state="readonly",
                         width=12).pack(side="left", padx=(4, 14))
        ttk.Button(box, text="Apply (restarts the app)", command=self.apply_prefs).pack(side="left")

        box = ttk.LabelFrame(f, text="Automatic daily run", padding=10)
        box.pack(fill="x")
        ttk.Label(box, wraplength=900, justify="left", text=(
            "Every weekday at the time below (while you're logged in), Windows runs the tracker "
            "in the background: it saves that day's pick to your journal (so the Track record "
            "grows), checks your watchlist, and updates practice tests. Nothing is bought or "
            "sold for real. Log: daily.log in the data folder.")).pack(anchor="w")
        row = ttk.Frame(box)
        row.pack(anchor="w", pady=(6, 0))
        ttk.Label(row, text="Time (24h):").pack(side="left")
        self.daily_time = tk.StringVar(value="17:30")
        ttk.Entry(row, textvariable=self.daily_time, width=6).pack(side="left", padx=4)
        ttk.Button(row, text="Turn on", command=lambda: self.set_daily(True)).pack(side="left")
        ttk.Button(row, text="Turn off", command=lambda: self.set_daily(False)).pack(side="left", padx=6)
        self.daily_state = tk.StringVar(value="Status: " + ("ON" if daily_task_exists() else "off"))
        ttk.Label(row, textvariable=self.daily_state, style="Bold.TLabel").pack(side="left", padx=8)

        ttk.Label(f, justify="left", style="Muted.TLabel", text=(
            "About this tool\n\n"
            "- Buy-only: it suggests stocks to research buying, and when to consider selling\n"
            "  shares you already own. No shorting, margin or options, so the most you can\n"
            "  lose is what you put in.\n"
            "- It ranks stocks on measurable facts. It cannot predict prices.\n"
            "- Not financial advice. Do your own research before investing."
        )).pack(anchor="w", pady=10)

    def save_contact(self):
        email = self.contact.get().strip()
        if email and "@" not in email:
            messagebox.showwarning("Stock Tracker", "That doesn't look like an email address.")
            return
        with st.STATE_LOCK:
            s = st.load_state()
            s["contact"] = email or None
            st.save_state(s)
        self.status.set("Saved." if email else "Cleared. SEC filings will be skipped.")

    def make_shortcut(self):
        try:
            p = create_shortcut()
        except Exception as e:
            log_error(traceback.format_exc())
            messagebox.showerror("Stock Tracker", f"Couldn't create the shortcut:\n{e}")
            return
        messagebox.showinfo("Stock Tracker", f"Shortcut created:\n{p}")

    def apply_prefs(self):
        with st.STATE_LOCK:
            s = st.load_state()
            s["prefs"] = {k: v.get() for k, v in self.pref_vars.items()}
            st.save_state(s)
        if self.busy and not messagebox.askyesno("Stock Tracker", "Something is still loading. "
                                                 "Restart anyway?"):
            return
        subprocess.Popen([str(pythonw()), str(APP_DIR / "StockTracker.pyw")], cwd=str(APP_DIR))
        self.root.destroy()

    def set_daily(self, on):
        try:
            set_daily_task(on, self.daily_time.get().strip())
        except Exception as e:
            messagebox.showerror("Stock Tracker", f"Couldn't change the daily run:\n{e}")
            return
        self.daily_state.set("Status: " + ("ON" if daily_task_exists() else "off"))

    def open_data(self):
        st.HOME.mkdir(parents=True, exist_ok=True)
        os.startfile(st.HOME)

    def offer_shortcut(self):
        s = st.load_state()
        if s.get("shortcut_offered") or sys.platform != "win32":
            return
        s["shortcut_offered"] = True
        st.save_state(s)
        if desktop_shortcut_path().exists():
            return
        if messagebox.askyesno("Stock Tracker", "Put a Stock Tracker shortcut on your desktop?\n"
                               "(You can also do this later in Settings.)"):
            self.make_shortcut()


def main():
    global st
    sys.excepthook = show_error
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)    # crisp text on scaled screens
        except Exception:
            pass
    if "--shortcut" in sys.argv:
        print(create_shortcut())
        return
    if not ensure_packages():
        return
    sys.path.insert(0, str(APP_DIR))
    import stock_tracker as st
    root = tk.Tk()
    root.report_callback_exception = show_error
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
