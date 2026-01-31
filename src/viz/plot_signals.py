import plotly.graph_objects as go
from plotly.subplots import make_subplots


def plot_signals(df):
    """
    Simple plot function based on working reference code
    """
    
    # Create figure with 5 subplots
    fig = make_subplots(
        rows=5, cols=1, 
        shared_xaxes=True, 
        row_heights=[0.5, 0.15, 0.2, 0.2, 0.2],
        vertical_spacing=0.05, 
        subplot_titles=("Candlesticks", "Volume", "Adaptive RSI & MFI", "Strength", "Stochastic & BBMAngle")
    )

    # ===== ROW 1: Candlestick Chart =====
    fig.add_trace(
        go.Candlestick(
            x=df['Date'],
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
                x=df['Date'][df['Buy_Signal']],
                y=df['Low'][df['Buy_Signal']],  
                mode='markers',
                marker=dict(color='Black', size=14, symbol='triangle-up'),
                name="Buy Signal"
            ),
            row=1, col=1
        )

    # Sell Signals
    if 'Sell_Signal' in df.columns and df['Sell_Signal'].any():
        fig.add_trace(
            go.Scatter(
                x=df['Date'][df['Sell_Signal']],
                y=df['High'][df['Sell_Signal']],  
                mode='markers',
                marker=dict(color='Red', size=14, symbol='triangle-down'),
                name="Sell Signal"
            ),
            row=1, col=1
        )

    # Mid Buy Signal
    if 'Mid_Buy_Signal' in df.columns and df['Mid_Buy_Signal'].any():
        fig.add_trace(
            go.Scatter(
                x=df['Date'][df['Mid_Buy_Signal']], 
                y=df['BBM'][df['Mid_Buy_Signal']], 
                mode="markers",
                marker=dict(size=14, color="Green", symbol='triangle-up'),
                name="Mid_Buy_Signal"
            ), 
            row=1, col=1
        )

    # RSI Range Buy Signal
    if 'RSI_Range_Buy_Signal' in df.columns and df['RSI_Range_Buy_Signal'].any():
        fig.add_trace(
            go.Scatter(
                x=df['Date'][df['RSI_Range_Buy_Signal']],
                y=df['Low'][df['RSI_Range_Buy_Signal']],  
                mode='markers',
                marker=dict(color='Purple', size=16, symbol='triangle-up'),
                name="RSI_Range_Buy_Signal"
            ),
            row=1, col=1
        )

    # OverSold Buy Signal
    if 'OverSold_Buy_Signal' in df.columns and df['OverSold_Buy_Signal'].any():
        fig.add_trace(
            go.Scatter(
                x=df['Date'][df['OverSold_Buy_Signal']],
                y=df['Low'][df['OverSold_Buy_Signal']],  
                mode='markers',
                marker=dict(color='Blue', size=16, symbol='triangle-up'),
                name="OverSold_Buy_Signal"
            ),
            row=1, col=1
        )

    # Super Low Buy Signal
    if 'Super_Low_Buy_Signal' in df.columns and df['Super_Low_Buy_Signal'].any():
        fig.add_trace(
            go.Scatter(
                x=df['Date'][df['Super_Low_Buy_Signal']],
                y=df['Low'][df['Super_Low_Buy_Signal']],  
                mode='markers',
                marker=dict(color='Brown', size=16, symbol='triangle-up'),
                name="Super_Low_Buy_Signal"
            ),
            row=1, col=1
        )

    # Mid Buy Signal 2
    if 'Mid_Buy_Signal_2' in df.columns and df['Mid_Buy_Signal_2'].any():
        fig.add_trace(
            go.Scatter(
                x=df['Date'][df['Mid_Buy_Signal_2']],
                y=df['Low'][df['Mid_Buy_Signal_2']],  
                mode='markers',
                marker=dict(color='Cyan', size=16, symbol='triangle-up'),
                name="Mid_Buy_Signal_2"
            ),
            row=1, col=1
        )

    # Bollinger Bands
    if 'BBL' in df.columns:
        fig.add_trace(go.Scatter(x=df['Date'], y=df['BBL'], line=dict(color='blue', width=1), name="Lower BB"), row=1, col=1)
    
    if 'BBU' in df.columns:
        fig.add_trace(go.Scatter(x=df['Date'], y=df['BBU'], line=dict(color='blue', width=1), name="Upper BB"), row=1, col=1)
    
    if 'BBM' in df.columns:
        fig.add_trace(go.Scatter(x=df['Date'], y=df['BBM'], line=dict(color='orange', width=1), name="Middle BB"), row=1, col=1)
    
    if 'EMA9' in df.columns:
        fig.add_trace(go.Scatter(x=df['Date'], y=df['EMA9'], line=dict(color='black', width=1), name="EMA9"), row=1, col=1)
    
    if 'VWAP' in df.columns:
        fig.add_trace(go.Scatter(x=df['Date'], y=df['VWAP'], line=dict(color='purple', width=2), name="VWAP"), row=1, col=1)

    # ===== ROW 2: Volume =====
    volume_colors = ['green' if c >= o else 'red' for c, o in zip(df['Close'], df['Open'])]
    fig.add_trace(
        go.Bar(
            x=df['Date'],
            y=df['Volume'],
            marker_color=volume_colors,
            name='Volume',
            opacity=0.7
        ),
        row=2, col=1
    )

    # ===== ROW 3: RSI & MFI =====
    if 'RSI' in df.columns:
        fig.add_trace(
            go.Scatter(x=df['Date'], y=df['RSI'], mode='lines', name='RSI', line=dict(color='blue', width=2)), 
            row=3, col=1
        )
    
    if 'RSI_hi' in df.columns:
        fig.add_trace(
            go.Scatter(x=df['Date'], y=df['RSI_hi'], mode='lines', name='RSI High', line=dict(color='red', width=1, dash='dash')), 
            row=3, col=1
        )
    
    if 'RSI_lo' in df.columns:
        fig.add_trace(
            go.Scatter(x=df['Date'], y=df['RSI_lo'], mode='lines', name='RSI Low', line=dict(color='green', width=1, dash='dash')), 
            row=3, col=1
        )
    
    if 'MFI_pct' in df.columns:
        fig.add_trace(
            go.Scatter(x=df['Date'], y=df['MFI_pct'] * 100, mode='lines', name='MFI %', line=dict(color='orange', width=2)), 
            row=3, col=1
        )

    # ===== ROW 4: RSI & MFI & BBM Angle % =====
    if 'RSI' in df.columns:
        fig.add_trace(
            go.Scatter(x=df['Date'], y=df['RSI'], mode='lines', name='RSI', line=dict(color='purple', width=2)), 
            row=4, col=1
        )
    
    if 'MFI' in df.columns:
        fig.add_trace(
            go.Scatter(x=df['Date'], y=df['MFI'], mode='lines', name='MFI', line=dict(color='black', width=2)), 
            row=4, col=1
        )

    if 'BBM_Angle_pct' in df.columns:
        fig.add_trace(
            go.Scatter(x=df['Date'], y=df['BBM_Angle_pct'] * 100, mode='lines', name='BBM Angle %', line=dict(color='brown', width=2)), 
            row=4, col=1
        )

    fig.add_hline(y=70, line=dict(color='black', dash='dash'), row=4, col=1)
    fig.add_hline(y=30, line=dict(color='black', dash='dash'), row=4, col=1)

    # ===== ROW 5: Stochastic RSI + BBM Angle + EMA Angle =====
    if 'STOCHRSIk' in df.columns:
        fig.add_trace(
            go.Scatter(x=df['Date'], y=df['STOCHRSIk'], mode='lines', name='StochRSI %K', line=dict(color='blue', width=2)), 
            row=5, col=1
        )
    
    if 'STOCHRSId' in df.columns:
        fig.add_trace(
            go.Scatter(x=df['Date'], y=df['STOCHRSId'], mode='lines', name='StochRSI %D', line=dict(color='red', width=2, dash='dot')), 
            row=5, col=1
        )

    if 'BBM_Angle' in df.columns:
        fig.add_trace(
            go.Scatter(x=df['Date'], y=df['BBM_Angle'], mode='lines', name='BBM Angle', line=dict(color='orange', width=2)), 
            row=5, col=1
        )

    if 'EMA_Angle' in df.columns:
        fig.add_trace(
            go.Scatter(x=df['Date'], y=df['EMA_Angle'], mode='lines', name='EMA Angle', line=dict(color='brown', width=2)), 
            row=5, col=1
        )

    fig.add_hline(y=80, line=dict(color='black', dash='dash'), row=5, col=1)
    fig.add_hline(y=20, line=dict(color='black', dash='dash'), row=5, col=1)

    # ===== Layout =====
    fig.update_layout(
        title="📊 Q-FAD Algo HFT Trading",
        xaxis_title="Date",
        showlegend=True,
        xaxis_rangeslider_visible=False,
        height=900,
        width=1400,
        hovermode='x unified'
    )

    return fig
