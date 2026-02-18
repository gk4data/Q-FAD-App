# ui.py - UI/Layout definitions for Q-FAD Trading App (Mini Sidebar Layout + Auth UI)
from datetime import date
import os
from shiny import ui
from shinywidgets import output_widget


# ---------------- AUTH UI ----------------

def create_auth_ui():
    redirect_default = os.getenv("UPSTOX_REDIRECT_URI", "")
    return ui.div(
        ui.div(
            ui.h2(ui.tags.i(class_="bi bi-lightning-charge"), " Q-FAD", style="text-align: center; margin-bottom: 8px;"),
            ui.p("Algorithmic HFT Platform", style="text-align: center; font-size: 11px; margin-bottom: 24px; letter-spacing: 1px;"),
            style="margin-bottom: 20px;"
        ),
        ui.div(
            ui.h4(ui.tags.i(class_="bi bi-shield-lock"), " Authentication"),
            ui.output_text_verbatim("auth_status"),
            ui.input_text("redirect_uri", "Redirect URI", value=redirect_default, placeholder="https://your-app-url/callback"),
            ui.input_action_button("show_login", ui.HTML("<i class='bi bi-key'></i> Show Login URL"), class_="btn-primary", style="width: 100%; margin-bottom: 8px;"),
            ui.output_ui("login_url_display"),
            ui.input_text("auth_code", "Authorization Code", placeholder="Paste your auth code here"),
            ui.row(
                ui.column(6, ui.input_action_button("do_auth", ui.HTML("<i class='bi bi-check2'></i> Submit"), class_="btn-success")),
                ui.column(6, ui.input_action_button("clear_cache", ui.HTML("<i class='bi bi-box-arrow-right'></i> Logout"), class_="btn-danger")),
            ),
            style="margin-bottom: 24px;"
        ),
        ui.div(
            ui.h5(ui.tags.i(class_="bi bi-broadcast"), " SYSTEM STATUS", style="font-size: 11px; margin-bottom: 8px;"),
            ui.output_text_verbatim("status"),
            style="margin-top: 16px;"
        ),
        style="max-width: 520px; margin: 40px auto;"
    )


# ---------------- CONTROL CARDS ----------------

def instrument_loader_card():
    return ui.div(
        ui.h5(ui.tags.i(class_="bi bi-collection"), " Instrument Loader"),
        ui.row(
            ui.column(6, ui.input_action_button("load_instruments", ui.HTML("<i class='bi bi-arrow-clockwise'></i> Load"), class_="btn-info btn-sm")),
            ui.column(6, ui.input_checkbox("auto_load_instruments", "Auto-load", value=True)),
        ),
        ui.output_text_verbatim("instruments_status"),
    )


def instrument_selector_card():
    return ui.div(
        ui.h5(ui.tags.i(class_="bi bi-search"), " Instrument Selector"),
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
            choices={"CE": "Call", "PE": "Put"},
            selected="CE", inline=True
        ),
        ui.output_ui("strike_selector"),
        ui.row(
            ui.column(6, ui.input_action_button("apply_instrument", "Apply", class_="btn-success btn-sm")),
            ui.column(6, ui.output_ui("selected_instrument_display"))
        ),
    )


def data_processing_card():
    return ui.div(
        ui.h5(ui.tags.i(class_="bi bi-graph-up"), " Data & Processing"),
        ui.input_text("instrument", "Instrument Key", value="NSE_FO|40088"),
        ui.input_select("interval", "Timeframe", choices=["1minute", "5minute", "15minute"], selected="1minute"),
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
            )
        ),
        ui.row(
            ui.column(8, ui.input_action_button("fetch", ui.HTML("<i class='bi bi-lightning-charge'></i> Fetch & Process"), class_="btn-primary")),
            ui.column(4, ui.input_checkbox("auto_save", "Save", value=True)),
        ),
        ui.input_text("save_dir", "Save Directory", value=""),
    )


def live_data_card():
    return ui.div(
        ui.h5(ui.tags.i(class_="bi bi-record-circle"), " Live Data (REST API)"),
        ui.input_text("live_save_dir", "Live Data Directory", value=""),
        ui.row(
            ui.column(6, ui.input_action_button("start_live", ui.HTML("<i class='bi bi-play-fill'></i> Start"), class_="btn-success")),
            ui.column(6, ui.input_action_button("stop_live", ui.HTML("<i class='bi bi-stop-fill'></i> Stop"), class_="btn-danger")),
        ),
        ui.output_text_verbatim("live_status"),
    )


def websocket_card():
    return ui.div(
        ui.h5(ui.tags.i(class_="bi bi-wifi"), " Live Data (WebSocket)"),
        ui.input_text("websocket_save_dir", "WebSocket Save Directory", value=""),
        ui.row(
            ui.column(6, ui.input_action_button("start_websocket", ui.HTML("<i class='bi bi-play-fill'></i> Start"), class_="btn-success")),
            ui.column(6, ui.input_action_button("stop_websocket", ui.HTML("<i class='bi bi-stop-fill'></i> Stop"), class_="btn-danger")),
        ),
        ui.output_text_verbatim("websocket_status"),
    )


