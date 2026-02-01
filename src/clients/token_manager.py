import os
import json
from datetime import datetime, timedelta
from pathlib import Path


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

    def save_token(self, access_token, expires_in_seconds=86400):
        """
        Save token to disk with expiration time.
        
        Parameters
        ----------
        access_token : str
            The access token from OAuth
        expires_in_seconds : int
            Token lifetime in seconds (default: 24h = 86400s)
        """
        expiry = datetime.now() + timedelta(seconds=expires_in_seconds)
        data = {
            "access_token": access_token,
            "created_at": datetime.now().isoformat(),
            "expires_at": expiry.isoformat()
        }
        with open(self.token_file, "w") as f:
            json.dump(data, f, indent=2)
        print(f"[OK] Token saved. Expires at: {expiry}")

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
            if datetime.now() < expiry:
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
