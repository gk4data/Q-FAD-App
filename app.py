# app.py - UPDATED WITH INSTRUMENT FILTERING
# Aligned with Q-FAD APP project structure

import os
import traceback
import pandas as pd
import numpy as np
from datetime import date
from shiny import App, ui, render, reactive
from shinywidgets import output_widget, render_plotly

# Project imports - aligned with your structure
from src.clients.upstox_client import UpstoxClient
from src.data.data_fetcher import fetch_intraday_data, concatenate_with_previous_day, filter_to_current_day
from src.data.instrument_manager import InstrumentManager  # NEW
from src.indicators.indicators import calculate_indicators
from src.signals.regime_detection import detect_regimes_relaxed
from src.signals.angle_classification import classify_trend_by_angles
from src.signals.generator import add_long_signal
from src.data.save_results import save_to_csv
from src.viz.plot_signals import plot_signals
from src.backtest.backtest_engine import calculate_manual_pnl, get_summary_stats_manual


# ---------------------------
# UI setup
# ---------------------------
app_ui = ui.page_sidebar(
    ui.sidebar(
        ui.h4("Authentication"),
        ui.output_text_verbatim("auth_status"),
        ui.input_action_button("show_login", "Show Login URL", class_="btn-primary"),
        ui.output_ui("login_url_display"),
        ui.input_text("auth_code", "Paste auth code here", placeholder="enter code"),
        ui.input_action_button("do_auth", "Exchange code for token", class_="btn-success"),
        ui.input_action_button("clear_cache", "Logout (Clear Cache)", class_="btn-danger btn-sm"),
        ui.tags.hr(),

        # NEW: Instrument Selector Section
        ui.h4("Instrument Selector"),
        ui.row(
            ui.column(
                4,
                ui.input_action_button("load_instruments", "Load Instruments", class_="btn-info btn-sm"),
            ),
            ui.column(
                4,
                ui.input_checkbox("auto_load_instruments", "Auto-load", value=True)
            ),
            ui.column(
                4,
                ui.input_checkbox("use_local_instruments", "Use local NSE_Output.xlsx", value=True)
            )
        ),
        ui.output_text_verbatim("instruments_status"),
        ui.output_text_verbatim("instruments_debug"),
        ui.tags.hr(),
        
        # Symbol, Expiry, Type Selection
        ui.h5("Step 1: Select Symbol"),
        ui.output_ui("symbol_selector"),
        
        ui.h5("Step 2: Select Expiry"),
        ui.output_ui("expiry_selector"),
        
        ui.h5("Step 3: Select Type"),
        ui.input_radio_buttons(
            "select_type", "Instrument Type",
            choices={"CE": "Call (CE)", "PE": "Put (PE)", "FUT": "Futures (FUT)"},
            selected="CE", inline=False
        ),
        
        ui.h5("Step 4: Select Strike"),
        ui.output_ui("strike_selector"),
        
        ui.row(
            ui.column(4, ui.input_action_button("apply_instrument", "Apply Selection", class_="btn-success btn-sm")),
            ui.column(8, ui.output_ui("selected_instrument_display"))
        ),
        ui.tags.hr(),

        ui.h4("Data & Processing"),
        ui.input_text("instrument", "Instrument Key", value="NSE_FO|40088", placeholder="Auto-filled or manual"),
        ui.input_select("interval", "Interval", choices=["1minute", "5minute", "15minute"], selected="1minute"),
        ui.input_radio_buttons(
            "fetch_mode", "Fetch mode",
            choices={"intraday": "Intraday (session)", "date_range": "Active Options Date Range", "expired": "Expired Options (date range)"},
            selected="date_range", inline=True
        ),
        ui.panel_conditional(
            "input.fetch_mode === 'date_range' || input.fetch_mode === 'expired'",
            ui.input_date("start_date", "Start", value=date.today()),
            ui.input_date("end_date", "End", value=date.today()),
        ),
        ui.input_action_button("fetch", "Fetch & Process", class_="btn-primary"),
        ui.input_checkbox("auto_save", "Save CSV after fetch", value=True),
        ui.input_text("save_dir", "Optional Save Directory", value=""),
        ui.tags.hr(),

        ui.h4("Backtesting"),
        ui.input_numeric("initial_cash", "Initial Capital ($)", value=100000, min=1000, max=10000000),
        ui.input_action_button("run_backtest", "Run Backtest", class_="btn-warning"),
        ui.tags.hr(),

        ui.p("Status:"),
        ui.output_text_verbatim("status")
    ),
    ui.navset_tab(
        ui.nav_panel("Chart", output_widget("price_plot")),
        ui.nav_panel(
            "Signals Table",
            ui.download_button("download_csv", "Download CSV", class_="btn-success mb-3"),
            ui.output_data_frame("signals_table")
        ),
        ui.nav_panel(
            "Backtest Summary",
            ui.output_ui("backtest_summary")
        ),
        ui.nav_panel(
            "Trade Log",
            ui.output_data_frame("trades_table")
        ),
    ),
    title="Upstox Algo Trading (Q-FAD)"
)


