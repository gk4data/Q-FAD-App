import asyncio
import json
import logging
import os
import ssl
import threading
from datetime import datetime, timedelta

import pandas as pd
import requests
from google.protobuf.json_format import MessageToDict

from .MarketDataFeedV3_pb2 import FeedResponse

logger = logging.getLogger(__name__)


class LiveDataRecorder:
    def __init__(self):
        self._thread = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._running = False
        self._last_error = None
        self._last_save_path = None
        self._last_save_time = None
        self._instrument_key = None

    def start(self, access_token, instrument_key, output_dir, mode="full", save_interval=60):
        if not access_token:
            return False, "Missing access token"
        if not instrument_key:
            return False, "Missing instrument key"
        with self._lock:
            if self._running:
                return False, "Live data already running"
            self._stop_event.clear()
            self._last_error = None
            self._last_save_path = None
            self._last_save_time = None
            self._instrument_key = instrument_key
            self._running = True

        thread = threading.Thread(
            target=self._run,
            args=(access_token, instrument_key, output_dir, mode, save_interval),
            daemon=True,
        )
        self._thread = thread
        thread.start()
        return True, "Live data started"

    def stop(self, timeout=5):
        with self._lock:
            if not self._running:
                return False, "Live data is not running"
            self._stop_event.set()

        if self._thread:
            self._thread.join(timeout=timeout)

        with self._lock:
            self._running = False
        return True, "Live data stopped"

    def status(self):
        with self._lock:
            running = self._running
            error = self._last_error
            last_save = self._last_save_time
            last_path = self._last_save_path
            instrument = self._instrument_key

        if error:
            return f"[ERROR] Live data: {error}"
        if not running:
            return "[INFO] Live data idle"
        last_save_str = last_save.strftime("%Y-%m-%d %H:%M:%S") if last_save else "--"
        path_str = last_path or "--"
        return f"[OK] Live data running | {instrument} | last save: {last_save_str} | {path_str}"

    def _run(self, access_token, instrument_key, output_dir, mode, save_interval):
        try:
            asyncio.run(
                self._async_loop(access_token, instrument_key, output_dir, mode, save_interval)
            )
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
                self._running = False
            logger.exception("Live data thread error: %s", exc)

    async def _async_loop(self, access_token, instrument_key, output_dir, mode, save_interval):
        import websockets

        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE


        ohlc_df = pd.DataFrame(
            columns=["timestamp", "symbol", "open", "high", "low", "close", "volume"]
        )
        output_path = self._build_output_path(output_dir, instrument_key)
        last_exchange_minute = None

        while not self._stop_event.is_set():
            try:
                auth_response = self._authorize(access_token)
                logger.info("Authorization response: %s", auth_response)
                ws_url = auth_response.get("data", {}).get("authorized_redirect_uri")
                if not ws_url:
                    raise RuntimeError("WebSocket URL not found in authorization response")

                async with websockets.connect(ws_url, ssl=ssl_context) as websocket:
                    logger.info("Live data websocket connected")
                    await asyncio.sleep(0.5)
                    payload = {
                        "guid": "qfad-live",
                        "method": "sub",
                        "data": {"mode": mode, "instrumentKeys": [instrument_key]},
                    }
                    await websocket.send(json.dumps(payload).encode("utf-8"))
                    logger.info("Live data subscribed: %s", instrument_key)
                    while not self._stop_event.is_set():
                        try:
                            message = await asyncio.wait_for(websocket.recv(), timeout=1)
                        except asyncio.TimeoutError:
                            continue

                        decoded = FeedResponse()
                        decoded.ParseFromString(message)
                        data_dict = MessageToDict(decoded, preserving_proto_field_name=True)
                        feeds = data_dict.get("feeds", {})

                        for symbol, details in feeds.items():
                            ohlc_data = (
                                details.get("fullFeed", {})
                                .get("marketFF", {})
                                .get("marketOHLC", {})
                                .get("ohlc", [])
                            )
                            for candle in ohlc_data:
                                if candle.get("interval") != "I1":
                                    continue
                                ts_value = candle.get("ts")
                                timestamp = self._parse_timestamp(ts_value).replace(
                                    second=0, microsecond=0
                                )

                                mask = (ohlc_df["timestamp"] == timestamp) & (
                                    ohlc_df["symbol"] == symbol
                                )
                                if not ohlc_df[mask].empty:
                                    ohlc_df.loc[
                                        mask, ["open", "high", "low", "close", "volume"]
                                    ] = [
                                        candle.get("open"),
                                        candle.get("high"),
                                        candle.get("low"),
                                        candle.get("close"),
                                        candle.get("vol", 0),
                                    ]
                                else:
                                    new_row = {
                                        "timestamp": timestamp,
                                        "symbol": symbol,
                                        "open": candle.get("open"),
                                        "high": candle.get("high"),
                                        "low": candle.get("low"),
                                        "close": candle.get("close"),
                                        "volume": candle.get("vol", 0),
                                    }
                                    ohlc_df.loc[len(ohlc_df)] = new_row

                            if ohlc_data:
                                last_candle = ohlc_data[-1]
                                readable_ts = self._parse_timestamp(last_candle.get("ts"))
                                current_minute = readable_ts.replace(second=0, microsecond=0)
                                logger.info(
                                    "Live tick %s %s ts=%s ts_hr=%s O=%s H=%s L=%s C=%s V=%s",
                                    symbol,
                                    last_candle.get("interval"),
                                    last_candle.get("ts"),
                                    readable_ts.strftime("%Y-%m-%d %H:%M:%S"),
                                    last_candle.get("open"),
                                    last_candle.get("high"),
                                    last_candle.get("low"),
                                    last_candle.get("close"),
                                    last_candle.get("vol", 0),
                                )
                                if last_exchange_minute is None:
                                    last_exchange_minute = current_minute
                                elif current_minute != last_exchange_minute:
                                    last_exchange_minute = current_minute
                                    save_df = ohlc_df[ohlc_df["timestamp"] < current_minute]
                                    if not save_df.empty:
                                        save_df = save_df.drop_duplicates(
                                            subset=["timestamp", "symbol"], keep="last"
                                        ).sort_values(by="timestamp")
                                        save_df.to_csv(output_path, index=False)
                                        with self._lock:
                                            self._last_save_path = output_path
                                            self._last_save_time = datetime.now()
                                        logger.info(
                                            "Live data saved: %s rows to %s",
                                            len(save_df),
                                            output_path,
                                        )

            except Exception as exc:
                logger.warning("Live data websocket error: %s", exc)
                with self._lock:
                    self._last_error = str(exc)
                continue

        with self._lock:
            self._running = False

    def _authorize(self, access_token):
        headers = {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}
        url = "https://api.upstox.com/v3/feed/market-data-feed/authorize"
        response = requests.get(url=url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()

    def _build_output_path(self, output_dir, instrument_key):
        safe_key = instrument_key.replace("|", "_").replace("/", "_")
        base_dir = output_dir or os.path.join(os.getcwd(), "live_data")
        os.makedirs(base_dir, exist_ok=True)
        date_str = datetime.now().strftime("%Y%m%d")
        return os.path.join(base_dir, f"live_data_{safe_key}_{date_str}.csv")

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
