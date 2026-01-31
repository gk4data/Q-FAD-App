import requests
import pandas as pd
from datetime import datetime

BASE = "https://api.upstox.com/v2"

def _normalize_date(date_str: str) -> str:
    """Convert DD-MM-YYYY or YYYY-MM-DD to YYYY-MM-DD"""
    for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    raise ValueError(f"Date '{date_str}' must be YYYY-MM-DD or DD-MM-YYYY")

def _to_df(candles):
    cols = ["timestamp","open","high","low","close","volume","oi"]
    df = pd.DataFrame(candles, columns=cols[:len(candles[0])])
    rename = {
        "timestamp":"Date","open":"Open","high":"High",
        "low":"Low","close":"Close","volume":"Volume","oi":"OI"
    }
    df.rename(columns=rename, inplace=True)
    df["Date"] = pd.to_datetime(df["Date"])
    if "OI" in df.columns:
        df.drop(columns=["OI"], inplace=True)
    return df.sort_values("Date").reset_index(drop=True)

def fetch_intraday_data(
    instrument_code: str,
    access_token: str,
    interval: str = "1minute",
    mode: str = "date_range",
    start: str = None,
    end: str = None
) -> pd.DataFrame:
    """
    mode='intraday'   -> /historical-candle/intraday/{instrument}/{interval}
    mode='date_range' -> /historical-candle/{instrument}/{interval}/{start}/{end}
    Dates in YYYY-MM-DD or DD-MM-YYYY (will be normalized)
    """
    if mode == "intraday":
        url = f"{BASE}/historical-candle/intraday/{instrument_code}/{interval}"
    else:
        if not start or not end:
            raise ValueError("Provide start and end dates for date_range mode")
        # Normalize dates to YYYY-MM-DD
        start = _normalize_date(start)
        end = _normalize_date(end)
        url = f"{BASE}/historical-candle/{instrument_code}/{interval}/{start}/{end}"

    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {access_token}"
    }
    
    try:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        # Print response body for debugging
        print(f"HTTP Error: {e}")
        print(f"Response: {r.text}")
        raise
    
    data = r.json().get("data", {})
    candles = data.get("candles", [])
    if not candles:
        return pd.DataFrame(columns=["Date","Open","High","Low","Close","Volume"])
    return _to_df(candles)