# ---------------------------
# Server logic
# ---------------------------
def server(input, output, session):
    client = UpstoxClient(use_cache=True)
    instrument_manager = InstrumentManager()  # NEW

    # Reactive state
    token = reactive.Value(None)
    df_data = reactive.Value(pd.DataFrame())
    backtest_summary_data = reactive.Value({})
    trades_data = reactive.Value(pd.DataFrame())
    initial_cash_used = reactive.Value(100000)
    login_url = reactive.Value("")
    status_msg = reactive.Value("Starting app...")

    # NEW: Instrument selector state
    instruments_loaded = reactive.Value(False)
    available_symbols = reactive.Value([])
    available_expiries = reactive.Value([])
    available_strikes = reactive.Value([])
    selected_symbol = reactive.Value(None)
    selected_expiry = reactive.Value(None)
    selected_strike = reactive.Value(None)
    selected_instrument_key = reactive.Value(None)

    # Try cache token at startup
    @reactive.effect
    def _init():
        cached = client.get_cached_token()
        if cached:
            token.set(cached)
            status_msg.set("[OK] Using cached token (valid for 24h)")
        else:
            status_msg.set("[INFO] No valid token. Click 'Show Login URL' to authenticate.")

    # NEW: Auto-load instruments on startup
    @reactive.effect
    def _auto_load_instruments():
        if input.auto_load_instruments():
            try:
                instruments_loaded.set(False)
                prefer_local = input.use_local_instruments() if 'use_local_instruments' in dir(input) else True
                if instrument_manager.fetch_instruments(force_refresh=False, prefer_local=prefer_local):
                    symbols = instrument_manager.get_unique_symbols()
                    available_symbols.set(symbols)
                    instruments_loaded.set(True)
                    status_msg.set(f"[OK] Instruments auto-loaded: {len(symbols)} symbols")
            except Exception as e:
                print(f"Auto-load error: {e}")

    # Auth status
    @output
    @render.text
    def auth_status():
        t = token.get()
        if t:
            return "[OK] Authenticated (cached token valid)"
        else:
            return "[ERROR] Not authenticated"

    # Status text
    @output
    @render.text
    def status():
        return status_msg.get()

    # NEW: Instruments status
    @output
    @render.text
    def instruments_status():
        if instruments_loaded.get():
            src = getattr(instrument_manager, 'source', None)
            src_display = f" ({src})" if src else ""
            return f"[OK] Ready | {len(available_symbols.get())} symbols loaded{src_display}"
        else:
            return "[INFO] Click 'Load Instruments' or enable Auto-load"

    # DEBUG: Instruments debug info (temporary)
    @output
    @render.text
    def instruments_debug():
        sel = None
        if 'select_symbol' in dir(input):
            try:
                sel = input.select_symbol()
            except Exception:
                sel = None
        return (
            f"selected_symbol: {sel}\n"
            f"instruments_loaded: {instruments_loaded.get()}\n"
            f"available_symbols: {len(available_symbols.get())}\n"
            f"available_expiries: {len(available_expiries.get())}\n"
            f"available_strikes: {len(available_strikes.get())}\n"
        )

    # Show login URL
    @reactive.effect
    @reactive.event(input.show_login)
    def _():
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
        url = login_url.get()
        if not url:
            return ui.div()
        return ui.div(
            ui.p("Open this URL in your browser:"),
            ui.tags.a("Upstox Login", href=url, target="_blank", class_="btn btn-link"),
            ui.tags.hr(),
            ui.tags.code(url, style="font-size:0.8em;word-wrap:break-word;")
        )

    # Exchange code for token
    @reactive.effect
    @reactive.event(input.do_auth)
    def _():
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

    # Clear token cache
    @reactive.effect
    @reactive.event(input.clear_cache)
    def _():
        if client.token_manager:
            client.token_manager.clear_token()
        token.set(None)
        status_msg.set("[OK] Token cache cleared. Click 'Show Login URL' to re-authenticate.")

    # NEW: Load instruments button
    @reactive.effect
    @reactive.event(input.load_instruments)
    def _():
        try:
            status_msg.set("[INFO] Loading instruments...")
            # If user wants to force API reload despite local file, they can clear the checkbox
            prefer_local = input.use_local_instruments() if 'use_local_instruments' in dir(input) else True
            # When user actively clicks 'Load Instruments' we allow refresh from API by passing force_refresh=True
            loaded = instrument_manager.fetch_instruments(force_refresh=True, prefer_local=prefer_local)
            if loaded:
                symbols = instrument_manager.get_unique_symbols()
                available_symbols.set(symbols)
                instruments_loaded.set(True)
                status_msg.set(f"[OK] Loaded {len(symbols)} symbols (source: {getattr(instrument_manager, 'source', 'unknown')})")
            else:
                status_msg.set("[ERROR] Failed to load instruments")
        except Exception as e:
            status_msg.set(f"[ERROR] Error: {e}")
            traceback.print_exc()

    # NEW: Symbol selector UI
    @output
    @render.ui
    def symbol_selector():
        symbols = available_symbols.get()
        if not symbols:
            return ui.div("Load instruments first", style="color: #999;")
        print(f"[DEBUG] symbol_selector render: {len(symbols)} symbols, default={symbols[0]}")
        # Default to first symbol so expiry update triggers immediately
        return ui.input_select("select_symbol", "Choose Symbol", choices=symbols, selected=symbols[0])

    # NEW: Update expiries when symbol changes
    @reactive.effect
    def _update_expiries():
        symbol = input.select_symbol()
        print(f"[DEBUG] _update_expiries triggered: symbol={symbol}, instruments_loaded={instruments_loaded.get()}")
        if not symbol:
            return
        if symbol and instruments_loaded.get():
            try:
                expiries = instrument_manager.get_expiry_dates(symbol)
                print(f"[DEBUG] _update_expiries: fetched {len(expiries)} expiries for {symbol}")
                available_expiries.set(expiries)
                selected_symbol.set(symbol)
            except Exception as e:
                available_expiries.set([])
                print(f"[ERROR] Error fetching expiries: {e}")

    # NEW: Expiry selector UI (calendar picker)
    @output
    @render.ui
    def expiry_selector():
        expiries = available_expiries.get()
        print(f"[DEBUG] expiry_selector render: {len(expiries)} expiries available")
        if not expiries:
            return ui.div("Select symbol first", style="color: #999;")

        # Convert expiry strings (YYYY-MM-DD) to date objects for the calendar picker
        try:
            expiry_dates = [pd.to_datetime(x).date() for x in expiries]
        except Exception:
            expiry_dates = []

        if not expiry_dates:
            return ui.div("No valid expiries", style="color: #999;")

        default = expiry_dates[0]
        min_date = min(expiry_dates)
        max_date = max(expiry_dates)

        print(f"[DEBUG] expiry_selector default (date): {default}")
        return ui.input_date("select_expiry", "Choose Expiry", value=default, min=min_date, max=max_date)

    # NEW: Update strikes when symbol or type changes
    @reactive.effect
    def _update_strikes():
        symbol = input.select_symbol()
        expiry = input.select_expiry()
        instr_type = input.select_type()

        print(f"[DEBUG] _update_strikes triggered: symbol={symbol}, expiry={expiry}, type={instr_type}, instruments_loaded={instruments_loaded.get()}")

        # If futures selected, no strikes to compute
        if instr_type and instr_type.upper() == 'FUT':
            available_strikes.set([])
            selected_expiry.set(expiry)
            print(f"[DEBUG] FUT selected -> available_strikes cleared")
            return

        if not (symbol and expiry and instruments_loaded.get()):
            return
        if symbol and expiry and instruments_loaded.get():
            try:
                strikes = instrument_manager.get_strikes(symbol, expiry, instr_type)
                print(f"[DEBUG] _update_strikes: fetched {len(strikes)} strikes")
                available_strikes.set(strikes)
                selected_expiry.set(expiry)
            except Exception as e:
                available_strikes.set([])
                print(f"[ERROR] Error fetching strikes: {e}")

    # NEW: Strike selector UI (always present for options)
    @output
    @render.ui
    def strike_selector():
        strikes = available_strikes.get()
        instr_type = input.select_type()
        print(f"[DEBUG] strike_selector render: instr_type={instr_type}, strikes_count={len(strikes) if strikes else 0}")

        # For futures, no strike selection is required
        if instr_type and instr_type.upper() == 'FUT':
            return ui.div("Futures selected — no strike required", style="color: #333;")

        # Prefill with a suggested strike when available, else empty
        default = str(strikes[0]) if strikes else ""
        print(f"[DEBUG] strike_selector default (manual): {default}")

        helper = ui.div("No strikes found — enter strike manually", style="color: #999;") if not strikes else ui.div(f"Suggested: {', '.join(str(s) for s in strikes[:6])}", style="color: #666; font-size:0.9em")

        return ui.tags.div(
            ui.input_text("select_strike", "Strike (enter numeric)", value=default, placeholder="e.g. 23100"),
            helper
        )

    # NEW: Apply instrument selection
    @reactive.effect
    @reactive.event(input.apply_instrument)
    def _():
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
                strike = int(strike_val)
                key = instrument_manager.get_instrument_key(symbol, expiry, strike, instr_type)
                strike_display = str(strike)

            if key:
                selected_instrument_key.set(key)
                selected_strike.set(strike_val if instr_type != 'FUT' else None)
                # Populate the Data & Processing Instrument Key input so the user can fetch immediately
                try:
                    # Use the Shiny helper to update text input value so it's compatible across versions
                    ui.update_text("instrument", value=key, session=session)
                    print(f"[DEBUG] ui.update_text instrument={key}")
                except Exception as e:
                    print(f"[WARN] Could not update input instrument via ui.update_text: {e}")
                status_msg.set(f"[OK] Selected: {symbol} {expiry} {strike_display} {instr_type}")
            else:
                status_msg.set(f"[ERROR] Instrument not found")
        except Exception as e:
            status_msg.set(f"[ERROR] Error: {e}")
            traceback.print_exc()

    # NEW: Display selected instrument
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

    # Sync selected instrument key into the 'instrument' input field so it is prefilled for fetching
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
                    print(f"[DEBUG] _sync_selected_instrument set instrument={key}")
                except Exception as e:
                    print(f"[WARN] Could not update input instrument via ui.update_text in sync: {e}")
        except Exception as e:
            print(f"[WARN] _sync_selected_instrument error: {e}")

    # Fetch and process data
    @reactive.effect
    @reactive.event(input.fetch)
    def _():
        if not token.get():
            status_msg.set("[ERROR] Authenticate first before fetching data")
            return
        try:
            # Use selected instrument if available, else manual input
            key = selected_instrument_key.get()
            inst = key if key else input.instrument().strip()

            if not inst or inst == "NSE_FO|40088":
                status_msg.set("[ERROR] Please select an instrument")
                return

            interval = input.interval()
            mode = input.fetch_mode()

            status_msg.set(f"[INFO] Fetching data for {inst}...")

            if mode == "intraday":
                status_msg.set(f"[INFO] Fetching intraday data for {inst} ({interval})...")
                raw_df = fetch_intraday_data(
                    inst, token.get(), interval=interval, mode="intraday"
                )
            elif mode == "date_range":
                status_msg.set(f"[INFO] Fetching {interval} data for {inst} from {start} to {end}...")
                start_val = input.start_date()
                end_val = input.end_date()
                # Accept date object or string; normalize to YYYY-MM-DD
                from datetime import date as _date, datetime as _dt
                def _as_iso(d):
                    if isinstance(d, (_date, _dt)):
                        return d.strftime("%Y-%m-%d")
                    if d is None:
                        return None
                    s = str(d).strip()
                    return s

                start = _as_iso(start_val)
                end = _as_iso(end_val)

                if not start or not end:
                    status_msg.set("[ERROR] Please provide start and end dates")
                    return

                raw_df = fetch_intraday_data(
                    inst, token.get(), interval=interval, mode="date_range", start=start, end=end
                )
            elif mode == "expired":
                # Use the selected expiry from the expiry_selector and the start/end dates
                start_val = input.start_date()
                end_val = input.end_date()
                expiry_val = None
                try:
                    expiry_val = input.select_expiry()
                except Exception:
                    expiry_val = None

                from datetime import date as _date, datetime as _dt
                def _as_iso(d):
                    if isinstance(d, (_date, _dt)):
                        return d.strftime("%Y-%m-%d")
                    if d is None:
                        return None
                    s = str(d).strip()
                    return s

                start = _as_iso(start_val)
                end = _as_iso(end_val)

                if not start or not end:
                    status_msg.set("[ERROR] Please provide start and end dates")
                    return

                if not expiry_val:
                    status_msg.set("[ERROR] Please choose an expiry date (used for expired instruments)")
                    return

                # Pass expiry as ISO (YYYY-MM-DD); the fetcher will convert to DD-MM-YYYY for the URL
                expiry_iso = _as_iso(expiry_val)

                # Ensure we have a valid base instrument key (e.g., 'NSE_FO|49792').
                # If the user provided a manual 'instrument' that already contains an expiry
                # part (e.g., 'NSE_FO|49792|23-12-2025'), split it; otherwise try to derive
                # the base key from selected instrumentation state.
                base_inst = inst
                # If instrument string includes two pipes, it likely contains an expiry suffix
                if base_inst and base_inst.count('|') >= 2:
                    parts = base_inst.split('|')
                    # base = first two parts (e.g., NSE_FO|49792)
                    base_inst = '|'.join(parts[:2])
                    print(f"[DEBUG] Stripped expiry from instrument input, base_inst={base_inst}")
                # If instrument looks like a symbol rather than a key, try selected_instrument_key
                if not base_inst or '|' not in base_inst:
                    candidate = selected_instrument_key.get()
                    if candidate:
                        base_inst = candidate
                        print(f"[DEBUG] Using selected_instrument_key as base_inst: {base_inst}")
                    else:
                        # Try to build base key from symbol/strike/expiry/type
                        symbol = selected_symbol.get() or input.select_symbol() if 'select_symbol' in dir(input) else None
                        strike_val = selected_strike.get() or (input.select_strike() if 'select_strike' in dir(input) else None)
                        instr_type = input.select_type() if 'select_type' in dir(input) else None
                        try:
                            if symbol and expiry_iso and instr_type:
                                strike_num = int(strike_val) if strike_val not in (None, "") else None
                                candidate_key = instrument_manager.get_instrument_key(symbol, expiry_iso, strike_num, instr_type)
                                if candidate_key:
                                    base_inst = candidate_key
                                    print(f"[DEBUG] Derived base_inst via InstrumentManager: {base_inst}")
                        except Exception as e:
                            print(f"[WARN] Could not derive base inst: {e}")

                if not base_inst or '|' not in base_inst:
                    status_msg.set("[ERROR] Could not determine base instrument key for expired fetch. Please Apply selection or enter a valid 'Instrument Key'.")
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

            # Determine the target date (the date we're fetching data for)
            from datetime import date as _date, datetime as _dt
            def _as_iso(d):
                if isinstance(d, (_date, _dt)):
                    return d.strftime("%Y-%m-%d")
                if d is None:
                    return None
                s = str(d).strip()
                return s

            # Get target date based on fetch mode
            if mode == "intraday":
                target_date_str = _as_iso(_dt.now().date())
            else:
                target_date_str = _as_iso(end_val)

            status_msg.set(f"[INFO] Concatenating with previous market day data...")
            
            # Concatenate with previous day's data for indicator calculation warmup
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
            
            # Filter back to current day only after indicators are calculated
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

    # Run backtest
    @reactive.effect
    @reactive.event(input.run_backtest)
    def _():
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

    # Chart plot
    @output
    @render_plotly
    def price_plot():
        df = df_data.get()
        import plotly.graph_objects as go
        if df is None or df.empty:
            fig = go.Figure()
            fig.update_layout(
                title="No data available. Click 'Fetch & Process' to load data.",
                height=700
            )
            return fig
        try:
            return plot_signals(df)
        except Exception as e:
            traceback.print_exc()
            fig = go.Figure()
            fig.update_layout(title=f"Plot error: {e}", height=700)
            return fig

    # Signals table with 2 decimals
    @output
    @render.data_frame
    def signals_table():
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

    # Backtest summary UI
    @output
    @render.ui
    def backtest_summary():
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

    # Trades table with 2 decimals
    @output
    @render.data_frame
    def trades_table():
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

    # Download CSV
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


app = App(app_ui, server)

if __name__ == "__main__":
    print("🚀 Starting Q-FAD Upstox Algo Trading App...")
    print("Run with: shiny run --reload app.py")