# Local backtest storage

The app creates `data/market_data.sqlite3` automatically. Set `QFAD_DATABASE_PATH`
to an absolute path to use a different location (for example a persistent disk
on a deployed server). No database service or additional Python dependency is needed.
Database files and their SQLite sidecars are ignored by Git.

Completed single-day historical downloads are cached by instrument, expiry,
interval and trading date. This includes option candles, previous-day warmup
candles and the NIFTY data fetched to choose strikes. Current-day data is always
fetched again, and empty or failed API responses are not cached. Downloads that
return candles are recorded atomically with their source and fetch timestamp;
this records a successful API response, not a guarantee that the provider has
supplied every market minute. Raw OHLCV and OI (when supplied) are stored;
indicators and signals are recalculated each run. Historical contract mappings
retain underlying, strike, side, exchange and expiry separately from candles.

Historical runs are automatically labelled with their start timestamp in IST.
Selected-instrument runs use the Backtest label field in the sidebar. Each run
saves its metrics, settings, timestamp, label and a fingerprint of the strategy,
indicator and data preparation source files. Historical runs save the daily
CE/PE table and its existing TOTAL row; selected-instrument runs save trades.
The Saved Backtests tab displays all saved runs and lets you inspect their
details without downloading candles or recomputing signals. Select a run at the
top to see the same return summary cards and colour-coded results as Historical
Backtest. Export Excel saves the selected run's results and summary in separate
sheets; expand Compare saved runs for a compact comparison of core metrics.
Refresh preserves the selected run and picks up
runs saved in other sessions. Changing strategy code creates a new fingerprint;
each run remains a separate record even if the strategy is unchanged.

The 10 most recently saved runs are retained across historical and selected-
instrument backtests combined, ordered by save order rather than trading date.
Saving a new run deletes older run records (including summaries and detailed
results) in the same transaction. Startup also applies this limit to existing
history. Export Excel before a run falls outside the latest 10 if you need to
keep it. Cached candles and contract metadata are not deleted by this policy.
Retained runs survive app restarts; deleting or replacing the database removes
access to its saved history. Git does not contain a copy.

Historical TOTAL returns preserve the app's existing average daily/side return
calculation, not a compounded portfolio return. Missing contracts, missing data
and calculation failures are identified in daily rows and an Incomplete Rows
count is saved with the run. The app still requires authentication to execute
historical backtests, although saved-results inspection needs no API requests.

The first historical run downloads data; only subsequent requests for the same
cached days avoid candle API calls. Existing results from before this feature
cannot be recovered automatically. Back up the database using SQLite's backup
API, or copy it while the app is stopped. Store it on persistent storage when
deploying; Git does not back it up. To refetch corrected provider data, stop the
app and delete the relevant candle_days and candles records using a SQLite
client. Keep the database if you want to preserve backtest history.
