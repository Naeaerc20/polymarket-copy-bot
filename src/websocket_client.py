"""
WebSocket Client for Polymarket

Provides real-time market data and order updates via WebSocket.

Channels:
- Market Channel: Orderbook, price updates, trades
- User Channel: Personal order and trade updates (requires auth)
"""

import asyncio
import json
import time
from typing import Optional, Callable, Dict, Any, List, Set
from dataclasses import dataclass
import websockets


@dataclass
class WSMessage:
    """WebSocket message container"""
    type: str
    data: Dict[str, Any]
    timestamp: float = 0.0
    
    @classmethod
    def from_raw(cls, raw_data: str) -> "WSMessage":
        """Parse raw WebSocket message"""
        try:
            data = json.loads(raw_data)
            return cls(
                type=data.get("type", data.get("event_type", "unknown")),
                data=data,
                timestamp=time.time()
            )
        except json.JSONDecodeError:
            return cls(type="raw", data={"raw": raw_data})


class PolymarketWebSocket:
    """
    WebSocket client for Polymarket real-time data
    
    Market Channel (public):
    - Orderbook updates
    - Price changes
    - Trade executions
    
    User Channel (authenticated):
    - Order status updates
    - Trade confirmations
    """
    
    MARKET_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    USER_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/user"
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        api_passphrase: Optional[str] = None,
        on_message: Optional[Callable[[WSMessage], None]] = None,
        on_connect: Optional[Callable[[], None]] = None,
        on_disconnect: Optional[Callable[[], None]] = None
    ):
        """
        Initialize WebSocket client
        
        Args:
            api_key: API key for user channel
            api_secret: API secret for user channel
            api_passphrase: API passphrase for user channel
            on_message: Callback for incoming messages
            on_connect: Callback when connected
            on_disconnect: Callback when disconnected
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_passphrase = api_passphrase
        self.on_message = on_message
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._subscribed_assets: Set[str] = set()
        self._subscribed_markets: Set[str] = set()
        self._last_ping = 0.0
    
    @property
    def has_credentials(self) -> bool:
        """Check if credentials are available"""
        return all([self.api_key, self.api_secret, self.api_passphrase])
    
    async def connect_market_channel(self) -> None:
        """Connect to market data WebSocket"""
        print("[WS] Connecting to market channel...")
        self._ws = await websockets.connect(self.MARKET_WS_URL)
        self._running = True
        print("[WS] Connected to market channel")
        
        if self.on_connect:
            self.on_connect()
    
    async def connect_user_channel(self) -> None:
        """Connect to user WebSocket (requires authentication)"""
        if not self.has_credentials:
            raise ValueError("Credentials required for user channel")
        
        print("[WS] Connecting to user channel...")
        self._ws = await websockets.connect(self.USER_WS_URL)
        self._running = True
        print("[WS] Connected to user channel")
        
        if self.on_connect:
            self.on_connect()
    
    async def subscribe_market(
        self,
        asset_ids: List[str],
        custom_features: bool = False
    ) -> None:
        """
        Subscribe to market updates
        
        Args:
            asset_ids: List of token/asset IDs to subscribe to
            custom_features: Enable best_bid_ask, new_market, market_resolved events
        """
        message = {
            "assets_ids": asset_ids,
            "type": "market"
        }
        
        if custom_features:
            message["custom_feature_enabled"] = True
        
        await self._send(message)
        self._subscribed_assets.update(asset_ids)
        print(f"[WS] Subscribed to {len(asset_ids)} assets")
    
    async def subscribe_user(
        self,
        markets: Optional[List[str]] = None
    ) -> None:
        """
        Subscribe to user updates (requires authentication)
        
        Args:
            markets: List of condition IDs to filter (optional)
        """
        if not self.has_credentials:
            raise ValueError("Credentials required for user channel")
        
        message = {
            "auth": {
                "apiKey": self.api_key,
                "secret": self.api_secret,
                "passphrase": self.api_passphrase
            },
            "type": "user"
        }
        
        if markets:
            message["markets"] = markets
            self._subscribed_markets.update(markets)
        
        await self._send(message)
        print("[WS] Subscribed to user channel")
    
    async def unsubscribe_assets(self, asset_ids: List[str]) -> None:
        """Unsubscribe from specific assets"""
        message = {
            "assets_ids": asset_ids,
            "operation": "unsubscribe"
        }
        await self._send(message)
        self._subscribed_assets.difference_update(asset_ids)
    
    async def unsubscribe_markets(self, markets: List[str]) -> None:
        """Unsubscribe from specific markets (user channel)"""
        message = {
            "markets": markets,
            "operation": "unsubscribe"
        }
        await self._send(message)
        self._subscribed_markets.difference_update(markets)
    
    async def _send(self, message: Dict[str, Any]) -> None:
        """Send message through WebSocket"""
        if self._ws:
            await self._ws.send(json.dumps(message))
    
    async def _send_ping(self) -> None:
        """Send heartbeat ping"""
        if self._ws:
            await self._ws.send("PING")
            self._last_ping = time.time()
    
    async def listen(self) -> None:
        """Listen for incoming messages"""
        if not self._ws:
            raise RuntimeError("WebSocket not connected")
        
        last_ping = time.time()
        
        try:
            async for message in self._ws:
                if not self._running:
                    break
                
                # Handle pong
                if message == "PONG":
                    continue
                
                # Parse and handle message
                ws_message = WSMessage.from_raw(message)
                
                if self.on_message:
                    try:
                        self.on_message(ws_message)
                    except Exception as e:
                        print(f"[WS] Callback error: {e}")
                
                # Send heartbeat every 10 seconds
                if time.time() - last_ping > 10:
                    await self._send_ping()
                    last_ping = time.time()
                    
        except websockets.exceptions.ConnectionClosed as e:
            print(f"[WS] Connection closed: {e}")
            if self.on_disconnect:
                self.on_disconnect()
    
    async def close(self) -> None:
        """Close WebSocket connection"""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        print("[WS] Connection closed")
    
    async def run_forever(self) -> None:
        """Keep connection alive with automatic reconnection"""
        retry_delay = 1
        
        while True:
            try:
                ws_url = self.USER_WS_URL if self.has_credentials else self.MARKET_WS_URL
                async with websockets.connect(ws_url) as ws:
                    self._ws = ws
                    self._running = True
                    retry_delay = 1  # Reset retry delay on successful connection
                    
                    if self.on_connect:
                        self.on_connect()
                    
                    await self.listen()
                    
            except Exception as e:
                print(f"[WS] Error: {e}")
                print(f"[WS] Reconnecting in {retry_delay}s...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60)  # Exponential backoff


class MarketActivityMonitor:
    """
    Monitor for detecting trades on specific markets via WebSocket
    
    Useful for watching when specific traders are active in markets
    """
    
    def __init__(
        self,
        on_trade_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ):
        """
        Initialize monitor
        
        Args:
            on_trade_callback: Called when a trade is detected
        """
        self.on_trade_callback = on_trade_callback
        self.ws = PolymarketWebSocket(on_message=self._handle_message)
        self._tracked_assets: Dict[str, str] = {}  # asset_id -> metadata
    
    def _handle_message(self, message: WSMessage) -> None:
        """Handle incoming WebSocket message"""
        # Look for trade events
        if message.type in ["last_trade_price", "TRADE"]:
            trade_data = message.data
            
            if self.on_trade_callback:
                self.on_trade_callback(trade_data)
    
    async def watch_assets(self, asset_ids: List[str]) -> None:
        """Start watching assets for trades"""
        await self.ws.connect_market_channel()
        await self.ws.subscribe_market(asset_ids, custom_features=True)
        
        print(f"[Monitor] Watching {len(asset_ids)} assets for trades...")
        
        try:
            await self.ws.listen()
        finally:
            await self.ws.close()
    
    async def stop(self) -> None:
        """Stop monitoring"""
        await self.ws.close()


async def test_websocket():
    """Test WebSocket connection"""
    
    def on_message(msg: WSMessage):
        print(f"[WS] Received: {msg.type}")
        if msg.type == "last_trade_price":
            data = msg.data
            print(f"  Trade: {data.get('size', 0)} @ {data.get('price', 0)}")
    
    client = PolymarketWebSocket(on_message=on_message)
    
    # Example asset IDs (replace with real ones)
    test_assets = [
        "21742633143463906290569050155826241533067272736897614950488156847949938836455"
    ]
    
    print("Testing WebSocket connection...")
    
    try:
        await client.connect_market_channel()
        await client.subscribe_market(test_assets)
        
        # Listen for 30 seconds
        print("Listening for 30 seconds...")
        await asyncio.sleep(30)
        
    finally:
        await client.close()
    
    print("Test complete")


if __name__ == "__main__":
    asyncio.run(test_websocket())
