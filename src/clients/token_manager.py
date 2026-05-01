import os
import json
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


UPSTOX_TZ = ZoneInfo("Asia/Kolkata")


class TokenManager:
    """
    Manages Upstox access token persistence and expiration.
    Caches token to disk; reuses if valid, otherwise requires re-auth.
    """

    def __init__(self, cache_dir=None):
        if cache_dir is None:
            cache_dir = Path.home() / ".upstox_cache"
        else:
            cache_dir = Path(cache_dir)
        
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.token_file = self.cache_dir / "access_token.json"

    def _compute_upstox_expiry(self, issued_at=None):
        """
        Compute Upstox token expiry as 3:30 AM Asia/Kolkata the following day.
        """
        issued_at = issued_at or datetime.now(UPSTOX_TZ)
        if issued_at.tzinfo is None:
            issued_at = issued_at.replace(tzinfo=UPSTOX_TZ)
        else:
            issued_at = issued_at.astimezone(UPSTOX_TZ)

        next_day = issued_at.date() + timedelta(days=1)
        return datetime.combine(next_day, time(hour=3, minute=30), tzinfo=UPSTOX_TZ)

    def save_token(self, access_token, expires_in_seconds=86400, expires_at=None):
        """
        Save token to disk with expiration time.
        
        Parameters
        ----------
        access_token : str
            The access token from OAuth
        expires_in_seconds : int
            Token lifetime in seconds. Retained for backward compatibility.
        expires_at : datetime | str | None
            Explicit token expiry. If omitted, Upstox's documented rule is used:
            3:30 AM Asia/Kolkata on the following day.
        """
        issued_at = datetime.now(UPSTOX_TZ)
        if expires_at:
            if isinstance(expires_at, str):
                expiry = datetime.fromisoformat(expires_at)
            else:
                expiry = expires_at
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=UPSTOX_TZ)
            else:
                expiry = expiry.astimezone(UPSTOX_TZ)
        else:
            expiry = self._compute_upstox_expiry(issued_at)

        data = {
            "access_token": access_token,
            "created_at": issued_at.isoformat(),
            "expires_at": expiry.isoformat()
        }
        with open(self.token_file, "w") as f:
            json.dump(data, f, indent=2)
        print(f"[OK] Token saved. Expires at (Asia/Kolkata): {expiry}")

    def load_token(self):
        """
        Load token from disk if it exists and hasn't expired.
        
        Returns
        -------
        str or None
            Valid access_token, or None if expired/missing
        """
        if not self.token_file.exists():
            return None
        
        try:
            with open(self.token_file, "r") as f:
                data = json.load(f)
            
            expiry = datetime.fromisoformat(data["expires_at"])
            now = datetime.now(expiry.tzinfo) if expiry.tzinfo else datetime.now()
            if now < expiry:
                print(f"[OK] Using cached token. Expires at: {expiry}")
                return data["access_token"]
            else:
                print("[INFO] Cached token expired.")
                return None
        except Exception as e:
            print(f"[ERROR] Error loading token: {e}")
            return None

    def clear_token(self):
        """Delete cached token."""
        if self.token_file.exists():
            self.token_file.unlink()
            print("[OK] Token cache cleared.")
