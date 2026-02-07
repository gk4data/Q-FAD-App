# ui.py - UI/Layout definitions for Q-FAD Trading App
from datetime import date
from shiny import ui
from shinywidgets import output_widget


def create_auth_ui():
    return ui.div(
        ui.div(
            ui.h2("⚡ Q-FAD", style="text-align: center; margin-bottom: 8px;"),
            ui.p("Algorithmic HFT Platform", style="text-align: center; color: #858585; font-size: 11px; margin-bottom: 24px; letter-spacing: 1px;"),
            style="margin-bottom: 20px;"
        ),
        ui.div(
            ui.h4("🔐 Authentication", style="display: flex; align-items: center; gap: 8px;"),
            ui.output_text_verbatim("auth_status"),
            ui.input_action_button("show_login", "🔑 Show Login URL", class_="btn-primary", style="width: 100%; margin-bottom: 8px;"),
            ui.output_ui("login_url_display"),
            ui.input_text("auth_code", "Authorization Code", placeholder="Paste your auth code here"),
            ui.row(
                ui.column(6, ui.input_action_button("do_auth", "✓ Submit", class_="btn-success")),
                ui.column(6, ui.input_action_button("clear_cache", "✗ Logout", class_="btn-danger")),
            ),
            style="margin-bottom: 24px;"
        ),
        ui.div(
            ui.h5("📡 SYSTEM STATUS", style="font-size: 11px; margin-bottom: 8px;"),
            ui.output_text_verbatim("status"),
            style="margin-top: 16px;"
        ),
        style="max-width: 520px; margin: 40px auto;"
    )


def create_main_ui():
    return ui.page_sidebar(
        ui.sidebar(
            ui.div(
                ui.h2("⚡ Q-FAD", style="text-align: center; margin-bottom: 8px;"),
                ui.p("Algorithmic HFT Platform", style="text-align: center; color: #858585; font-size: 11px; margin-bottom: 24px; letter-spacing: 1px;"),
                style="margin-bottom: 20px;"
            ),

            # Instrument Selector Section
            ui.div(
                ui.h4("📊 INSTRUMENT SELECTOR"),
                ui.row(
                    ui.column(
                        6,
                        ui.input_action_button("load_instruments", "⟳ Load", class_="btn-info btn-sm"),
                    ),
                    ui.column(
                        6,
                        ui.input_checkbox("auto_load_instruments", "Auto-load", value=True)
                    ),
                ),
                ui.output_text_verbatim("instruments_status"),
                style="margin-bottom: 24px;"
            ),
            ui.tags.hr(),
            
            # Symbol, Expiry, Type Selection
            ui.div(
                ui.h5("TRADING PAIR", style="font-size: 11px; text-transform: uppercase; opacity: 0.8; margin-bottom: 12px;"),
                ui.input_select(
                    "exchange",
                    "Exchange",
                    choices={"NSE": "NSE (Index/Equity)", "MCX": "MCX (Commodity)"},
                    selected="NSE"
                ),
                ui.output_ui("symbol_selector"),
                ui.output_ui("expiry_selector"),
                ui.input_radio_buttons(
                    "select_type", "Type",
                    choices={"CE": "📈 Call", "PE": "📉 Put", "FUT": "⚡ Futures"},
                    selected="CE", inline=True
                ),
                ui.output_ui("strike_selector"),
                
                ui.row(
                    ui.column(6, ui.input_action_button("apply_instrument", "Apply", class_="btn-success btn-sm")),
                    ui.column(6, ui.output_ui("selected_instrument_display"))
                ),
                style="margin-bottom: 24px;"
            ),
            ui.tags.hr(),

            ui.div(
                ui.h4("📈 DATA & PROCESSING"),
                ui.input_text("instrument", "Instrument Key", value="NSE_FO|40088", placeholder="Auto or manual entry"),
                ui.input_select("interval", "Timeframe", choices=["1minute", "5minute", "15minute"], selected="1minute"),
                ui.input_radio_buttons(
                    "fetch_mode", "Mode",
                    choices={"intraday": "📊 Intraday", "date_range": "📅 Range", "expired": "🗃️ Expired"},
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
                    ui.column(8, ui.input_action_button("fetch", "⚡ Fetch & Process", class_="btn-primary")),
                    ui.column(4, ui.input_checkbox("auto_save", "Save", value=True)),
                ),
                ui.input_text("save_dir", "Save Directory", value="", placeholder="Optional save path"),
                style="margin-bottom: 24px;"
            ),
            ui.tags.hr(),

            ui.div(
                ui.h4("🔴 LIVE DATA"),
                ui.input_text("live_save_dir", "Live Data Directory", value="", placeholder="Default: ./live_data"),
                ui.row(
                    ui.column(6, ui.input_action_button("start_live", "▶ Start", class_="btn-primary")),
                    ui.column(6, ui.input_action_button("stop_live", "■ Stop", class_="btn-secondary")),
                ),
                ui.output_text_verbatim("live_status"),
                style="margin-bottom: 24px;"
            ),
            ui.tags.hr(),

            ui.div(
                ui.h4("🎯 BACKTESTING"),
                ui.input_numeric("initial_cash", "Initial Capital", value=100000, min=1000, max=10000000),
                ui.input_action_button("run_backtest", "▶ Run Backtest", class_="btn-warning", style="width: 100%;"),
                style="margin-bottom: 24px;"
            ),
            ui.tags.hr(),

            ui.div(
                ui.h5("📡 SYSTEM STATUS", style="font-size: 11px; margin-bottom: 8px;"),
                ui.output_text_verbatim("status"),
                style="margin-top: 16px;"
            ),
            ui.div(
                ui.input_action_button("clear_cache", "✗ Logout", class_="btn-danger", style="width: 100%;"),
                style="margin-top: 12px;"
            ),
            title="Controls",
            width="320px"
        ),
        ui.navset_tab(
            ui.nav_panel(
                "📈 Chart",
                ui.div(
                    output_widget("price_plot"),
                    class_="chart-container fade-in"
                )
            ),
            ui.nav_panel(
                "📋 Signals",
                ui.div(
                    ui.row(
                        ui.column(12, ui.download_button("download_csv", "⬇️ Download Signals CSV", class_="btn-success")),
                    ),
                    ui.output_data_frame("signals_table"),
                    class_="fade-in",
                    style="padding: 16px;"
                )
            ),
            ui.nav_panel(
                "📊 Backtest",
                ui.div(
                    ui.output_ui("backtest_summary"),
                    class_="fade-in",
                    style="padding: 16px;"
                )
            ),
            ui.nav_panel(
                "📝 Trades",
                ui.div(
                    ui.output_data_frame("trades_table"),
                    class_="fade-in",
                    style="padding: 16px;"
                )
            ),
        ),
        title="⚡ Q-FAD: Algorithmic Trading Platform",
        fillable=True
    )


