import pandas as pd
import numpy as np
from src.signals.angle_classification import classify_trend_by_angles


def make_angle_df(n=20):
    rng = pd.date_range("2025-01-01 09:30", periods=n, freq="T")
    df = pd.DataFrame({
        'Date': rng,
        'BBM_Angle_Degree': np.linspace(180, 182, n),
        'EMA_Angle_Degree': np.linspace(180, 181, n),
        'BBU_Angle_Degree': np.linspace(180, 183, n),
        'BBL_Angle_Degree': np.linspace(180, 179, n),
        'EMA9': np.linspace(100, 100.1, n),
        'BBM': np.linspace(100, 100.05, n),
        'BBU': np.linspace(101, 101.05, n),
        'BBL': np.linspace(99, 99.05, n),
    })
    return df


def test_classify_trend_by_angles_basic():
    df = make_angle_df()
    out = classify_trend_by_angles(df)
    assert 'trend_regime_angles' in out.columns
    # values must be within allowed set
    allowed = { 'pure_sideways','sideways_up','sideways_down','pure_up','pure_down','up_trend_mixed','down_trend_mixed','trend_mixed'}
    assert set(out['trend_regime_angles']).issubset(allowed)
