import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def _coerce_time_labels(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )
    dt = pd.to_datetime(cleaned, errors="coerce")
    if dt.notna().all():
        return pd.Series(
            dt.dt.strftime("%Y-%m-%d %H:%M:%S"),
            index=series.index,
            dtype="object",
        )
    return cleaned


def _longest_drawdown_duration(drawdown_pct: pd.Series) -> tuple[int, tuple[int, int] | None]:
    mask = drawdown_pct.fillna(0).lt(0).tolist()
    best_len = 0
    best_range = None
    start = None

    for idx, in_dd in enumerate(mask):
        if in_dd and start is None:
            start = idx
        elif not in_dd and start is not None:
            length = idx - start
            if length > best_len:
                best_len = length
                best_range = (start, idx - 1)
            start = None

    if start is not None:
        length = len(mask) - start
        if length > best_len:
            best_len = length
            best_range = (start, len(mask) - 1)

    return best_len, best_range


def plot_backtest_overview(trades_df: pd.DataFrame, initial_cash: float = 100000.0) -> go.Figure:
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.58, 0.42],
        vertical_spacing=0.12,
        subplot_titles=("Equity", "Profit / Loss"),
    )

    if trades_df is None or trades_df.empty:
        fig.update_layout(height=420, template="plotly_white", title="No trades executed")
        return fig

    plot_df = trades_df.copy()
    exit_x = _coerce_time_labels(plot_df["Exit Time"] if "Exit Time" in plot_df.columns else pd.Series(plot_df.index))
    equity = pd.to_numeric(plot_df.get("Equity"), errors="coerce")
    returns = pd.to_numeric(plot_df.get("Return %"), errors="coerce")

    equity_pct = ((equity / float(initial_cash)) - 1.0) * 100.0
    running_peak = equity.cummax()
    running_peak_pct = ((running_peak / float(initial_cash)) - 1.0) * 100.0
    drawdown_pct = ((equity - running_peak) / running_peak.replace(0, pd.NA)) * 100.0

    peak_idx = equity.idxmax() if equity.notna().any() else None
    final_idx = equity.last_valid_index()
    dd_idx = drawdown_pct.idxmin() if drawdown_pct.notna().any() else None
    dd_dur_len, dd_dur_range = _longest_drawdown_duration(drawdown_pct)

    if dd_dur_range:
        fig.add_vrect(
            x0=exit_x.iloc[dd_dur_range[0]],
            x1=exit_x.iloc[dd_dur_range[1]],
            fillcolor="rgba(225, 229, 216, 0.35)",
            line_width=0,
            row=1,
            col=1,
        )

    fig.add_trace(
        go.Scatter(
            x=exit_x,
            y=equity_pct,
            mode="lines",
            name="Equity",
            line=dict(color="#2580d8", width=2),
            hovertemplate="<b>Equity</b><br>%{x|%Y-%m-%d %H:%M:%S}<br>%{y:.2f}%<extra></extra>",
            showlegend=False,
        ),
        row=1,
        col=1,
    )

    if peak_idx is not None:
        fig.add_trace(
            go.Scatter(
                x=[exit_x.loc[peak_idx]],
                y=[equity_pct.loc[peak_idx]],
                mode="markers",
                marker=dict(color="#20d5e8", size=10),
                name=f"Peak ({equity_pct.loc[peak_idx]:.0f}%)",
                hovertemplate="<b>Peak</b><br>%{x}<br>%{y:.2f}%<extra></extra>",
            ),
            row=1,
            col=1,
        )
    if final_idx is not None:
        fig.add_trace(
            go.Scatter(
                x=[exit_x.loc[final_idx]],
                y=[equity_pct.loc[final_idx]],
                mode="markers",
                marker=dict(color="#243bff", size=10),
                name=f"Final ({equity_pct.loc[final_idx]:.0f}%)",
                hovertemplate="<b>Final</b><br>%{x}<br>%{y:.2f}%<extra></extra>",
            ),
            row=1,
            col=1,
        )
    if dd_idx is not None and pd.notna(drawdown_pct.loc[dd_idx]):
        fig.add_trace(
            go.Scatter(
                x=[exit_x.loc[dd_idx]],
                y=[equity_pct.loc[dd_idx]],
                mode="markers",
                marker=dict(color="#ff1d1d", size=10),
                name=f"Max Drawdown ({drawdown_pct.loc[dd_idx]:.1f}%)",
                hovertemplate="<b>Max Drawdown</b><br>%{x}<br>%{y:.2f}%<extra></extra>",
            ),
            row=1,
            col=1,
        )
    if dd_dur_len > 0:
        fig.add_trace(
            go.Scatter(
                x=[None],
                y=[None],
                mode="markers",
                marker=dict(size=0, opacity=0),
                name=f"Max Dd Dur. ({dd_dur_len})",
                hoverinfo="skip",
            ),
            row=1,
            col=1,
        )

    pos_mask = returns.fillna(0) > 0
    neg_mask = ~pos_mask
    fig.add_trace(
        go.Scatter(
            x=exit_x,
            y=returns,
            mode="lines",
            line=dict(color="#a8a8a8", width=1),
            hoverinfo="skip",
            showlegend=False,
        ),
        row=2,
        col=1,
    )
    if pos_mask.any():
        fig.add_trace(
            go.Scatter(
                x=exit_x[pos_mask],
                y=returns[pos_mask],
                mode="markers",
                marker=dict(color="#17ff17", size=14, symbol="triangle-up", line=dict(color="#111111", width=1)),
                name="Winning Trades",
                hovertemplate="<b>Winning Trade</b><br>%{x}<br>%{y:.2f}%<extra></extra>",
                showlegend=False,
            ),
            row=2,
            col=1,
        )
    if neg_mask.any():
        fig.add_trace(
            go.Scatter(
                x=exit_x[neg_mask],
                y=returns[neg_mask],
                mode="markers",
                marker=dict(color="#ff6442", size=14, symbol="triangle-up", line=dict(color="#111111", width=1)),
                name="Losing Trades",
                hovertemplate="<b>Losing Trade</b><br>%{x}<br>%{y:.2f}%<extra></extra>",
                showlegend=False,
            ),
            row=2,
            col=1,
        )

    fig.add_hline(y=0, line_dash="dot", line_color="#999999", row=1, col=1)
    fig.add_hline(y=0, line_dash="dash", line_color="#8c8c8c", row=2, col=1)

    fig.update_layout(
        height=430,
        template="plotly_white",
        margin=dict(l=50, r=24, t=40, b=40),
        legend=dict(
            orientation="v",
            yanchor="top",
            y=0.98,
            xanchor="left",
            x=0.0,
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor="#c8c8c8",
            borderwidth=1,
        ),
        hovermode="x unified",
        plot_bgcolor="#fafafa",
        paper_bgcolor="#ffffff",
    )

    fig.update_yaxes(title_text="Equity", ticksuffix="%", row=1, col=1)
    fig.update_yaxes(title_text="Profit / Loss", ticksuffix="%", row=2, col=1)
    fig.update_xaxes(
        showgrid=True,
        gridcolor="#e1e1e1",
        type="category",
        row=1,
        col=1,
    )
    fig.update_xaxes(
        title_text="Trade Exit Time",
        showgrid=True,
        gridcolor="#e1e1e1",
        type="category",
        row=2,
        col=1,
    )
    fig.update_yaxes(showgrid=True, gridcolor="#e1e1e1")

    return fig
