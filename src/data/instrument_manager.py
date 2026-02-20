# src/data/instrument_manager.py
# FIXED VERSION - Expiry as string, better UI responsiveness

import requests
import gzip
import json
import pandas as pd
import logging
from io import BytesIO
from datetime import datetime, timedelta
from typing import List, Optional
import re
import os
import pickle

logger = logging.getLogger(__name__)


class InstrumentManager:
    """Instrument manager with exchange-aware caching and filters."""

    EXCHANGE_URLS = {
        "NSE": "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz",
        "MCX": "https://assets.upstox.com/market-quote/instruments/exchange/MCX.json.gz",
    }
    CACHE_FILE_TEMPLATE = "instruments_cache_{exchange}.pkl"
    CACHE_DURATION_DAYS = 30
    REQUIRED_COLUMNS = ['name', 'instrument_type', 'expiry', 'instrument_key', 'strike_price', 'lot_size', 'tick_size']
    
    def __init__(self):
        self.df = None
        self.fno_df = None
        self.nifty_df = None
        self.focus_df = None
        self.last_fetched = None
        self.cache_timestamp = None
        self.exchange = "NSE"

    def _normalize_exchange(self, exchange: Optional[str]) -> str:
        if not exchange:
            return "NSE"
        ex = str(exchange).strip().upper()
        return ex if ex in self.EXCHANGE_URLS else "NSE"

    def _get_cache_file(self, exchange: Optional[str] = None) -> str:
        ex = self._normalize_exchange(exchange or self.exchange)
        return self.CACHE_FILE_TEMPLATE.format(exchange=ex)
    
    def _is_cache_valid(self) -> bool:
        """Check if cache file exists and is fresh (<30 days)"""
        cache_file = self._get_cache_file()
        if not os.path.exists(cache_file):
            return False
        
        try:
            file_age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(cache_file))
            is_valid = file_age < timedelta(days=self.CACHE_DURATION_DAYS)
            
            if is_valid:
                logger.info("Cache is fresh (%s days old, valid for %s days)", file_age.days, self.CACHE_DURATION_DAYS)
            else:
                logger.warning("Cache expired (%s days old, max %s)", file_age.days, self.CACHE_DURATION_DAYS)
            
            return is_valid
        except Exception as e:
            logger.exception("Error checking cache: %s", e)
            return False
    
    def _load_from_cache(self) -> bool:
        """Load cached data"""
        cache_file = self._get_cache_file()
        try:
            logger.info("Loading from cache...")
            with open(cache_file, 'rb') as f:
                cached_data = pickle.load(f)
            
            self.df = cached_data.get('df')
            self.fno_df = cached_data.get('fno_df')
            self.nifty_df = cached_data.get('nifty_df')
            self.focus_df = cached_data.get('focus_df')
            self.cache_timestamp = cached_data.get('timestamp')
            self.exchange = cached_data.get('exchange', self.exchange)

            # Re-apply current filters to cached data to avoid stale FUT/GOLD/SILVER
            if self.df is not None and not self.df.empty and 'instrument_type' in self.df.columns:
                self.fno_df = self.df[self.df['instrument_type'].astype(str).str.strip().isin(['CE', 'PE'])].copy()

            if self.exchange == "MCX" and self.fno_df is not None and not self.fno_df.empty:
                mcx_symbols = {"CRUDEOIL", "NATURALGAS"}
                name_upper = self.fno_df['name'].astype(str).str.upper().str.strip()
                self.focus_df = self.fno_df[name_upper.isin(mcx_symbols)].copy()
            elif self.fno_df is not None and not self.fno_df.empty:
                # NSE focus symbol (NIFTY only)
                self.focus_df = self.fno_df[
                    self.fno_df['name'].astype(str).str.upper().str.strip() == "NIFTY"
                ].copy()
            else:
                self.focus_df = self.fno_df

            self.nifty_df = self.focus_df

            logger.info("Loaded from cache (cached at: %s)", self.cache_timestamp)
            logger.info("Total FnO: %s", len(self.fno_df) if self.fno_df is not None else 0)
            logger.info("Popular symbols: %s", len(self.nifty_df) if self.nifty_df is not None else 0)
            
            return True
        except Exception as e:
            logger.exception("Error loading cache: %s", e)
            return False
    
    def _save_to_cache(self):
        """Save data to cache"""
        try:
            cache_data = {
                'df': self.df,
                'fno_df': self.fno_df,
                'nifty_df': self.nifty_df,
                'focus_df': self.focus_df,
                'timestamp': datetime.now()
            }
            cache_data['exchange'] = self.exchange

            cache_file = self._get_cache_file()
            with open(cache_file, 'wb') as f:
                pickle.dump(cache_data, f)

            logger.info("Saved to cache: %s", cache_file)
        except Exception as e:
            logger.exception("Error saving cache: %s", e)
    
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
            logger.warning("Error converting expiry: %s", e)
            return str(expiry_val)

    def load_from_excel(self, file_path: str) -> bool:
        """Load instruments from a local Excel file (e.g., NSE_Output.xlsx).
        This will be used automatically when the file exists in the repo root.
        """
        if not os.path.exists(file_path):
            return False
        try:
            logger.info("Loading instruments from local file: %s", file_path)
            if str(file_path).lower().endswith(('.xlsx', '.xls')):
                df_full = pd.read_excel(file_path, engine='openpyxl')
            else:
                df_full = pd.read_csv(file_path)

            if df_full is None or df_full.empty:
                logger.error("Local file empty")
                return False

            self.df = df_full.copy()

            # Normalize expiry if present
            if 'expiry' in self.df.columns:
                self.df['expiry'] = self.df['expiry'].apply(self._convert_expiry_to_date)

            # Ensure option rows and required columns (CE/PE only)
            if 'instrument_type' in self.df.columns:
                self.fno_df = self.df[self.df['instrument_type'].astype(str).str.strip().isin(['CE', 'PE'])].copy()
            else:
                self.fno_df = self.df.copy()

            # For backward compatibility, keep nifty_df as same view
            self.nifty_df = self.fno_df
            self.focus_df = self.fno_df

            self.source = 'local'
            logger.info("Local instruments loaded: %s rows", len(self.fno_df))
            self._save_to_cache()
            return True
        except Exception as e:
            logger.exception("Error loading local file: %s", e)
            import traceback
            traceback.print_exc()
            return False

    def fetch_instruments(self, exchange: str = "NSE", force_refresh: bool = False, prefer_local: bool = False) -> bool:
        """Fetch instruments with filtering and caching (can prefer local file)

        prefer_local: when True (NSE only) will try to load `NSE_Output.xlsx` from the repo root
                      and will prefer it over the cached API results.
        """

        exchange = self._normalize_exchange(exchange)
        self.exchange = exchange
        local_file = "NSE_Output.xlsx"

        # If user explicitly prefers local file, try it first (override cache)
        if exchange == "NSE" and prefer_local and os.path.exists(local_file):
            loaded = self.load_from_excel(local_file)
            if loaded:
                logger.info("Instruments loaded from local file (preferred)")
                return True
            else:
                logger.warning("Preferred local file present but failed to load — falling back to cache/API")

        # Do not auto-use local file unless explicitly requested

        # Try cache first (unless forced to refresh)
        if not force_refresh and self._is_cache_valid():
            if self._load_from_cache():
                return True
        
        try:
            logger.info("Fetching instruments from Upstox...")
            url = self.EXCHANGE_URLS.get(exchange, self.EXCHANGE_URLS["NSE"])
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            
            logger.info("Decompressing...")
            with gzip.GzipFile(fileobj=BytesIO(response.content)) as gz:
                raw_data = json.loads(gz.read().decode('utf-8'))
            
            # Extract data
            if isinstance(raw_data, list):
                instruments = raw_data
            elif isinstance(raw_data, dict) and 'data' in raw_data:
                instruments = raw_data['data']
            else:
                logger.error("Unexpected data structure")
                return False
            
            logger.info("Downloaded %s instruments", len(instruments))
            
            # Convert to DataFrame
            logger.info("Loading data...")
            df_full = pd.DataFrame(instruments)
            
            logger.info("Full columns: %s", len(df_full.columns))
            
            # Filter 1: Keep only required columns
            logger.info("Keeping only required columns...")
            available_cols = [col for col in self.REQUIRED_COLUMNS if col in df_full.columns]
            
            if len(available_cols) < 3:
                logger.error("Missing critical columns")
                logger.error("Available: %s", list(df_full.columns))
                return False
            
            self.df = df_full[available_cols].copy()
            
            # FIX: Convert expiry to readable date format
            logger.info("Converting expiry dates to readable format...")
            if 'expiry' in self.df.columns:
                self.df['expiry'] = self.df['expiry'].apply(self._convert_expiry_to_date)
                logger.info("Sample expiries: %s", self.df['expiry'].unique()[:5])
            
            # Filter 2: Keep only options (CE, PE)
            logger.info("Options instruments (CE, PE)...")
            self.fno_df = self.df[
                (self.df['instrument_type'].astype(str).str.strip().isin(['CE', 'PE']))
            ].copy()
            
            logger.info("FnO count: %s", len(self.fno_df))
            
            # Filter 3: Exchange-specific focus symbols
            if exchange == "MCX":
                logger.info("MCX focus symbols (CRUDEOIL, NATURALGAS)...")
                mcx_symbols = {"CRUDEOIL", "NATURALGAS"}
                name_upper = self.fno_df['name'].astype(str).str.upper().str.strip()
                self.focus_df = self.fno_df[name_upper.isin(mcx_symbols)].copy()
            else:
                logger.info("NSE focus symbols (NIFTY)...")
                self.focus_df = self.fno_df[
                    self.fno_df['name'].astype(str).str.upper().str.strip() == "NIFTY"
                ].copy()

            # Do not fallback to all symbols for NSE; keep NIFTY-only focus

            self.nifty_df = self.focus_df

            logger.info("Focus symbols count: %s", len(self.focus_df))
            
            # Show statistics
            logger.info("Summary:")
            logger.info("Total downloaded: %s", len(df_full))
            logger.info("After FnO filter: %s", len(self.fno_df))
            logger.info("After symbol filter: %s", len(self.focus_df))
            logger.info("Memory used: ~%.1f MB", self.focus_df.memory_usage(deep=True).sum() / (1024*1024))
            
            # Show sample
            if len(self.focus_df) > 0:
                logger.info("Sample instruments:\n%s", self.focus_df.head(3)[['name', 'instrument_type', 'expiry', 'strike_price']].to_string())
            
            # Mark source and save to cache
            self.source = 'api'
            self._save_to_cache()

            self.last_fetched = datetime.now()
            return True
        
        except Exception as e:
            logger.exception("Error: %s", e)
            import traceback
            traceback.print_exc()
            return False
    
    def get_unique_symbols(self) -> List[str]:
        """Get unique symbols (prefer FnO dataset if present)"""
        df = None
        if self.focus_df is not None and not self.focus_df.empty:
            df = self.focus_df
        elif self.fno_df is not None and not self.fno_df.empty:
            df = self.fno_df

        if df is None or df.empty:
            logger.error("No data loaded")
            return []

        try:
            symbols = sorted(df['name'].dropna().unique().tolist())
            logger.info("Found %s unique symbols: %s...", len(symbols), symbols[:10])
            return symbols
        except Exception as e:
            logger.exception("Error in get_unique_symbols: %s", e)
            return []
    
    def get_expiry_dates(self, symbol: Optional[str] = None, instrument_type: Optional[str] = None) -> List[str]:
        """Get unique expiry dates (uses options dataset when available)"""
        df = None
        if self.focus_df is not None and not self.focus_df.empty:
            df = self.focus_df
        elif self.fno_df is not None and not self.fno_df.empty:
            df = self.fno_df

        if df is None or df.empty:
            logger.warning("No data loaded")
            return []

        try:
            df_filtered = df
            if symbol:
                df_filtered = df_filtered[
                    df_filtered['name'].astype(str).str.upper() == symbol.upper()
                ]

            if instrument_type:
                df_filtered = df_filtered[
                    df_filtered['instrument_type'].astype(str).str.strip() == instrument_type
                ]

            if df_filtered.empty:
                logger.warning("No instruments for symbol: %s", symbol)
                return []

            expiries_raw = df_filtered['expiry'].dropna().unique().tolist()
            # Normalize expiries to YYYY-MM-DD
            expiries = sorted(list({self._convert_expiry_to_date(x) for x in expiries_raw if x is not None and str(x).strip() != ''}))
            logger.info("Found %s expiry dates for %s: %s...", len(expiries), symbol or 'all symbols', expiries[:5])
            return expiries

        except Exception as e:
            logger.exception("Error in get_expiry_dates: %s", e)
            import traceback
            traceback.print_exc()
            return []

    def get_strikes(self, symbol: str, expiry: str, instrument_type: Optional[str] = None) -> List[int]:
        """Get unique strikes for options (CE/PE)"""
        df = None
        if self.focus_df is not None and not self.focus_df.empty:
            df = self.focus_df
        elif self.fno_df is not None and not self.fno_df.empty:
            df = self.fno_df

        if df is None or df.empty or not symbol or not expiry:
            logger.warning("Missing parameters: symbol=%s, expiry=%s", symbol, expiry)
            return []

        try:
            # Filter by symbol first
            df_filtered = df[(df['name'].astype(str).str.upper() == symbol.upper())]

            # Normalize expiry parameter and filter by normalized expiry string
            if expiry is not None and str(expiry).strip() != "":
                expiry_s = self._convert_expiry_to_date(expiry)
                df_filtered = df_filtered[df_filtered['expiry'].apply(lambda x: self._convert_expiry_to_date(x)) == expiry_s]

            logger.debug("Filtered to %s rows for %s %s", len(df_filtered), symbol, expiry)

            # Filter by type if specified
            if instrument_type:
                df_filtered = df_filtered[
                    df_filtered['instrument_type'].astype(str).str.strip() == instrument_type
                ]
                logger.debug("After type filter (%s): %s rows", instrument_type, len(df_filtered))

            if df_filtered.empty:
                logger.warning("No strikes found for %s %s %s", symbol, expiry, instrument_type)
                return []

            strikes = sorted(
                [int(float(s)) for s in df_filtered['strike_price'].dropna().unique() if s is not None and s != '']
            )

            logger.info("Found %s strikes: %s...", len(strikes), strikes[:10])
            return strikes

        except Exception as e:
            logger.exception("Error in get_strikes: %s", e)
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
        if self.focus_df is not None and not self.focus_df.empty:
            df = self.focus_df
        elif self.fno_df is not None and not self.fno_df.empty:
            df = self.fno_df
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

    def format_expired_instrument_code(self, base_instrument_key: str, expiry_iso: str) -> Optional[str]:
        """Return an expired-instrument code like 'NSE_FO|57021|23-12-2025' given a base key and expiry in YYYY-MM-DD or DD-MM-YYYY.
        Returns None when base_instrument_key is falsy.
        """
        if not base_instrument_key:
            return None
        try:
            from datetime import datetime as _dt
            # Try parse ISO YYYY-MM-DD first
            try:
                dt = _dt.strptime(str(expiry_iso), "%Y-%m-%d")
                expiry_str = dt.strftime("%d-%m-%Y")
            except Exception:
                # Try DD-MM-YYYY
                try:
                    dt = _dt.strptime(str(expiry_iso), "%d-%m-%Y")
                    expiry_str = dt.strftime("%d-%m-%Y")
                except Exception:
                    expiry_str = str(expiry_iso)
            return f"{base_instrument_key}|{expiry_str}"
        except Exception as e:
            print(f"[WARN] format_expired_instrument_code error: {e}")
            return f"{base_instrument_key}|{expiry_iso}"

    def get_expired_instrument_code_from_selection(
        self,
        symbol: str = None,
        expiry: str = None,
        strike: Optional[int] = None,
        instrument_type: str = 'CE'
    ) -> Optional[str]:
        """Convenience method: find base instrument key for selection and return formatted expired code.
        Returns None if no matching base instrument key was found.
        """
        try:
            base_key = self.get_instrument_key(symbol, expiry, strike, instrument_type)
            if not base_key:
                return None
            return self.format_expired_instrument_code(base_key, expiry)
        except Exception as e:
            print(f"[ERROR] get_expired_instrument_code_from_selection error: {e}")
            return None

    def clear_cache(self):
        """Clear cache"""
        try:
            cache_file = self._get_cache_file()
            if os.path.exists(cache_file):
                os.remove(cache_file)
                print(f"[OK] Cache cleared")
            else:
                print("[INFO] No cache to clear")
        except Exception as e:
            print(f"[ERROR] Error: {e}")

    def get_lot_size(self, instrument_key: str) -> int:
        """Return lot size for an instrument key; defaults to 1 when unavailable."""
        df = None
        if self.focus_df is not None and not self.focus_df.empty:
            df = self.focus_df
        elif self.fno_df is not None and not self.fno_df.empty:
            df = self.fno_df
        elif self.df is not None and not self.df.empty:
            df = self.df

        if df is None or df.empty:
            return 1

        if 'lot_size' not in df.columns:
            return 1

        try:
            row = df[df['instrument_key'] == instrument_key].head(1)
            if row.empty:
                return 1
            lot_size = row['lot_size'].iloc[0]
            if lot_size is None or pd.isna(lot_size):
                return 1
            lot_size_int = int(float(lot_size))
            return lot_size_int if lot_size_int > 0 else 1
        except Exception:
            return 1

    def get_tick_size(self, instrument_key: str, default: float = 0.05) -> float:
        """Return tick size for an instrument key; defaults when unavailable."""
        df = None
        if self.focus_df is not None and not self.focus_df.empty:
            df = self.focus_df
        elif self.fno_df is not None and not self.fno_df.empty:
            df = self.fno_df
        elif self.df is not None and not self.df.empty:
            df = self.df

        if df is None or df.empty or 'tick_size' not in df.columns:
            return float(default)

        try:
            row = df[df['instrument_key'] == instrument_key].head(1)
            if row.empty:
                return float(default)
            tick = row['tick_size'].iloc[0]
            if tick is None or pd.isna(tick):
                return float(default)
            tick_f = float(tick)
            return tick_f if tick_f > 0 else float(default)
        except Exception:
            return float(default)
    
    def get_cache_info(self) -> dict:
        """Get cache info"""
        cache_file = self._get_cache_file()
        if not os.path.exists(cache_file):
            return {'cached': False}
        
        try:
            file_age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(cache_file))
            file_size = os.path.getsize(cache_file) / (1024 * 1024)
            
            return {
                'cached': True,
                'age_days': file_age.days,
                'size_mb': round(file_size, 2),
                'valid': file_age < timedelta(days=self.CACHE_DURATION_DAYS),
                'expires_in_days': self.CACHE_DURATION_DAYS - file_age.days
            }
        except Exception as e:
            return {'cached': True, 'error': str(e)}
