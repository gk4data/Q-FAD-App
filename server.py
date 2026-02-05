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

    # ===== Reactive State =====
    token = reactive.Value(None)
    df_data = reactive.Value(pd.DataFrame())
    backtest_summary_data = reactive.Value({})
    trades_data = reactive.Value(pd.DataFrame())
    initial_cash_used = reactive.Value(100000)
    login_url = reactive.Value("")
    status_msg = reactive.Value("Starting app...")

    # Instrument selector state
    instruments_loaded = reactive.Value(False)
    available_symbols = reactive.Value([])
    available_expiries = reactive.Value([])
    available_strikes = reactive.Value([])
    selected_symbol = reactive.Value(None)
    selected_expiry = reactive.Value(None)
    selected_strike = reactive.Value(None)
    selected_instrument_key = reactive.Value(None)


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
                if instrument_manager.fetch_instruments(force_refresh=False, prefer_local=False):
                    symbols = instrument_manager.get_unique_symbols()
                    symbols = [s for s in symbols if str(s).upper() == "NIFTY"]
                    available_symbols.set(symbols)
                    instruments_loaded.set(True)
                    status_msg.set(f"[OK] Instruments auto-loaded: {len(symbols)} symbols")
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
    def instruments_status():
        if instruments_loaded.get():
            src = getattr(instrument_manager, 'source', None)
            src_display = f" ({src})" if src else ""
            return f"[OK] Ready | {len(available_symbols.get())} symbols loaded{src_display}"
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

    # ===== Instrument Loading & Selection =====
    @reactive.effect
    @reactive.event(input.load_instruments)
    def _load_instruments():
        try:
            status_msg.set("[INFO] Loading instruments...")
            loaded = instrument_manager.fetch_instruments(force_refresh=True, prefer_local=False)
            if loaded:
                symbols = instrument_manager.get_unique_symbols()
                symbols = [s for s in symbols if str(s).upper() == "NIFTY"]
                available_symbols.set(symbols)
                instruments_loaded.set(True)
                status_msg.set(f"[OK] Loaded {len(symbols)} symbols (source: {getattr(instrument_manager, 'source', 'unknown')})")
            else:
                status_msg.set("[ERROR] Failed to load instruments")
        except Exception as e:
            status_msg.set(f"[ERROR] Error: {e}")
            traceback.print_exc()

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
        min_date = min(expiry_dates)
        max_date = max(expiry_dates)

        logger.debug("expiry_selector default (date): %s", default)
        return ui.input_date("select_expiry", "Choose Expiry", value=default, min=min_date, max=max_date)

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

    @output
    @render.ui
    def selected_instrument_display():
        key = selected_instrument_key.get()
        if key:
            return ui.div(
                ui.tags.strong("Selected: "),
                ui.tags.code(key, style="background-color: #f0f0f0; padding: 5px; border-radius: 3px; font-weight: bold;"),
                style="padding: 10px; background-color: #e8f5e9; border-left: 4px solid green; margin: 10px 0;"
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
                        ui.tags.td(ui.strong(k + ":")),
                        ui.tags.td(formatted_v)
                    )
                )
            return ui.div(
                ui.h4("Backtest Results"),
                ui.tags.table(
                    ui.tags.tbody(*rows),
                    style="border-collapse: collapse; width: 100%; margin-top: 10px; border: 1px solid #ddd;",
                ),
                style="padding: 20px; background-color: #f8f9fa; border-radius: 5px;"
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
