# Import necessary modules
import asyncio
import json
import ssl
import websockets
import requests
from google.protobuf.json_format import MessageToDict
import pandas as pd
from src.data import MarketDataFeedV3_pb2 as pb
import time
from datetime import datetime

# Initialize DataFrame
ohlc_df = pd.DataFrame(columns=['timestamp', 'symbol', 'open', 'high', 'low', 'close', 'volume'])
last_save_time = time.time()

def get_market_data_feed_authorize_v3():
    """Get authorization for market data feed."""
    access_token = 'eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiIyWUNVMkYiLCJqdGkiOiI2OTg2MmIwMWM4NTFmZDQ3MTdkNmY2YWEiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6dHJ1ZSwiaWF0IjoxNzcwNDAwNTEzLCJpc3MiOiJ1ZGFwaS1nYXRld2F5LXNlcnZpY2UiLCJleHAiOjE3NzA0MTUyMDB9.HRp_XJ8DMRWCHpvcAt4h2izGxBzR8kcatgpozRQX7PA'
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {access_token}'
    }
    url = 'https://api.upstox.com/v3/feed/market-data-feed/authorize'
    api_response = requests.get(url=url, headers=headers)
    return api_response.json()

def decode_protobuf(buffer):
    """Decode protobuf message."""
    feed_response = pb.FeedResponse()
    feed_response.ParseFromString(buffer)
    return feed_response

async def fetch_market_data():
    """Fetch market data using WebSocket."""
    global ohlc_df, last_save_time

    # SSL context setup
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    # Authorization
    response = get_market_data_feed_authorize_v3()
    print("Authorization Response:", response)

    ws_url = response.get("data", {}).get("authorized_redirect_uri")
    if not ws_url:
        print("❌ WebSocket URL not found. Check your access token.")
        return

    async with websockets.connect(ws_url, ssl=ssl_context) as websocket:
        print('✅ Connection established')

        await asyncio.sleep(1)

        # Subscription
        data = {
            "guid": "someguid",
            "method": "sub",
            "data": {
                "mode": "full",
                "instrumentKeys": ["MCX_FO|488604"]
            }
        }

        await websocket.send(json.dumps(data).encode('utf-8'))

        while True:
            try:
                message = await websocket.recv()
                decoded_data = decode_protobuf(message)
                data_dict = MessageToDict(decoded_data)

                feeds = data_dict.get('feeds', {})
                for symbol, details in feeds.items():
                    ohlc_data = details.get('fullFeed', {}).get('marketFF', {}).get('marketOHLC', {}).get('ohlc', [])
                    for candle in ohlc_data:
                        if candle.get('interval') == 'I1':
                            candle_minute = pd.Timestamp(datetime.now().replace(second=0, microsecond=0))

                            mask = (ohlc_df['timestamp'] == candle_minute) & (ohlc_df['symbol'] == symbol)

                            if not ohlc_df[mask].empty:
                                # Update existing row
                                ohlc_df.loc[mask, ['open', 'high', 'low', 'close', 'volume']] = [
                                    candle.get('open'),
                                    candle.get('high'),
                                    candle.get('low'),
                                    candle.get('close'),
                                    candle.get('vol', 0)
                                ]
                            else:
                                # Add new row
                                new_row = {
                                    'timestamp': candle_minute,
                                    'symbol': symbol,
                                    'open': candle.get('open'),
                                    'high': candle.get('high'),
                                    'low': candle.get('low'),
                                    'close': candle.get('close'),
                                    'volume': candle.get('vol', 0)
                                }
                                ohlc_df.loc[len(ohlc_df)] = new_row

                # Save to CSV every 60 seconds
                if time.time() - last_save_time > 60:
                    ohlc_df.drop_duplicates(subset=['timestamp', 'symbol'], keep='last', inplace=True)
                    ohlc_df.sort_values(by='timestamp', inplace=True)
                    ohlc_df.to_csv("ohlc_data.csv", index=False)
                    print("💾 Saved CSV with rows:", len(ohlc_df))
                    print(ohlc_df.tail(1))
                    last_save_time = time.time()

            except Exception as e:
                print(f"❌ Error receiving data: {e}")
                continue

asyncio.run(fetch_market_data())
