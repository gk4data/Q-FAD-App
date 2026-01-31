import pandas as pd
import numpy as np
import pandas_ta as ta

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    max_high = df['High'].max()
    min_low = df['Low'].min()
    df['mean_middle'] = (max_high + min_low) / 2
    df['min_close_rolling'] = df['Close'].rolling(window=20, min_periods=1).min()

    df['RSI'] = ta.rsi(df['Close'], length=14)
    df['MFI'] = ta.mfi(close=df['Close'], high=df['High'], low=df['Low'], volume=df['Volume'], length=14)
    df['EMA9'] = ta.ema(df['Close'], length=10)
    df['volume_profile'] = np.where(df['Close'] >= df['Open'], 1, 0)

    bb = ta.bbands(df['Close'], length=14, std=2.0)
    bb = bb.rename(columns={
        'BBL_14_2.0_2.0': 'BBL', 'BBM_14_2.0_2.0': 'BBM', 'BBU_14_2.0_2.0': 'BBU',
        'BBB_14_2.0_2.0': 'BBB', 'BBP_14_2.0_2.0': 'BBP'
    })
    df = df.join(bb)
    df['cumulative_avg_bbb'] = df['BBB'].expanding().mean()

    df['BBM_Angle'] = np.degrees(np.arctan(df['BBM'].diff(5) / 5))
    df['EMA_Angle'] = np.degrees(np.arctan(df['EMA9'].diff(5) / 5))

    df['TP'] = (df['High'] + df['Low'] + df['Close'])/3
    df['CumVol'] = df['Volume'].cumsum()
    df['CumTPV'] = (df['TP'] * df['Volume']).cumsum()
    df['VWAP'] = df['CumTPV'] / df['CumVol']

    stochrsi = ta.stochrsi(close=df['Close'], length=19, d=3, k=3, rsi_length=19)
    df['STOCHRSIk'] = stochrsi.iloc[:, 0]
    df['STOCHRSId'] = stochrsi.iloc[:, 1]

    atr_len = 14
    df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=atr_len)
    atr_lookback = 16
    df['ATR_pctile'] = df['ATR'].rolling(atr_lookback).apply(
        lambda arr: pd.Series(arr).rank(pct=True).iloc[-1] if pd.Series(arr).notna().sum() else np.nan,
        raw=False).clip(0,1)

    mask_live = df['Date'].dt.time >= pd.to_datetime('09:30:00').time()
    df.loc[~mask_live, 'ATR_pctile'] = np.nan
    df['ATR_pctile'] = df['ATR_pctile'].ffill()

    win = 30
    slope = df['Close'].rolling(win).apply(lambda arr: np.polyfit(np.arange(len(arr)), arr, 1)[0], raw=True)
    vol = df['Close'].rolling(win).std()
    df['trend_norm'] = (slope / vol.replace(0, np.nan)).clip(-3,3).fillna(0)

    base_lo, base_hi = 30, 70
    shift = 5 * df['trend_norm']
    vol_widen = (df['ATR_pctile'] - 0.5) * 10
    df['RSI_lo'] = (base_lo - shift - vol_widen).clip(20,40)
    df['RSI_hi'] = (base_hi + shift + vol_widen).clip(60,85)

    def pct_rank_col(s, n=30):
        return s.rolling(n).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1] if len(pd.Series(x).dropna()) else np.nan, raw=False)

    df['MFI_pct'] = pct_rank_col(df['MFI'], 16)
    df['BBM_Angle_pct'] = pct_rank_col(df['BBM_Angle'], 8)

    df.dropna(inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df
