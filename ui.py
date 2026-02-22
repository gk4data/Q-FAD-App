# ui.py - UI/Layout definitions for Q-FAD Trading App (Mini Sidebar Layout + Auth UI)
from datetime import date
import os
from shiny import ui
from shinywidgets import output_widget

SIDEBAR_HEADER_STYLE = "text-align:center; font-weight:700; font-size:1.15rem;"


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
        ui.h5(ui.tags.i(class_="bi bi-collection"), " Instrument Loader", style=SIDEBAR_HEADER_STYLE),
        ui.row(
            ui.column(6, ui.input_action_button("load_instruments", ui.HTML("<i class='bi bi-arrow-clockwise'></i> Load"), class_="btn-info btn-sm")),
            ui.column(6, ui.input_checkbox("auto_load_instruments", "Auto-load", value=True)),
        ),
        ui.output_text_verbatim("instruments_status"),
    )


def instrument_selector_card():
    return ui.div(
        ui.h5(ui.tags.i(class_="bi bi-search"), " Instrument Selector", style=SIDEBAR_HEADER_STYLE),
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
        ui.h5(ui.tags.i(class_="bi bi-graph-up"), " Data & Processing", style=SIDEBAR_HEADER_STYLE),
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
        ui.h5(ui.tags.i(class_="bi bi-record-circle"), " Live Data (REST API)", style=SIDEBAR_HEADER_STYLE),
        ui.row(
            ui.column(6, ui.input_action_button("start_live_data", ui.HTML("<i class='bi bi-play-fill'></i> Start"), class_="btn-success")),
            ui.column(6, ui.input_action_button("stop_live_data", ui.HTML("<i class='bi bi-stop-fill'></i> Stop"), class_="btn-danger")),
        ),
        ui.output_text_verbatim("live_status"),
    )


def websocket_card():
    return ui.div(
        ui.h5(ui.tags.i(class_="bi bi-wifi"), " Live Data (WebSocket)", style=SIDEBAR_HEADER_STYLE),
        ui.row(
            ui.column(6, ui.input_action_button("start_websocket", ui.HTML("<i class='bi bi-play-fill'></i> Start"), class_="btn-success")),
            ui.column(6, ui.input_action_button("stop_websocket", ui.HTML("<i class='bi bi-stop-fill'></i> Stop"), class_="btn-danger")),
        ),
        ui.output_text_verbatim("websocket_status"),
    )


def live_trading_card():
    return ui.div(
        ui.h6("Sandbox Trading", style=SIDEBAR_HEADER_STYLE),
        ui.input_password("sandbox_token", "Sandbox Token"),
        ui.input_numeric("sandbox_capital", "Available Capital", value=1000, min=1),
        ui.input_numeric("sandbox_sl_percent", "Stop Loss %", value=15, min=1, max=50),
        ui.input_select("sandbox_product_type", "Product", choices={"I": "Intraday", "D": "Delivery"}, selected="I"),
        ui.row(
            ui.column(6, ui.input_action_button("start_sandbox", ui.HTML("<i class='bi bi-play-fill'></i> Start Sandbox"), class_="btn-success")),
            ui.column(6, ui.input_action_button("stop_sandbox", ui.HTML("<i class='bi bi-stop-fill'></i> Stop"), class_="btn-danger")),
        ),

        ui.tags.hr(),

        ui.h6("Live Trading (Production)", style=SIDEBAR_HEADER_STYLE),
        ui.input_checkbox("confirm_live_trading", "I understand this will place real orders", value=False),
        ui.input_numeric("live_sl_percent", "Stop Loss %", value=15, min=1, max=50),
        ui.input_select("live_product_type", "Product", choices={"I": "Intraday", "D": "Delivery"}, selected="I"),
        ui.row(
            ui.column(6, ui.input_action_button("start_live", ui.HTML("<i class='bi bi-play-fill'></i> Start Live"), class_="btn-warning")),
            ui.column(6, ui.input_action_button("stop_live", ui.HTML("<i class='bi bi-stop-fill'></i> Stop"), class_="btn-danger")),
        ),

        ui.output_text_verbatim("trade_status"),
    )


