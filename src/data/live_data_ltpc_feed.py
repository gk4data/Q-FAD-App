import asyncio
import json
import logging
import os
import ssl
import threading
from datetime import datetime

import pandas as pd
import requests
from google.protobuf.json_format import MessageToDict

from .MarketDataFeedV3_pb2 import FeedResponse
from .data_fetcher import (
    concatenate_with_previous_day,
    fetch_intraday_data,
)

logger = logging.getLogger(__name__)


class LTPCDataRecorder:
    """Build 1-minute OHLCV candles locally from LTPC websocket ticks."""

    def __init__(self):
        self._thread = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._running = False
        self._last_error = None
        self._last_save_path = None
        self._last_save_time = None
        self._live_save_counter = 0
        self._instrument_key = None

    def start(self, access_token, instrument_key, output_dir, mode="ltpc", save_interval=60):
        if not access_token:
            return False, "Missing access token"
        if not instrument_key:
            return False, "Missing instrument key"
        with self._lock:
            if self._running:
                return False, "LTPC live data already running"
            self._stop_event.clear()
            self._last_error = None
            self._last_save_path = None
            self._last_save_time = None
            self._live_save_counter = 0
            self._instrument_key = instrument_key
            self._running = True

        thread = threading.Thread(
            target=self._run,
            args=(access_token, instrument_key, output_dir, mode, save_interval),
            daemon=True,
        )
        self._thread = thread
        thread.start()
        return True, "LTPC live data started"

    def stop(self, timeout=5):
        with self._lock:
            if not self._running:
                return False, "LTPC live data is not running"
            self._stop_event.set()

        if self._thread:
            self._thread.join(timeout=timeout)

        with self._lock:
            self._running = False
        return True, "LTPC live data stopped"

    def status(self):
        with self._lock:
            running = self._running
            error = self._last_error
            last_save = self._last_save_time
            last_path = self._last_save_path
            instrument = self._instrument_key

        if error:
            return f"[ERROR] LTPC live data: {error}"
        if not running:
            return "[INFO] LTPC live data idle"
        last_save_str = last_save.strftime("%Y-%m-%d %H:%M:%S") if last_save else "--"
        path_str = last_path or "--"
        return f"[OK] LTPC live data running | {instrument} | last save: {last_save_str} | {path_str}"

    def live_save_snapshot(self):
        with self._lock:
            return {
                "counter": self._live_save_counter,
                "last_save_time": self._last_save_time,
                "last_save_path": self._last_save_path,
                "running": self._running,
                "error": self._last_error,
            }

    def _run(self, access_token, instrument_key, output_dir, mode, save_interval):
        try:
            asyncio.run(
                self._async_loop(access_token, instrument_key, output_dir, mode, save_interval)
            )
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
                self._running = False
            logger.exception("LTPC live data thread error: %s", exc)

    async def _async_loop(self, access_token, instrument_key, output_dir, mode, save_interval):
        import websockets

        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        output_path = self._build_output_path(output_dir, instrument_key)
        ohlc_df, minute_state = self._backfill_from_rest(access_token, instrument_key, output_path)

        while not self._stop_event.is_set():
            try:
                auth_response = self._authorize(access_token)
                logger.info("LTPC authorization response: %s", auth_response)
                ws_url = auth_response.get("data", {}).get("authorized_redirect_uri")
                if not ws_url:
                    raise RuntimeError("WebSocket URL not found in authorization response")

                async with websockets.connect(ws_url, ssl=ssl_context) as websocket:
                    logger.info("LTPC websocket connected")
                    await asyncio.sleep(0.5)
                    payload = {
                        "guid": "qfad-ltpc",
                        "method": "sub",
                        "data": {"mode": mode, "instrumentKeys": [instrument_key]},
                    }
                    await websocket.send(json.dumps(payload).encode("utf-8"))
                    logger.info("LTPC live data subscribed: %s", instrument_key)
                    while not self._stop_event.is_set():
                        try:
                            message = await asyncio.wait_for(websocket.recv(), timeout=1)
                        except asyncio.TimeoutError:
                            continue

                        decoded = FeedResponse()
                        decoded.ParseFromString(message)
                        data_dict = MessageToDict(decoded, preserving_proto_field_name=True)
                        feeds = data_dict.get("feeds", {})
                        current_ts = data_dict.get("currentTs")

                        for symbol, details in feeds.items():
                            ltpc = details.get("ltpc")
                            if not ltpc:
                                continue

                            timestamp = self._parse_timestamp(ltpc.get("ltt") or current_ts).replace(
                                second=0, microsecond=0
                            )
                            ltp = float(ltpc.get("ltp", 0) or 0)
                            ltq = int(float(ltpc.get("ltq", 0) or 0))
                            cp = float(ltpc.get("cp", 0) or 0)

                            state = minute_state.get(symbol)
                            if state is None:
                                minute_state[symbol] = self._new_minute_state(
                                    timestamp, ltp, ltq, cp
                                )
                            elif timestamp == state["timestamp"]:
                                state["high"] = max(state["high"], ltp)
                                state["low"] = min(state["low"], ltp)
                                state["close"] = ltp
                                state["volume"] += ltq
                                state["cp"] = cp
                            elif timestamp > state["timestamp"]:
                                ohlc_df = self._finalize_minute(
                                    ohlc_df, output_path, symbol, state
                                )
                                minute_state[symbol] = self._new_minute_state(
                                    timestamp, ltp, ltq, cp
                                )
                            else:
                                logger.debug(
                                    "Ignoring out-of-order LTPC tick for %s at %s",
                                    symbol,
                                    timestamp,
                                )
                                continue

                            logger.info(
                                "LTPC tick %s ts=%s LTP=%s LTQ=%s CP=%s",
                                symbol,
                                timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                                ltp,
                                ltq,
                                cp,
                            )

            except Exception as exc:
                logger.warning("LTPC websocket error: %s", exc)
                with self._lock:
                    self._last_error = str(exc)
                continue

        for symbol, state in list(minute_state.items()):
            if state and state.get("close") is not None:
                ohlc_df = self._finalize_minute(ohlc_df, output_path, symbol, state)

        with self._lock:
            self._running = False

    def _new_minute_state(self, timestamp, ltp, ltq, cp):
        return {
            "timestamp": timestamp,
            "open": ltp,
            "high": ltp,
            "low": ltp,
            "close": ltp,
            "volume": ltq,
            "cp": cp,
        }

    def _finalize_minute(self, ohlc_df, output_path, symbol, state):
        row = {
            "timestamp": state["timestamp"],
            "symbol": symbol,
            "open": state["open"],
            "high": state["high"],
            "low": state["low"],
            "close": state["close"],
            "volume": state["volume"],
        }
        if ohlc_df.empty:
            ohlc_df = pd.DataFrame([row])
        else:
            mask = (ohlc_df["timestamp"] == row["timestamp"]) & (ohlc_df["symbol"] == row["symbol"])
            if mask.any():
                ohlc_df.loc[mask, ["open", "high", "low", "close", "volume"]] = [
                    row["open"],
                    row["high"],
                    row["low"],
                    row["close"],
                    row["volume"],
                ]
            else:
                ohlc_df.loc[len(ohlc_df)] = row

        ohlc_df = ohlc_df.sort_values(["timestamp", "symbol"]).reset_index(drop=True)
        ohlc_df.to_csv(output_path, index=False)

        with self._lock:
            self._last_save_path = output_path
            self._last_save_time = datetime.now()
            self._live_save_counter += 1

        logger.info(
            "LTPC candle saved: %s %s O=%s H=%s L=%s C=%s V=%s",
            symbol,
            state["timestamp"].strftime("%Y-%m-%d %H:%M:%S"),
            state["open"],
            state["high"],
            state["low"],
            state["close"],
            state["volume"],
        )
        return ohlc_df

    def _authorize(self, access_token):
        headers = {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}
        url = "https://api.upstox.com/v3/feed/market-data-feed/authorize"
        response = requests.get(url=url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()

    def _build_output_path(self, output_dir, instrument_key):
        base_dir = output_dir or os.path.join(os.getcwd(), "live_data")
        os.makedirs(base_dir, exist_ok=True)
        return os.path.join(base_dir, "live_data_ltpc.csv")

    def _backfill_from_rest(self, access_token, instrument_key, output_path):
        """Seed LTPC candle CSV using REST data and warm current minute state."""
        empty_df = pd.DataFrame(
            columns=["timestamp", "symbol", "open", "high", "low", "close", "volume"]
        )
        minute_state = {}
        try:
            open(output_path, "w").close()
            interval = "1minute"
            raw_df = fetch_intraday_data(
                instrument_key, access_token, interval=interval, mode="intraday"
            )
            if raw_df is None or raw_df.empty:
                logger.info("LTPC backfill: no intraday data returned")
                return empty_df, minute_state

            target_date_str = datetime.now().strftime("%Y-%m-%d")
            raw_df = concatenate_with_previous_day(
                raw_df,
                instrument_key,
                access_token,
                target_date_str,
                interval=interval,
                mode="date_range",
            )
            if raw_df.empty:
                logger.info("LTPC backfill: no rows after previous-day concatenation")
                return empty_df, minute_state

            ts = pd.to_datetime(raw_df["Date"], errors="coerce")
            if getattr(ts.dt, "tz", None) is not None:
                ts = ts.dt.tz_localize(None)
            backfill_df = pd.DataFrame(
                {
                    "timestamp": ts,
                    "symbol": instrument_key,
                    "open": raw_df["Open"],
                    "high": raw_df["High"],
                    "low": raw_df["Low"],
                    "close": raw_df["Close"],
                    "volume": raw_df["Volume"],
                }
            ).dropna(subset=["timestamp"])
            backfill_df = backfill_df.sort_values(["timestamp", "symbol"]).reset_index(drop=True)
            backfill_df.to_csv(output_path, index=False)

            if not backfill_df.empty:
                last_row = backfill_df.iloc[-1]
                minute_state[instrument_key] = {
                    "timestamp": pd.to_datetime(last_row["timestamp"]).to_pydatetime(),
                    "open": float(last_row["open"]),
                    "high": float(last_row["high"]),
                    "low": float(last_row["low"]),
                    "close": float(last_row["close"]),
                    "volume": int(float(last_row["volume"])),
                    "cp": float(last_row["close"]),
                }

            with self._lock:
                self._last_save_path = output_path
                self._last_save_time = datetime.now()
                self._live_save_counter += 1
            logger.info(
                "LTPC backfill saved: rows=%s last=%s path=%s",
                len(backfill_df),
                (
                    pd.to_datetime(backfill_df["timestamp"]).max().strftime("%Y-%m-%d %H:%M:%S")
                    if not backfill_df.empty
                    else "--"
                ),
                output_path,
            )
            return backfill_df, minute_state
        except Exception as exc:
            logger.warning("LTPC backfill error: %s", exc)
            return empty_df, minute_state

    def _parse_timestamp(self, ts_value):
        if ts_value is None:
            return datetime.now().replace(second=0, microsecond=0)
        try:
            ts_int = int(ts_value)
        except Exception:
            return datetime.now().replace(second=0, microsecond=0)
        if ts_int > 1_000_000_000_000:
            return datetime.fromtimestamp(ts_int / 1000)
        return datetime.fromtimestamp(ts_int)
