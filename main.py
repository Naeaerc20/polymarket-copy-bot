#!/usr/bin/env python3
"""
Polymarket Copy Trading Bot

Main entry point for the bot.

Features:
- Follow multiple traders from JSON config
- Copy trades with configurable sizing (fixed or percentage)
- Support for market (FAK) and limit (FOK) orders
- Real-time monitoring via polling
- WebSocket support for market activity
- Comprehensive logging

Usage:
    python main.py                    # Run with default config
    python main.py --dry-run          # Test without executing trades
    python main.py --config my.json   # Use custom trader config
"""

import os
import sys
import json
import time
import signal
import argparse
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
from dataclasses import asdict

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from dotenv import load_dotenv

from src.auth import PolymarketAuth, setup_auth_from_env
from src.trader_monitor import (
    TraderMonitor, 
    TraderConfig, 
    Trade, 
    load_traders_from_json,
    DataAPIClient,
    GammaAPIClient
)
from src.order_executor import OrderExecutor, CopyTradeConfig
from src.websocket_client import PolymarketWebSocket


# Configure logging
def setup_logging(log_level: str = "INFO", log_file: Optional[str] = None):
    """Setup logging configuration"""
    level = getattr(logging, log_level.upper(), logging.INFO)
    
    handlers: List[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path))
    
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers
    )
    
    return logging.getLogger(__name__)


