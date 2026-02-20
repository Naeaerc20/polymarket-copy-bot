"""
Polymarket Copy Trading Bot

A bot for automatically copying trades from selected Polymarket traders.
"""

from .auth import PolymarketAuth
from .trader_monitor import TraderMonitor, TraderConfig, Trade
from .order_executor import OrderExecutor, CopyTradeConfig
from .websocket_client import PolymarketWebSocket

__version__ = "1.0.0"
__all__ = [
    "PolymarketAuth",
    "TraderMonitor",
    "TraderConfig",
    "Trade",
    "OrderExecutor",
    "CopyTradeConfig",
    "PolymarketWebSocket",
]
