import os
import requests
from dotenv import load_dotenv
from .token_manager import TokenManager


load_dotenv()


class UpstoxClient:
    def __init__(self, use_cache=True, cache_dir=None):
        self.client_id = os.getenv("UPSTOX_CLIENT_ID")
        self.client_secret = os.getenv("UPSTOX_CLIENT_SECRET")
        self.redirect_uri = os.getenv("UPSTOX_REDIRECT_URI")
        self.base_url = "https://api.upstox.com/v2"
        self.base_url_v3 = "https://api-hft.upstox.com/v3"
        self.access_token = None
        
        # Token caching
        self.use_cache = use_cache
        self.token_manager = TokenManager(cache_dir) if use_cache else None

    def get_cached_token(self):
        """Try to load valid token from cache."""
        if self.token_manager:
            return self.token_manager.load_token()
        return None

    def get_login_url(self, redirect_uri=None):
        uri = redirect_uri or self.redirect_uri
        return (
            f"{self.base_url}/login/authorization/dialog"
            f"?response_type=code&client_id={self.client_id}&redirect_uri={uri}"
        )

    def exchange_token(self, code: str, redirect_uri=None):
        uri = redirect_uri or self.redirect_uri
        url = f"{self.base_url}/login/authorization/token"
        headers = {"accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": uri,
            "grant_type": "authorization_code",
        }
        r = requests.post(url, headers=headers, data=data, timeout=30)
        r.raise_for_status()
        
        response_data = r.json()
        self.access_token = response_data.get("access_token")
        
        # Cache the token (expires_in is typically 86400 seconds = 24h)
        if self.use_cache and self.access_token:
            expires_in = response_data.get("expires_in", 86400)
            self.token_manager.save_token(self.access_token, expires_in)
        
        return self.access_token

    def get_funds_and_margin(self, access_token: str, segment: str | None = None):
        """Fetch account funds and margin snapshot."""
        url = f"{self.base_url}/user/get-funds-and-margin"
        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        }
        params = {"segment": segment} if segment else None
        r = requests.get(url, headers=headers, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def place_order(self, access_token: str, payload: dict):
        """Place order using v3 order API."""
        url = f"{self.base_url_v3}/order/place"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        }
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        r.raise_for_status()
        return r.json()

    def cancel_order(self, access_token: str, order_id: str):
        """Cancel order using v3 order API."""
        url = f"{self.base_url_v3}/order/cancel"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        }
        r = requests.delete(url, headers=headers, params={"order_id": order_id}, timeout=30)
        r.raise_for_status()
        return r.json()

    def get_order_history(self, access_token: str, order_id: str):
        """Fetch order history for a specific order id."""
        url = f"{self.base_url}/order/history"
        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        }
        r = requests.get(url, headers=headers, params={"order_id": order_id}, timeout=30)
        r.raise_for_status()
        return r.json()

    def get_order_book(self, access_token: str):
        """Fetch all orders (order book) for the day."""
        url = f"{self.base_url}/order/retrieve-all"
        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        }
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        return r.json()

    def get_trades_for_day(self, access_token: str):
        """Fetch all executed trades for the day."""
        url = f"{self.base_url}/order/trades/get-trades-for-day"
        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        }
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        return r.json()

    def exit_all_positions(self, access_token: str, segment: str | None = None, tag: str | None = None):
        """Exit all open positions, optionally filtered by segment and/or tag."""
        url = f"{self.base_url}/order/positions/exit"
        headers = {
            "accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        }
        params = {}
        if segment:
            params["segment"] = segment
        if tag:
            params["tag"] = tag
        r = requests.post(url, headers=headers, params=params or None, timeout=30)
        r.raise_for_status()
        return r.json()
