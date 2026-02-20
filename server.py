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
from src.data.live_data_feed import LiveDataRecorder
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
    live_recorder = LiveDataRecorder()

    # ===== Reactive State =====
    token = reactive.Value(None)
    df_data = reactive.Value(pd.DataFrame())
    backtest_summary_data = reactive.Value({})
    trades_data = reactive.Value(pd.DataFrame())
    initial_cash_used = reactive.Value(100000)
    login_url = reactive.Value("")
    status_msg = reactive.Value("Starting app...")
    funds_msg = reactive.Value("[INFO] Funds: --")
    funds_available = reactive.Value(None)
    live_status_msg = reactive.Value("[INFO] Live data idle")
    websocket_status_msg = reactive.Value("[INFO] WebSocket idle")
    trade_status_msg = reactive.Value("[INFO] Live trading idle")
    live_trading_enabled = reactive.Value(False)
    live_trading_mode = reactive.Value(None)
    live_fetch_enabled = reactive.Value(False)
    websocket_csv_enabled = reactive.Value(False)
    websocket_last_processed_counter = reactive.Value(0)
    websocket_chart_tick = reactive.Value(0)
    last_signal_key = reactive.Value(None)
    last_traded_ts = reactive.Value(None)
    order_history_data = reactive.Value(pd.DataFrame())
    order_history_status_msg = reactive.Value("[INFO] Click 'Fetch Today's Orders' to load history")
    order_history_totals = reactive.Value({"pnl": None, "pct": None, "rows": None})
    order_log = reactive.Value(pd.DataFrame(columns=[
        "time", "action", "instrument", "qty", "price", "fill_price", "entry_price_ref", "pnl", "pnl_pct", "order_id", "status", "message"
    ]))
    position_state = reactive.Value({
        "open": False,
        "entry_order_id": None,
        "sl_order_id": None,
        "entry_price": None,
        "entry_fill_price": None,
        "qty": 0,
        "instrument": None,
        "product": None,
        "sl_pct": None,
        "sl_placed": False,
        "sl_attempts": 0,
        "sl_next_retry_ts": None,
    })
    pending_exit = reactive.Value(None)
    last_realized_pnl = reactive.Value(None)

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

    def _extract_funds_display(payload):
        data = (payload or {}).get("data", {})
        equity = data.get("equity", {}) if isinstance(data, dict) else {}
        used = data.get("used_margin", {}) if isinstance(data, dict) else {}
        available = (
            equity.get("available_margin")
            or equity.get("available")
            or equity.get("net")
            or equity.get("opening_balance")
        )
        if available is None and isinstance(used, dict):
            available = used.get("available")
        try:
            if available is not None:
                return f"[OK] INR {float(available):,.2f}"
        except Exception:
            pass
        return "[WARN] --"

    def _extract_funds_value(payload):
        data = (payload or {}).get("data", {})
        equity = data.get("equity", {}) if isinstance(data, dict) else {}
        used = data.get("used_margin", {}) if isinstance(data, dict) else {}
        available = (
            equity.get("available_margin")
            or equity.get("available")
            or equity.get("net")
            or equity.get("opening_balance")
        )
        if available is None and isinstance(used, dict):
            available = used.get("available")
        try:
            return float(available) if available is not None else None
        except Exception:
            return None

    def _refresh_funds():
        tkn = token.get()
        if not tkn:
            funds_msg.set("[INFO] Funds: --")
            funds_available.set(None)
            return
        try:
            payload = client.get_funds_and_margin(tkn, segment=None)
            funds_msg.set(_extract_funds_display(payload))
            funds_available.set(_extract_funds_value(payload))
            return
        except Exception:
            pass

        try:
            payload = client.get_funds_and_margin(tkn, segment="SEC")
            funds_msg.set(_extract_funds_display(payload))
            funds_available.set(_extract_funds_value(payload))
            return
        except Exception as exc:
            logger.warning("Funds fetch failed: %s", exc)
            funds_msg.set("[WARN] --")
            funds_available.set(None)

    # ===== Initialization =====
    @reactive.effect
    def _init():
        """Initialize app with cached token and auto-load instruments."""
        cached = client.get_cached_token()
        if cached:
            token.set(cached)
            status_msg.set("[OK] Using cached token (valid for 24h)")
            _refresh_funds()
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
    def websocket_status():
        return websocket_status_msg.get()

    @output
    @render.text
    def trade_status():
        pnl_total = _get_total_pnl()
        if pnl_total is None:
            return trade_status_msg.get()
        return f"{trade_status_msg.get()} | PnL: {pnl_total}"

    @output
    @render.ui
    def order_history_status():
        totals = order_history_totals.get() or {}
        rows = totals.get("rows")
        pnl = totals.get("pnl")
        pct = totals.get("pct")

        if rows is None or pnl is None:
            return ui.tags.span(order_history_status_msg.get(), class_="oh-status-text")

        try:
            pnl_f = float(pnl)
        except Exception:
            pnl_f = 0.0
        try:
            pct_f = float(pct)
        except Exception:
            pct_f = 0.0

        pnl_cls = "oh-val-pos" if pnl_f > 0 else ("oh-val-neg" if pnl_f < 0 else "oh-val-zero")
        pct_cls = "oh-val-pos" if pct_f > 0 else ("oh-val-neg" if pct_f < 0 else "oh-val-zero")

        return ui.tags.span(
            ui.tags.span(f"[OK] Today's orders loaded: {int(rows)} rows", class_="oh-status-text"),
            ui.tags.span(" | ", class_="oh-status-text"),
            ui.tags.span(f"Total PnL: {pnl_f:.2f}", class_=pnl_cls),
            ui.tags.span(" | ", class_="oh-status-text"),
            ui.tags.span(f"PnL %: {pct_f:.2f}%", class_=pct_cls),
            class_="oh-status-text",
        )

    def _get_total_pnl():
        df = order_log.get()
        if df is None or df.empty or "pnl" not in df.columns:
            return None
        try:
            pnl_series = pd.to_numeric(df["pnl"], errors="coerce").dropna()
            if pnl_series.empty:
                return None
            return round(float(pnl_series.sum()), 2)
        except Exception:
            return None

    def _extract_rows(payload):
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            data = payload.get("data", [])
            return data if isinstance(data, list) else []
        return []

    def _num(v):
        try:
            return float(v)
        except Exception:
            return np.nan

    def _build_order_history(order_rows, trade_rows):
        order_df = pd.DataFrame(order_rows) if order_rows else pd.DataFrame()
        order_map = {}
        if not order_df.empty and "order_id" in order_df.columns:
            for _, r in order_df.iterrows():
                oid = str(r.get("order_id", "")).strip()
                if oid:
                    order_map[oid] = r.to_dict()

        # Upstox often returns trades newest-first; FIFO PnL requires oldest-first processing.
        def _trade_ts(trade):
            order_id = str(trade.get("order_id", "")).strip()
            order_info = order_map.get(order_id, {})
            raw = (
                trade.get("trade_time")
                or trade.get("exchange_timestamp")
                or trade.get("order_timestamp")
                or order_info.get("exchange_timestamp")
                or order_info.get("order_timestamp")
                or None
            )
            try:
                return pd.to_datetime(raw, errors="coerce")
            except Exception:
                return pd.NaT

        trade_with_ts = []
        for i, t in enumerate(trade_rows or []):
            ts_val = _trade_ts(t)
            trade_with_ts.append((i, t, ts_val))

        trade_rows_sorted = [
            t for _, t, _ in sorted(
                trade_with_ts,
                key=lambda x: (pd.isna(x[2]), x[2], x[0])
            )
        ]

        book = {}
        out_rows = []
        for t in trade_rows_sorted:
            order_id = str(t.get("order_id", "")).strip()
            order_info = order_map.get(order_id, {})

            inst = t.get("instrument_token") or order_info.get("instrument_token") or ""
            symbol = t.get("trading_symbol") or order_info.get("trading_symbol") or ""
            side = str(t.get("transaction_type") or order_info.get("transaction_type") or "").upper()
            qty = _num(t.get("quantity", t.get("traded_quantity", order_info.get("filled_quantity", 0))))
            price = _num(t.get("trade_price", t.get("average_price", order_info.get("average_price", order_info.get("price")))))
            ts = (
                t.get("trade_time")
                or t.get("exchange_timestamp")
                or t.get("order_timestamp")
                or order_info.get("exchange_timestamp")
                or order_info.get("order_timestamp")
                or ""
            )

            realized_pnl = np.nan
            realized_pct = np.nan
            matched_cost = np.nan
            qty_val = 0.0 if np.isnan(qty) else float(qty)
            price_val = np.nan if np.isnan(price) else float(price)

            if inst not in book:
                book[inst] = []

            if side == "BUY" and qty_val > 0 and not np.isnan(price_val):
                book[inst].append([qty_val, price_val])
            elif side == "SELL" and qty_val > 0 and not np.isnan(price_val):
                remain = qty_val
                pnl_val = 0.0
                cost_val = 0.0
                lots = book[inst]
                while remain > 0 and lots:
                    lot_qty, lot_price = lots[0]
                    m = min(remain, lot_qty)
                    pnl_val += (price_val - lot_price) * m
                    cost_val += lot_price * m
                    remain -= m
                    lot_qty -= m
                    if lot_qty <= 0:
                        lots.pop(0)
                    else:
                        lots[0][0] = lot_qty
                if cost_val > 0:
                    realized_pnl = round(pnl_val, 2)
                    matched_cost = cost_val
                    realized_pct = round((pnl_val / cost_val) * 100.0, 2)

            out_rows.append({
                "time": ts,
                "symbol": symbol,
                "side": side,
                "qty": qty_val if qty_val else np.nan,
                "price": price_val,
                "order_id": order_id,
                "order_type": order_info.get("order_type", ""),
                "product": order_info.get("product", ""),
                "status": order_info.get("status", ""),
                "tag": order_info.get("tag", ""),
                "message": order_info.get("status_message_raw", order_info.get("status_message", "")),
                "PnL": realized_pnl,
                "PnL %": realized_pct,
                "_matched_cost": matched_cost,
            })

        out = pd.DataFrame(out_rows)
        if out.empty:
            return out, 0.0, np.nan

        try:
            parsed = pd.to_datetime(out["time"], errors="coerce")
            today = _dt.now().date()
            mask = parsed.dt.date == today
            if mask.any():
                out = out[mask].copy()
                out["_time_sort"] = parsed[mask]
                out = out.sort_values("_time_sort", ascending=True, na_position="last")
                out["time"] = out["_time_sort"].dt.strftime("%Y-%m-%d %H:%M:%S")
                out = out.drop(columns=["_time_sort"], errors="ignore")
        except Exception:
            pass

        total_pnl = round(float(pd.to_numeric(out["PnL"], errors="coerce").dropna().sum()), 2)
        total_cost = float(pd.to_numeric(out["_matched_cost"], errors="coerce").dropna().sum())
        total_pct = round((total_pnl / total_cost) * 100.0, 2) if total_cost else np.nan

        summary = {c: "" for c in out.columns}
        summary["side"] = "TOTAL"
        summary["PnL"] = total_pnl
        summary["PnL %"] = total_pct
        out = pd.concat([out, pd.DataFrame([summary])], ignore_index=True)

        out["qty"] = out["qty"].apply(lambda x: round(float(x), 2) if pd.notna(x) and x != "" else x)
        out["price"] = out["price"].apply(lambda x: round(float(x), 2) if pd.notna(x) and x != "" else x)
        out["PnL"] = out["PnL"].apply(lambda x: round(float(x), 2) if pd.notna(x) and x != "" else x)
        out["PnL %"] = out["PnL %"].apply(lambda x: round(float(x), 2) if pd.notna(x) and x != "" else x)
        out["PnL %"] = out["PnL %"].apply(
            lambda x: f"{float(x):.2f}%" if pd.notna(x) and x != "" else x
        )
        out = out.drop(columns=["_matched_cost"], errors="ignore")
        return out, total_pnl, total_pct

    def _refresh_order_history_data(update_status=False, auto=False):
        access_token = token.get()
        if not access_token:
            if update_status:
                order_history_status_msg.set("[ERROR] Authenticate first to fetch order history")
            return
        try:
            order_payload = client.get_order_book(access_token)
            trade_payload = client.get_trades_for_day(access_token)
            order_rows = _extract_rows(order_payload)
            trade_rows = _extract_rows(trade_payload)
            history_df, total_pnl, total_pct = _build_order_history(order_rows, trade_rows)
            if history_df is None or history_df.empty:
                order_history_data.set(pd.DataFrame({"Message": ["No executed trades found for today"]}))
                order_history_totals.set({"pnl": None, "pct": None, "rows": None})
                if update_status:
                    order_history_status_msg.set("[INFO] No executed trades found for today")
                return
            order_history_data.set(history_df)
            order_history_totals.set(
                {
                    "pnl": total_pnl,
                    "pct": (0.0 if pd.isna(total_pct) else total_pct),
                    "rows": max(len(history_df) - 1, 0),
                }
            )
            if update_status:
                total_pct_text = f"{total_pct:.2f}%" if pd.notna(total_pct) else "--"
                prefix = "[AUTO]" if auto else "[OK]"
                order_history_status_msg.set(
                    f"{prefix} Today's orders loaded: {max(len(history_df) - 1, 0)} rows | Total PnL: {total_pnl:.2f} | PnL %: {total_pct_text}"
                )
        except Exception as exc:
            err = _extract_http_error_message(exc)
            order_history_data.set(pd.DataFrame({"Message": [f"Fetch failed: {err}"]}))
            order_history_totals.set({"pnl": None, "pct": None, "rows": None})
            if update_status:
                order_history_status_msg.set(f"[ERROR] Order history fetch failed: {err}")

    @output
    @render.ui
    def funds_indicator():
        msg = funds_msg.get()
        if msg.startswith("[OK]"):
            return ui.div(
                ui.tags.span("Funds", class_="funds-label"),
                ui.tags.span(msg.replace("[OK]", "").strip(), class_="funds-value"),
                class_="funds-indicator",
            )
        return ui.div(
            ui.tags.span("Funds", class_="funds-label"),
            ui.tags.span("--", class_="funds-value"),
            class_="funds-indicator funds-indicator-off",
        )

    @output
    @render.ui
    def live_trading_indicator():
        if live_trading_enabled.get():
            return ui.div(
                ui.tags.span(class_="live-dot"),
                ui.tags.span("LIVE", class_="live-label"),
                class_="live-indicator live-indicator-on",
            )
        return ui.div(
            ui.tags.span(class_="live-dot"),
            ui.tags.span("LIVE OFF", class_="live-label"),
            class_="live-indicator live-indicator-off",
        )

    @output
    @render.text
    def position_status():
        state = position_state.get() or {}
        if not state.get("open"):
            pnl = last_realized_pnl.get()
            if pnl is not None:
                return f"[INFO] No open position | Last PnL: {pnl}"
            return "[INFO] No open position"
        price = state.get("entry_price")
        fill_price = state.get("entry_fill_price")
        qty = state.get("qty")
        inst = state.get("instrument")
        fill_msg = f" fill={fill_price}" if fill_price else ""
        return f"[OK] Open position: {inst} qty={qty} entry={price}{fill_msg}"

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
            redirect_uri = input.redirect_uri().strip()
            if not redirect_uri:
                redirect_uri = os.getenv("UPSTOX_REDIRECT_URI", "").strip()
            if not redirect_uri:
                raise ValueError("Redirect URI is missing")
            url = client.get_login_url(redirect_uri=redirect_uri)
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
            redirect_uri = input.redirect_uri().strip()
            if not redirect_uri:
                redirect_uri = os.getenv("UPSTOX_REDIRECT_URI", "").strip()
            if not redirect_uri:
                status_msg.set("[ERROR] Redirect URI is required for auth")
                return
            tkn = client.exchange_token(code.strip(), redirect_uri=redirect_uri)
            token.set(tkn)
            status_msg.set("[OK] Authenticated successfully! Token cached for 24h.")
            _refresh_funds()
        except Exception as e:
            status_msg.set(f"[ERROR] Auth failed: {e}")
            traceback.print_exc()

    @reactive.effect
    @reactive.event(input.clear_cache)
    def _clear_cache():
        if client.token_manager:
            client.token_manager.clear_token()
        token.set(None)
        funds_msg.set("[INFO] Funds: --")
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
        instr_type = input.select_type()
        logger.debug("_update_expiries triggered: symbol=%s, instruments_loaded=%s", symbol, instruments_loaded.get())
        if not symbol or not instruments_loaded.get():
            return
        try:
            expiries = instrument_manager.get_expiry_dates(symbol, instrument_type=instr_type)
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
        reactive.invalidate_later(2)
        if live_fetch_enabled.get():
            return
        live_status_msg.set("[INFO] Live fetch idle")

    @reactive.effect
    def _poll_websocket_status():
        reactive.invalidate_later(2)
        websocket_status_msg.set(live_recorder.status())

    def _get_websocket_csv_path():
        base_dir = os.path.join(os.getcwd(), "live_data")
        return os.path.join(base_dir, "live_data_websocket.csv")

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
                save_to_csv(df, base_dir=base_dir)
                live_status_msg.set(
                    f"[OK] Live fetch updated ({len(df)} rows) last={last_ts_str}"
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
        # Run 12 seconds after the minute boundary (i.e., at :12)
        if now.second != 20:
            if now.second < 20:
                delay = 20 - now.second
            else:
                delay = 60 - now.second + 20
            reactive.invalidate_later(max(delay, 1))
            return
        reactive.invalidate_later(60)
        _live_fetch_once()

    @reactive.effect
    @reactive.event(input.start_live_data)
    def _start_live():
        live_fetch_enabled.set(True)
        _live_fetch_once()

    @reactive.effect
    @reactive.event(input.stop_live_data)
    def _stop_live():
        live_fetch_enabled.set(False)
        live_status_msg.set("[INFO] Live fetch stopped")

    @reactive.effect
    @reactive.event(input.start_websocket)
    def _start_websocket():
        if not token.get():
            websocket_status_msg.set("[ERROR] Authenticate first before starting WebSocket")
            return

        inst = selected_instrument_key.get() or input.instrument().strip()
        if not inst:
            websocket_status_msg.set("[ERROR] Select an instrument before starting WebSocket")
            return

        ok, message = live_recorder.start(
            token.get(), inst, None, mode="full", save_interval=60
        )
        websocket_status_msg.set("[OK] WebSocket started" if ok else f"[ERROR] {message}")
        if ok:
            websocket_csv_enabled.set(True)
            websocket_last_processed_counter.set(0)
            df_data.set(pd.DataFrame())
            websocket_chart_tick.set(websocket_chart_tick.get() + 1)

    @reactive.effect
    @reactive.event(input.stop_websocket)
    def _stop_websocket():
        ok, message = live_recorder.stop()
        websocket_status_msg.set("[OK] WebSocket stopped" if ok else f"[INFO] {message}")
        websocket_csv_enabled.set(False)
        websocket_last_processed_counter.set(0)

    @reactive.effect
    def _websocket_csv_loop():
        try:
            if not websocket_csv_enabled.get():
                return
            snapshot = live_recorder.live_save_snapshot()
            live_save_counter = int(snapshot.get("counter", 0) or 0)
            if live_save_counter <= websocket_last_processed_counter.get():
                return

            path = snapshot.get("last_save_path") or _get_websocket_csv_path()
            if not path or not os.path.exists(path) or os.path.getsize(path) == 0:
                websocket_last_processed_counter.set(live_save_counter)
                return

            try:
                raw_df = pd.read_csv(path)
            except Exception as exc:
                logger.warning("WebSocket CSV read error: %s", exc)
                return

            required = {"timestamp", "open", "high", "low", "close", "volume"}
            if not required.issubset(set(raw_df.columns)):
                logger.warning("WebSocket CSV missing columns: %s", sorted(required - set(raw_df.columns)))
                return

            df = raw_df.copy()
            df["Date"] = pd.to_datetime(df["timestamp"], errors="coerce")
            if getattr(df["Date"].dt, "tz", None) is not None:
                df["Date"] = df["Date"].dt.tz_localize(None)
            df.rename(
                columns={
                    "open": "Open",
                    "high": "High",
                    "low": "Low",
                    "close": "Close",
                    "volume": "Volume",
                },
                inplace=True,
            )
            df = df[["Date", "Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Date"])
            df = df.sort_values("Date").reset_index(drop=True)
            if df.empty:
                websocket_last_processed_counter.set(live_save_counter)
                return

            target_date_str = _as_iso(_dt.now().date())
            try:
                inst = selected_instrument_key.get() or input.instrument().strip()
                # If CSV already contains previous-day rows, skip concatenation
                has_prev_day = False
                try:
                    min_date = df["Date"].dt.date.min()
                    max_date = df["Date"].dt.date.max()
                    target_date = _dt.strptime(target_date_str, "%Y-%m-%d").date()
                    has_prev_day = (min_date is not None and max_date is not None and min_date < target_date <= max_date)
                except Exception:
                    has_prev_day = False
                if inst and token.get() and not has_prev_day:
                    df = concatenate_with_previous_day(
                        df, inst, token.get(), target_date_str,
                        interval="1minute", mode="date_range"
                    )
                df = calculate_indicators(df)
                df = detect_regimes_relaxed(df)
                df = classify_trend_by_angles(df)
                has_915 = (df["Date"].dt.time == _dt.strptime("09:15:00", "%H:%M:%S").time()).any()
                if has_915:
                    df = add_long_signal(df)
                else:
                    logger.warning("WebSocket CSV: skipping signals (no 09:15 candle found)")
                df = filter_to_current_day(df, target_date_str)
                df_data.set(df.copy())
                _maybe_execute_trade(df)
                websocket_last_processed_counter.set(live_save_counter)
                websocket_chart_tick.set(websocket_chart_tick.get() + 1)
            except Exception as exc:
                logger.exception("WebSocket CSV processing error: %s", exc)
                return
        finally:
            reactive.invalidate_later(1)

    def _append_order_log(action, instrument, qty, price, order_id, status, message):
        df = order_log.get()
        entry = pd.DataFrame([
            {
                "time": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
                "action": action,
                "instrument": instrument,
                "qty": qty,
                "price": price,
                "fill_price": None,
                "entry_price_ref": None,
                "pnl": None,
                "pnl_pct": None,
                "order_id": order_id,
                "status": status,
                "message": message,
            }
        ])
        order_log.set(pd.concat([df, entry], ignore_index=True))
        # Keep Order History tab in sync with successful production order events.
        try:
            if (
                live_trading_mode.get() == "live"
                and str(status).lower() == "success"
                and str(action).upper() in {"BUY", "SELL", "SL", "CANCEL", "EXIT_ALL"}
            ):
                _refresh_order_history_data(update_status=True, auto=True)
        except Exception:
            pass

    def _update_order_log(order_id, **updates):
        if not order_id:
            return
        df = order_log.get()
        if df is None or df.empty:
            return
        idx = df.index[df["order_id"] == order_id]
        if len(idx) == 0:
            return
        i = idx[-1]
        for k, v in updates.items():
            if k in df.columns:
                df.at[i, k] = v
        order_log.set(df)

    def _use_production_trading():
        mode = live_trading_mode.get()
        return mode == "live"

    def _get_trade_client_and_token():
        if _use_production_trading():
            tkn = token.get()
            return client, tkn, True
        tkn = _get_sandbox_token()
        return sandbox_client, tkn, False

    def _extract_http_error_message(exc):
        """Best-effort extraction of API error body from HTTP exceptions."""
        try:
            resp = getattr(exc, "response", None)
            if resp is not None:
                try:
                    body = resp.json()
                    if isinstance(body, dict):
                        errors = body.get("errors")
                        if isinstance(errors, list) and errors:
                            msg = errors[0].get("message")
                            if msg:
                                return str(msg)
                        msg = body.get("message")
                        if msg:
                            return str(msg)
                    if body:
                        return str(body)
                except Exception:
                    text = getattr(resp, "text", None)
                    if text:
                        return str(text)
        except Exception:
            pass
        return str(exc)

    def _place_order_safe(trade_client, token_val, payload):
        try:
            return trade_client.place_order(token_val, payload)
        except Exception as exc:
            err = _extract_http_error_message(exc)
            return {"status": "error", "errors": [{"message": err}]}

    def _cancel_order_safe(trade_client, token_val, order_id):
        try:
            return trade_client.cancel_order(token_val, order_id)
        except Exception as exc:
            return {"status": "error", "errors": [{"message": _extract_http_error_message(exc)}]}

    def _exit_all_positions_safe(token_val, segment=None, tag=None):
        try:
            return client.exit_all_positions(token_val, segment=segment, tag=tag)
        except Exception as exc:
            return {"status": "error", "errors": [{"message": _extract_http_error_message(exc)}]}

    def _round_to_tick(value, tick_size):
        try:
            v = float(value)
            t = float(tick_size)
            if t <= 0:
                return round(v, 2)
            return round(round(v / t) * t, 2)
        except Exception:
            return round(float(value), 2) if value is not None else None

    def _build_sl_payload(inst, qty, product, sl_trigger, tick_size):
        payload = {
            "quantity": qty,
            "product": product,
            "validity": "DAY",
            "tag": "qfad-sl",
            "instrument_token": inst,
            "order_type": "SL",
            "transaction_type": "SELL",
            "disclosed_quantity": 0,
            "trigger_price": sl_trigger,
            "is_amo": False,
            "slice": False,
        }
        # For SELL SL (limit), keep limit just below trigger.
        limit_price = _round_to_tick(max(float(sl_trigger) - float(tick_size), float(tick_size)), tick_size)
        payload["price"] = limit_price
        return payload

    def _place_stop_loss_order(trade_client, token_val, inst, qty, product, sl_trigger, tick_size):
        payload = _build_sl_payload(inst, qty, product, sl_trigger, tick_size)
        resp = _place_order_safe(trade_client, token_val, payload)
        return resp, "SL"

    def _fetch_order_fill(order_id, access_token):
        try:
            payload = client.get_order_history(access_token, order_id)
        except Exception:
            return None, None, None
        data = (payload or {}).get("data", [])
        if not data:
            return None, None, None
        last = data[-1]
        avg_price = last.get("average_price")
        status = (last.get("status") or "").lower()
        filled_qty = last.get("filled_quantity")
        try:
            avg_price = float(avg_price) if avg_price is not None else None
        except Exception:
            avg_price = None
        return avg_price, status, filled_qty

    def _maybe_execute_trade(df):
        if not live_trading_enabled.get():
            return
        if not (live_fetch_enabled.get() or websocket_csv_enabled.get()):
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

        buy_signal = (
            bool(last_row.get('Buy_Signal', False)) or
            bool(last_row.get('Mid_Buy_Signal', False)) or
            bool(last_row.get('Mid_Buy_Signal_2', False)) or
            bool(last_row.get('OverSold_Buy_Signal', False)) or
            bool(last_row.get('RSI_Range_Buy_Signal', False)) or
            bool(last_row.get('Super_Low_Buy_Signal', False)) or 
            bool(last_row.get('Super_Low_Buy_Signal_2', False)) or 
            bool(last_row.get('New_Uptrend_Buy_Signal', False)) or
            bool(last_row.get('Downtrend_Reverse_Buy_Signal', False)) or 
            bool(last_row.get('RSI_pct_buy', False))
        )
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

        trade_client, token_val, is_production = _get_trade_client_and_token()
        if not token_val:
            if is_production:
                trade_status_msg.set("[ERROR] Missing production token (authenticate first)")
            else:
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

        if _use_production_trading():
            capital = funds_available.get() or 0
            sl_pct = input.live_sl_percent()
            product_type = input.live_product_type()
        else:
            capital = input.sandbox_capital()
            sl_pct = input.sandbox_sl_percent()
            product_type = input.sandbox_product_type()
        state = position_state.get() or {}
        lot_size = instrument_manager.get_lot_size(inst)
        qty = _calculate_qty(price, capital, lot_size)

        if buy_signal and not state.get("open") and qty <= 0:
            trade_status_msg.set("[ERROR] Quantity calculated as 0; check capital/price/lot size")
            _append_order_log("SKIP", inst, qty, price, None, "error", "Quantity is 0")
            last_signal_key.set(signal_key)
            return

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
                resp = _place_order_safe(trade_client, token_val, payload)
                logger.info("Entry order response: %s", resp)
                resp_status = resp.get("status", "")
                entry_id = None
                if resp_status == "success":
                    order_ids = resp.get("data", {}).get("order_ids", [])
                    entry_id = order_ids[0] if order_ids else None
                    _append_order_log("BUY", inst, qty, price, entry_id, "success", f"Entry placed: {entry_id}")
                    if entry_id:
                        _update_order_log(entry_id, fill_price=price, message=f"Entry placed @ {price}")
                else:
                    error_msg = resp.get("errors", [{}])[0].get("message", resp.get("message", "Unknown error"))
                    _append_order_log("BUY", inst, qty, price, None, "error", f"Entry failed: {error_msg}")
                    trade_status_msg.set(f"[ERROR] Entry order failed: {error_msg}")
                    return

                sl_id = None
                position_state.set({
                    "open": True,
                    "entry_order_id": entry_id,
                    "sl_order_id": sl_id,
                    "entry_price": price,
                    "entry_fill_price": None,
                    "qty": qty,
                    "instrument": inst,
                    "product": product_type,
                    "sl_pct": sl_pct,
                    "sl_placed": False,
                    "sl_attempts": 0,
                    "sl_next_retry_ts": None,
                })
                last_realized_pnl.set(None)
                mode_msg = "production" if is_production else "sandbox"
                if is_production:
                    trade_status_msg.set(f"[OK] Entry placed ({mode_msg}); waiting for fill to place SL")
                else:
                    tick_size = instrument_manager.get_tick_size(inst, default=0.05)
                    sl_trigger = _round_to_tick(price * (1 - (sl_pct / 100.0)), tick_size) if price else 0
                    sl_resp, sl_type = _place_stop_loss_order(
                        trade_client, token_val, inst, qty, product_type, sl_trigger, tick_size
                    )
                    logger.info("SL order response: %s", sl_resp)
                    sl_status = sl_resp.get("status", "")
                    if sl_status == "success":
                        sl_order_ids = sl_resp.get("data", {}).get("order_ids", [])
                        sl_id = sl_order_ids[0] if sl_order_ids else None
                        _append_order_log("SL", inst, qty, sl_trigger, sl_id, "success", f"Stop loss placed ({sl_type}): {sl_id}")
                        position_state.set({
                            **position_state.get(),
                            "sl_order_id": sl_id,
                            "sl_placed": True,
                            "sl_attempts": 0,
                            "sl_next_retry_ts": None,
                        })
                        trade_status_msg.set(f"[OK] Entry + SL placed ({mode_msg})")
                    else:
                        error_msg = sl_resp.get("errors", [{}])[0].get("message", sl_resp.get("message", "Unknown error"))
                        _append_order_log("SL", inst, qty, sl_trigger, None, "error", f"SL ({sl_type}) failed: {error_msg}")
                        trade_status_msg.set(f"[ERROR] Stop loss order failed: {error_msg}")
                _refresh_funds()

            if sell_signal:
                state = position_state.get() or {}
                sl_id = state.get("sl_order_id")
                if sl_id:
                    try:
                        cancel_resp = _cancel_order_safe(trade_client, token_val, sl_id)
                        if cancel_resp.get("status") != "success":
                            raise RuntimeError(cancel_resp.get("errors", [{}])[0].get("message", "Cancel failed"))
                        _append_order_log("CANCEL", inst, state.get("qty"), price, sl_id, "success", "SL canceled")
                    except Exception as cancel_exc:
                        _append_order_log("CANCEL", inst, state.get("qty"), price, sl_id, "error", str(cancel_exc))

                exit_id = None
                exit_ok = False
                if is_production:
                    segment = ""
                    try:
                        segment = str(inst).split("|", 1)[0]
                    except Exception:
                        segment = ""
                    exit_all_resp = _exit_all_positions_safe(token_val, segment=segment or None, tag="qfad-entry")
                    logger.info("Exit all positions response: %s", exit_all_resp)
                    if exit_all_resp.get("status") in {"success", "partial_success"}:
                        exit_ids = exit_all_resp.get("data", {}).get("order_ids", []) if isinstance(exit_all_resp.get("data"), dict) else []
                        exit_id = exit_ids[0] if exit_ids else None
                        _append_order_log("EXIT_ALL", inst, state.get("qty"), price, exit_id, "success", f"Exit-all placed: {exit_id}")
                        exit_ok = True
                    else:
                        error_msg = exit_all_resp.get("errors", [{}])[0].get("message", exit_all_resp.get("message", "Unknown error"))
                        _append_order_log("EXIT_ALL", inst, state.get("qty"), price, None, "error", f"Exit-all failed: {error_msg}")

                if not exit_ok:
                    exit_payload = {
                        "quantity": state.get("qty"),
                        "product": state.get("product") or product_type,
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
                    exit_resp = _place_order_safe(trade_client, token_val, exit_payload)
                    logger.info("Exit order response: %s", exit_resp)
                    exit_status = exit_resp.get("status", "")
                    if exit_status == "success":
                        exit_order_ids = exit_resp.get("data", {}).get("order_ids", [])
                        exit_id = exit_order_ids[0] if exit_order_ids else None
                        _append_order_log("SELL", inst, state.get("qty"), price, exit_id, "success", f"Exit placed: {exit_id}")
                        exit_ok = True
                    else:
                        error_msg = exit_resp.get("errors", [{}])[0].get("message", exit_resp.get("message", "Unknown error"))
                        _append_order_log("SELL", inst, state.get("qty"), price, None, "error", f"Exit failed: {error_msg}")
                        trade_status_msg.set(f"[ERROR] Exit order failed: {error_msg}")
                        return

                entry_fill = state.get("entry_fill_price") or state.get("entry_price")
                est_pnl = None
                try:
                    if entry_fill is not None and state.get("qty"):
                        est_pnl = round((float(price) - float(entry_fill)) * float(state.get("qty")), 2)
                except Exception:
                    est_pnl = None
                est_pnl_pct = None
                try:
                    if entry_fill is not None and float(entry_fill) != 0:
                        est_pnl_pct = round(((float(price) - float(entry_fill)) / float(entry_fill)) * 100.0, 2)
                except Exception:
                    est_pnl_pct = None
                if exit_id:
                    _update_order_log(
                        exit_id,
                        fill_price=price,
                        entry_price_ref=entry_fill,
                        pnl=est_pnl,
                        pnl_pct=est_pnl_pct,
                        message=f"Exit placed @ {price}",
                    )
                last_realized_pnl.set(est_pnl)
                if exit_id:
                    pending_exit.set({
                        "exit_order_id": exit_id,
                        "entry_fill_price": entry_fill,
                        "qty": state.get("qty"),
                        "instrument": inst,
                        "placed_price": price,
                        "is_production": is_production,
                    })
                position_state.set({
                    "open": False,
                    "entry_order_id": None,
                    "sl_order_id": None,
                    "entry_price": None,
                    "entry_fill_price": None,
                    "qty": 0,
                    "instrument": None,
                    "product": None,
                    "sl_pct": None,
                    "sl_placed": False,
                    "sl_attempts": 0,
                    "sl_next_retry_ts": None,
                })
                mode_msg = "production" if is_production else "sandbox"
                trade_status_msg.set(f"[OK] Exit placed ({mode_msg})")
                _refresh_funds()

            last_signal_key.set(signal_key)

        except Exception as exc:
            err = _extract_http_error_message(exc)
            trade_status_msg.set(f"[ERROR] Trading error: {err}")
            _append_order_log("ERROR", inst, qty, price, None, "error", err)

    def _calculate_qty(price, capital, lot_size):
        if price is None or price <= 0:
            return 0
        qty = int(capital // price)
        if lot_size and lot_size > 1:
            qty = (qty // lot_size) * lot_size
        return max(qty, 0)

    @reactive.effect
    @reactive.event(input.refresh_order_history)
    def _refresh_order_history():
        _refresh_order_history_data(update_status=True, auto=False)

    def _get_sandbox_token():
        ui_token = input.sandbox_token().strip()
        if ui_token:
            return ui_token
        return os.getenv("UPSTOX_SANDBOX_TOKEN", "").strip()

    @reactive.effect
    @reactive.event(input.start_sandbox)
    def _start_sandbox_trading():
        token_val = _get_sandbox_token()
        if not token_val:
            trade_status_msg.set("[ERROR] Provide sandbox token to start trading")
            return
        live_trading_mode.set("sandbox")
        live_trading_enabled.set(True)
        trade_status_msg.set("[OK] Sandbox trading enabled")

    @reactive.effect
    @reactive.event(input.stop_sandbox)
    def _stop_sandbox_trading():
        live_trading_enabled.set(False)
        live_trading_mode.set(None)
        trade_status_msg.set("[INFO] Sandbox trading stopped")

    @reactive.effect
    @reactive.event(input.start_live)
    def _start_live_trading():
        if not input.confirm_live_trading():
            trade_status_msg.set("[ERROR] Confirm live trading checkbox before starting")
            return
        if not token.get():
            trade_status_msg.set("[ERROR] Authenticate to use live trading")
            return
        if not funds_available.get():
            trade_status_msg.set("[ERROR] Funds unavailable; refresh or login again")
            return
        live_trading_mode.set("live")
        live_trading_enabled.set(True)
        trade_status_msg.set("[OK] Live trading enabled (production)")

    @reactive.effect
    @reactive.event(input.stop_live)
    def _stop_live_trading():
        live_trading_enabled.set(False)
        live_trading_mode.set(None)
        trade_status_msg.set("[INFO] Live trading stopped")

    @reactive.effect
    def _resolve_live_fills():
        if not live_trading_enabled.get():
            reactive.invalidate_later(3)
            return
        if not _use_production_trading():
            reactive.invalidate_later(3)
            return
        access_token = token.get()
        if not access_token:
            reactive.invalidate_later(3)
            return

        state = position_state.get() or {}
        entry_id = state.get("entry_order_id")
        if entry_id and not state.get("entry_fill_price"):
            avg_price, status, _ = _fetch_order_fill(entry_id, access_token)
            if avg_price and ("complete" in status or "filled" in status):
                position_state.set({
                    **state,
                    "entry_fill_price": avg_price,
                    "entry_price": avg_price,
                })
                _update_order_log(entry_id, fill_price=avg_price, message=f"Entry filled @ {avg_price}")
                state = position_state.get() or {}

        # In production, place SL only after entry fill is confirmed.
        retry_after = state.get("sl_next_retry_ts") or 0
        now_ts = _dt.now().timestamp()
        if state.get("open") and not state.get("sl_placed") and state.get("entry_fill_price") and now_ts >= float(retry_after):
            inst = state.get("instrument")
            qty = state.get("qty") or 0
            product = state.get("product") or input.live_product_type()
            sl_pct = state.get("sl_pct") or input.live_sl_percent()
            entry_fill = state.get("entry_fill_price")
            tick_size = instrument_manager.get_tick_size(inst, default=0.05)
            sl_trigger = _round_to_tick(float(entry_fill) * (1 - (float(sl_pct) / 100.0)), tick_size)
            sl_resp, sl_type = _place_stop_loss_order(
                client, access_token, inst, qty, product, sl_trigger, tick_size
            )
            logger.info("Deferred SL order response: %s", sl_resp)
            if sl_resp.get("status") == "success":
                sl_ids = sl_resp.get("data", {}).get("order_ids", [])
                sl_id = sl_ids[0] if sl_ids else None
                _append_order_log("SL", inst, qty, sl_trigger, sl_id, "success", f"Stop loss placed ({sl_type}): {sl_id}")
                position_state.set({
                    **state,
                    "sl_order_id": sl_id,
                    "sl_placed": True,
                    "sl_attempts": 0,
                    "sl_next_retry_ts": None,
                })
                trade_status_msg.set("[OK] Entry filled and SL placed")
            else:
                error_msg = sl_resp.get("errors", [{}])[0].get("message", sl_resp.get("message", "Unknown error"))
                attempts = int(state.get("sl_attempts") or 0) + 1
                next_retry = _dt.now().timestamp() + 30
                _append_order_log("SL", inst, qty, sl_trigger, None, "error", f"SL ({sl_type}) failed: {error_msg}")
                position_state.set({
                    **state,
                    "sl_attempts": attempts,
                    "sl_next_retry_ts": next_retry,
                })
                trade_status_msg.set(f"[ERROR] Stop loss order failed ({sl_type}): {error_msg}. Retrying in 30s")

        pending = pending_exit.get()
        if pending and pending.get("exit_order_id"):
            exit_id = pending.get("exit_order_id")
            avg_price, status, _ = _fetch_order_fill(exit_id, access_token)
            if avg_price and ("complete" in status or "filled" in status):
                entry_fill = pending.get("entry_fill_price")
                qty = pending.get("qty") or 0
                pnl = None
                try:
                    if entry_fill is not None and qty:
                        pnl = round((avg_price - float(entry_fill)) * float(qty), 2)
                except Exception:
                    pnl = None
                pnl_pct = None
                try:
                    if entry_fill is not None and float(entry_fill) != 0:
                        pnl_pct = round(((float(avg_price) - float(entry_fill)) / float(entry_fill)) * 100.0, 2)
                except Exception:
                    pnl_pct = None
                _update_order_log(
                    exit_id,
                    fill_price=avg_price,
                    entry_price_ref=entry_fill,
                    pnl=pnl,
                    pnl_pct=pnl_pct,
                    message=f"Exit filled @ {avg_price}",
                )
                last_realized_pnl.set(pnl)
                pending_exit.set(None)

        reactive.invalidate_later(3)

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
                save_to_csv(df, base_dir=base_dir)
                status_msg.set(f"[OK] Fetched & processed {len(df)} rows (current day only).")
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
        _ = websocket_chart_tick.get()
        df = df_data.get()
        if df is None or df.empty:
            fig = go.Figure()
            fig.update_layout(title="No data available. Click 'Fetch & Process' to load data.", height=700)
            return fig
        try:
            return plot_signals(df)
        except Exception as e:
            traceback.print_exc()
            logger.exception("Chart render error: %s", e)
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
        out["qty"] = pd.to_numeric(out.get("qty"), errors="coerce")
        out["pnl"] = pd.to_numeric(out.get("pnl"), errors="coerce")
        out["entry_price_ref"] = pd.to_numeric(out.get("entry_price_ref"), errors="coerce")
        out["pnl_pct"] = pd.to_numeric(out.get("pnl_pct"), errors="coerce")

        # Backfill pnl% when possible from pnl / (entry_price_ref * qty)
        can_derive_pct = (
            out["pnl_pct"].isna()
            & out["pnl"].notna()
            & out["entry_price_ref"].notna()
            & out["qty"].notna()
            & ((out["entry_price_ref"] * out["qty"]) != 0)
        )
        out.loc[can_derive_pct, "pnl_pct"] = (
            out.loc[can_derive_pct, "pnl"] / (out.loc[can_derive_pct, "entry_price_ref"] * out.loc[can_derive_pct, "qty"])
        ) * 100.0

        total_pnl = round(float(out["pnl"].dropna().sum()), 2) if out["pnl"].notna().any() else 0.0
        notional = out["entry_price_ref"] * out["qty"]
        total_notional = float(notional.where(out["pnl"].notna(), np.nan).dropna().sum()) if notional.notna().any() else 0.0
        total_pnl_pct = round((total_pnl / total_notional) * 100.0, 2) if total_notional else np.nan

        summary_row = {col: "" for col in out.columns}
        summary_row["action"] = "TOTAL"
        summary_row["pnl"] = total_pnl
        summary_row["pnl_pct"] = total_pnl_pct
        out = pd.concat([out, pd.DataFrame([summary_row])], ignore_index=True)

        if "pnl" in out.columns:
            out["pnl"] = out["pnl"].apply(lambda x: round(float(x), 2) if pd.notna(x) and x != "" else x)
        if "pnl_pct" in out.columns:
            out["pnl_pct"] = out["pnl_pct"].apply(lambda x: round(float(x), 2) if pd.notna(x) and x != "" else x)

        if "pnl_pct" in out.columns:
            out.rename(columns={"pnl_pct": "PnL %"}, inplace=True)
        return render.DataTable(out, width="100%", height="calc(100vh - 260px)")

    @output
    @render.data_frame
    def order_history_table():
        from shiny import render
        df = order_history_data.get()
        if df is None or df.empty:
            return render.DataTable(pd.DataFrame({"Message": ["No order history loaded"]}))
        styles = []
        if "side" in df.columns:
            side_s = df["side"].astype(str).str.upper()
            styles.append({
                "cols": ["side"],
                "rows": side_s.eq("BUY").tolist(),
                "style": {"color": "#67d49b", "font-weight": "700"},
            })
            styles.append({
                "cols": ["side"],
                "rows": side_s.eq("SELL").tolist(),
                "style": {"color": "#ff7c6a", "font-weight": "700"},
            })

        if "PnL" in df.columns:
            pnl_s = pd.to_numeric(df["PnL"], errors="coerce")
            styles.append({
                "cols": ["PnL"],
                "rows": pnl_s.gt(0).fillna(False).tolist(),
                "style": {"color": "#67d49b", "font-weight": "700"},
            })
            styles.append({
                "cols": ["PnL"],
                "rows": pnl_s.lt(0).fillna(False).tolist(),
                "style": {"color": "#ff7c6a", "font-weight": "700"},
            })

        if "PnL %" in df.columns:
            pnlp_s = pd.to_numeric(df["PnL %"].astype(str).str.replace("%", "", regex=False), errors="coerce")
            styles.append({
                "cols": ["PnL %"],
                "rows": pnlp_s.gt(0).fillna(False).tolist(),
                "style": {"color": "#67d49b", "font-weight": "700"},
            })
            styles.append({
                "cols": ["PnL %"],
                "rows": pnlp_s.lt(0).fillna(False).tolist(),
                "style": {"color": "#ff7c6a", "font-weight": "700"},
            })

        return render.DataTable(df, width="100%", height="calc(100vh - 320px)", styles=styles)

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