def live_trading_card():
    return ui.div(
        ui.h5(ui.tags.i(class_="bi bi-flask"), " Live Trading (Sandbox)"),
        ui.input_password("sandbox_token", "Sandbox Token"),
        ui.input_numeric("trade_capital", "Available Capital", value=1000, min=1),
        ui.input_numeric("sl_percent", "Stop Loss %", value=15, min=1, max=50),
        ui.input_select("product_type", "Product", choices={"I": "Intraday", "D": "Delivery"}, selected="I"),
        ui.row(
            ui.column(6, ui.input_action_button("start_trading", ui.HTML("<i class='bi bi-play-fill'></i> Start"), class_="btn-success")),
            ui.column(6, ui.input_action_button("stop_trading", ui.HTML("<i class='bi bi-stop-fill'></i> Stop"), class_="btn-danger")),
        ),
        ui.output_text_verbatim("trade_status"),
    )


def backtesting_card():
    return ui.div(
        ui.h5(ui.tags.i(class_="bi bi-bullseye"), " Backtesting"),
        ui.input_numeric("initial_cash", "Initial Capital", value=100000, min=1000, max=10000000),
        ui.input_action_button("run_backtest", ui.HTML("<i class='bi bi-play-circle'></i> Run Backtest"), class_="btn-warning", style="width:100%"),
    )


# ---------------- MAIN APP UI ----------------

def create_main_ui():
    return ui.page_fluid(
        # Top bar
        ui.div(
            ui.div(
                ui.h4(ui.tags.i(class_="bi bi-lightning-charge"), " Q-FAD: Algo Trading Platform", style="margin:0;"),
                class_="topbar-left",
            ),
            ui.div(
                ui.div(
                    ui.div(ui.output_ui("live_trading_indicator"), class_="topbar-live-wrap"),
                    ui.h6(ui.tags.i(class_="bi bi-broadcast"), " SYSTEM STATUS", style="margin:0;"),
                    class_="topbar-status-row",
                ),
                ui.output_text_verbatim("status"),
                class_="topbar-right"
            ),
            class_="app-topbar"
        ),

        # Main layout
        ui.div(
            # Mini sidebar
            ui.div(
                ui.div(
                    ui.input_radio_buttons(
                        "sidebar_mode",
                        label="",
                       choices={
                        "controls": ui.HTML('<i class="bi bi-sliders"></i>'),
                        "data": ui.HTML('<i class="bi bi-folder2-open"></i>'),
                        "live_trading": ui.HTML('<i class="bi bi-lightning-charge"></i>'),
                        "backtest": ui.HTML('<i class="bi bi-graph-up"></i>'),
                        "logout": ui.HTML('<i class="bi bi-box-arrow-right"></i>'),
                        },
                        selected="controls",
                        inline=False
                    ),
                    class_="mini-sidebar-radios"
                ),
                class_="mini-sidebar"
            ),

            # Controls column
            ui.div(
                ui.panel_conditional(
                    "input.sidebar_mode === 'controls'",
                    ui.div(
                        ui.div(instrument_loader_card(), class_="sidebar-card"),
                        ui.div(instrument_selector_card(), class_="sidebar-card"),
                    )
                ),

                ui.panel_conditional(
                    "input.sidebar_mode === 'data'",
                    ui.div(
                        ui.div(data_processing_card(), class_="sidebar-card sidebar-card-tall"),
                        ui.div(live_data_card(), class_="sidebar-card sidebar-card-tall"),
                        ui.div(websocket_card(), class_="sidebar-card sidebar-card-tall"),
                    )
                ),

                ui.panel_conditional(
                    "input.sidebar_mode === 'live_trading'",
                    ui.div(live_trading_card(), class_="sidebar-card")
                ),

                ui.panel_conditional(
                    "input.sidebar_mode === 'backtest'",
                    ui.div(backtesting_card(), class_="sidebar-card")
                ),

                ui.panel_conditional(
                    "input.sidebar_mode === 'logout'",
                    ui.div(
                        ui.h5(ui.tags.i(class_="bi bi-shield-lock"), " Logout & Session"),
                        ui.input_action_button("clear_cache", ui.HTML("<i class='bi bi-box-arrow-right'></i> Logout"), class_="btn-danger", style="width:100%"),
                        class_="sidebar-card"
                    )
                ),

                class_="controls-column"
            ),

            # Main area with tabs
            ui.div(
                ui.navset_tab(
                    ui.nav_panel(ui.HTML("<i class='bi bi-graph-up'></i> Chart"), ui.div(output_widget("price_plot"), class_="chart-container")),
                    ui.nav_panel(ui.HTML("<i class='bi bi-activity'></i> Signals"), ui.div(ui.download_button("download_csv", ui.HTML("<i class='bi bi-download'></i> Download Signals CSV"), class_="btn-success"), ui.output_data_frame("signals_table"), style="padding:16px;")),
                    ui.nav_panel(ui.HTML("<i class='bi bi-bar-chart'></i> Backtest"), ui.div(ui.output_ui("backtest_summary"), style="padding:16px;")),
                    ui.nav_panel(ui.HTML("<i class='bi bi-receipt'></i> Trades"), ui.div(ui.output_data_frame("trades_table"), style="padding:16px;")),
                    ui.nav_panel(ui.HTML("<i class='bi bi-flask'></i> Live Trading"), ui.div(ui.output_text_verbatim("position_status"), ui.output_data_frame("orders_table"), style="padding:16px;")),
                ),
                class_="main-area"
            ),

            class_="app-layout",
            style="display:flex; gap:12px;"
        ),
        ui.div(
            ui.div("Designed By Skyrock INC 2025-26", class_="footer-left"),
            ui.div(ui.output_ui("funds_indicator"), class_="footer-right"),
            class_="app-footer"
        )
    )


def create_app_ui():
    return ui.page_fluid(
        ui.tags.head(
            ui.tags.link(rel="stylesheet", href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css"),
            ui.include_css("static/theme.css"),
        ),
        ui.output_ui("app_root"),
    )
