# ui.py - UI/Layout definitions for Q-FAD Trading App
from datetime import date
from shiny import ui
from shinywidgets import output_widget


def create_app_ui():
    """Create the main UI layout for the Q-FAD Trading Application."""
    
    return ui.page_sidebar(
        ui.sidebar(
            ui.h2("Q-FAD Trading", style="text-align: center; margin-bottom: 24px; color: #0d3739; font-weight: 700;"),
            
            ui.h4("🔐 Authentication"),
            ui.output_text_verbatim("auth_status"),
            ui.input_action_button("show_login", "Show Login URL", class_="btn-primary"),
            ui.output_ui("login_url_display"),
            ui.input_text("auth_code", "Paste auth code here", placeholder="enter code"),
            ui.row(
                ui.column(6, ui.input_action_button("do_auth", "Exchange Token", class_="btn-success")),
                ui.column(6, ui.input_action_button("clear_cache", "Logout", class_="btn-danger btn-sm")),
            ),
            ui.tags.hr(),

            # Instrument Selector Section
            ui.h4("📊 Instrument Selector"),
            ui.row(
                ui.column(
                    6,
                    ui.input_action_button("load_instruments", "Load Instruments", class_="btn-info btn-sm"),
                ),
                ui.column(
                    6,
                    ui.input_checkbox("auto_load_instruments", "Auto-load", value=True)
                ),
            ),
            ui.input_checkbox("use_local_instruments", "Use local file", value=True),
            ui.output_text_verbatim("instruments_status"),
            ui.tags.hr(),
            
            # Symbol, Expiry, Type Selection
            ui.h5("Select Trading Pair", style="font-size: 12px; text-transform: uppercase; opacity: 0.8;"),
            ui.output_ui("symbol_selector"),
            ui.output_ui("expiry_selector"),
            ui.input_radio_buttons(
                "select_type", "Type",
                choices={"CE": "📈 Call", "PE": "📉 Put", "FUT": "Futures"},
                selected="CE", inline=True
            ),
            ui.output_ui("strike_selector"),
            
            ui.row(
                ui.column(6, ui.input_action_button("apply_instrument", "Apply", class_="btn-success btn-sm")),
                ui.column(6, ui.output_ui("selected_instrument_display"))
            ),
            ui.tags.hr(),

            ui.h4("📈 Data & Processing"),
            ui.input_text("instrument", "Instrument Key", value="NSE_FO|40088", placeholder="Auto or manual"),
            ui.input_select("interval", "Interval", choices=["1minute", "5minute", "15minute"], selected="1minute"),
            ui.input_radio_buttons(
                "fetch_mode", "Mode",
                choices={"intraday": "Intraday", "date_range": "Range", "expired": "Expired"},
                selected="date_range", inline=True
            ),
            ui.panel_conditional(
                "input.fetch_mode === 'date_range' || input.fetch_mode === 'expired'",
                ui.row(
                    ui.column(6, ui.input_date("start_date", "From", value=date.today())),
                    ui.column(6, ui.input_date("end_date", "To", value=date.today())),
                ),
            ),
            ui.row(
                ui.column(8, ui.input_action_button("fetch", "Fetch & Process", class_="btn-primary")),
                ui.column(4, ui.input_checkbox("auto_save", "Save CSV", value=True)),
            ),
            ui.input_text("save_dir", "Save dir", value="", placeholder="Optional"),
            ui.tags.hr(),

            ui.h4("🎯 Backtesting"),
            ui.input_numeric("initial_cash", "Initial Capital ($)", value=100000, min=1000, max=10000000),
            ui.input_action_button("run_backtest", "Run Backtest", class_="btn-warning"),
            ui.tags.hr(),

            ui.p("Status:"),
            ui.output_text_verbatim("status"),
            title="Controls"
        ),
        ui.navset_tab(
            ui.nav_panel(
                "📈 Chart",
                output_widget("price_plot")
            ),
            ui.nav_panel(
                "📋 Signals",
                ui.row(
                    ui.column(12, ui.download_button("download_csv", "⬇️ Download CSV", class_="btn-success")),
                ),
                ui.output_data_frame("signals_table")
            ),
            ui.nav_panel(
                "📊 Backtest",
                ui.output_ui("backtest_summary")
            ),
            ui.nav_panel(
                "📝 Trades",
                ui.output_data_frame("trades_table")
            ),
        ),
        ui.tags.head(
            ui.tags.link(rel="stylesheet", href="static/theme.css"),
            ui.tags.title("Q-FAD Algo - HFT Trading Platform"),
            ui.tags.meta(name="viewport", content="width=device-width, initial-scale=1.0"),
        ),
        title="Q-FAD: Algorithmic Trading Platform"
    )
