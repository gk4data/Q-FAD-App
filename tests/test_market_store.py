from unittest.mock import Mock, patch

import pandas as pd

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
