"""Open the desktop app with fake_run's offline data. Numbers are made up.
Runs in a throwaway data folder, so your real watchlist and journal are untouched."""
import runpy
from pathlib import Path

import fake_run  # noqa: F401  (patches yfinance and requests on import)

runpy.run_path(str(Path(__file__).resolve().parents[1] / "StockTracker.pyw"), run_name="__main__")
