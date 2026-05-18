import requests


class UpstoxSandboxClient:
    def __init__(self, base_url=None):
        self.base_url = base_url or "https://api-sandbox.upstox.com/v3"

    def place_order(self, access_token, payload):
        url = f"{self.base_url}/order/place"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        }
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()

    def cancel_order(self, access_token, order_id):
        url = f"{self.base_url}/order/cancel"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        }
        response = requests.delete(url, headers=headers, params={"order_id": order_id}, timeout=30)
        response.raise_for_status()
        return response.json()

    def get_order_history(self, access_token, order_id):
        url = f"{self.base_url}/order/history"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        }
        response = requests.get(url, headers=headers, params={"order_id": order_id}, timeout=30)
        response.raise_for_status()
        return response.json()

    def get_order_book(self, access_token):
        url = f"{self.base_url}/order/retrieve-all"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        }
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()

    def get_positions(self, access_token):
        url = f"{self.base_url}/portfolio/short-term-positions"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        }
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
