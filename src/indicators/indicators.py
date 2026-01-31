import pandas as pd
import numpy as np
import pandas_ta as ta

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # Ensure Date column is datetime dtype to avoid pandas comparison FutureWarnings
    if 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    max_high = df['High'].max()
    min_low = df['Low'].min()

    df['mean_middle'] = (max_high + min_low) / 2
    df['min_close_rolling'] = df['Close'].rolling(window=20, min_periods=1).min()

    df['RSI'] = ta.rsi(df['Close'], length=14)  # RSI with length 30
    df['MFI'] = ta.mfi(close=df['Close'],high=df['High'], low=df['Low'], volume=df['Volume'], length=14)
    df['EMA9'] = ta.ema(df['Close'], length=10)  # EMA 9
    df['volume_profile'] = np.where(df['Close'] >= df['Open'], 1, 0)

    # Compute Bollinger Bands
    my_bbands = ta.bbands(df['Close'], length=14, std=2.0)
    df = df.join(my_bbands.rename(columns={"BBL_14_2.0_2.0": "BBL", "BBM_14_2.0_2.0": "BBM", "BBU_14_2.0_2.0": "BBU", "BBB_14_2.0_2.0" : "BBB", "BBP_14_2.0_2.0" : "BBP"}))
    df['cumulative_avg_bbb'] = df['BBB'].expanding().mean()

    # ADX (Average Directional Index)
    adx_df = ta.adx(high=df['High'], low=df['Low'], close=df['Close'], length=14)
    adx_df = adx_df.rename(columns={f"ADX_{14}": "ADX", f"DMP_{14}": "DI+", f"DMN_{14}": "DI-"})
    df = df.join(adx_df)

    # calculate angle and slope of line and candle
    BBM_Slope = df['BBM'].diff(5) / 5  # Change in EMA9 per candle
    df['BBM_Angle'] = np.degrees(np.arctan(BBM_Slope))  # Convert to degrees
    EMA_Slope = df['EMA9'].diff(5) / 5  # Change in EMA9 per candle
    df['EMA_Angle'] = np.degrees(np.arctan(EMA_Slope))  # Convert to degrees

    # Calculate BBU angle (restricted to 90-270° range)
    BBM_diff = df['BBM'] - df['BBM'].shift(1)
    BBM_Angle_Radians = np.arctan2(BBM_diff, 1)
    df['BBM_Angle_Degree'] = 180 - np.degrees(BBM_Angle_Radians)  # Restricted 90-270°

    # Calculate BBU angle (restricted to 90-270° range)
    EMA_diff = df['EMA9'] - df['EMA9'].shift(1)
    EMA_Angle_Radians = np.arctan2(EMA_diff, 1)
    df['EMA_Angle_Degree'] = 180 - np.degrees(EMA_Angle_Radians)  # Restricted 90-270°

    # Calculate BBU angle (restricted to 90-270° range)
    BBU_diff = df['BBU'] - df['BBU'].shift(1)
    BBU_Angle_Radians = np.arctan2(BBU_diff, 1)
    df['BBU_Angle_Degree'] = 180 - np.degrees(BBU_Angle_Radians)  # Restricted 90-270°

    # Calculate BBL angle (restricted to 90-270° range)
    BBU_diff = df['BBL'] - df['BBL'].shift(1)
    BBU_Angle_Radians = np.arctan2(BBU_diff, 1)
    df['BBL_Angle_Degree'] = 180 - np.degrees(BBU_Angle_Radians)  # Restricted 90-270°

    # VWAP intraday
    tp = (df['High'] + df['Low'] + df['Close'])/3

    # 4) keep your session VWAP as well (if desired)
    df['TP'] = tp
    df['CumVol'] = df['Volume'].cumsum()
    df['CumTPV'] = (df['TP'] * df['Volume']).cumsum()
    df['VWAP'] = df['CumTPV'] / df['CumVol']

    # Compute Stochastic RSI    
    stochrsi_df = ta.stochrsi(close=df['Close'], length=19, d=3, k=3, rsi_length=19)  # Returns multiple columns
    df['STOCHRSIk'] = stochrsi_df.iloc[:, 0]  # Extract %K line
    df['STOCHRSId'] = stochrsi_df.iloc[:, 1]  # Extract %D line


    # ATR Percentile for Volatility Regime
    atr_len = 14
    df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=atr_len)
    atr_lookback = 16
    
    def pct_rank(arr):
        return arr.rank(pct=True).iloc[-1] if arr.notna().sum() else np.nan
    df['ATR_pctile'] = df['ATR'].rolling(atr_lookback).apply(pct_rank, raw=False).clip(0, 1)
    # Avoid using .dt.time directly in comparisons (can raise FutureWarning); compare by seconds since midnight
    time_seconds = df['Date'].dt.hour * 3600 + df['Date'].dt.minute * 60 + df['Date'].dt.second
    market_start_seconds = 9 * 3600 + 30 * 60
    mask_live = time_seconds >= market_start_seconds
    df.loc[~mask_live, 'ATR_pctile'] = np.nan
    df['ATR_pctile'] = df['ATR_pctile'].ffill()

    # Rolling linear regression slope: must return a scalar
    win = 30  # 20–40 for 1-minute intraday
    def lr_slope(window_ndarray):
        x = np.arange(window_ndarray.shape[0])
        # Return only the slope (index 0) — scalar
        return np.polyfit(x, window_ndarray, 1)[0]

    # raw=True passes ndarray to avoid scalar-conversion errors
    slope = df['Close'].rolling(win).apply(lr_slope, raw=True)

    # Vol normalization to make slope dimensionless
    vol = df['Close'].rolling(win).std()
    trend_norm = (slope / vol.replace(0, np.nan)).clip(-3, 3).fillna(0)
    df['trend_norm'] = (slope / vol.replace(0, np.nan)).clip(-3, 3).fillna(0)


    # Adaptive RSI bands for intraday
    base_lo, base_hi = 30, 70
    shift = 5 * trend_norm                         # relax/tighten by trend strength
    vol_widen = (df['ATR_pctile'] - 0.5) * 10      # widen in high vol, tighten in low

    # Conservative clamps for options on 1m chart
    df['RSI_lo'] = (base_lo - shift - vol_widen).clip(20, 40)
    df['RSI_hi'] = (base_hi + shift + vol_widen).clip(60, 85)

    #4)  Adaptive MFI and volume filter 
    def pct_rank(s, n=30):
        return s.rolling(n).apply(lambda x: x.rank(pct=True).iloc[-1] if len(x.dropna()) else np.nan, raw=False)
    df['MFI_pct'] = pct_rank(df['MFI'], 16)
    df['BBM_Angle_pct'] = pct_rank(df['BBM_Angle'], 8)
    df['RSI_pct'] = pct_rank(df['RSI'], 14)

    df.dropna(inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df
