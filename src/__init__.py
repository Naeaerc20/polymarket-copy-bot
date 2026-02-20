"""
Polymarket Copy Trading Bot

A bot for automatically copying trades from selected Polymarket traders.
"""

from .auth import PolymarketAuth, PolymarketCredentials
from .trader_monitor import TraderMonitor, TraderConfig, Trade
from .order_executor import OrderExecutor, CopyTradeConfig
from .websocket_client import PolymarketWebSocket

__version__ = "1.0.0"
__all__ = [
    "PolymarketAuth",
    "PolymarketCredentials",
    "TraderMonitor",
    "TraderConfig",
    "Trade",
    "OrderExecutor",
    "CopyTradeConfig",
    "PolymarketWebSocket",
]
