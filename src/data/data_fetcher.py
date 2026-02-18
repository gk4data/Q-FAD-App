import requests
import pandas as pd
from datetime import datetime, timedelta

BASE = "https://api.upstox.com/v2"

def is_market_holiday(date_str: str) -> bool:
    """
    Check if a specific date is a market holiday using Upstox date-based API.
    date_str should be in YYYY-MM-DD format.
    Returns True if it's a holiday, False otherwise.
    """
    url = f"{BASE}/market/holidays/{date_str}"
    headers = {"Accept": "application/json"}
    
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json().get("data", {})
        # If API returns data about the date, it's likely a holiday
        if data:
            return True
        return False
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            # 404 means it's not a holiday (not found in holidays list)
            return False
        print(f"[WARN] Could not check market holiday for {date_str}: {e}")
        return False
    except Exception as e:
        print(f"[WARN] Could not fetch market holiday info for {date_str}: {e}")
        return False

def get_previous_market_day(target_date_str: str) -> str:
    """
    Get the previous market day (excluding weekends and holidays) for a given date.
    target_date_str should be in YYYY-MM-DD format.
    Uses Upstox API to check if dates are holidays.
    Returns the previous market day in YYYY-MM-DD format.
    """
    target_date = datetime.strptime(target_date_str, "%Y-%m-%d")
    prev_date = target_date - timedelta(days=1)
    
    # Go back until we find a weekday that's not a holiday
    max_iterations = 30  # Prevent infinite loop (roughly 1 month)
    iterations = 0
    
    while iterations < max_iterations:
        # Check if it's a weekend (Saturday=5, Sunday=6)
        if prev_date.weekday() < 5:  # Monday-Friday
            prev_date_str = prev_date.strftime("%Y-%m-%d")
            # Check if it's a holiday using the API
            if not is_market_holiday(prev_date_str):
                print(f"[INFO] Found previous market day: {prev_date_str}")
                return prev_date_str
            else:
                print(f"[DEBUG] {prev_date_str} is a market holiday, checking earlier...")
        else:
            print(f"[DEBUG] {prev_date.strftime('%Y-%m-%d')} is weekend, checking earlier...")
        
        prev_date -= timedelta(days=1)
        iterations += 1
    
    # Fallback: return 5 days back as a safe bet
    fallback_date = (target_date - timedelta(days=5)).strftime("%Y-%m-%d")
    print(f"[WARN] Could not determine previous market day after {max_iterations} iterations. Using {fallback_date}")
    return fallback_date

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

def concatenate_with_previous_day(
    current_df: pd.DataFrame, 
    instrument_code: str, 
    access_token: str,
    target_date_str: str,
    interval: str = "1minute",
    mode: str = "date_range",
    expiry_for_expired: str = None,
    previous_rows: int = 60
) -> pd.DataFrame:
    """
    Concatenate the last N rows from the previous market day with current day data.
    This provides historical context for indicators to calculate immediately.
    
    Args:
        current_df: Current day's dataframe
        instrument_code: Instrument key (e.g., 'NSE_FO|49795')
        access_token: API access token
        target_date_str: Target date in YYYY-MM-DD format
        interval: Candle interval (default '1minute')
        mode: 'date_range' or 'expired'
        expiry_for_expired: Expiry date if mode is 'expired'
        previous_rows: Number of previous day's rows to keep (default 60)
    
    Returns:
        Concatenated dataframe with previous + current day data
    """
    try:
        prev_market_day = get_previous_market_day(target_date_str)
        
        print(f"[INFO] Fetching {previous_rows} rows from previous market day: {prev_market_day}")
        
        # Fetch previous day's data
        if mode == "expired":
            prev_df = fetch_intraday_data(
                instrument_code, access_token, interval=interval, mode=mode,
                start=prev_market_day, end=prev_market_day, expiry_for_expired=expiry_for_expired
            )
        else:
            prev_df = fetch_intraday_data(
                instrument_code, access_token, interval=interval, mode="date_range",
                start=prev_market_day, end=prev_market_day
            )
        
        if prev_df.empty:
            print(f"[WARN] No data found for previous market day {prev_market_day}. Using current data only.")
            return current_df.copy()

        # Normalize timezones to avoid tz-aware vs tz-naive comparisons
        for _df in (current_df, prev_df):
            if "Date" in _df.columns:
                _df["Date"] = pd.to_datetime(_df["Date"], errors="coerce")
                if getattr(_df["Date"].dt, "tz", None) is not None:
                    _df["Date"] = _df["Date"].dt.tz_localize(None)
        
        # Keep only last N rows from previous day
        prev_df = prev_df.tail(previous_rows).reset_index(drop=True)
        
        # Concatenate previous day + current day
        combined_df = pd.concat([prev_df, current_df], ignore_index=True)
        combined_df = combined_df.sort_values("Date").reset_index(drop=True)
        
        print(f"[INFO] Combined {len(prev_df)} previous + {len(current_df)} current = {len(combined_df)} rows")
        
        return combined_df
    
    except Exception as e:
        print(f"[WARN] Error concatenating with previous day data: {e}. Returning current data only.")
        return current_df.copy()

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
def filter_to_current_day(df: pd.DataFrame, target_date_str: str) -> pd.DataFrame:
    """
    Filter dataframe to keep only rows from the target date.
    Removes previous day's data after indicators have been calculated.
    
    Args:
        df: DataFrame with Date column (datetime type)
        target_date_str: Target date in YYYY-MM-DD format
    
    Returns:
        Filtered dataframe with only current day data
    """
    if df.empty:
        return df.copy()
    
    try:
        target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        df = df.copy()
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        
        # Filter to target date only
        filtered_df = df[df['Date'].dt.date == target_date].reset_index(drop=True)
        
        # Keep logs quiet for live processing
        
        return filtered_df
    
    except Exception as e:
        print(f"[WARN] Error filtering to current day: {e}. Returning all data.")
        return df.copy()
