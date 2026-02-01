import numpy as np
import pandas as pd
from typing import Optional


def classify_trend_by_angles(
    df: pd.DataFrame,
    angle_win: int = 3,           # NO smoothing → reacts instantly to angle change
    bb_width_win: int = 7,        # very short window to detect tight bands
    angle_mag_thresh: float = 1,  # very small threshold → count even tiny angle changes
    bb_width_thresh: float = 0.01,# tighter threshold → detect sideways very early
    slope_win: int = 3,           # very fast EMA/BBM slope confirmation
    slope_thresh: float = 2e-5    # tiny slope threshold → slope reacts instantly
) -> pd.DataFrame:
    """Classify trend using BB/EMA angle columns and short-term EMA9/BBM slopes.

    Reads: BBM_Angle_Degree, EMA_Angle_Degree, BBU_Angle_Degree, BBL_Angle_Degree, BBM, BBU, BBL, EMA9.
    Writes only: df['trend_regime_angles'] (one of:
      'pure_sideways','sideways_up','sideways_down',
      'pure_up','pure_down','up_trend_mixed','down_trend_mixed','trend_mixed')
    """

    out = df.copy().reset_index(drop=True)
    n = len(out)
    if n == 0:
        out['trend_regime_angles'] = []
        return out

    def offset_from_180(arr: pd.Series) -> pd.Series:
        return (arr.astype(float) - 180.0)

    required_angles = ['BBM_Angle_Degree', 'EMA_Angle_Degree', 'BBU_Angle_Degree', 'BBL_Angle_Degree']
    for c in required_angles:
        if c not in out.columns:
            raise ValueError(f"Missing required angle column: {c}")

    # compute smoothed signed offsets (negative => upward tilt)
    bbm_off = offset_from_180(out['BBM_Angle_Degree']).rolling(angle_win, min_periods=1).mean()
    ema_off = offset_from_180(out['EMA_Angle_Degree']).rolling(angle_win, min_periods=1).mean()
    bbu_off = offset_from_180(out['BBU_Angle_Degree']).rolling(angle_win, min_periods=1).mean()
    bbl_off = offset_from_180(out['BBL_Angle_Degree']).rolling(angle_win, min_periods=1).mean()

    # magnitude (abs) smoothed
    bbm_mag = bbm_off.abs()
    ema_mag = ema_off.abs()
    bbu_mag = bbu_off.abs()
    bbl_mag = bbl_off.abs()

    if 'EMA9' not in out.columns or 'BBM' not in out.columns:
        raise ValueError("Missing EMA9 or BBM column required for slope confirmation.")
    ema_slope = (out['EMA9'] - out['EMA9'].shift(slope_win)) / slope_win
    bbm_slope = (out['BBM'] - out['BBM'].shift(slope_win)) / slope_win

    # bb width and stability check (tight tube)
    bb_width = (out['BBU'] - out['BBL']) / out['BBM'].replace(0, np.nan)
    bb_width_mean = bb_width.rolling(bb_width_win, min_periods=1).mean()

    res = [''] * n

    for i in range(n):
        offs = np.array([bbm_off.iat[i], ema_off.iat[i], bbu_off.iat[i], bbl_off.iat[i]])
        mags = np.array([bbm_mag.iat[i], ema_mag.iat[i], bbu_mag.iat[i], bbl_mag.iat[i]])

        votes = np.zeros(4, dtype=int)
        for k, val in enumerate(offs):
            if abs(val) < angle_mag_thresh:
                votes[k] = 0
            else:
                votes[k] = -1 if val < 0 else 1

        up_votes = int((votes == -1).sum())
        down_votes = int((votes == 1).sum())

        # weighted confirmation: EMA and BBM count double
        weight_up = 0
        weight_down = 0
        comp_names = ['BBM', 'EMA', 'BBU', 'BBL']
        for idx, v in enumerate(votes):
            w = 2 if comp_names[idx] in ('BBM', 'EMA') else 1
            if v == -1:
                weight_up += w
            elif v == 1:
                weight_down += w

        # EMA/BBM slope confirmation
        ema_conf_up = (ema_slope.iat[i] > slope_thresh)
        ema_conf_down = (ema_slope.iat[i] < -slope_thresh)
        bbm_conf_up = (bbm_slope.iat[i] > slope_thresh)
        bbm_conf_down = (bbm_slope.iat[i] < -slope_thresh)

        simple_majority_up = (up_votes >= 2)
        simple_majority_down = (down_votes >= 2)
        weighted_majority_up = (weight_up >= 3)
        weighted_majority_down = (weight_down >= 3)

        tight = (bb_width_mean.iat[i] < bb_width_thresh)

        # decision hierarchy
        if tight and (mags.max() < angle_mag_thresh):
            res[i] = 'pure_sideways'
            continue

        if tight:
            if ema_conf_up and bbm_conf_up:
                res[i] = 'sideways_up'
                continue
            if ema_conf_down and bbm_conf_down:
                res[i] = 'sideways_down'
                continue
            if (weight_up == 0 and weight_down == 0):
                res[i] = 'pure_sideways'
                continue

        if (simple_majority_up or weighted_majority_up) and (ema_conf_up or bbm_conf_up):
            res[i] = 'pure_up'
            continue
        if (simple_majority_down or weighted_majority_down) and (ema_conf_down or bbm_conf_down):
            res[i] = 'pure_down'
            continue

        if (simple_majority_up or weighted_majority_up):
            res[i] = 'up_trend_mixed'
            continue
        if (simple_majority_down or weighted_majority_down):
            res[i] = 'down_trend_mixed'
            continue

        res[i] = 'trend_mixed'

    out['trend_regime_angles'] = res
    return out
