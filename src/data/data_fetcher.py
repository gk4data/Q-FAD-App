import requests
import pandas as pd
from datetime import datetime

BASE = "https://api.upstox.com/v2"

def _normalize_date(date_str: str) -> str:
    """Convert DD-MM-YYYY or YYYY-MM-DD to YYYY-MM-DD"""
    # Support common day-first and ISO formats, plus accidental YYYY-DD-MM inputs
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%Y-%d-%m"):
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
    end: str = None,
    expiry_for_expired: str = None,
) -> pd.DataFrame:
    """
    mode='intraday'   -> /historical-candle/intraday/{instrument}/{interval}
    mode='date_range' -> /historical-candle/{instrument}/{interval}/{start}/{end}
    mode='expired'    -> /expired-instruments/historical-candle/{instrument}|{DD-MM-YYYY}/{interval}/{start}/{end}

    Dates in YYYY-MM-DD or DD-MM-YYYY (will be normalized) for start/end. Expiry for expired mode must be provided
    and is formatted as DD-MM-YYYY in the URL.
    """
    if mode == "intraday":
        url = f"{BASE}/historical-candle/intraday/{instrument_code}/{interval}"
    elif mode == "date_range":
        if not start or not end:
            raise ValueError("Provide start and end dates for date_range mode")
        # Normalize dates to YYYY-MM-DD
        start = _normalize_date(start)
        end = _normalize_date(end)
        url = f"{BASE}/historical-candle/{instrument_code}/{interval}/{start}/{end}"
    elif mode == "expired":
        # expired mode requires expiry_for_expired plus start/end
        if not expiry_for_expired:
            raise ValueError("Provide expiry for expired mode (expiry_for_expired)")
        if not start or not end:
            raise ValueError("Provide start and end dates for expired mode")
        # Normalize start/end
        start = _normalize_date(start)
        end = _normalize_date(end)
        # expiry_for_expired should be formatted as DD-MM-YYYY in the URL
        # Accept expiry passed in as YYYY-MM-DD or date-like; convert
        try:
            from datetime import datetime as _dt
            # Try parsing common formats
            exp_dt = _dt.strptime(str(expiry_for_expired), "%Y-%m-%d")
            expiry_url = exp_dt.strftime("%d-%m-%Y")
        except Exception:
            # fallback: try to parse DD-MM-YYYY directly or leave as-is
            expiry_url = str(expiry_for_expired)
        url = f"{BASE}/expired-instruments/historical-candle/{instrument_code}|{expiry_url}/{interval}/{start}/{end}"
    else:
        raise ValueError(f"Unknown mode: {mode}")

    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
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
