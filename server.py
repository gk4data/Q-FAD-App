# server.py - Server logic for Q-FAD Trading App
import os
import logging
import traceback
import pandas as pd
import numpy as np
from datetime import date as _date, datetime as _dt

from shiny import render, reactive, ui
from shinywidgets import render_plotly
import plotly.graph_objects as go

logger = logging.getLogger(__name__)

# Project imports
from src.clients.upstox_client import UpstoxClient
from src.clients.upstox_sandbox_client import UpstoxSandboxClient
from src.data.data_fetcher import (
    fetch_intraday_data,
    concatenate_with_previous_day,
    filter_to_current_day,
)
from src.data.instrument_manager import InstrumentManager
from src.indicators.indicators import calculate_indicators
from src.signals.regime_detection import detect_regimes_relaxed
from src.signals.angle_classification import classify_trend_by_angles
from src.signals.generator import add_long_signal
from src.data.save_results import save_to_csv
from src.viz.plot_signals import plot_signals
from src.backtest.backtest_engine import calculate_manual_pnl, get_summary_stats_manual
from ui import create_auth_ui, create_main_ui

# Utility function to get next Tuesday
def get_next_tuesday():
    """Get the next Tuesday date (or today if today is Tuesday)."""
    from datetime import timedelta
    today = _date.today()
    # Tuesday is weekday 1 (0=Monday)
    days_until_tuesday = (1 - today.weekday()) % 7
    if days_until_tuesday == 0:
        days_until_tuesday = 0 if today.weekday() == 1 else 7
    return today + timedelta(days=days_until_tuesday)


