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
        'ATR_pctile_trend': 0.50,
        'ATR_pctile_range': 0.35,
        'trend_norm_down': -0.02,
        'bb_width_median_window': 50,
        'bb_width_low_factor': 0.9,
        'stoch_std_window': 8,
        'stoch_std_max_for_range': 12,
        'mfi_pct_mid_low': 0.3,
        'mfi_pct_mid_high': 0.7,
        'consecutive_required': 1,
        'bb_trend_win': 9,
        'bb_trend_norm_base': 'BBM',
        'bb_trend_thresh': 0.0008,
        'bb_trend_require_both': True
    }
    if params:
        p.update(params)

    # small linear slope helper
    def lr_slope(arr):
        x = np.arange(arr.shape[0])
        if arr.size <= 1 or np.all(np.isclose(arr, arr[0])):
            return 0.0
        return np.polyfit(x, arr, 1)[0]

    # require k consecutive True helper
    def require_consecutive(bool_series, k):
        if k <= 1:
            return bool_series.astype(bool)
        return (bool_series.astype(int).rolling(window=k, min_periods=k).sum() >= k).fillna(False)

    # --- EMA short/long & normalized slope (EMA_Trend) ---
    if p['ema_short_col'] in df.columns:
        ema_short = df[p['ema_short_col']]
    else:
        ema_short = df['Close'].ewm(span=9, adjust=False).mean()

    ema_long = df['Close'].ewm(span=p['ema_long_len'], adjust=False).mean()
    ema_cross_down = ema_short < ema_long
    ema_cross_up = ema_short > ema_long

    slope = ema_short.rolling(p['slope_win'], min_periods=1).apply(lr_slope, raw=True)
    ema_mean = ema_short.rolling(p['slope_win'], min_periods=1).mean().replace(0, np.nan)
    slope_norm = slope / ema_mean
    slope_down = slope_norm < -abs(p['slope_norm_thresh'])
    slope_up = slope_norm > abs(p['slope_norm_thresh'])

    ema_down_raw = (ema_cross_down & slope_down)
    ema_up_raw = (ema_cross_up & slope_up)
    k_h = max(1, int(p['hysteresis_k']))
    ema_down = require_consecutive(ema_down_raw, k_h)
    ema_up = require_consecutive(ema_up_raw, k_h)
    EMA_Trend_series = pd.Series(np.where(ema_down, 'Downtrend', np.where(ema_up, 'Uptrend', 'Flat')), index=df.index)

    # --- BBM (Trend) via BBM_Angle if present else BBM slope ---
    if 'BBM_Angle' in df.columns:
        bbm_angle = df['BBM_Angle']
        bbm_down_raw = bbm_angle < -abs(p['angle_thresh_deg'])
        bbm_up_raw = bbm_angle > abs(p['angle_thresh_deg'])
    elif 'BBM' in df.columns:
        bbm_slope = df['BBM'].rolling(p['slope_win'], min_periods=1).apply(lr_slope, raw=True)
        bbm_mean = df['BBM'].rolling(p['slope_win'], min_periods=1).mean().replace(0, np.nan)
        bbm_slope_norm = bbm_slope / bbm_mean
        bbm_down_raw = bbm_slope_norm < -abs(p['slope_norm_thresh'])
        bbm_up_raw = bbm_slope_norm > abs(p['slope_norm_thresh'])
    else:
        bbm_down_raw = pd.Series(False, index=df.index)
        bbm_up_raw = pd.Series(False, index=df.index)

    bbm_down = require_consecutive(bbm_down_raw, k_h)
    bbm_up = require_consecutive(bbm_up_raw, k_h)
    Trend_series = pd.Series(np.where(bbm_down, 'Downtrend', np.where(bbm_up, 'Uptrend', 'Flat')), index=df.index)

    # --- Bollinger Bands trend detection (BB_trend) ---
    if ('BBU' in df.columns) and ('BBL' in df.columns):
        bbu_slope = df['BBU'].rolling(p['bb_trend_win'], min_periods=1).apply(lr_slope, raw=True)
        bbl_slope = df['BBL'].rolling(p['bb_trend_win'], min_periods=1).apply(lr_slope, raw=True)
        if p['bb_trend_norm_base'] == 'BBM' and 'BBM' in df.columns:
            base = df['BBM'].rolling(p['bb_trend_win'], min_periods=1).mean().replace(0, np.nan)
        else:
            base = df['Close'].rolling(p['bb_trend_win'], min_periods=1).mean().replace(0, np.nan)

        bbu_slope_norm = bbu_slope / base
        bbl_slope_norm = bbl_slope / base

        bb_up_bbu = bbu_slope_norm > p['bb_trend_thresh']
        bb_up_bbl = bbl_slope_norm > p['bb_trend_thresh']
        bb_down_bbu = bbu_slope_norm < -p['bb_trend_thresh']
        bb_down_bbl = bbl_slope_norm < -p['bb_trend_thresh']

        if p['bb_trend_require_both']:
            BB_bullish = (bb_up_bbu & bb_up_bbl)
            BB_bearish = (bb_down_bbu & bb_down_bbl)
        else:
            BB_bullish = (bb_up_bbu | bb_up_bbl)
            BB_bearish = (bb_down_bbu | bb_down_bbl)

        BB_trend_series = pd.Series(np.where(BB_bullish, 'bullish', np.where(BB_bearish, 'bearish', 'neutral')), index=df.index)
    else:
        BB_trend_series = pd.Series('neutral', index=df.index)

    # --- Relaxed regime rules (no day-level outputs) ---
    exists = lambda c: c in df.columns
    price_below = (df['Close'] < df.get('EMA9', ema_short)) if exists('Close') else pd.Series(False, index=df.index)
    atr_high = (df['ATR_pctile'] > p['ATR_pctile_trend']) if exists('ATR_pctile') else pd.Series(False, index=df.index)
    lower_lows = ((df['Low'] < df['Low'].shift(1)) & (df['Low'].shift(1) < df['Low'].shift(2))) if exists('Low') else pd.Series(False, index=df.index)
    lower_closes = ((df['Close'] < df['Close'].shift(1)) & (df['Close'].shift(1) < df['Close'].shift(2))) if exists('Close') else pd.Series(False, index=df.index)
    lower_struct = lower_lows | lower_closes
    trend_norm_down = (df['trend_norm'] < p['trend_norm_down']) if exists('trend_norm') else pd.Series(False, index=df.index)

    EMA_down_bool = (EMA_Trend_series == 'Downtrend')
    BBM_down_bool = (Trend_series == 'Downtrend')

    # supportive confirmations include BB_trend == 'bearish'
    supportive = atr_high | lower_struct | trend_norm_down | (BB_trend_series == 'bearish')

    is_downtrend_raw = ((EMA_down_bool | BBM_down_bool) & price_below & supportive)
    k_final = max(1, int(p['consecutive_required']))
    is_downtrend = require_consecutive(is_downtrend_raw, k_final)

    # sideways detection
    if exists('BBU') and exists('BBL') and exists('BBM'):
        bb_width = (df['BBU'] - df['BBL']) / df['BBM'].replace(0, np.nan)
        bb_med = bb_width.rolling(p['bb_width_median_window'], min_periods=1).median()
        bb_narrow = (bb_width < bb_med * p['bb_width_low_factor'])
    else:
        bb_narrow = pd.Series(False, index=df.index)

    stoch_std = df['STOCHRSIk'].rolling(p['stoch_std_window'], min_periods=1).std().fillna(np.inf) if exists('STOCHRSIk') else pd.Series(np.inf, index=df.index)
    ema_flat = (df['EMA_Angle'].abs() < p['angle_thresh_deg']) if exists('EMA_Angle') else pd.Series(False, index=df.index)
    bbm_flat = (df['BBM_Angle'].abs() < p['angle_thresh_deg']) if exists('BBM_Angle') else pd.Series(False, index=df.index)
    mfi_mid = df['MFI_pct'].between(p['mfi_pct_mid_low'], p['mfi_pct_mid_high']) if exists('MFI_pct') else pd.Series(False, index=df.index)
    inside_bb5 = ((df['Close'] > df['BBL']) & (df['Close'] < df['BBU'])).rolling(5, min_periods=1).sum() == 5 if (exists('BBL') and exists('BBU')) else pd.Series(False, index=df.index)

    side_primary = (df['ATR_pctile'] < p['ATR_pctile_range']) if exists('ATR_pctile') else pd.Series(False, index=df.index)
    sideways_raw = ((side_primary | bb_narrow) & (ema_flat | bbm_flat | (stoch_std < p['stoch_std_max_for_range']) | inside_bb5 | mfi_mid))
    is_sideways = require_consecutive(sideways_raw, k_final)

    # final regime priority: downtrend > sideways > other
    regime_series = pd.Series('other', index=df.index)
    regime_series[is_sideways] = 'sideways'
    regime_series[is_downtrend] = 'downtrend'

    # --- write outputs (only these) ---
    df_out = df_input.copy().reset_index(drop=True)
    df_out['EMA_Trend'] = EMA_Trend_series.values
    df_out['Trend'] = Trend_series.values
    df_out['regime'] = regime_series.values
    # Also expose helper signals expected by downstream generators
    df_out['is_downtrend'] = is_downtrend.values
    try:
        df_out['BB_trend'] = BB_trend_series.values
    except NameError:
        # Fallback to neutral if BB_trend_series wasn't computed
        df_out['BB_trend'] = 'neutral'
    return df_out
