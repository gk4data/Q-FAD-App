import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def plot_signals(df):
    """
    Simple plot function based on working reference code
    """
    
    # Preserve original Date column values from API and use them as x-values
    if 'Date' in df.columns:
        df = df.copy()
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        # Don't force timezone conversions here - preserve timestamps exactly as provided by API
        try:
            # Use numpy array of Python datetimes for Plotly; this keeps hover rendering as Plotly default
            x_vals = np.array(df['Date'].dt.to_pydatetime(), dtype=object)
        except Exception:
            # fallback to strings to avoid numeric hover display
            x_vals = df['Date'].astype(str)
    else:
        x_vals = None

    # Create figure with 5 subplots
    fig = make_subplots(
        rows=5, cols=1, 
        shared_xaxes=True, 
        row_heights=[0.45, 0.12, 0.15, 0.14, 0.14],
        vertical_spacing=0.08, 
        subplot_titles=("Candlesticks", "Volume", "Adaptive RSI & MFI", "Strength", "Stochastic & BBMAngle")
    )

    # ===== ROW 1: Candlestick Chart =====
    fig.add_trace(
        go.Candlestick(
            x=x_vals,
            open=df['Open'],
            high=df['High'],
            low=df['Low'],
            close=df['Close'],
            name="Candlestick"
        ), 
        row=1, col=1
    )

    # Buy Signals
    if 'Buy_Signal' in df.columns and df['Buy_Signal'].any():
        fig.add_trace(
            go.Scatter(
                x=x_vals[df['Buy_Signal']],
                y=df['Low'][df['Buy_Signal']],  
                mode='markers',
                marker=dict(color="#030604", size=14, symbol='triangle-up'),
                name="Buy Signal",
                hovertemplate='<b>Buy Signal</b><br>%{x|%Y-%m-%d %H:%M:%S}<extra></extra>'
            ),
            row=1, col=1
        )

    # Sell Signals
    if 'Sell_Signal' in df.columns and df['Sell_Signal'].any():
        fig.add_trace(
            go.Scatter(
                x=x_vals[df['Sell_Signal']],
                y=df['High'][df['Sell_Signal']],  
                mode='markers',
                marker=dict(color='Red', size=14, symbol='triangle-down'),
                name="Sell Signal",
                hovertemplate='<b>Sell Signal</b><br>%{x|%Y-%m-%d %H:%M:%S}<extra></extra>'
            ),
            row=1, col=1
        )

    # Mid Buy Signal
    if 'Mid_Buy_Signal' in df.columns and df['Mid_Buy_Signal'].any():
        fig.add_trace(
            go.Scatter(
                x=x_vals[df['Mid_Buy_Signal']], 
                y=df['BBM'][df['Mid_Buy_Signal']], 
                mode="markers",
                marker=dict(size=14, color="Green", symbol='triangle-up'),
                name="Mid_Buy_Signal",
                hovertemplate='<b>Mid Buy Signal</b><br>%{x|%Y-%m-%d %H:%M:%S}<extra></extra>'
            ), 
            row=1, col=1
        )

    # RSI Range Buy Signal
    if 'RSI_Range_Buy_Signal' in df.columns and df['RSI_Range_Buy_Signal'].any():
        fig.add_trace(
            go.Scatter(
                x=x_vals[df['RSI_Range_Buy_Signal']],
                y=df['Low'][df['RSI_Range_Buy_Signal']],  
                mode='markers',
                marker=dict(color='Purple', size=16, symbol='triangle-up'),
                name="RSI_Range_Buy_Signal",
                hovertemplate='<b>RSI Range Buy</b><br>%{x|%Y-%m-%d %H:%M:%S}<extra></extra>'
            ),
            row=1, col=1
        )

    # OverSold Buy Signal
    if 'OverSold_Buy_Signal' in df.columns and df['OverSold_Buy_Signal'].any():
        fig.add_trace(
            go.Scatter(
                x=x_vals[df['OverSold_Buy_Signal']],
                y=df['Low'][df['OverSold_Buy_Signal']],  
                mode='markers',
                marker=dict(color='Blue', size=16, symbol='triangle-up'),
                name="OverSold_Buy_Signal",
                hovertemplate='<b>OverSold Buy</b><br>%{x|%Y-%m-%d %H:%M:%S}<extra></extra>'
            ),
            row=1, col=1
        )

    # Super Low Buy Signal
    if 'Super_Low_Buy_Signal' in df.columns and df['Super_Low_Buy_Signal'].any():
        fig.add_trace(
            go.Scatter(
                x=x_vals[df['Super_Low_Buy_Signal']],
                y=df['Low'][df['Super_Low_Buy_Signal']],  
                mode='markers',
                marker=dict(color='Brown', size=16, symbol='triangle-up'),
                name="Super_Low_Buy_Signal",
                hovertemplate='<b>Super Low Buy</b><br>%{x|%Y-%m-%d %H:%M:%S}<extra></extra>'
            ),
            row=1, col=1
        )

    # Mid Buy Signal 2
    if 'Mid_Buy_Signal_2' in df.columns and df['Mid_Buy_Signal_2'].any():
        fig.add_trace(
            go.Scatter(
                x=x_vals[df['Mid_Buy_Signal_2']],
                y=df['Low'][df['Mid_Buy_Signal_2']],  
                mode='markers',
                marker=dict(color='rgb(153,102,255)', size=16, symbol='triangle-up'),
                name="Mid_Buy_Signal_2",
                hovertemplate='<b>Mid Buy Signal 2</b><br>%{x|%Y-%m-%d %H:%M:%S}<extra></extra>'
            ),
            row=1, col=1
        )

    # Super Low Buy Signal 2
    if 'Super_Low_Buy_Signal_2' in df.columns and df['Super_Low_Buy_Signal_2'].any():
        fig.add_trace(
            go.Scatter(
                x=x_vals[df['Super_Low_Buy_Signal_2']],
                y=df['Low'][df['Super_Low_Buy_Signal_2']],  
                mode='markers',
                marker=dict(color='darkblue', size=16, symbol='triangle-up'),
                name="Super_Low_Buy_Signal_2",
                hovertemplate='<b>Super Low Buy 2</b><br>%{x|%Y-%m-%d %H:%M:%S}<extra></extra>'
            ),
            row=1, col=1
        )

    # RSI pct buy
    if 'RSI_pct_buy' in df.columns and df['RSI_pct_buy'].any():
        fig.add_trace(
            go.Scatter(
                x=x_vals[df['RSI_pct_buy']],
                y=df['Low'][df['RSI_pct_buy']],  
                mode='markers',
                marker=dict(color='rgb(224,6,208)', size=16, symbol='triangle-up'),
                name="RSI_pct_buy",
                hovertemplate='<b>RSI % Buy</b><br>%{x|%Y-%m-%d %H:%M:%S}<extra></extra>'
            ),
            row=1, col=1
        )

    # New Uptrend Buy Signal
    if 'New_Uptrend_Buy_Signal' in df.columns and df['New_Uptrend_Buy_Signal'].any():
        fig.add_trace(
            go.Scatter(
                x=x_vals[df['New_Uptrend_Buy_Signal']],
                y=df['Low'][df['New_Uptrend_Buy_Signal']],  
                mode='markers',
                marker=dict(color='rgb(68,179,225)', size=16, symbol='triangle-up'),
                name="New_Uptrend_Buy_Signal",
                hovertemplate='<b>New Uptrend Buy</b><br>%{x|%Y-%m-%d %H:%M:%S}<extra></extra>'
            ),
            row=1, col=1
        )

    # Downtrend Reverse Buy Signal
    if 'Downtrend_Reverse_Buy_Signal' in df.columns and df['Downtrend_Reverse_Buy_Signal'].any():
        fig.add_trace(
            go.Scatter(
                x=x_vals[df['Downtrend_Reverse_Buy_Signal']],
                y=df['Low'][df['Downtrend_Reverse_Buy_Signal']],  
                mode='markers',
                marker=dict(color='rgb(144,108,152)', size=16, symbol='triangle-up'),
                name="Downtrend_Reverse_Buy_Signal",
                hovertemplate='<b>Downtrend Reverse</b><br>%{x|%Y-%m-%d %H:%M:%S}<extra></extra>'
            ),
            row=1, col=1
        )

    # Bollinger Bands
    if 'BBL' in df.columns:
        fig.add_trace(go.Scatter(x=x_vals, y=df['BBL'], line=dict(color='blue', width=1), name="Lower BB", hovertemplate='<b>Lower BB</b><br>%{x|%Y-%m-%d %H:%M:%S}<br>%{y:.2f}<extra></extra>'), row=1, col=1)
    
    if 'BBU' in df.columns:
        fig.add_trace(go.Scatter(x=x_vals, y=df['BBU'], line=dict(color='blue', width=1), name="Upper BB", hovertemplate='<b>Upper BB</b><br>%{x|%Y-%m-%d %H:%M:%S}<br>%{y:.2f}<extra></extra>'), row=1, col=1)
    
    if 'BBM' in df.columns:
        fig.add_trace(go.Scatter(x=x_vals, y=df['BBM'], line=dict(color='orange', width=1), name="Middle BB", hovertemplate='<b>Middle BB</b><br>%{x|%Y-%m-%d %H:%M:%S}<br>%{y:.2f}<extra></extra>'), row=1, col=1)
    
    if 'EMA9' in df.columns:
        fig.add_trace(go.Scatter(x=x_vals, y=df['EMA9'], line=dict(color='black', width=1), name="EMA9", hovertemplate='<b>EMA9</b><br>%{x|%Y-%m-%d %H:%M:%S}<br>%{y:.2f}<extra></extra>'), row=1, col=1)
    
    if 'VWAP' in df.columns:
        fig.add_trace(go.Scatter(x=x_vals, y=df['VWAP'], line=dict(color='purple', width=2), name="VWAP", hovertemplate='<b>VWAP</b><br>%{x|%Y-%m-%d %H:%M:%S}<br>%{y:.2f}<extra></extra>'), row=1, col=1)

    # ===== ROW 2: Volume =====
    volume_colors = ['green' if c >= o else 'red' for c, o in zip(df['Close'], df['Open'])]
    fig.add_trace(
        go.Bar(
            x=x_vals,
            y=df['Volume'],
            marker_color=volume_colors,
            name='Volume',
            opacity=0.7,
            hovertemplate='<b>Volume</b><br>%{x|%Y-%m-%d %H:%M:%S}<br>%{y:,}<extra></extra>'
        ),
        row=2, col=1
    )

    # ===== ROW 3: RSI & MFI =====
    if 'RSI' in df.columns:
        fig.add_trace(
            go.Scatter(x=x_vals, y=df['RSI'], mode='lines', name='RSI', line=dict(color='blue', width=2), hovertemplate='<b>RSI</b><br>%{x|%Y-%m-%d %H:%M:%S}<br>%{y:.2f}<extra></extra>'), 
            row=3, col=1
        )
    
    if 'RSI_hi' in df.columns:
        fig.add_trace(
            go.Scatter(x=x_vals, y=df['RSI_hi'], mode='lines', name='RSI High', line=dict(color='red', width=1, dash='dash'), hovertemplate='<b>RSI High</b><br>%{x|%Y-%m-%d %H:%M:%S}<br>%{y:.2f}<extra></extra>'), 
            row=3, col=1
        )
    
    if 'RSI_lo' in df.columns:
        fig.add_trace(
            go.Scatter(x=x_vals, y=df['RSI_lo'], mode='lines', name='RSI Low', line=dict(color='green', width=1, dash='dash'), hovertemplate='<b>RSI Low</b><br>%{x|%Y-%m-%d %H:%M:%S}<br>%{y:.2f}<extra></extra>'), 
            row=3, col=1
        )
    
    if 'MFI_pct' in df.columns:
        fig.add_trace(
            go.Scatter(x=x_vals, y=df['MFI_pct'] * 100, mode='lines', name='MFI %', line=dict(color='orange', width=2), hovertemplate='<b>MFI %</b><br>%{x|%Y-%m-%d %H:%M:%S}<br>%{y:.2f}<extra></extra>'), 
            row=3, col=1
        )

    # ===== ROW 4: RSI & MFI & BBM Angle % =====
    if 'RSI' in df.columns:
        fig.add_trace(
            go.Scatter(x=x_vals, y=df['RSI'], mode='lines', name='RSI', line=dict(color='purple', width=2), hovertemplate='<b>RSI</b><br>%{x|%Y-%m-%d %H:%M:%S}<br>%{y:.2f}<extra></extra>'), 
            row=4, col=1
        )
    
    if 'MFI' in df.columns:
        fig.add_trace(
            go.Scatter(x=x_vals, y=df['MFI'], mode='lines', name='MFI', line=dict(color='black', width=2), hovertemplate='<b>MFI</b><br>%{x|%Y-%m-%d %H:%M:%S}<br>%{y:.2f}<extra></extra>'), 
            row=4, col=1
        )

    if 'BBM_Angle_pct' in df.columns:
        fig.add_trace(
            go.Scatter(x=x_vals, y=df['BBM_Angle_pct'] * 100, mode='lines', name='BBM Angle %', line=dict(color='brown', width=2), hovertemplate='<b>BBM Angle %</b><br>%{x|%Y-%m-%d %H:%M:%S}<br>%{y:.2f}<extra></extra>'), 
            row=4, col=1
        )

    fig.add_hline(y=70, line=dict(color='black', dash='dash'), row=4, col=1)
    fig.add_hline(y=30, line=dict(color='black', dash='dash'), row=4, col=1)

    # ===== ROW 5: Stochastic RSI + BBM Angle + EMA Angle =====
    if 'STOCHRSIk' in df.columns:
        fig.add_trace(
            go.Scatter(x=x_vals, y=df['STOCHRSIk'], mode='lines', name='StochRSI %K', line=dict(color='blue', width=2), hovertemplate='<b>StochRSI %K</b><br>%{x|%Y-%m-%d %H:%M:%S}<br>%{y:.2f}<extra></extra>'), 
            row=5, col=1
        )
    
    if 'STOCHRSId' in df.columns:
        fig.add_trace(
            go.Scatter(x=x_vals, y=df['STOCHRSId'], mode='lines', name='StochRSI %D', line=dict(color='red', width=2, dash='dot'), hovertemplate='<b>StochRSI %D</b><br>%{x|%Y-%m-%d %H:%M:%S}<br>%{y:.2f}<extra></extra>'), 
            row=5, col=1
        )

    if 'BBM_Angle' in df.columns:
        fig.add_trace(
            go.Scatter(x=x_vals, y=df['BBM_Angle'], mode='lines', name='BBM Angle', line=dict(color='orange', width=2), hovertemplate='<b>BBM Angle</b><br>%{x|%Y-%m-%d %H:%M:%S}<br>%{y:.2f}<extra></extra>'), 
            row=5, col=1
        )

    if 'EMA_Angle' in df.columns:
        fig.add_trace(
            go.Scatter(x=x_vals, y=df['EMA_Angle'], mode='lines', name='EMA Angle', line=dict(color='brown', width=2), hovertemplate='<b>EMA Angle</b><br>%{x|%Y-%m-%d %H:%M:%S}<br>%{y:.2f}<extra></extra>'), 
            row=5, col=1
        )

    fig.add_hline(y=80, line=dict(color='#666', dash='dash', width=1), row=5, col=1)
    fig.add_hline(y=20, line=dict(color='#666', dash='dash', width=1), row=5, col=1)

    # ===== Layout - Professional Light-Gray Theme =====
    fig.update_layout(
        title=None,
        xaxis_title="",
        yaxis_title="Price",
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="middle",
            y=0.66,
            xanchor="left",
            x=0.0,
            font=dict(size=10, color="#1a1a1a", family="Inter, Segoe UI, sans-serif"),
            bgcolor="rgba(240, 240, 245, 0.95)",
            bordercolor="#ccccdd",
            borderwidth=1,
            tracegroupgap=8
        ),
        xaxis_rangeslider_visible=False,
        height=1400,
        autosize=True,
        hovermode='closest',
        margin=dict(l=40, r=40, t=60, b=50),
        plot_bgcolor="#f5f5f9",
        paper_bgcolor="#e8e8f0",
        font=dict(color="#1a1a1a", family="Inter, Segoe UI, sans-serif", size=11),
    )

    # Make subplot titles cleaner and more readable
    fig.update_annotations(
        font=dict(size=14, color="#111827", family="Inter, Segoe UI Semibold, sans-serif")
    )

    # Update axes styling
    fig.update_xaxes(
        type='date',
        tickformat='%Y-%m-%d %H:%M',
        showgrid=True,
        gridwidth=1,
        gridcolor="#d0d0dd",
        showline=True,
        linewidth=1,
        linecolor="#a0a0b8",
        zeroline=False,
        tickfont=dict(color="#4a4a5e", size=10, family="Inter, Segoe UI, sans-serif"),
        title_font=dict(color="#1a1a1a", size=12, family="Inter, Segoe UI Semibold, sans-serif")
    )

    fig.update_yaxes(
        showgrid=True,
        gridwidth=1,
        gridcolor="#d0d0dd",
        showline=True,
        linewidth=1,
        linecolor="#a0a0b8",
        zeroline=False,
        tickfont=dict(color="#4a4a5e", size=10, family="Inter, Segoe UI, sans-serif"),
        title_font=dict(color="#1a1a1a", size=12, family="Inter, Segoe UI Semibold, sans-serif")
    )

    # Leave hover formatting to Plotly defaults so the hover shows date and time exactly as provided by the data

    return fig