def backtesting_card():
    return ui.div(
        ui.h5(ui.tags.i(class_="bi bi-bullseye"), " Backtesting", style=SIDEBAR_HEADER_STYLE),
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
                        "controls": ui.HTML('<span class="mini-sidebar-icon" data-tooltip="Controls"><i class="bi bi-sliders"></i></span>'),
                        "data": ui.HTML('<span class="mini-sidebar-icon" data-tooltip="Data & Processing"><i class="bi bi-folder2-open"></i></span>'),
                        "live_trading": ui.HTML('<span class="mini-sidebar-icon" data-tooltip="Live Trading"><i class="bi bi-lightning-charge"></i></span>'),
                        "backtest": ui.HTML('<span class="mini-sidebar-icon" data-tooltip="Backtesting"><i class="bi bi-graph-up"></i></span>'),
                        "logout": ui.HTML('<span class="mini-sidebar-icon" data-tooltip="Logout & Session"><i class="bi bi-box-arrow-right"></i></span>'),
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
                        ui.h5(ui.tags.i(class_="bi bi-shield-lock"), " Logout & Session", style=SIDEBAR_HEADER_STYLE),
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
                    ui.nav_panel(
                        ui.HTML("<i class='bi bi-clock'></i> Historical Backtest"),
                        ui.div(
                            ui.div(
                                ui.row(
                                    ui.column(3, ui.input_date("historical_bt_start", "From", value=date.today())),
                                    ui.column(3, ui.input_date("historical_bt_end", "To", value=date.today())),
                                    ui.column(3, ui.input_action_button("run_historical_backtest", ui.HTML("<i class='bi bi-play-fill'></i> Run"), class_="btn-primary")),
                                ),
                                class_="order-history-actions",
                            ),
                            ui.div(ui.output_text_verbatim("historical_backtest_status"), class_="order-history-status"),
                            ui.div(ui.output_ui("historical_backtest_summary"), class_="order-history-status"),
                            ui.div(ui.output_data_frame("historical_backtest_table"), class_="order-history-table-wrap"),
                            class_="order-history-panel",
                        ),
                    ),
                    ui.nav_panel(ui.HTML("<i class='bi bi-receipt'></i> Trades"), ui.div(ui.output_data_frame("trades_table"), style="padding:16px;")),
                    ui.nav_panel(ui.HTML("<i class='bi bi-flask'></i> Live Trading"), ui.div(ui.output_text_verbatim("position_status"), ui.output_data_frame("orders_table"), style="padding:16px;")),
                    ui.nav_panel(
                        ui.HTML("<i class='bi bi-clock-history'></i> Daily Order Data"),
                        ui.div(
                            ui.div(
                                ui.input_action_button(
                                    "save_order_history",
                                    ui.HTML("<i class='bi bi-save'></i> Save Data"),
                                    class_="btn-success order-history-refresh-btn",
                                ),
                                ui.input_action_button(
                                    "refresh_order_history",
                                    ui.HTML("<i class='bi bi-arrow-repeat'></i> Fetch Today's Orders"),
                                    class_="btn-info order-history-refresh-btn",
                                ),
                                class_="order-history-actions",
                            ),
                            ui.div(ui.output_ui("order_history_status"), class_="order-history-status"),
                            ui.div(ui.output_data_frame("order_history_table"), class_="order-history-table-wrap"),
                            class_="order-history-panel"
                        )
                    ),
                    ui.nav_panel(
                        ui.HTML("<i class='bi bi-journal-text'></i> Historical Orders"),
                        ui.div(
                            ui.div(ui.output_ui("historical_orders_status"), class_="order-history-status"),
                            ui.div(ui.output_data_frame("historical_orders_table"), class_="order-history-table-wrap"),
                            class_="order-history-panel"
                        )
                    ),
                ),
                class_="main-area"
            ),

            class_="app-layout",
            style="display:flex; gap:12px;"
        ),
        ui.div(
            ui.div("©️ 2026 Skyrock INC. All Rights Reserved.", class_="footer-left"),
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
