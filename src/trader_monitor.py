"""
Trader Activity Monitor

Monitors Polymarket trader activity using:
- Data API for historical trades
- WebSocket for real-time updates
"""

import asyncio
import json
import time
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
import aiohttp
import requests

from auth import PolymarketCredentials


@dataclass
class Trade:
    """Represents a trade on Polymarket"""
    trader_address: str
    condition_id: str
    asset_id: str
    side: str  # BUY or SELL
    size: float
    price: float
    usdc_size: float
    timestamp: int
    outcome: str
    outcome_index: int
    title: str
    slug: str
    transaction_hash: Optional[str] = None
    
    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> "Trade":
        """Create Trade from API response"""
        return cls(
            trader_address=data.get("proxyWallet", ""),
            condition_id=data.get("conditionId", ""),
            asset_id=data.get("asset", ""),
            side=data.get("side", "BUY"),
            size=float(data.get("size", 0)),
            price=float(data.get("price", 0)),
            usdc_size=float(data.get("usdcSize", data.get("size", 0) * data.get("price", 1))),
            timestamp=data.get("timestamp", 0),
            outcome=data.get("outcome", ""),
            outcome_index=data.get("outcomeIndex", 0),
            title=data.get("title", ""),
            slug=data.get("slug", ""),
            transaction_hash=data.get("transactionHash", "")
        )
    
    def __str__(self) -> str:
        return (
            f"Trade({self.side} {self.size:.2f} {self.outcome} @ ${self.price:.4f} "
            f"= ${self.usdc_size:.2f} on '{self.title[:40]}...')"
        )


@dataclass
class TraderConfig:
    """Configuration for a trader to follow"""
    address: str
    nickname: str = ""
    enabled: bool = True
    copy_buys: bool = True
    copy_sells: bool = True
    max_position_size: float = float("inf")
    notes: str = ""
    
    # Runtime state
    last_known_trade_ts: int = 0
    total_trades_copied: int = 0
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TraderConfig":
        return cls(
            address=data.get("address", ""),
            nickname=data.get("nickname", ""),
            enabled=data.get("enabled", True),
            copy_buys=data.get("copy_buys", True),
            copy_sells=data.get("copy_sells", True),
            max_position_size=data.get("max_position_size", float("inf")),
            notes=data.get("notes", "")
        )


