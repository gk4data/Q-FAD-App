import pandas as pd
import numpy as np
from src.signals.buy_signals import generate_buy_signals
from src.signals.sell_signals import generate_sell_signals
from src.signals.generator import add_long_signal


def make_base_df(n=40):
    rng = pd.date_range("2025-01-01 09:30", periods=n, freq="T")
    df = pd.DataFrame({
        'Date': rng,
        'Open': np.linspace(100, 110, n),
        'High': np.linspace(101, 111, n),
        'Low': np.linspace(99, 109, n),
        'Close': np.linspace(100, 110, n),
        'Volume': np.linspace(1000, 2000, n).astype(int)
    })

    # Minimal indicator columns with safe defaults to exercise logic
    df['RSI'] = 50
    df['STOCHRSIk'] = 60
    df['STOCHRSId'] = 55
    df['BBM_Angle'] = 5
    df['EMA9'] = df['Close'] - 0.5
    df['MFI_pct'] = 0.5
    df['volume_profile'] = 1
    df['BBM'] = df['Close'] - 0.4
    df['BBL'] = df['Close'] - 1.0
    df['BBU'] = df['Close'] + 1.0
    df['RSI_lo'] = 30
    df['is_downtrend'] = False
    df['BBM_Angle_pct'] = 0.5
    df['MFI'] = 40
    df['EMA_Angle'] = 2
    df['EMA_Trend'] = 'Downtrend'
    df['RSI_hi'] = 70
    return df


def test_generate_buy_signals_creates_columns():
    df = make_base_df()
    out = generate_buy_signals(df)
    for col in ['Buy_Signal', 'Mid_Buy_Signal', 'OverSold_Buy_Signal', 'RSI_Range_Buy_Signal', 'Super_Low_Buy_Signal', 'Mid_Buy_Signal_2']:
        assert col in out.columns
        assert out[col].dtype == 'bool'


def test_generate_sell_signals_creates_column():
    df = make_base_df()
    out = generate_sell_signals(df)
    assert 'Sell_Signal' in out.columns
    assert out['Sell_Signal'].dtype == 'bool'


def test_add_long_signal_wrapper():
    df = make_base_df()
    out = add_long_signal(df)
    # both buy and sell cols present
    assert 'Buy_Signal' in out.columns
    assert 'Sell_Signal' in out.columns