def create_app_ui():
    """Create the main UI layout for the Q-FAD Trading Application."""

    return ui.page_fluid(
        ui.tags.head(
            ui.tags.link(rel="stylesheet", href="static/theme.css"),
            ui.tags.title("Q-FAD Algo - HFT Trading Platform"),
            ui.tags.meta(name="viewport", content="width=device-width, initial-scale=1.0"),
            ui.tags.meta(name="description", content="Professional Algorithmic Trading Platform"),
            ui.tags.style("""
                /* CRITICAL INLINE OVERRIDES - Light Grey Main, Dark Sidebar */
                * { background-color: initial; }
                html, body { 
                    background-color: #f5f5f5 !important;
                    color: #333333 !important;
                    font-smoothing: antialiased; 
                    -webkit-font-smoothing: antialiased; 
                    -moz-osx-font-smoothing: grayscale; 
                }
                body { background: #f5f5f5 !important; color: #333333 !important; }
                .bslib-page { background-color: #f5f5f5 !important; color: #333333 !important; }
                .container, .container-fluid { background-color: #f5f5f5 !important; color: #333333 !important; }
                .navbar, .navbar-default, .navbar-light, .navbar-expand { background-color: #f5f5f5 !important; border-color: #ddd !important; }
                .bg-light { background-color: #f5f5f5 !important; color: #333333 !important; }
                .bg-white { background-color: #f5f5f5 !important; color: #333333 !important; }
                .bg-body { background-color: #f5f5f5 !important; color: #333333 !important; }
                .tab-content { background-color: #f5f5f5 !important; color: #333333 !important; }
                .nav-tabs { background-color: #f5f5f5 !important; }
                .card { background-color: #ffffff !important; color: #333333 !important; border-color: #ddd !important; }
                table { color: #333333 !important; background-color: #ffffff !important; }
                thead { background-color: #f9f9f9 !important; }
                th { color: #007acc !important; background-color: #f9f9f9 !important; }
                td { color: #333333 !important; }
                tr { color: #333333 !important; }
                p, div, span, label { color: #333333 !important; }
                h1, h2, h3, h4, h5, h6 { color: #222222 !important; }
                
                /* Loading screen */
                .loading-overlay {
                    position: fixed;
                    top: 0;
                    left: 0;
                    right: 0;
                    bottom: 0;
                    background: #f5f5f5;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    z-index: 9999;
                    opacity: 0;
                    pointer-events: none;
                    transition: opacity 0.3s;
                }
                
                .loading-overlay.active {
                    opacity: 1;
                    pointer-events: all;
                }
            """)
        ),
        ui.output_ui("app_root"),
        title="⚡ Q-FAD: Algorithmic Trading Platform",
        fillable=True
    )
