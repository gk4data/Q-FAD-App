# src/data/instrument_manager.py
# FIXED VERSION - Expiry as string, better UI responsiveness

import requests
import gzip
import json
import pandas as pd
from io import BytesIO
from datetime import datetime, timedelta
from typing import List, Optional
import re
import os
import pickle


class InstrumentManager:
    """Ultra-fast instrument manager - NIFTY focused with 1-month cache"""
    
    NSE_INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
    CACHE_FILE = "instruments_cache.pkl"
    CACHE_DURATION_DAYS = 30
    REQUIRED_COLUMNS = ['name', 'instrument_type', 'expiry', 'instrument_key', 'strike_price']
    
    def __init__(self):
        self.df = None
        self.fno_df = None
        self.nifty_df = None
        self.last_fetched = None
        self.cache_timestamp = None
    
    def _is_cache_valid(self) -> bool:
        """Check if cache file exists and is fresh (<30 days)"""
        if not os.path.exists(self.CACHE_FILE):
            return False
        
        try:
            file_age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(self.CACHE_FILE))
            is_valid = file_age < timedelta(days=self.CACHE_DURATION_DAYS)
            
            if is_valid:
                print(f"[OK] Cache is fresh ({file_age.days} days old, valid for {self.CACHE_DURATION_DAYS} days)")
            else:
                print(f"[WARN] Cache expired ({file_age.days} days old, max {self.CACHE_DURATION_DAYS})")
            
            return is_valid
        except Exception as e:
            print(f"[ERROR] Error checking cache: {e}")
            return False
    
    def _load_from_cache(self) -> bool:
        """Load cached data"""
        try:
            print("[LOAD] Loading from cache...")
            with open(self.CACHE_FILE, 'rb') as f:
                cached_data = pickle.load(f)
            
            self.df = cached_data.get('df')
            self.fno_df = cached_data.get('fno_df')
            self.nifty_df = cached_data.get('nifty_df')
            self.cache_timestamp = cached_data.get('timestamp')
            
            print(f"[OK] Loaded from cache (cached at: {self.cache_timestamp})")
            print(f"   Total FnO: {len(self.fno_df) if self.fno_df is not None else 0}")
            print(f"   Popular symbols: {len(self.nifty_df) if self.nifty_df is not None else 0}")
            
            return True
        except Exception as e:
            print(f"[ERROR] Error loading cache: {e}")
            return False
    
    def _save_to_cache(self):
        """Save data to cache"""
        try:
            cache_data = {
                'df': self.df,
                'fno_df': self.fno_df,
                'nifty_df': self.nifty_df,
                'timestamp': datetime.now()
            }
            
            with open(self.CACHE_FILE, 'wb') as f:
                pickle.dump(cache_data, f)
            
            print(f"[OK] Saved to cache: {self.CACHE_FILE}")
        except Exception as e:
            print(f"[ERROR] Error saving cache: {e}")
    
    def _convert_expiry_to_date(self, expiry_val) -> str:
        """Convert expiry to readable date format YYYY-MM-DD"""
        try:
            # Handle None/NaN
            if expiry_val is None:
                return ""

            # If it's already a datetime-like object
            try:
                import pandas as _pd
                if isinstance(expiry_val, (datetime, _pd.Timestamp)):
                    return pd.to_datetime(expiry_val).strftime('%Y-%m-%d')
            except Exception:
                pass

            # Numeric timestamps (seconds or milliseconds)
            if isinstance(expiry_val, (int, float)) and not pd.isna(expiry_val):
                if expiry_val > 1e11:  # looks like milliseconds
                    timestamp = expiry_val / 1000
                else:
                    timestamp = expiry_val
                date_obj = datetime.fromtimestamp(timestamp)
                return date_obj.strftime('%Y-%m-%d')

            # Use pandas flexible parsing
            try:
                dt = pd.to_datetime(expiry_val, errors='coerce')
                if not pd.isna(dt):
                    return dt.strftime('%Y-%m-%d')
            except Exception:
                pass

            # Fallback explicit formats
            expiry_str = str(expiry_val).strip()
            for fmt in ['%Y-%m-%d', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%d-%m-%Y', '%d%m%Y', '%Y%m%d']:
                try:
                    date_obj = datetime.strptime(expiry_str, fmt)
                    return date_obj.strftime('%Y-%m-%d')
                except Exception:
                    continue

            # If all else fails, return original string
            return expiry_str
        except Exception as e:
            print(f"[WARN] Error converting expiry: {e}")
            return str(expiry_val)

    def load_from_excel(self, file_path: str) -> bool:
        """Load instruments from a local Excel file (e.g., NSE_Output.xlsx).
        This will be used automatically when the file exists in the repo root.
        """
        if not os.path.exists(file_path):
            return False
        try:
            print(f"[LOAD] Loading instruments from local file: {file_path}")
            if str(file_path).lower().endswith(('.xlsx', '.xls')):
                df_full = pd.read_excel(file_path, engine='openpyxl')
            else:
                df_full = pd.read_csv(file_path)

            if df_full is None or df_full.empty:
                print("[ERROR] Local file empty")
                return False

            self.df = df_full.copy()

            # Normalize expiry if present
            if 'expiry' in self.df.columns:
                self.df['expiry'] = self.df['expiry'].apply(self._convert_expiry_to_date)

            # Ensure FnO rows and required columns
            if 'instrument_type' in self.df.columns:
                self.fno_df = self.df[self.df['instrument_type'].astype(str).str.strip().isin(['CE', 'PE', 'FUT'])].copy()
            else:
                self.fno_df = self.df.copy()

            # For backward compatibility, keep nifty_df as same view
            self.nifty_df = self.fno_df

            self.source = 'local'
            print(f"[OK] Local instruments loaded: {len(self.fno_df)} rows")
            self._save_to_cache()
            return True
        except Exception as e:
            print(f"[ERROR] Error loading local file: {e}")
            import traceback
            traceback.print_exc()
            return False

    def fetch_instruments(self, force_refresh: bool = False, prefer_local: bool = False) -> bool:
        """Fetch instruments with filtering and caching (can prefer local file)

        prefer_local: when True will try to load `NSE_Output.xlsx` from the repo root
                      and will prefer it over the cached API results.
        """

        local_file = "NSE_Output.xlsx"

        # If user explicitly prefers local file, try it first (override cache)
        if prefer_local and os.path.exists(local_file):
            loaded = self.load_from_excel(local_file)
            if loaded:
                print("[OK] Instruments loaded from local file (preferred)")
                return True
            else:
                print("[WARN] Preferred local file present but failed to load — falling back to cache/API")

        # If local file exists and preference not explicit, keep previous behavior: prefer local unless force_refresh
        if os.path.exists(local_file) and not force_refresh and not prefer_local:
            loaded = self.load_from_excel(local_file)
            if loaded:
                print("[INFO] Instruments loaded from local file")
                return True

        # Try cache first (unless forced to refresh)
        if not force_refresh and self._is_cache_valid():
            if self._load_from_cache():
                return True
        if not force_refresh and self._is_cache_valid():
            if self._load_from_cache():
                return True
        
        try:
            print("[LOAD] Fetching instruments from Upstox...")
            response = requests.get(self.NSE_INSTRUMENTS_URL, timeout=60)
            response.raise_for_status()
            
            print("[DECOMPRESS] Decompressing...")
            with gzip.GzipFile(fileobj=BytesIO(response.content)) as gz:
                raw_data = json.loads(gz.read().decode('utf-8'))
            
            # Extract data
            if isinstance(raw_data, list):
                instruments = raw_data
            elif isinstance(raw_data, dict) and 'data' in raw_data:
                instruments = raw_data['data']
            else:
                print("[ERROR] Unexpected data structure")
                return False
            
            print(f"[OK] Downloaded {len(instruments)} instruments")
            
            # Convert to DataFrame
            print("[LOAD] Loading data...")
            df_full = pd.DataFrame(instruments)
            
            print(f"   Full columns: {len(df_full.columns)}")
            
            # Filter 1: Keep only required columns
            print("[FILTER] Keeping only required columns...")
            available_cols = [col for col in self.REQUIRED_COLUMNS if col in df_full.columns]
            
            if len(available_cols) < 3:
                print(f"[ERROR] Missing critical columns")
                print(f"   Available: {list(df_full.columns)}")
                return False
            
            self.df = df_full[available_cols].copy()
            
            # FIX: Convert expiry to readable date format
            print("[INFO] Converting expiry dates to readable format...")
            if 'expiry' in self.df.columns:
                self.df['expiry'] = self.df['expiry'].apply(self._convert_expiry_to_date)
                print(f"   Sample expiries: {self.df['expiry'].unique()[:5]}")
            
            # Filter 2: Keep only FnO (CE, PE, FUT)
            print("[FILTER] FnO instruments (CE, PE, FUT)...")
            self.fno_df = self.df[
                (self.df['instrument_type'].astype(str).str.strip().isin(['CE', 'PE', 'FUT']))
            ].copy()
            
            print(f"   [OK] FnO count: {len(self.fno_df)}")
            
            # Filter 3: Keep NIFTY, BANKNIFTY, FINNIFTY, etc.
            print("[FILTER] Popular symbols...")
            popular_symbols = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50']
            
            self.nifty_df = self.fno_df[
                self.fno_df['name'].astype(str).str.upper().str.contains(
                    '|'.join(popular_symbols), na=False, regex=True
                )
            ].copy()
            
            print(f"   [OK] Popular symbols count: {len(self.nifty_df)}")
            
            # Show statistics
            print("\n[STATS] Summary:")
            print(f"   Total downloaded: {len(df_full)}")
            print(f"   After FnO filter: {len(self.fno_df)}")
            print(f"   After symbol filter: {len(self.nifty_df)}")
            print(f"   Memory used: ~{self.nifty_df.memory_usage(deep=True).sum() / (1024*1024):.1f} MB")
            
            # Show sample
            if len(self.nifty_df) > 0:
                print("\n[SAMPLE] Sample instruments:")
                print(self.nifty_df.head(3)[['name', 'instrument_type', 'expiry', 'strike_price']].to_string())
            
            # Mark source and save to cache
            self.source = 'api'
            self._save_to_cache()

            self.last_fetched = datetime.now()
            return True
        
        except Exception as e:
            print(f"[ERROR] Error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def get_unique_symbols(self) -> List[str]:
        """Get unique symbols (prefer FnO dataset if present)"""
        df = None
        if self.fno_df is not None and not self.fno_df.empty:
            df = self.fno_df
        elif self.nifty_df is not None and not self.nifty_df.empty:
            df = self.nifty_df

        if df is None or df.empty:
            print("[ERROR] No data loaded")
            return []

        try:
            symbols = sorted(df['name'].dropna().unique().tolist())
            print(f"[OK] Found {len(symbols)} unique symbols: {symbols[:10]}...")
            return symbols
        except Exception as e:
            print(f"[ERROR] Error in get_unique_symbols: {e}")
            return []
    
    def get_expiry_dates(self, symbol: Optional[str] = None) -> List[str]:
        """Get unique expiry dates (uses FnO dataset when available)"""
        df = None
        if self.fno_df is not None and not self.fno_df.empty:
            df = self.fno_df
        elif self.nifty_df is not None and not self.nifty_df.empty:
            df = self.nifty_df

        if df is None or df.empty:
            print("[WARN] No data loaded")
            return []

        try:
            df_filtered = df
            if symbol:
                df_filtered = df_filtered[
                    df_filtered['name'].astype(str).str.upper() == symbol.upper()
                ]

            if df_filtered.empty:
                print(f"[WARN] No instruments for symbol: {symbol}")
                return []

            expiries_raw = df_filtered['expiry'].dropna().unique().tolist()
            # Normalize expiries to YYYY-MM-DD
            expiries = sorted(list({self._convert_expiry_to_date(x) for x in expiries_raw if x is not None and str(x).strip() != ''}))
            print(f"[OK] Found {len(expiries)} expiry dates for {symbol or 'all symbols'}: {expiries[:5]}...")
            return expiries

        except Exception as e:
            print(f"[ERROR] Error in get_expiry_dates: {e}")
            import traceback
            traceback.print_exc()
            return []

    def get_strikes(self, symbol: str, expiry: str, instrument_type: Optional[str] = None) -> List[int]:
        """Get unique strikes; returns empty list for FUT (no strike)"""
        df = None
        if self.fno_df is not None and not self.fno_df.empty:
            df = self.fno_df
        elif self.nifty_df is not None and not self.nifty_df.empty:
            df = self.nifty_df

        if df is None or df.empty or not symbol or not expiry:
            print(f"[WARN] Missing parameters: symbol={symbol}, expiry={expiry}")
            return []

        try:
            # Filter by symbol first
            df_filtered = df[(df['name'].astype(str).str.upper() == symbol.upper())]

            # Normalize expiry parameter and filter by normalized expiry string
            if expiry is not None and str(expiry).strip() != "":
                expiry_s = self._convert_expiry_to_date(expiry)
                df_filtered = df_filtered[df_filtered['expiry'].apply(lambda x: self._convert_expiry_to_date(x)) == expiry_s]

            print(f"[DEBUG] Filtered to {len(df_filtered)} rows for {symbol} {expiry}")

            # Filter by type if specified
            if instrument_type:
                df_filtered = df_filtered[
                    df_filtered['instrument_type'].astype(str).str.strip() == instrument_type
                ]
                print(f"   After type filter ({instrument_type}): {len(df_filtered)} rows")

            if df_filtered.empty:
                print(f"[WARN] No strikes found for {symbol} {expiry} {instrument_type}")
                return []

            # FUT instruments typically have no strike prices
            if instrument_type and instrument_type.upper() == 'FUT':
                return []

            strikes = sorted(
                [int(float(s)) for s in df_filtered['strike_price'].dropna().unique() if s is not None and s != '']
            )

            print(f"[OK] Found {len(strikes)} strikes: {strikes[:10]}...")
            return strikes

        except Exception as e:
            print(f"[ERROR] Error in get_strikes: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def get_instrument_key(
        self, 
        symbol: str, 
        expiry: str, 
        strike: Optional[int] = None, 
        instrument_type: str = 'CE'
    ) -> Optional[str]:
        """Get instrument key (tolerant matching)"""
        df = None
        if self.fno_df is not None and not self.fno_df.empty:
            df = self.fno_df
        elif self.nifty_df is not None and not self.nifty_df.empty:
            df = self.nifty_df
        else:
            return None

        try:
            # Normalize inputs
            sym_u = symbol.upper()
            expiry_s = str(self._convert_expiry_to_date(expiry)) if expiry is not None else None
            itype = str(instrument_type).strip()

            df_filtered = df[
                (df['name'].astype(str).str.upper() == sym_u) &
                (df['instrument_type'].astype(str).str.strip() == itype)
            ]

            # Match expiry (try direct match, else try normalized expiry)
            if expiry_s is not None:
                df_filtered = df_filtered[df_filtered['expiry'].astype(str) == expiry_s]

            print(f"[DEBUG] Found {len(df_filtered)} matches for {symbol} {expiry} {instrument_type}")

            if strike is not None:
                df_filtered = df_filtered[df_filtered['strike_price'].astype(float) == float(strike)]
                print(f"   After strike filter: {len(df_filtered)} rows")

            if df_filtered.empty:
                print(f"[WARN] No match for {symbol} {expiry} {strike} {instrument_type}")
                return None

            key = str(df_filtered['instrument_key'].iloc[0])
            print(f"[OK] Found: {key}")
            return key

        except Exception as e:
            print(f"[ERROR] Error in get_instrument_key: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def clear_cache(self):
        """Clear cache"""
        try:
            if os.path.exists(self.CACHE_FILE):
                os.remove(self.CACHE_FILE)
                print(f"[OK] Cache cleared")
            else:
                print("[INFO] No cache to clear")
        except Exception as e:
            print(f"[ERROR] Error: {e}")
    
    def get_cache_info(self) -> dict:
        """Get cache info"""
        if not os.path.exists(self.CACHE_FILE):
            return {'cached': False}
        
        try:
            file_age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(self.CACHE_FILE))
            file_size = os.path.getsize(self.CACHE_FILE) / (1024 * 1024)
            
            return {
                'cached': True,
                'age_days': file_age.days,
                'size_mb': round(file_size, 2),
                'valid': file_age < timedelta(days=self.CACHE_DURATION_DAYS),
                'expires_in_days': self.CACHE_DURATION_DAYS - file_age.days
            }
        except Exception as e:
            return {'cached': True, 'error': str(e)}