class CopyTradingBot:
    """
    Main Copy Trading Bot
    
    Coordinates:
    - Authentication
    - Trader monitoring
    - Order execution
    - Logging and notifications
    """
    
    DEFAULT_CONFIG_PATH = "config/traders.json"
    DEFAULT_CREDS_PATH = "credentials.json"
    
    def __init__(
        self,
        private_key: str,
        funder_address: str,
        signature_type: int = 1,
        traders_config_path: str = DEFAULT_CONFIG_PATH,
        copy_config: Optional[CopyTradeConfig] = None,
        dry_run: bool = False,
        log_level: str = "INFO",
        log_file: Optional[str] = None
    ):
        """
        Initialize the bot
        
        Args:
            private_key: Wallet private key
            funder_address: Proxy wallet address
            signature_type: Wallet signature type (0, 1, or 2)
            traders_config_path: Path to traders.json
            copy_config: Copy trading configuration
            dry_run: If True, don't execute actual trades
            log_level: Logging level
            log_file: Optional log file path
        """
        self.dry_run = dry_run
        self.log_file = log_file
        self.logger = setup_logging(log_level, log_file)
        
        # Load traders config
        self.traders_config_path = traders_config_path
        self.traders = self._load_traders()
        
        # Setup copy config
        self.copy_config = copy_config or CopyTradeConfig.from_env()
        
        # Setup authentication
        self.logger.info("Setting up authentication...")
        self.auth = PolymarketAuth(
            private_key=private_key,
            funder_address=funder_address,
            signature_type=signature_type
        )
        
        # Initialize components (lazy)
        self._monitor: Optional[TraderMonitor] = None
        self._executor: Optional[OrderExecutor] = None
        
        # State
        self._running = False
        self._stats = {
            "trades_detected": 0,
            "trades_executed": 0,
            "trades_skipped": 0,
            "errors": 0,
            "start_time": None,
            "last_activity": None
        }
    
    def _load_traders(self) -> List[TraderConfig]:
        """Load trader configurations"""
        try:
            traders = load_traders_from_json(self.traders_config_path)
            self.logger.info(f"Loaded {len(traders)} traders from config")
            return traders
        except FileNotFoundError:
            self.logger.warning(f"Traders config not found: {self.traders_config_path}")
            self.logger.info("Creating default traders.json template...")
            self._create_default_traders_config()
            return []
    
    def _create_default_traders_config(self) -> None:
        """Create default traders.json template"""
        default_config = {
            "traders": [
                {
                    "address": "0xYOUR_TRADER_ADDRESS_HERE",
                    "nickname": "Trader1",
                    "enabled": False,
                    "copy_buys": True,
                    "copy_sells": True,
                    "max_position_size": 500,
                    "notes": "Add your traders here"
                }
            ],
            "global_settings": {
                "enabled": True,
                "copy_delay_seconds": 1,
                "max_concurrent_trades": 5,
                "stop_on_error": False
            }
        }
        
        Path(self.traders_config_path).parent.mkdir(parents=True, exist_ok=True)
        
        with open(self.traders_config_path, "w") as f:
            json.dump(default_config, f, indent=2)
        
        self.logger.info(f"Created template at {self.traders_config_path}")
    
    def _create_monitor(self) -> TraderMonitor:
        """Create trader monitor instance"""
        return TraderMonitor(
            traders=self.traders,
            poll_interval=float(os.getenv("POLL_INTERVAL", "5")),
            on_trade_callback=self._on_trade_detected
        )
    
    def _create_executor(self) -> OrderExecutor:
        """Create order executor instance"""
        return OrderExecutor(
            auth=self.auth,
            copy_config=self.copy_config,
            dry_run=self.dry_run
        )
    
    @property
    def monitor(self) -> TraderMonitor:
        """Get or create monitor"""
        if self._monitor is None:
            self._monitor = self._create_monitor()
        return self._monitor
    
    @property
    def executor(self) -> OrderExecutor:
        """Get or create executor"""
        if self._executor is None:
            self._executor = self._create_executor()
        return self._executor
    
    def _on_trade_detected(self, trade: Trade, trader: TraderConfig) -> None:
        """Callback when a new trade is detected"""
        self._stats["trades_detected"] += 1
        self._stats["last_activity"] = datetime.now().isoformat()
        
        self.logger.info("=" * 60)
        self.logger.info(f"NEW TRADE DETECTED from {trader.nickname or trade.trader_address[:10]}...")
        self.logger.info(f"  Market: {trade.title}")
        self.logger.info(f"  Action: {trade.side} {trade.size:.2f} {trade.outcome} @ ${trade.price:.4f}")
        self.logger.info(f"  Value: ${trade.usdc_size:.2f}")
        
        # Execute copy trade
        try:
            result = self.executor.execute_copy_trade(trade, trader)
            
            if result["success"]:
                self._stats["trades_executed"] += 1
                self.logger.info(f"✓ Copy trade executed: ${result['copy_size_usdc']:.2f}")
            else:
                self._stats["trades_skipped"] += 1
                self.logger.info(f"✗ Copy trade skipped: {result.get('reason', result.get('error'))}")
                
        except Exception as e:
            self._stats["errors"] += 1
            self.logger.error(f"Error executing copy trade: {e}")
        
        self.logger.info("=" * 60)
    
    def verify_setup(self) -> bool:
        """Verify bot setup is correct"""
        self.logger.info("Verifying setup...")
        
        # Check traders
        if not self.traders:
            self.logger.error("No traders configured!")
            return False
        
        enabled_traders = [t for t in self.traders if t.enabled]
        if not enabled_traders:
            self.logger.warning("No traders enabled! Edit traders.json to enable traders.")
        
        self.logger.info(f"Traders: {len(self.traders)} total, {len(enabled_traders)} enabled")
        
        # Check authentication
        try:
            if self.auth.verify_connection():
                self.logger.info("✓ Authentication successful")
            else:
                self.logger.error("✗ Authentication failed")
                return False
        except Exception as e:
            self.logger.error(f"✗ Authentication error: {e}")
            return False
        
        # Check copy config
        self.logger.info(f"Copy mode: {self.copy_config.copy_mode.value}")
        self.logger.info(f"Amount: ${self.copy_config.amount_to_copy}")
        self.logger.info(f"Percentage: {self.copy_config.percentage_to_copy}")
        self.logger.info(f"Order type: {self.copy_config.order_type}")
        self.logger.info(f"Copy sells: {self.copy_config.copy_sell}")
        self.logger.info(f"Dry run: {self.dry_run}")
        
        return True
    
    def print_banner(self) -> None:
        """Print startup banner"""
        banner = """
╔═══════════════════════════════════════════════════════════╗
║         POLYMARKET COPY TRADING BOT                      ║
║                                                           ║
║  Copy trades from top traders automatically             ║
╚═══════════════════════════════════════════════════════════╝
"""
        print(banner)
        
        if self.dry_run:
            print("  ⚠️  DRY RUN MODE - No actual trades will be executed\n")
    
    def print_stats(self) -> None:
        """Print current statistics"""
        print("\n" + "=" * 50)
        print("BOT STATISTICS")
        print("=" * 50)
        print(f"  Trades Detected: {self._stats['trades_detected']}")
        print(f"  Trades Executed: {self._stats['trades_executed']}")
        print(f"  Trades Skipped:  {self._stats['trades_skipped']}")
        print(f"  Errors:          {self._stats['errors']}")
        
        if self._stats['start_time']:
            start = datetime.fromisoformat(self._stats['start_time'])
            elapsed = datetime.now() - start
            print(f"  Running Time:    {elapsed}")
        
        print("=" * 50 + "\n")
    
    def run(self) -> None:
        """Run the bot"""
        self._running = True
        self._stats["start_time"] = datetime.now().isoformat()
        
        self.print_banner()
        
        if not self.verify_setup():
            self.logger.error("Setup verification failed. Exiting.")
            return
        
        # Setup signal handlers
        def signal_handler(signum, frame):
            self.logger.info("\nReceived shutdown signal...")
            self._running = False
            self.print_stats()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        self.logger.info("Starting copy trading bot...")
        self.logger.info(f"Monitoring {len([t for t in self.traders if t.enabled])} traders")
        self.logger.info("Press Ctrl+C to stop\n")
        
        # Run monitor
        try:
            self.monitor.run()
        except Exception as e:
            self.logger.error(f"Bot error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self._running = False
            self.print_stats()
    
    def stop(self) -> None:
        """Stop the bot"""
        self._running = False
        if self._monitor:
            self._monitor.stop()


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Polymarket Copy Trading Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python main.py                      # Run with .env config
    python main.py --dry-run            # Test without executing trades
    python main.py --config traders.json  # Custom trader config
    python main.py --amount 100         # Set fixed copy amount
    python main.py --percentage 50      # Copy 50% of trade size
        """
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without executing actual trades"
    )
    
    parser.add_argument(
        "--config",
        type=str,
        default="config/traders.json",
        help="Path to traders configuration JSON"
    )
    
    parser.add_argument(
        "--amount",
        type=float,
        help="Fixed amount in USDC to copy per trade"
    )
    
    parser.add_argument(
        "--percentage",
        type=float,
        help="Percentage of trade size to copy (1-100)"
    )
    
    parser.add_argument(
        "--order-type",
        type=str,
        choices=["FOK", "FAK"],
        default=None,  # None = use value from .env (TYPE_ORDER)
        help="Order type: FOK (limit) or FAK (market). Defaults to TYPE_ORDER in .env"
    )
    
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level"
    )
    
    parser.add_argument(
        "--log-file",
        type=str,
        help="Log file path"
    )
    
    args = parser.parse_args()
    
    # Load environment
    load_dotenv()
    
    # Get required environment variables
    private_key = os.getenv("PRIVATE_KEY")
    funder_address = os.getenv("FUNDER_ADDRESS")
    signature_type = int(os.getenv("SIGNATURE_TYPE", "1"))
    
    if not private_key:
        print("ERROR: PRIVATE_KEY not set in environment")
        print("Create a .env file with your configuration")
        sys.exit(1)
    
    if not funder_address:
        print("ERROR: FUNDER_ADDRESS not set in environment")
        print("This should be your proxy wallet address from Polymarket.com")
        sys.exit(1)
    
    # Create copy config
    copy_config = CopyTradeConfig.from_env()
    
    # Override with command line args
    if args.amount:
        copy_config.amount_to_copy = args.amount
        copy_config.percentage_to_copy = None
    
    if args.percentage:
        copy_config.percentage_to_copy = args.percentage
    
    if args.order_type:
        copy_config.order_type = args.order_type
    
    # Create and run bot
    bot = CopyTradingBot(
        private_key=private_key,
        funder_address=funder_address,
        signature_type=signature_type,
        traders_config_path=args.config,
        copy_config=copy_config,
        dry_run=args.dry_run,
        log_level=args.log_level,
        log_file=args.log_file
    )
    
    bot.run()


if __name__ == "__main__":
    main()