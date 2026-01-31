import pandas as pd
import numpy as np

def detect_regimes_relaxed(df_input: pd.DataFrame, params: dict = None) -> pd.DataFrame:
    df = df_input.copy()
    p = {
        'ema_short_col': 'EMA9',
        'ema_long_len': 21,
        'slope_win': 9,
        'slope_norm_thresh': 0.002,
        'hysteresis_k': 1,
        'angle_thresh_deg': 0.8,
        'EMA_angle_flat_abs': 0.8,
        'ATR_pctile_trend': 0.50,
        'ATR_pctile_range': 0.35,
        'trend_norm_down': -0.02,
        'bb_width_median_window': 50,
        'bb_width_low_factor': 0.9,
        'stoch_std_window': 8,
        'stoch_std_max_for_range': 12,
        'consecutive_required': 1
    }
    if params:
        p.update(params)

    def lr_slope(arr):
        x = np.arange(arr.shape[0])
        if np.all(np.isclose(arr, arr[0])):
            return 0.0
        return np.polyfit(x, arr, 1)[0]

    ema_short = df.get(p['ema_short_col'], df['Close'].ewm(span=9, adjust=False).mean())
    ema_long = df['Close'].ewm(span=p['ema_long_len'], adjust=False).mean()
    slope = ema_short.rolling(p['slope_win'], min_periods=1).apply(lr_slope, raw=True)
    ema_mean = ema_short.rolling(p['slope_win'], min_periods=1).mean().replace(0, np.nan)
    slope_norm = slope / ema_mean

    ema_down_raw = (ema_short < ema_long) & (slope_norm < -abs(p['slope_norm_thresh']))
    ema_up_raw   = (ema_short > ema_long) & (slope_norm > abs(p['slope_norm_thresh']))
    k_h = max(1, int(p['hysteresis_k']))
    if k_h > 1:
        ema_down = (ema_down_raw.astype(int).rolling(k_h, min_periods=1).min() == 1)
        ema_up   = (ema_up_raw.astype(int).rolling(k_h, min_periods=1).min() == 1)
    else:
        ema_down = ema_down_raw.astype(bool)
        ema_up = ema_up_raw.astype(bool)

    EMA_Trend_series = pd.Series(np.where(ema_down, 'Downtrend', np.where(ema_up, 'Uptrend', 'Flat')), index=df.index)

    if 'BBM_Angle' in df.columns:
        bbm_angle = df['BBM_Angle']
        bbm_down_raw = bbm_angle < -abs(p['angle_thresh_deg'])
        bbm_up_raw   = bbm_angle > abs(p['angle_thresh_deg'])
    elif 'BBM' in df.columns:
        bbm_slope = df['BBM'].rolling(p['slope_win'], min_periods=1).apply(lr_slope, raw=True)
        bbm_mean = df['BBM'].rolling(p['slope_win'], min_periods=1).mean().replace(0, np.nan)
        bbm_slope_norm = bbm_slope / bbm_mean
        bbm_down_raw = bbm_slope_norm < -abs(p['slope_norm_thresh'])
        bbm_up_raw   = bbm_slope_norm > abs(p['slope_norm_thresh'])
    else:
        bbm_down_raw = pd.Series(False, index=df.index)
        bbm_up_raw   = pd.Series(False, index=df.index)

    if k_h > 1:
        bbm_down = (bbm_down_raw.astype(int).rolling(k_h, min_periods=1).min() == 1)
        bbm_up   = (bbm_up_raw.astype(int).rolling(k_h, min_periods=1).min() == 1)
    else:
        bbm_down = bbm_down_raw.astype(bool)
        bbm_up   = bbm_up_raw.astype(bool)

    Trend_series = pd.Series(np.where(bbm_down, 'Downtrend', np.where(bbm_up, 'Uptrend', 'Flat')), index=df.index)

    exists = lambda c: c in df.columns
    price_below = (df['Close'] < df.get('EMA9', ema_short))
    atr_high = (df['ATR_pctile'] > p['ATR_pctile_trend']) if exists('ATR_pctile') else pd.Series(False, index=df.index)
    lower_lows = (df['Low'] < df['Low'].shift(1)) & (df['Low'].shift(1) < df['Low'].shift(2)) if exists('Low') else pd.Series(False, index=df.index)
    lower_closes = (df['Close'] < df['Close'].shift(1)) & (df['Close'].shift(1) < df['Close'].shift(2)) if exists('Close') else pd.Series(False, index=df.index)
    lower_struct = lower_lows | lower_closes
    trend_norm_down = (df['trend_norm'] < p['trend_norm_down']) if exists('trend_norm') else pd.Series(False, index=df.index)

    EMA_down = EMA_Trend_series == 'Downtrend'
    BBM_down = Trend_series == 'Downtrend'

    supportive = atr_high | lower_struct | trend_norm_down
    is_downtrend_raw = ( (EMA_down | BBM_down) & price_below & supportive )

    k = max(1, int(p['consecutive_required']))
    if k > 1:
        is_downtrend = (is_downtrend_raw.astype(int).rolling(k, min_periods=1).min() == 1)
    else:
        is_downtrend = is_downtrend_raw.astype(bool)

    bb_width = (df['BBU'] - df['BBL']) / df['BBM'] if (exists('BBU') and exists('BBL') and exists('BBM')) else pd.Series(np.nan, index=df.index)
    bb_med = bb_width.rolling(p['bb_width_median_window'], min_periods=1).median() if not bb_width.isna().all() else pd.Series(np.nan, index=df.index)
    bb_narrow = (bb_width < bb_med * p['bb_width_low_factor']) if not bb_width.isna().all() else pd.Series(False, index=df.index)
    stoch_std = df['STOCHRSIk'].rolling(p['stoch_std_window'], min_periods=1).std().fillna(np.inf) if exists('STOCHRSIk') else pd.Series(np.inf, index=df.index)
    ema_flat = (df['EMA_Angle'].abs() < p['EMA_angle_flat_abs']) if exists('EMA_Angle') else pd.Series(False, index=df.index)
    bbm_flat = (df['BBM_Angle'].abs() < p['EMA_angle_flat_abs']) if exists('BBM_Angle') else pd.Series(False, index=df.index)
    mfi_mid = df['MFI_pct'].between(0.3, 0.7) if exists('MFI_pct') else pd.Series(False, index=df.index)
    inside_bb5 = ((df['Close'] > df['BBL']) & (df['Close'] < df['BBU'])).rolling(5, min_periods=1).sum() == 5 if (exists('BBL') and exists('BBU')) else pd.Series(False, index=df.index)

    side_primary = (df['ATR_pctile'] < p['ATR_pctile_range']) if exists('ATR_pctile') else pd.Series(False, index=df.index)
    sideways_raw = ( (side_primary | bb_narrow) & (ema_flat | bbm_flat | (stoch_std < p['stoch_std_max_for_range']) | inside_bb5 | mfi_mid) )

    if k > 1:
        is_sideways = (sideways_raw.astype(int).rolling(k, min_periods=1).min() == 1)
    else:
        is_sideways = sideways_raw.astype(bool)

    regime = pd.Series('other', index=df.index)
    regime[is_sideways] = 'sideways'
    regime[is_downtrend] = 'downtrend'

    df_out = df_input.copy()
    df_out['EMA_Trend'] = EMA_Trend_series.values
    df_out['Trend'] = Trend_series.values
    df_out['is_downtrend'] = is_downtrend.values.astype(bool)
    df_out['is_sideways'] = is_sideways.values.astype(bool)
    df_out['regime'] = regime.values
    return df_out
