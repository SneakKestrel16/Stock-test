# Tasks

## Done in the overnight run (2026-10-22/23)

- Hindsight-free backtest (`--universe sp500`, default in the Backtest tab).
  Results in README and IDEAS.md.
- Stock tab / `lookup`: numbers, S&P 500 same-period returns, chart, Yahoo +
  web news, SEC filings, checklist.
- Web headlines in the Pick checklist window.
- Settings > Look: light/dark, accent colour, text size.
- Other-apps comparison (IDEAS.md), with short interest, insider ownership,
  payout ratio and a one-year-held note built.
- Tests: `tests/regression.py`, offline smoke of every command (fake_run,
  now including fake Wikipedia), GUI tour light/dark, real-data `lookup KO`.

## Open

- User to clean up: an early GUI test run wrote fake data into the real
  `~/.stock_tracker` before fake_run was isolated: a watchlist entry
  `MSFT` with `"added": "x"` and `"bought": 500`, a `prefs` block (Dark/Green),
  and 3 fake rows dated 2026-10-22 23:58 in `picks.csv` (NKE, GOOGL, CAT).
  Copies of both files are in `~/.stock_tracker/backup-tour/`.
- Idea: grade a looked-up stock against the list (Seeking Alpha-style).
- Idea: peers table on the Stock tab (Stock Rover-style).
