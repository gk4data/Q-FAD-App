import pandas as pd
from .buy_signals import generate_buy_signals
from .sell_signals import generate_sell_signals


def add_long_signal(df: pd.DataFrame, expiry_date=None) -> pd.DataFrame:
    """Add buy and sell signals to `df` in place and return it.

    This is a thin wrapper that delegates buy/sell computation to
    `generate_buy_signals` and `generate_sell_signals` for clearer separation
    of concerns.
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be a pandas DataFrame")

    df = generate_buy_signals(df, expiry_date=expiry_date)
    df = generate_sell_signals(df)
    return df