class DataAPIClient:
    """Client for Polymarket Data API (public endpoints)"""
    
    BASE_URL = "https://data-api.polymarket.com"
    
    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
    
    def get_user_activity(
        self,
        user_address: str,
        limit: int = 100,
        offset: int = 0,
        activity_type: Optional[str] = "TRADE",
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get activity for a specific user
        
        Args:
            user_address: User's wallet address (0x prefixed)
            limit: Number of results (max 500)
            offset: Pagination offset
            activity_type: Filter by type (TRADE, SPLIT, MERGE, REDEEM, etc.)
            start_ts: Start timestamp filter
            end_ts: End timestamp filter
        """
        params = {
            "user": user_address,
            "limit": min(limit, 500),
            "offset": offset
        }
        
        if activity_type:
            params["type"] = activity_type
        if start_ts:
            params["start"] = start_ts
        if end_ts:
            params["end"] = end_ts
        
        response = self.session.get(
            f"{self.BASE_URL}/activity",
            params=params
        )
        response.raise_for_status()
        return response.json()
    
    def get_trades(
        self,
        user_address: str,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get trades for a specific user"""
        params = {
            "user": user_address,
            "limit": min(limit, 10000),
            "offset": offset
        }
        
        response = self.session.get(
            f"{self.BASE_URL}/trades",
            params=params
        )
        response.raise_for_status()
        return response.json()
    
    def get_current_positions(self, user_address: str) -> List[Dict[str, Any]]:
        """Get current positions for a user"""
        response = self.session.get(
            f"{self.BASE_URL}/positions",
            params={"user": user_address}
        )
        response.raise_for_status()
        return response.json()


class GammaAPIClient:
    """Client for Polymarket Gamma API (market data)"""
    
    BASE_URL = "https://gamma-api.polymarket.com"
    
    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
    
    def get_markets(
        self,
        limit: int = 100,
        offset: int = 0,
        active: bool = True
    ) -> List[Dict[str, Any]]:
        """Get list of markets"""
        params = {
            "limit": limit,
            "offset": offset,
            "active": str(active).lower()
        }
        
        response = self.session.get(
            f"{self.BASE_URL}/markets",
            params=params
        )
        response.raise_for_status()
        return response.json()
    
    def get_market_by_condition_id(self, condition_id: str) -> Optional[Dict[str, Any]]:
        """Get market by condition ID"""
        response = self.session.get(
            f"{self.BASE_URL}/markets",
            params={"condition_id": condition_id}
        )
        response.raise_for_status()
        markets = response.json()
        return markets[0] if markets else None
    
    def get_market_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        """Get market by slug"""
        response = self.session.get(
            f"{self.BASE_URL}/markets",
            params={"slug": slug}
        )
        response.raise_for_status()
        markets = response.json()
        return markets[0] if markets else None
    
    def get_token_info(self, condition_id: str, outcome_index: int) -> Optional[Dict[str, Any]]:
        """Get token information for a market outcome"""
        market = self.get_market_by_condition_id(condition_id)
        if not market:
            return None
        
        tokens = market.get("tokens", [])
        for token in tokens:
            if token.get("outcome_index") == outcome_index:
                return token
        
        return None


class TraderMonitor:
    """
    Monitors trader activity and detects new trades
    
    Uses polling (Data API) for reliable detection.
    Can optionally use WebSocket for real-time updates.
    """
    
    def __init__(
        self,
        traders: List[TraderConfig],
        poll_interval: float = 5.0,
        on_trade_callback: Optional[Callable[[Trade, TraderConfig], None]] = None
    ):
        """
        Initialize monitor
        
        Args:
            traders: List of traders to monitor
            poll_interval: Seconds between polling
            on_trade_callback: Callback when new trade is detected
        """
        self.traders = {t.address.lower(): t for t in traders}
        self.poll_interval = poll_interval
        self.on_trade_callback = on_trade_callback
        
        self.data_api = DataAPIClient()
        self.gamma_api = GammaAPIClient()
        
        self._running = False
        self._seen_trades: Dict[str, set] = {}  # address -> set of seen trade hashes
    
    def add_trader(self, trader: TraderConfig) -> None:
        """Add a trader to monitor"""
        self.traders[trader.address.lower()] = trader
        print(f"[Monitor] Added trader: {trader.nickname or trader.address}")
    
    def remove_trader(self, address: str) -> None:
        """Remove a trader from monitoring"""
        addr_lower = address.lower()
        if addr_lower in self.traders:
            del self.traders[addr_lower]
            print(f"[Monitor] Removed trader: {address}")
    
    def update_trader_state(self, address: str, trade_ts: int) -> None:
        """Update last known trade timestamp for a trader"""
        addr_lower = address.lower()
        if addr_lower in self.traders:
            self.traders[addr_lower].last_known_trade_ts = trade_ts
    
    def _get_trade_hash(self, trade: Dict[str, Any]) -> str:
        """Create unique hash for a trade"""
        return f"{trade.get('timestamp', 0)}_{trade.get('conditionId', '')}_{trade.get('side', '')}_{trade.get('size', 0)}"
    
    def _initialize_trader_state(self, address: str) -> None:
        """Initialize state for a trader by fetching their latest trades"""
        try:
            activity = self.data_api.get_user_activity(
                user_address=address,
                limit=10,
                activity_type="TRADE"
            )
            
            if address.lower() not in self._seen_trades:
                self._seen_trades[address.lower()] = set()
            
            for act in activity:
                trade_hash = self._get_trade_hash(act)
                self._seen_trades[address.lower()].add(trade_hash)
            
            # Update last known timestamp
            if activity:
                latest_ts = max(a.get("timestamp", 0) for a in activity)
                self.update_trader_state(address, latest_ts)
            
            print(f"[Monitor] Initialized state for {address[:10]}... ({len(activity)} recent trades)")
            
        except Exception as e:
            print(f"[Monitor] Error initializing {address[:10]}...: {e}")
    
    def check_trader_activity(self, address: str) -> List[Trade]:
        """
        Check for new activity from a trader
        
        Returns:
            List of new trades (empty if none)
        """
        new_trades = []
        
        try:
            activity = self.data_api.get_user_activity(
                user_address=address,
                limit=50,
                activity_type="TRADE"
            )
            
            if address.lower() not in self._seen_trades:
                self._seen_trades[address.lower()] = set()
            
            for act in activity:
                trade_hash = self._get_trade_hash(act)
                
                if trade_hash not in self._seen_trades[address.lower()]:
                    # New trade!
                    trade = Trade.from_api_response(act)
                    new_trades.append(trade)
                    self._seen_trades[address.lower()].add(trade_hash)
            
            if new_trades:
                # Sort by timestamp (oldest first for proper order)
                new_trades.sort(key=lambda t: t.timestamp)
                latest_ts = new_trades[-1].timestamp
                self.update_trader_state(address, latest_ts)
            
        except Exception as e:
            print(f"[Monitor] Error checking {address[:10]}...: {e}")
        
        return new_trades
    
    def check_all_traders(self) -> List[tuple]:
        """
        Check all traders for new activity
        
        Returns:
            List of (trade, trader_config) tuples
        """
        all_new_trades = []
        
        for address, trader in self.traders.items():
            if not trader.enabled:
                continue
            
            new_trades = self.check_trader_activity(address)
            
            for trade in new_trades:
                all_new_trades.append((trade, trader))
        
        return all_new_trades
    
    async def run_async(self) -> None:
        """Run the monitor loop asynchronously"""
        self._running = True
        
        print(f"[Monitor] Starting to monitor {len(self.traders)} traders...")
        
        # Initialize state for all traders
        for address in self.traders:
            self._initialize_trader_state(address)
        
        print(f"[Monitor] Initialization complete. Starting poll loop...")
        
        while self._running:
            try:
                new_trades = self.check_all_traders()
                
                for trade, trader in new_trades:
                    ts_str = datetime.fromtimestamp(trade.timestamp).strftime("%Y-%m-%d %H:%M:%S")
                    print(f"\n[Monitor] NEW TRADE DETECTED!")
                    print(f"  Trader: {trader.nickname or trade.trader_address[:10]}...")
                    print(f"  Time: {ts_str}")
                    print(f"  {trade}")
                    
                    if self.on_trade_callback:
                        try:
                            self.on_trade_callback(trade, trader)
                        except Exception as e:
                            print(f"[Monitor] Callback error: {e}")
                
                await asyncio.sleep(self.poll_interval)
                
            except Exception as e:
                print(f"[Monitor] Loop error: {e}")
                await asyncio.sleep(self.poll_interval)
    
    def run(self) -> None:
        """Run the monitor loop (blocking)"""
        try:
            asyncio.run(self.run_async())
        except KeyboardInterrupt:
            print("\n[Monitor] Stopped by user")
    
    def stop(self) -> None:
        """Stop the monitor"""
        self._running = False


def load_traders_from_json(filepath: str) -> List[TraderConfig]:
    """Load trader configurations from JSON file"""
    with open(filepath, "r") as f:
        data = json.load(f)
    
    traders = []
    for t in data.get("traders", []):
        traders.append(TraderConfig.from_dict(t))
    
    return traders


if __name__ == "__main__":
    import sys
    
    # Test monitor with traders from config
    traders = load_traders_from_json("../config/traders.json")
    
    def on_new_trade(trade: Trade, trader: TraderConfig):
        print(f"  -> Would copy this trade!")
    
    monitor = TraderMonitor(
        traders=traders,
        poll_interval=10.0,
        on_trade_callback=on_new_trade
    )
    
    try:
        monitor.run()
    except KeyboardInterrupt:
        monitor.stop()
