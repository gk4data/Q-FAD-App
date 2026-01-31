# app.py - UPDATED WITH INSTRUMENT FILTERING
# Aligned with Q-FAD APP project structure

import os
import traceback
import pandas as pd
import numpy as np
from shiny import App, ui, render, reactive
from shinywidgets import output_widget, render_plotly

# Project imports - aligned with your structure
from src.clients.upstox_client import UpstoxClient
from src.data.data_fetcher import fetch_intraday_data
from src.data.instrument_manager import InstrumentManager  # NEW
from src.indicators.indicators import calculate_indicators
from src.signals.regime_detection import detect_regimes_relaxed
from src.signals.generator import add_long_signal
from src.data.save_results import save_to_csv
from src.viz.plot_signals import plot_signals
from src.backtest.backtest_engine import calculate_manual_pnl, get_summary_stats_manual


# ---------------------------
# UI setup
# ---------------------------
app_ui = ui.page_sidebar(
    ui.sidebar(
        ui.h4("🔐 Authentication"),
        ui.output_text_verbatim("auth_status"),
        ui.input_action_button("show_login", "Show Login URL", class_="btn-primary"),
        ui.output_ui("login_url_display"),
        ui.input_text("auth_code", "Paste auth code here", placeholder="enter code"),
        ui.input_action_button("do_auth", "Exchange code for token", class_="btn-success"),
        ui.input_action_button("clear_cache", "Logout (Clear Cache)", class_="btn-danger btn-sm"),
        ui.tags.hr(),

        # NEW: Instrument Selector Section
        ui.h4("🔧 Instrument Selector"),
        ui.row(
            ui.column(
                6,
                ui.input_action_button("load_instruments", "📥 Load Instruments", class_="btn-info btn-sm"),
            ),
            ui.column(
                6,
                ui.input_checkbox("auto_load_instruments", "Auto-load", value=True)
            )
        ),
        ui.output_text_verbatim("instruments_status"),
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
        
        ui.input_action_button("apply_instrument", "✅ Apply Selection", class_="btn-success btn-sm"),
        ui.output_ui("selected_instrument_display"),
        ui.tags.hr(),

        ui.h4("📊 Data & Processing"),
        ui.input_text("instrument", "Instrument Key", value="NSE_FO|40088", placeholder="Auto-filled or manual"),
        ui.input_select("interval", "Interval", choices=["1minute", "5minute", "15minute"], selected="1minute"),
        ui.input_radio_buttons(
            "fetch_mode", "Fetch mode",
            choices={"intraday": "Intraday (session)", "date_range": "Date range"},
            selected="date_range", inline=True
        ),
        ui.panel_conditional(
            "input.fetch_mode === 'date_range'",
            ui.input_text("start_date", "Start (YYYY-MM-DD or DD-MM-YYYY)", value="2025-11-04"),
            ui.input_text("end_date", "End (YYYY-MM-DD or DD-MM-YYYY)", value="2025-11-04"),
        ),
        ui.input_action_button("fetch", "Fetch & Process", class_="btn-primary"),
        ui.input_checkbox("auto_save", "Save CSV after fetch", value=True),
        ui.input_text("save_dir", "Optional Save Directory", value=""),
        ui.tags.hr(),

        ui.h4("📈 Backtesting"),
        ui.input_numeric("initial_cash", "Initial Capital ($)", value=100000, min=1000, max=10000000),
        ui.input_action_button("run_backtest", "Run Backtest", class_="btn-warning"),
        ui.tags.hr(),

        ui.p("📡 Status:"),
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
    title="📈 Upstox Algo Trading (Q-FAD)"
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
            status_msg.set("✅ Using cached token (valid for 24h)")
        else:
            status_msg.set("⏳ No valid token. Click 'Show Login URL' to authenticate.")

    # NEW: Auto-load instruments on startup
    @reactive.effect
    def _auto_load_instruments():
        if input.auto_load_instruments():
            try:
                instruments_loaded.set(False)
                if instrument_manager.fetch_instruments(force_refresh=False):
                    symbols = instrument_manager.get_unique_symbols()
                    available_symbols.set(symbols)
                    instruments_loaded.set(True)
                    status_msg.set(f"✅ Instruments auto-loaded: {len(symbols)} symbols")
            except Exception as e:
                print(f"Auto-load error: {e}")

    # Auth status
    @output
    @render.text
    def auth_status():
        t = token.get()
        if t:
            return "✅ Authenticated (cached token valid)"
        else:
            return "❌ Not authenticated"

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
            return f"✅ Ready | {len(available_symbols.get())} symbols loaded"
        else:
            return "⏳ Click 'Load Instruments' or enable Auto-load"

    # Show login URL
    @reactive.effect
    @reactive.event(input.show_login)
    def _():
        try:
            url = client.get_login_url()
            login_url.set(url)
            status_msg.set("🔗 Login URL generated. Open in browser and complete auth.")
        except Exception as e:
            status_msg.set(f"❌ Error generating login URL: {e}")
            traceback.print_exc()

    @output
    @render.ui
    def login_url_display():
        url = login_url.get()
        if not url:
            return ui.div()
        return ui.div(
            ui.p("Open this URL in your browser:"),
            ui.tags.a("🔗 Upstox Login", href=url, target="_blank", class_="btn btn-link"),
            ui.tags.hr(),
            ui.tags.code(url, style="font-size:0.8em;word-wrap:break-word;")
        )

    # Exchange code for token
    @reactive.effect
    @reactive.event(input.do_auth)
    def _():
        code = input.auth_code()
        if not code or code.strip() == "":
            status_msg.set("❌ Please provide auth code")
            return
        try:
            tkn = client.exchange_token(code.strip())
            token.set(tkn)
            status_msg.set("✅ Authenticated successfully! Token cached for 24h.")
        except Exception as e:
            status_msg.set(f"❌ Auth failed: {e}")
            traceback.print_exc()

    # Clear token cache
    @reactive.effect
    @reactive.event(input.clear_cache)
    def _():
        if client.token_manager:
            client.token_manager.clear_token()
        token.set(None)
        status_msg.set("❌ Token cache cleared. Click 'Show Login URL' to re-authenticate.")

    # NEW: Load instruments button
    @reactive.effect
    @reactive.event(input.load_instruments)
    def _():
        try:
            status_msg.set("⏳ Loading instruments from Upstox...")
            if instrument_manager.fetch_instruments(force_refresh=True):
                symbols = instrument_manager.get_unique_symbols()
                available_symbols.set(symbols)
                instruments_loaded.set(True)
                status_msg.set(f"✅ Loaded {len(symbols)} symbols")
            else:
                status_msg.set("❌ Failed to load instruments")
        except Exception as e:
            status_msg.set(f"❌ Error: {e}")
            traceback.print_exc()

    # NEW: Symbol selector UI
    @output
    @render.ui
    def symbol_selector():
        symbols = available_symbols.get()
        if not symbols:
            return ui.div("⏳ Load instruments first", style="color: #999;")
        return ui.input_select("select_symbol", "Choose Symbol", choices=symbols)

    # NEW: Update expiries when symbol changes
    @reactive.effect
    def _update_expiries():
        symbol = input.select_symbol() if 'select_symbol' in dir(input) else None
        if symbol and instruments_loaded.get():
            try:
                expiries = instrument_manager.get_expiry_dates(symbol)
                available_expiries.set(expiries)
                selected_symbol.set(symbol)
            except Exception as e:
                available_expiries.set([])
                print(f"Error fetching expiries: {e}")

    # NEW: Expiry selector UI
    @output
    @render.ui
    def expiry_selector():
        expiries = available_expiries.get()
        if not expiries:
            return ui.div("Select symbol first", style="color: #999;")
        return ui.input_select("select_expiry", "Choose Expiry", choices=expiries)

    # NEW: Update strikes when symbol or type changes
    @reactive.effect
    def _update_strikes():
        symbol = input.select_symbol() if 'select_symbol' in dir(input) else None
        expiry = input.select_expiry() if 'select_expiry' in dir(input) else None
        instr_type = input.select_type() if 'select_type' in dir(input) else 'CE'

        if symbol and expiry and instruments_loaded.get():
            try:
                strikes = instrument_manager.get_strikes(symbol, expiry, instr_type)
                available_strikes.set(strikes)
                selected_expiry.set(expiry)
            except Exception as e:
                available_strikes.set([])
                print(f"Error fetching strikes: {e}")

    # NEW: Strike selector UI
    @output
    @render.ui
    def strike_selector():
        strikes = available_strikes.get()
        if not strikes:
            return ui.div("Select expiry and type first", style="color: #999;")
        # Convert to strings for select choices
        strike_choices = [str(s) for s in strikes]
        return ui.input_select("select_strike", "Choose Strike", choices=strike_choices)

    # NEW: Apply instrument selection
    @reactive.effect
    @reactive.event(input.apply_instrument)
    def _():
        symbol = input.select_symbol() if 'select_symbol' in dir(input) else None
        expiry = input.select_expiry() if 'select_expiry' in dir(input) else None
        strike_val = input.select_strike() if 'select_strike' in dir(input) else None
        instr_type = input.select_type() if 'select_type' in dir(input) else 'CE'

        if not all([symbol, expiry, instr_type]):
            status_msg.set("❌ Select Symbol, Expiry, and Type")
            return

        try:
            if instr_type == 'FUT':
                key = instrument_manager.get_instrument_key(symbol, expiry, None, 'FUT')
                strike_display = "FUT"
            else:
                if not strike_val:
                    status_msg.set("❌ Select Strike for Options")
                    return
                strike = int(strike_val)
                key = instrument_manager.get_instrument_key(symbol, expiry, strike, instr_type)
                strike_display = str(strike)

            if key:
                selected_instrument_key.set(key)
                selected_strike.set(strike_val if instr_type != 'FUT' else None)
                status_msg.set(f"✅ Selected: {symbol} {expiry} {strike_display} {instr_type}")
            else:
                status_msg.set(f"❌ Instrument not found")
        except Exception as e:
            status_msg.set(f"❌ Error: {e}")
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

    # Fetch and process data
    @reactive.effect
    @reactive.event(input.fetch)
    def _():
        if not token.get():
            status_msg.set("❌ Authenticate first before fetching data")
            return
        try:
            # Use selected instrument if available, else manual input
            key = selected_instrument_key.get()
            inst = key if key else input.instrument().strip()

            if not inst or inst == "NSE_FO|40088":
                status_msg.set("❌ Please select an instrument")
                return

            interval = input.interval()
            mode = input.fetch_mode()

            status_msg.set(f"⏳ Fetching data for {inst}...")

            if mode == "intraday":
                raw_df = fetch_intraday_data(
                    inst, token.get(), interval=interval, mode="intraday"
                )
            else:
                start = input.start_date().strip()
                end = input.end_date().strip()
                if not start or not end:
                    status_msg.set("❌ Please provide start and end dates")
                    return
                raw_df = fetch_intraday_data(
                    inst, token.get(), interval=interval, mode="date_range", start=start, end=end
                )

            if raw_df is None or raw_df.empty:
                status_msg.set("❌ No data returned from API")
                return

            status_msg.set(f"⏳ Processing {len(raw_df)} rows...")
            df = calculate_indicators(raw_df)
            df = detect_regimes_relaxed(df)
            df = add_long_signal(df)
            df_data.set(df)

            if input.auto_save():
                base_dir = input.save_dir().strip() or None
                path = save_to_csv(df, base_dir=base_dir)
                status_msg.set(f"✅ Fetched & processed {len(df)} rows. Saved: {path}")
            else:
                status_msg.set(f"✅ Fetched & processed {len(df)} rows successfully!")

        except ValueError as ve:
            status_msg.set(f"❌ Date format error: {ve}")
            traceback.print_exc()
        except Exception as e:
            status_msg.set(f"❌ Error: {str(e)}")
            traceback.print_exc()

    # Run backtest
    @reactive.effect
    @reactive.event(input.run_backtest)
    def _():
        df = df_data.get()
        if df is None or df.empty:
            status_msg.set("❌ Fetch & Process data first before backtesting")
            return

        try:
            status_msg.set("⏳ Running backtest...")
            cash = input.initial_cash()
            initial_cash_used.set(cash)

            trades_df = calculate_manual_pnl(df, initial_cash=cash, commission=0.0)
            summary = get_summary_stats_manual(df, trades_df, initial_cash=cash)

            backtest_summary_data.set(summary)
            trades_data.set(trades_df)

            if len(trades_df) == 0:
                status_msg.set("⚠️ No complete trades (no matching buy/sell signal pairs)")
            else:
                status_msg.set(f"✅ Backtest complete! {len(trades_df)} trades executed.")
        except Exception as e:
            status_msg.set(f"❌ Backtest error: {str(e)}")
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
                ui.h4("📊 Backtest Results"),
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