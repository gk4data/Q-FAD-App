from unittest.mock import Mock, patch
from contextlib import closing
import sqlite3

import pandas as pd
import pytest

from src.data.market_store import MarketStore, strategy_fingerprint
from src.data.data_fetcher import fetch_intraday_data


def candles():
    return pd.DataFrame({"Date": pd.date_range("2026-01-05 09:15", periods=2, freq="min", tz="Asia/Kolkata"),
                         "Open": [10., 11.], "High": [12., 13.], "Low": [9., 10.],
                         "Close": [11., 12.], "Volume": [100., 200.], "OI": [20., 30.]})


def test_candles_roundtrip_and_expiry_isolation(tmp_path):
    store = MarketStore(tmp_path / "market.sqlite3")
    df = candles()
    store.save_day("NSE_FO|1", "2026-01-06", "1minute", "2026-01-05", df, "expired")
    store.save_day("NSE_FO|1", "2026-01-06", "1minute", "2026-01-05", df, "expired")
    actual = store.load_day("NSE_FO|1", "2026-01-06", "1minute", "2026-01-05")
    pd.testing.assert_frame_equal(actual, df)
    assert store.load_day("NSE_FO|1", "2026-01-13", "1minute", "2026-01-05") is None
    assert store.load_day("NSE_FO|1", "2026-01-06", "day", "2026-01-05") is None


def test_empty_response_not_cached(tmp_path):
    store = MarketStore(tmp_path / "market.sqlite3")
    store.save_day("index", None, "1minute", "2026-01-05", pd.DataFrame(), "date_range")
    assert store.load_day("index", None, "1minute", "2026-01-05") is None


def test_saved_runs_survive_restart_and_preserve_versions(tmp_path):
    path = tmp_path / "market.sqlite3"
    store = MarketStore(path)
    for version in ("v1", "v2"):
        store.save_run("Historical", version, {"From": "2026-01-05", "Initial Capital": 100000},
                       {"Return (%)": 4.2, "Profit Factor": float("inf")},
                       [{"Date": "2026-01-05", "Return (%)": 4.2}], strategy=version)
    reopened = MarketStore(path)
    runs = reopened.list_runs()
    assert runs["Strategy"].tolist() == ["v2", "v1"]
    assert reopened.load_results(1).iloc[0]["Return (%)"] == 4.2
    assert runs.iloc[0]["Profit Factor"] == "inf"
    assert len(strategy_fingerprint()) == 16


def test_fetch_uses_disk_on_second_call(tmp_path, monkeypatch):
    monkeypatch.setenv("QFAD_DATABASE_PATH", str(tmp_path / "market.sqlite3"))
    response = Mock()
    response.json.return_value = {"data": {"candles": [["2026-01-05T09:15:00+05:30", 10, 12, 9, 11, 100, 20]]}}
    with patch("src.data.data_fetcher.requests.get", return_value=response) as request:
        kwargs = dict(interval="1minute", mode="expired", start="2026-01-05", end="2026-01-05", expiry_for_expired="2026-01-06")
        first = fetch_intraday_data("NSE_FO|1", "test-token", **kwargs)
        second = fetch_intraday_data("NSE_FO|1", "test-token", **kwargs)
        assert request.call_count == 1
        pd.testing.assert_frame_equal(first, second, check_dtype=False)


def test_today_always_refreshes(tmp_path, monkeypatch):
    monkeypatch.setenv("QFAD_DATABASE_PATH", str(tmp_path / "market.sqlite3"))
    today = pd.Timestamp.now(tz="Asia/Kolkata").strftime("%Y-%m-%d")
    response = Mock()
    response.json.return_value = {"data": {"candles": [[f"{today}T09:15:00+05:30", 10, 12, 9, 11, 100]]}}
    with patch("src.data.data_fetcher.requests.get", return_value=response) as request:
        for _ in range(2):
            fetch_intraday_data("index", "test-token", start=today, end=today)
        assert request.call_count == 2


def test_contract_metadata_roundtrip(tmp_path):
    store = MarketStore(tmp_path / "market.sqlite3")
    store.save_contract("NIFTY", "2026-01-05", 25000, "CE", "NSE", "NSE_FO|1", "2026-01-06", "expired_contract_api")
    assert store.load_contract("NIFTY", "2026-01-05", 25000, "CE", "NSE") == ("NSE_FO|1", "2026-01-06", "expired_contract_api")
    assert store.load_contract("NIFTY", "2026-01-05", 25000, "PE", "NSE") is None


def test_retention_keeps_latest_ten_runs_and_market_data(tmp_path):
    store = MarketStore(tmp_path / "market.sqlite3")
    store.save_day("NSE_FO|1", "2026-01-06", "1minute", "2026-01-05", candles(), "expired")
    store.save_contract("NIFTY", "2026-01-05", 25000, "CE", "NSE", "NSE_FO|1", "2026-01-06", "expired_contract_api")
    for index in range(12):
        kind = "Historical" if index % 2 else "Selected instrument"
        store.save_run(kind, f"run-{index}", {}, {"Return (%)": index},
                       [{"Return (%)": index}], strategy="v1")
    reopened = MarketStore(store.path)
    assert reopened.list_runs()["Run ID"].tolist() == list(range(12, 2, -1))
    assert reopened.load_results(1).empty and reopened.load_results(2).empty
    assert reopened.load_results(3).iloc[0]["Return (%)"] == 2
    pd.testing.assert_frame_equal(reopened.load_day("NSE_FO|1", "2026-01-06", "1minute", "2026-01-05"), candles())
    assert reopened.load_contract("NIFTY", "2026-01-05", 25000, "CE", "NSE") is not None


def test_prune_existing_history_is_idempotent(tmp_path):
    store = MarketStore(tmp_path / "market.sqlite3")
    with closing(store.connect()) as conn, conn:
        # Model history created before the retention policy was introduced.
        conn.executemany(
            "INSERT INTO backtest_runs (created_at,kind,label,strategy,context,summary,results) VALUES (?,?,?,?,?,?,?)",
            [("2026-01-01T00:00:00+00:00", "Historical", str(i), "v1", "{}", "{}", "[]") for i in range(15)],
        )
    assert store.prune_runs() == 5
    assert store.prune_runs() == 0
    assert store.list_runs()["Run ID"].tolist() == list(range(15, 5, -1))


def test_failed_retention_rolls_back_new_run(tmp_path):
    store = MarketStore(tmp_path / "market.sqlite3")
    for index in range(10):
        store.save_run("Historical", str(index), {}, {}, [], strategy="v1")
    with closing(store.connect()) as conn, conn:
        conn.execute("CREATE TRIGGER reject_delete BEFORE DELETE ON backtest_runs BEGIN SELECT RAISE(ABORT, 'test retention failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="test retention failure"):
        store.save_run("Historical", "new run", {}, {}, [], strategy="v1")
    assert store.list_runs()["Run ID"].tolist() == list(range(10, 0, -1))
