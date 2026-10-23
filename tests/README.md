# Offline test harness

`fake_run.py` swaps Yahoo Finance and the SEC API for random fake data, so every
command can be exercised without internet access (useful in sandboxes that
block those sites). The numbers it prints are made up.

```
python tests/fake_run.py pick --add
python tests/fake_run.py history MSFT
python tests/fake_run.py setup --contact test@example.com
python tests/fake_run.py add MSFT --bought 500
python tests/fake_run.py watch
```

Set `HOME` (or `USERPROFILE` on Windows) to a scratch folder first so the test
doesn't touch your real watchlist in `~/.stock_tracker`.