def define_server(input, output, session):
    """Define the server logic for Q-FAD Trading App."""
    
    client = UpstoxClient(use_cache=True)
    instrument_manager = InstrumentManager()
    sandbox_client = UpstoxSandboxClient()

    # ===== Reactive State =====
    token = reactive.Value(None)
    df_data = reactive.Value(pd.DataFrame())
    backtest_summary_data = reactive.Value({})
    trades_data = reactive.Value(pd.DataFrame())
    initial_cash_used = reactive.Value(100000)
    login_url = reactive.Value("")
    status_msg = reactive.Value("Starting app...")
    live_status_msg = reactive.Value("[INFO] Live data idle")
    trade_status_msg = reactive.Value("[INFO] Live trading idle")
    live_trading_enabled = reactive.Value(False)
    live_fetch_enabled = reactive.Value(False)
    last_signal_key = reactive.Value(None)
    last_traded_ts = reactive.Value(None)
    order_log = reactive.Value(pd.DataFrame(columns=[
        "time", "action", "instrument", "qty", "price", "order_id", "status", "message"
    ]))
    position_state = reactive.Value({
        "open": False,
        "entry_order_id": None,
        "sl_order_id": None,
        "entry_price": None,
        "qty": 0,
        "instrument": None,
    })

    # Instrument selector state
    instruments_loaded = reactive.Value(False)
    available_symbols = reactive.Value([])
    available_expiries = reactive.Value([])
    available_strikes = reactive.Value([])
    selected_symbol = reactive.Value(None)
    selected_expiry = reactive.Value(None)
    selected_strike = reactive.Value(None)
    selected_instrument_key = reactive.Value(None)
    selected_exchange = reactive.Value("NSE")


    # ===== Utility Functions =====
    def _as_iso(d):
        """Convert date/datetime to ISO format (YYYY-MM-DD)."""
        if isinstance(d, (_date, _dt)):
            return d.strftime("%Y-%m-%d")
        if d is None:
            return None
        return str(d).strip()

    # ===== Initialization =====
    @reactive.effect
    def _init():
        """Initialize app with cached token and auto-load instruments."""
        cached = client.get_cached_token()
        if cached:
            token.set(cached)
            status_msg.set("[OK] Using cached token (valid for 24h)")
        else:
            status_msg.set("[INFO] No valid token. Click 'Show Login URL' to authenticate.")

    @reactive.effect
    def _auto_load_instruments():
        """Auto-load instruments on startup if enabled."""
        if not token.get():
            return
        if input.auto_load_instruments():
            try:
                instruments_loaded.set(False)
                exchange = input.exchange() if "exchange" in dir(input) else "NSE"
                if instrument_manager.fetch_instruments(exchange=exchange, force_refresh=False, prefer_local=False):
                    symbols = instrument_manager.get_unique_symbols()
                    available_symbols.set(symbols)
                    instruments_loaded.set(True)
                    selected_exchange.set(exchange)
                    status_msg.set(f"[OK] Instruments auto-loaded: {len(symbols)} symbols ({exchange})")
            except Exception as e:
                logger.exception("Auto-load error: %s", e)

    # ===== Output Renderers =====
    @output
    @render.text
    def auth_status():
        t = token.get()
        return "[OK] Authenticated (cached token valid)" if t else "[ERROR] Not authenticated"

    @output
    @render.text
    def status():
        return status_msg.get()

    @output
    @render.text
    def live_status():
        return live_status_msg.get()

    @output
    @render.text
    def trade_status():
        return trade_status_msg.get()

    @output
    @render.text
    def position_status():
        state = position_state.get() or {}
        if not state.get("open"):
            return "[INFO] No open position"
        price = state.get("entry_price")
        qty = state.get("qty")
        inst = state.get("instrument")
        return f"[OK] Open position: {inst} qty={qty} entry={price}"

    @output
    @render.text
    def instruments_status():
        if instruments_loaded.get():
            src = getattr(instrument_manager, 'source', None)
            src_display = f" ({src})" if src else ""
            return f"[OK] Ready | {len(available_symbols.get())} symbols loaded{src_display} | {selected_exchange.get()}"
        else:
            return "[INFO] Click 'Load Instruments' or enable Auto-load"

    @output
    @render.ui
    def app_root():
        if token.get():
            return create_main_ui()
        return create_auth_ui()

    # ===== Authentication Events =====
    @reactive.effect
    @reactive.event(input.show_login)
    def _show_login():
        try:
            url = client.get_login_url()
            login_url.set(url)
            status_msg.set("[INFO] Login URL generated. Open in browser and complete auth.")
        except Exception as e:
            status_msg.set(f"[ERROR] Error generating login URL: {e}")
            traceback.print_exc()

    @output
    @render.ui
    def login_url_display():
        from shiny import ui
        url = login_url.get()
        if not url:
            return ui.div()
        return ui.div(
            ui.p("Open this URL in your browser:"),
            ui.tags.a("Upstox Login", href=url, target="_blank", class_="btn btn-link"),
            ui.tags.hr(),
            ui.tags.code(url, style="font-size:0.8em;word-wrap:break-word;")
        )

    @reactive.effect
    @reactive.event(input.do_auth)
    def _do_auth():
        code = input.auth_code()
        if not code or code.strip() == "":
            status_msg.set("[ERROR] Please provide auth code")
            return
        try:
            tkn = client.exchange_token(code.strip())
            token.set(tkn)
            status_msg.set("[OK] Authenticated successfully! Token cached for 24h.")
        except Exception as e:
            status_msg.set(f"[ERROR] Auth failed: {e}")
            traceback.print_exc()

    @reactive.effect
    @reactive.event(input.clear_cache)
    def _clear_cache():
        if client.token_manager:
            client.token_manager.clear_token()
        token.set(None)
        status_msg.set("[OK] Token cache cleared. Click 'Show Login URL' to re-authenticate.")

    @session.on_ended
    def _cleanup_session():
        pass

    # ===== Instrument Loading & Selection =====
    @reactive.effect
    @reactive.event(input.load_instruments)
    def _load_instruments():
        try:
            status_msg.set("[INFO] Loading instruments...")
            exchange = input.exchange() if "exchange" in dir(input) else "NSE"
            loaded = instrument_manager.fetch_instruments(exchange=exchange, force_refresh=True, prefer_local=False)
            if loaded:
                symbols = instrument_manager.get_unique_symbols()
                available_symbols.set(symbols)
                instruments_loaded.set(True)
                selected_exchange.set(exchange)
                status_msg.set(f"[OK] Loaded {len(symbols)} symbols ({exchange}) (source: {getattr(instrument_manager, 'source', 'unknown')})")
            else:
                status_msg.set("[ERROR] Failed to load instruments")
        except Exception as e:
            status_msg.set(f"[ERROR] Error: {e}")
            traceback.print_exc()

    @reactive.effect
    def _exchange_changed():
        if not token.get():
            return
        exchange = input.exchange() if "exchange" in dir(input) else "NSE"
        if selected_exchange.get() == exchange and instruments_loaded.get():
            return
        available_symbols.set([])
        available_expiries.set([])
        available_strikes.set([])
        selected_symbol.set(None)
        selected_expiry.set(None)
        selected_strike.set(None)
        selected_instrument_key.set(None)
        instruments_loaded.set(False)
        selected_exchange.set(exchange)

        try:
            current = None
            try:
                current = input.instrument()
            except Exception:
                current = None
            if exchange == "MCX":
                if not current or current in ("NSE_FO|40088", "MCX_FO|496920"):
                    ui.update_text("instrument", value="MCX_FO|496920", session=session)
            else:
                if not current or current in ("MCX_FO|496920", "NSE_FO|40088"):
                    ui.update_text("instrument", value="NSE_FO|40088", session=session)
        except Exception as e:
            logger.warning("Could not update instrument placeholder for exchange: %s", e)

    @output
    @render.ui
    def symbol_selector():
        from shiny import ui
        symbols = available_symbols.get()
        if not symbols:
            return ui.div("Load instruments first", style="color: #999;")
        logger.debug("symbol_selector render: %s symbols, default=%s", len(symbols), symbols[0])
        return ui.input_select("select_symbol", "Choose Symbol", choices=symbols, selected=symbols[0])

    @reactive.effect
    def _update_expiries():
        if not token.get():
            return
        symbol = input.select_symbol()
        logger.debug("_update_expiries triggered: symbol=%s, instruments_loaded=%s", symbol, instruments_loaded.get())
        if not symbol or not instruments_loaded.get():
            return
        try:
            expiries = instrument_manager.get_expiry_dates(symbol)
            logger.debug("_update_expiries: fetched %s expiries for %s", len(expiries), symbol)
            available_expiries.set(expiries)
            selected_symbol.set(symbol)
        except Exception as e:
            available_expiries.set([])
            logger.exception("Error fetching expiries: %s", e)

    @output
    @render.ui
    def expiry_selector():
        expiries = available_expiries.get()
        logger.debug("expiry_selector render: %s expiries available", len(expiries))
        if not expiries:
            return ui.div("Select symbol first", style="color: #999;")

        try:
            expiry_dates = [pd.to_datetime(x).date() for x in expiries]
        except Exception:
            expiry_dates = []

        if not expiry_dates:
            return ui.div("No valid expiries", style="color: #999;")

        # Default to next Tuesday
        next_tuesday = get_next_tuesday()
        default = next_tuesday if next_tuesday in expiry_dates else expiry_dates[0]
        logger.debug("expiry_selector default (date): %s", default)
        return ui.input_date("select_expiry", "Choose Expiry", value=default)

    @reactive.effect
    def _update_strikes():
        if not token.get():
            return
        symbol = input.select_symbol()
        expiry = input.select_expiry()
        instr_type = input.select_type()
        logger.debug("_update_strikes triggered: symbol=%s, expiry=%s, type=%s", symbol, expiry, instr_type)

        if instr_type and instr_type.upper() == 'FUT':
            available_strikes.set([])
            selected_expiry.set(expiry)
            logger.debug("FUT selected -> available_strikes cleared")
            return

        if not (symbol and expiry and instruments_loaded.get()):
            return
        try:
            strikes = instrument_manager.get_strikes(symbol, expiry, instr_type)
            logger.debug("_update_strikes: fetched %s strikes", len(strikes))
            available_strikes.set(strikes)
            selected_expiry.set(expiry)
        except Exception as e:
            available_strikes.set([])
            logger.exception("Error fetching strikes: %s", e)

    @output
    @render.ui
    def strike_selector():
        from shiny import ui
        strikes = available_strikes.get()
        instr_type = input.select_type()
        logger.debug("strike_selector render: instr_type=%s, strikes_count=%s", instr_type, len(strikes) if strikes else 0)

        if instr_type and instr_type.upper() == 'FUT':
            return ui.div("Futures selected — no strike required", style="color: #333;")

        default = str(strikes[0]) if strikes else ""
        helper = (
            ui.div("No strikes found — enter strike manually", style="color: #999;")
            if not strikes
            else ui.div(f"Suggested: {', '.join(str(s) for s in strikes[:6])}", style="color: #666; font-size:0.9em")
        )

        return ui.tags.div(
            ui.input_text("select_strike", "Strike (enter numeric)", value=default, placeholder="e.g. 23100"),
            helper
        )

    @reactive.effect
    @reactive.event(input.apply_instrument)
    def _apply_instrument():
        from shiny import ui
        symbol = input.select_symbol()
        expiry = input.select_expiry()
        strike_val = input.select_strike()
        instr_type = input.select_type()

        if not all([symbol, expiry, instr_type]):
            status_msg.set("[ERROR] Select Symbol, Expiry, and Type")
            return

        try:
            if instr_type == 'FUT':
                key = instrument_manager.get_instrument_key(symbol, expiry, None, 'FUT')
                strike_display = "FUT"
            else:
                if not strike_val:
                    status_msg.set("[ERROR] Select Strike for Options")
                    return
                strike_clean = str(strike_val).strip().replace(",", "")
                strike = int(float(strike_clean))
                key = instrument_manager.get_instrument_key(symbol, expiry, strike, instr_type)
                strike_display = str(strike)

            if key:
                selected_instrument_key.set(key)
                selected_strike.set(strike_val if instr_type != 'FUT' else None)
                try:
                    ui.update_text("instrument", value=key, session=session)
                    logger.debug("ui.update_text instrument=%s", key)
                except Exception as e:
                    logger.warning("Could not update input instrument via ui.update_text: %s", e)
                status_msg.set(f"[OK] Selected: {symbol} {expiry} {strike_display} {instr_type}")
            else:
                status_msg.set(f"[ERROR] Instrument not found")
        except Exception as e:
            status_msg.set(f"[ERROR] Error: {e}")
            traceback.print_exc()

    @reactive.effect
    def _poll_live_status():
        reactive.invalidate_later(2000)
        if live_fetch_enabled.get():
            return
        live_status_msg.set("[INFO] Live fetch idle")

    def _live_fetch_once():
        if not token.get():
            live_status_msg.set("[ERROR] Authenticate first before live fetch")
            return

        inst = selected_instrument_key.get() or input.instrument().strip()
        if not inst:
            live_status_msg.set("[ERROR] Select an instrument before live fetch")
            return

        try:
            interval = "1minute"
            live_status_msg.set(f"[INFO] Live fetch: {inst} ({interval})")
            raw_df = fetch_intraday_data(
                inst, token.get(), interval=interval, mode="intraday"
            )
            if raw_df is None or raw_df.empty:
                live_status_msg.set("[WARN] Live fetch returned no data")
                return

            required_cols = {"Date", "Open", "High", "Low", "Close", "Volume"}
            missing_cols = required_cols - set(raw_df.columns)
            if missing_cols:
                live_status_msg.set(f"[ERROR] Live fetch missing columns: {sorted(missing_cols)}")
                return

            target_date_str = _as_iso(_dt.now().date())
            raw_df = concatenate_with_previous_day(
                raw_df, inst, token.get(), target_date_str, interval=interval, mode="date_range"
            )

            df = calculate_indicators(raw_df)
            df = detect_regimes_relaxed(df)
            df = classify_trend_by_angles(df)
            df = add_long_signal(df)
            df = filter_to_current_day(df, target_date_str)
            df_data.set(df.copy())
            try:
                last_ts = df["Date"].max()
                last_ts_str = (
                    last_ts.strftime("%Y-%m-%d %H:%M:%S")
                    if last_ts is not None and pd.notna(last_ts)
                    else "--"
                )
            except Exception:
                last_ts_str = "--"

            if input.auto_save():
                base_dir = input.save_dir().strip() or None
                path = save_to_csv(df, base_dir=base_dir)
                live_status_msg.set(
                    f"[OK] Live fetch updated ({len(df)} rows) last={last_ts_str}. Saved: {path}"
                )
            else:
                live_status_msg.set(
                    f"[OK] Live fetch updated ({len(df)} rows) last={last_ts_str}"
                )
            logger.info("Live fetch updated: rows=%s last=%s", len(df), last_ts_str)
            _maybe_execute_trade(df)
        except Exception as exc:
            live_status_msg.set(f"[ERROR] Live fetch error: {exc}")
            traceback.print_exc()

    @reactive.effect
    def _live_fetch_loop():
        if not live_fetch_enabled.get():
            return
        now = _dt.now()
        if now.second != 0 or now.microsecond != 0:
            delay = 60 - now.second - (now.microsecond / 1_000_000)
            reactive.invalidate_later(max(delay, 0.5))
            return
        reactive.invalidate_later(60)
        _live_fetch_once()

    @reactive.effect
    @reactive.event(input.start_live)
    def _start_live():
        live_fetch_enabled.set(True)
        _live_fetch_once()

    @reactive.effect
    @reactive.event(input.stop_live)
    def _stop_live():
        live_fetch_enabled.set(False)
        live_status_msg.set("[INFO] Live fetch stopped")

    def _append_order_log(action, instrument, qty, price, order_id, status, message):
        df = order_log.get()
        entry = pd.DataFrame([
            {
                "time": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
                "action": action,
                "instrument": instrument,
                "qty": qty,
                "price": price,
                "order_id": order_id,
                "status": status,
                "message": message,
            }
        ])
        order_log.set(pd.concat([df, entry], ignore_index=True))

    def _maybe_execute_trade(df):
        if not live_trading_enabled.get():
            return
        if not live_fetch_enabled.get():
            return
        if df is None or df.empty:
            return

        last_row = df.iloc[-1]
        ts_val = last_row.get("Date")
        if ts_val is None or pd.isna(ts_val):
            return
        if last_traded_ts.get() == ts_val:
            return
        last_traded_ts.set(ts_val)

        buy_signal = bool(last_row.get("Buy_Signal", False))
        sell_signal = bool(last_row.get("Sell_Signal", False))
        logger.info(
            "Live trading check: latest=%s buy=%s sell=%s",
            ts_val,
            buy_signal,
            sell_signal,
        )
        signal_key = f"{ts_val}-{int(buy_signal)}-{int(sell_signal)}"
        if last_signal_key.get() == signal_key:
            return

        if not buy_signal and not sell_signal:
            last_signal_key.set(signal_key)
            return

        token_val = _get_sandbox_token()
        if not token_val:
            trade_status_msg.set("[ERROR] Missing sandbox token")
            return

        inst = selected_instrument_key.get() or input.instrument().strip()
        if not inst:
            trade_status_msg.set("[ERROR] Select an instrument for trading")
            return

        price = last_row.get("Close")
        try:
            price = float(price)
        except Exception:
            price = None

        capital = input.trade_capital()
        sl_pct = input.sl_percent()
        product_type = input.product_type()
        lot_size = instrument_manager.get_lot_size(inst)
        qty = _calculate_qty(price, capital, lot_size)

        if qty <= 0:
            trade_status_msg.set("[ERROR] Quantity calculated as 0; check capital/price/lot size")
            _append_order_log("SKIP", inst, qty, price, None, "error", "Quantity is 0")
            last_signal_key.set(signal_key)
            return

        state = position_state.get() or {}
        if buy_signal and state.get("open"):
            _append_order_log("SKIP", inst, qty, price, None, "info", "Position already open")
            last_signal_key.set(signal_key)
            return

        if sell_signal and not state.get("open"):
            _append_order_log("SKIP", inst, qty, price, None, "info", "No open position to close")
            last_signal_key.set(signal_key)
            return

        try:
            if buy_signal:
                payload = {
                    "quantity": qty,
                    "product": product_type,
                    "validity": "DAY",
                    "price": 0,
                    "tag": "qfad-entry",
                    "instrument_token": inst,
                    "order_type": "MARKET",
                    "transaction_type": "BUY",
                    "disclosed_quantity": 0,
                    "trigger_price": 0,
                    "is_amo": False,
                    "slice": False,
                }
                resp = sandbox_client.place_order(token_val, payload)
                order_ids = resp.get("data", {}).get("order_ids", [])
                entry_id = order_ids[0] if order_ids else None
                _append_order_log("BUY", inst, qty, price, entry_id, "success", "Entry placed")

                sl_trigger = round(price * (1 - (sl_pct / 100.0)), 2) if price else 0
                sl_payload = {
                    "quantity": qty,
                    "product": product_type,
                    "validity": "DAY",
                    "price": 0,
                    "tag": "qfad-sl",
                    "instrument_token": inst,
                    "order_type": "SL-M",
                    "transaction_type": "SELL",
                    "disclosed_quantity": 0,
                    "trigger_price": sl_trigger,
                    "is_amo": False,
                    "slice": False,
                }
                sl_resp = sandbox_client.place_order(token_val, sl_payload)
                sl_order_ids = sl_resp.get("data", {}).get("order_ids", [])
                sl_id = sl_order_ids[0] if sl_order_ids else None
                _append_order_log("SL", inst, qty, sl_trigger, sl_id, "success", "Stop loss placed")

                position_state.set({
                    "open": True,
                    "entry_order_id": entry_id,
                    "sl_order_id": sl_id,
                    "entry_price": price,
                    "qty": qty,
                    "instrument": inst,
                })
                trade_status_msg.set("[OK] Entry + SL placed (sandbox)")

            if sell_signal:
                sl_id = state.get("sl_order_id")
                if sl_id:
                    try:
                        sandbox_client.cancel_order(token_val, sl_id)
                        _append_order_log("CANCEL", inst, state.get("qty"), price, sl_id, "success", "SL canceled")
                    except Exception as cancel_exc:
                        _append_order_log("CANCEL", inst, state.get("qty"), price, sl_id, "error", str(cancel_exc))

                exit_payload = {
                    "quantity": state.get("qty"),
                    "product": product_type,
                    "validity": "DAY",
                    "price": 0,
                    "tag": "qfad-exit",
                    "instrument_token": inst,
                    "order_type": "MARKET",
                    "transaction_type": "SELL",
                    "disclosed_quantity": 0,
                    "trigger_price": 0,
                    "is_amo": False,
                    "slice": False,
                }
                exit_resp = sandbox_client.place_order(token_val, exit_payload)
                exit_order_ids = exit_resp.get("data", {}).get("order_ids", [])
                exit_id = exit_order_ids[0] if exit_order_ids else None
                _append_order_log("SELL", inst, state.get("qty"), price, exit_id, "success", "Exit placed")

                position_state.set({
                    "open": False,
                    "entry_order_id": None,
                    "sl_order_id": None,
                    "entry_price": None,
                    "qty": 0,
                    "instrument": None,
                })
                trade_status_msg.set("[OK] Exit placed (sandbox)")

            last_signal_key.set(signal_key)

        except Exception as exc:
            trade_status_msg.set(f"[ERROR] Trading error: {exc}")
            _append_order_log("ERROR", inst, qty, price, None, "error", str(exc))

    def _calculate_qty(price, capital, lot_size):
        if price is None or price <= 0:
            return 0
        qty = int(capital // price)
        if lot_size and lot_size > 1:
            qty = (qty // lot_size) * lot_size
        return max(qty, 0)

    def _get_sandbox_token():
        ui_token = input.sandbox_token().strip()
        if ui_token:
            return ui_token
        return os.getenv("UPSTOX_SANDBOX_TOKEN", "").strip()

    @reactive.effect
    @reactive.event(input.start_trading)
    def _start_trading():
        token_val = _get_sandbox_token()
        if not token_val:
            trade_status_msg.set("[ERROR] Provide sandbox token to start trading")
            return
        live_trading_enabled.set(True)
        trade_status_msg.set("[OK] Live trading enabled (sandbox)")

    @reactive.effect
    @reactive.event(input.stop_trading)
    def _stop_trading():
        live_trading_enabled.set(False)
        trade_status_msg.set("[INFO] Live trading stopped")

    @output
    @render.ui
    def selected_instrument_display():
        key = selected_instrument_key.get()
        if key:
            return ui.div(
                ui.tags.strong("Selected: "),
                ui.tags.code(key, class_="selected-instrument-code"),
                class_="selected-instrument-badge"
            )
        return ui.div()

    @reactive.effect
    def _sync_selected_instrument():
        key = selected_instrument_key.get()
        if not key:
            return
        try:
            current = None
            try:
                current = input.instrument()
            except Exception:
                current = None
            if current != key:
                try:
                    ui.update_text("instrument", value=key, session=session)
                    logger.debug("_sync_selected_instrument set instrument=%s", key)
                except Exception as e:
                    logger.warning("Could not update input instrument via ui.update_text in sync: %s", e)
        except Exception as e:
            logger.warning("_sync_selected_instrument error: %s", e)

    # ===== Data Fetching & Processing =====
    @reactive.effect
    @reactive.event(input.fetch)
    def _fetch_data():
        from shiny import ui
        if not token.get():
            status_msg.set("[ERROR] Authenticate first before fetching data")
            return
        try:
            key = selected_instrument_key.get()
            inst = key if key else input.instrument().strip()

            if not inst or inst == "NSE_FO|40088":
                status_msg.set("[ERROR] Please select an instrument")
                return

            interval = input.interval()
            mode = input.fetch_mode()

            status_msg.set(f"[INFO] Fetching data for {inst}...")

            # Fetch raw data based on mode
            if mode == "intraday":
                status_msg.set(f"[INFO] Fetching intraday data for {inst} ({interval})...")
                raw_df = fetch_intraday_data(
                    inst, token.get(), interval=interval, mode="intraday"
                )
            elif mode == "date_range":
                start_val = input.start_date()
                end_val = input.end_date()
                start = _as_iso(start_val)
                end = _as_iso(end_val)

                if not start or not end:
                    status_msg.set("[ERROR] Please provide start and end dates")
                    return
                
                status_msg.set(f"[INFO] Fetching {interval} data for {inst} from {start} to {end}...")
                raw_df = fetch_intraday_data(
                    inst, token.get(), interval=interval, mode="date_range", start=start, end=end
                )
            elif mode == "expired":
                start_val = input.start_date()
                end_val = input.end_date()
                expiry_val = None
                try:
                    expiry_val = input.select_expiry()
                except Exception:
                    expiry_val = None

                start = _as_iso(start_val)
                end = _as_iso(end_val)

                if not start or not end:
                    status_msg.set("[ERROR] Please provide start and end dates")
                    return

                if not expiry_val:
                    status_msg.set("[ERROR] Please choose an expiry date (used for expired instruments)")
                    return

                expiry_iso = _as_iso(expiry_val)

                # Determine base instrument key
                base_inst = inst
                if base_inst and base_inst.count('|') >= 2:
                    parts = base_inst.split('|')
                    base_inst = '|'.join(parts[:2])
                    logger.debug("Stripped expiry from instrument input, base_inst=%s", base_inst)
                if not base_inst or '|' not in base_inst:
                    candidate = selected_instrument_key.get()
                    if candidate:
                        base_inst = candidate
                        logger.debug("Using selected_instrument_key as base_inst: %s", base_inst)
                    else:
                        symbol = selected_symbol.get() or (input.select_symbol() if 'select_symbol' in dir(input) else None)
                        strike_val = selected_strike.get() or (input.select_strike() if 'select_strike' in dir(input) else None)
                        instr_type = input.select_type() if 'select_type' in dir(input) else None
                        try:
                            if symbol and expiry_iso and instr_type:
                                strike_num = int(strike_val) if strike_val not in (None, "") else None
                                candidate_key = instrument_manager.get_instrument_key(symbol, expiry_iso, strike_num, instr_type)
                                if candidate_key:
                                    base_inst = candidate_key
                                    logger.debug("Derived base_inst via InstrumentManager: %s", base_inst)
                        except Exception as e:
                            logger.warning("Could not derive base inst: %s", e)

                if not base_inst or '|' not in base_inst:
                    status_msg.set("[ERROR] Could not determine base instrument key for expired fetch.")
                    return

                status_msg.set(f"[INFO] Fetching expired-instrument data for {base_inst} expiry={expiry_iso} from {start} to {end}...")
                raw_df = fetch_intraday_data(
                    base_inst, token.get(), interval=interval, mode="expired", start=start, end=end, expiry_for_expired=expiry_iso
                )
            else:
                status_msg.set(f"[ERROR] Unsupported fetch mode: {mode}")
                return

            if raw_df is None or raw_df.empty:
                status_msg.set("[ERROR] No data returned from API")
                return

            required_cols = {"Date", "Open", "High", "Low", "Close", "Volume"}
            missing_cols = required_cols - set(raw_df.columns)
            if missing_cols:
                status_msg.set(f"[ERROR] Missing required data columns: {sorted(missing_cols)}")
                return

            # Determine target date
            if mode == "intraday":
                target_date_str = _as_iso(_dt.now().date())
            else:
                target_date_str = _as_iso(end_val)

            status_msg.set(f"[INFO] Concatenating with previous market day data...")
            
            # Concatenate with previous day's data for indicator warmup
            if mode == "expired":
                raw_df = concatenate_with_previous_day(
                    raw_df, inst, token.get(), target_date_str, 
                    interval=interval, mode="expired", expiry_for_expired=expiry_iso
                )
            else:
                raw_df = concatenate_with_previous_day(
                    raw_df, inst, token.get(), target_date_str, 
                    interval=interval, mode="date_range"
                )

            status_msg.set(f"[INFO] Processing {len(raw_df)} rows (combined with previous day)...")
            df = calculate_indicators(raw_df)
            df = detect_regimes_relaxed(df)
            df = classify_trend_by_angles(df)
            df = add_long_signal(df)
            
            # Filter back to current day only
            status_msg.set(f"[INFO] Filtering to current day data only...")
            df = filter_to_current_day(df, target_date_str)
            
            df_data.set(df)

            if input.auto_save():
                base_dir = input.save_dir().strip() or None
                path = save_to_csv(df, base_dir=base_dir)
                status_msg.set(f"[OK] Fetched & processed {len(df)} rows (current day only). Saved: {path}")
            else:
                status_msg.set(f"[OK] Fetched & processed {len(df)} rows (current day only) successfully!")

        except ValueError as ve:
            status_msg.set(f"[ERROR] Date format error: {ve}")
            traceback.print_exc()
        except Exception as e:
            status_msg.set(f"[ERROR] Error: {str(e)}")
            traceback.print_exc()

    @reactive.effect
    def _live_trading_loop():
        return

    # ===== Backtesting =====
    @reactive.effect
    @reactive.event(input.run_backtest)
    def _run_backtest():
        df = df_data.get()
        if df is None or df.empty:
            status_msg.set("[ERROR] Fetch & Process data first before backtesting")
            return

        try:
            status_msg.set("[INFO] Running backtest...")
            cash = input.initial_cash()
            initial_cash_used.set(cash)

            trades_df = calculate_manual_pnl(df, initial_cash=cash, commission=0.0)
            summary = get_summary_stats_manual(df, trades_df, initial_cash=cash)

            backtest_summary_data.set(summary)
            trades_data.set(trades_df)

            if len(trades_df) == 0:
                status_msg.set("[WARN] No complete trades (no matching buy/sell signal pairs)")
            else:
                status_msg.set(f"[OK] Backtest complete! {len(trades_df)} trades executed.")
        except Exception as e:
            status_msg.set(f"[ERROR] Backtest error: {str(e)}")
            traceback.print_exc()

    # ===== Chart Visualization =====
    @output
    @render_plotly
    def price_plot():
        reactive.invalidate_later(2000)
        df = df_data.get()
        if df is None or df.empty:
            fig = go.Figure()
            fig.update_layout(title="No data available. Click 'Fetch & Process' to load data.", height=700)
            return fig
        try:
            return plot_signals(df)
        except Exception as e:
            traceback.print_exc()
            fig = go.Figure()
            fig.update_layout(title=f"Plot error: {e}", height=700)
            return fig

    # ===== Data Tables =====
    @output
    @render.data_frame
    def signals_table():
        from shiny import render
        df = df_data.get()
        if df is None or df.empty:
            return render.DataTable(pd.DataFrame({"Message": ["No data loaded"]}))

        cols = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
        extras = [
            'RSI', 'MFI', 'EMA9', 'BBM', 'VWAP',
            'Buy_Signal', 'Mid_Buy_Signal', 'Mid_Buy_Signal_2',
            'Super_Low_Buy_Signal', 'RSI_Range_Buy_Signal', 'OverSold_Buy_Signal',
            'Sell_Signal', 'regime'
        ]
        for c in extras:
            if c in df.columns:
                cols.append(c)
        cols = list(dict.fromkeys(cols))

        out = df[cols].tail(200).copy()

        # Format numerics
        numeric_cols = out.select_dtypes(include=[np.number]).columns
        for col in numeric_cols:
            out[col] = out[col].round(2)

        if 'Date' in out.columns:
            out['Date'] = out['Date'].dt.strftime('%Y-%m-%d %H:%M:%S')

        return render.DataTable(out, width="100%", height="600px")

    @output
    @render.ui
    def backtest_summary():
        from shiny import ui
        summary = backtest_summary_data.get()
        if not summary:
            return ui.p("Run backtest to see results")

        try:
            rows = []
            for k, v in summary.items():
                if isinstance(v, float):
                    formatted_v = f"{v:,.2f}"
                elif isinstance(v, int):
                    formatted_v = f"{v:,}"
                else:
                    formatted_v = str(v)

                rows.append(
                    ui.tags.tr(
                        ui.tags.td(ui.strong(k + ":"), style="border: 1px solid #333; padding: 6px 8px;"),
                        ui.tags.td(formatted_v, style="border: 1px solid #333; padding: 6px 8px;")
                    )
                )
            return ui.div(
                ui.h4("Backtest Results", style="color: #e8e5f2;"),
                ui.tags.table(
                    ui.tags.tbody(*rows),
                    style="border-collapse: collapse; width: 100%; margin-top: 10px; border: 1px solid #333;",
                ),
                style="padding: 20px; background-color: #000; border-radius: 5px; color: #e8e5f2;"
            )
        except Exception as e:
            return ui.p(f"Error rendering summary: {e}")

    @output
    @render.data_frame
    def trades_table():
        from shiny import render
        trades_df = trades_data.get()
        if trades_df is None or trades_df.empty:
            return render.DataTable(pd.DataFrame({"Message": ["No trades executed"]}))

        display_df = trades_df.copy()

        # Format numerics
        numeric_cols = display_df.select_dtypes(include=[np.number]).columns
        for col in numeric_cols:
            display_df[col] = display_df[col].round(2)

        # Safe datetime formatting
        if 'Entry Time' in display_df.columns:
            try:
                if pd.api.types.is_datetime64_any_dtype(display_df['Entry Time']):
                    display_df['Entry Time'] = display_df['Entry Time'].dt.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    display_df['Entry Time'] = display_df['Entry Time'].astype(str)
            except:
                display_df['Entry Time'] = display_df['Entry Time'].astype(str)

        if 'Exit Time' in display_df.columns:
            try:
                if pd.api.types.is_datetime64_any_dtype(display_df['Exit Time']):
                    display_df['Exit Time'] = display_df['Exit Time'].dt.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    display_df['Exit Time'] = display_df['Exit Time'].astype(str)
            except:
                display_df['Exit Time'] = display_df['Exit Time'].astype(str)

        return render.DataTable(display_df, width="100%", height="600px")

    @output
    @render.data_frame
    def orders_table():
        from shiny import render
        df = order_log.get()
        if df is None or df.empty:
            return render.DataTable(pd.DataFrame({"Message": ["No orders placed"]}))

        out = df.copy()
        return render.DataTable(out, width="100%", height="400px")

    # ===== Download Handler =====
    @render.download(filename="signals_export.csv")
    def download_csv():
        df = df_data.get()
        if df is None or df.empty:
            return ""
        tmp_dir = os.path.join(os.getcwd(), "tmp_exports")
        os.makedirs(tmp_dir, exist_ok=True)
        path = save_to_csv(df, base_dir=tmp_dir, prefix="signals_export")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
