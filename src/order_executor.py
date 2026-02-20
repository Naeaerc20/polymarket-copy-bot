"""
Order Executor Module

Handles:
- Creating and posting orders to Polymarket CLOB
- Copy trade logic (amount/percentage calculations)
- Order type handling (FOK/FAK)
"""

import os
import time
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import math

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import OrderArgs, MarketOrderArgs, OrderType
except ImportError:
    print("Installing py-clob-client...")
    os.system("pip install py-clob-client")
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import OrderArgs, MarketOrderArgs, OrderType

from auth import PolymarketAuth
from trader_monitor import Trade, TraderConfig, GammaAPIClient


class CopyMode(Enum):
    """Copy trade sizing mode"""
    FIXED_AMOUNT = "fixed"      # Use AMOUNT_TO_COPY
    PERCENTAGE = "percentage"   # Use percentage of trader's size


@dataclass
class CopyTradeConfig:
    """Configuration for copy trading behavior"""
    amount_to_copy: float = 50.0           # Fixed amount in USDC
    percentage_to_copy: Optional[float] = 100.0  # Percentage or None for fixed
    copy_sell: bool = True                  # Copy sell orders
    order_type: str = "FOK"                 # FOK or FAK
    min_trade_size: float = 1.0            # Minimum USDC to copy
    max_trade_size: float = 1000.0         # Maximum USDC to copy
    
    @classmethod
    def from_env(cls) -> "CopyTradeConfig":
        """Load configuration from environment variables"""
        from dotenv import load_dotenv
        load_dotenv()
        
        # Parse percentage
        pct_str = os.getenv("PERCENTAGE_TO_COPY", "100")
        percentage = None if pct_str.lower() == "null" else float(pct_str)
        
        return cls(
            amount_to_copy=float(os.getenv("AMOUNT_TO_COPY", "50")),
            percentage_to_copy=percentage,
            copy_sell=os.getenv("COPY_SELL", "true").lower() == "true",
            order_type=os.getenv("TYPE_ORDER", "FOK").upper(),
            min_trade_size=float(os.getenv("MIN_TRADE_SIZE", "1")),
            max_trade_size=float(os.getenv("MAX_TRADE_SIZE", "1000"))
        )
    
    @property
    def copy_mode(self) -> CopyMode:
        """Determine copy mode from configuration"""
        if self.percentage_to_copy is None:
            return CopyMode.FIXED_AMOUNT
        return CopyMode.PERCENTAGE


class OrderExecutor:
    """
    Executes copy trades on Polymarket
    
    Handles:
    - Order creation with proper sizing
    - EIP-712 order signing
    - Posting orders to CLOB
    - Error handling and retries
    """
    
    def __init__(
        self,
        auth: PolymarketAuth,
        copy_config: Optional[CopyTradeConfig] = None,
        dry_run: bool = False
    ):
        """
        Initialize executor
        
        Args:
            auth: PolymarketAuth instance
            copy_config: Copy trade configuration
            dry_run: If True, don't actually execute trades
        """
        self.auth = auth
        self.copy_config = copy_config or CopyTradeConfig.from_env()
        self.dry_run = dry_run
        
        self._client: Optional[ClobClient] = None
        self.gamma_api = GammaAPIClient()
        
        # Track executed trades
        self.executed_trades: list = []
        self.failed_trades: list = []
    
    @property
    def client(self) -> ClobClient:
        """Get authenticated CLOB client"""
        if self._client is None:
            self._client = self.auth.get_trading_client()
        return self._client
    
    def calculate_copy_size(
        self,
        original_trade: Trade,
        trader_config: Optional[TraderConfig] = None
    ) -> Tuple[float, str]:
        """
        Calculate the size to copy based on configuration
        
        Args:
            original_trade: The trade being copied
            trader_config: Optional trader-specific config
        
        Returns:
            Tuple of (size_in_usdc, reason_string)
        """
        config = self.copy_config
        
        # Check if we should copy sells
        if original_trade.side == "SELL" and not config.copy_sell:
            return 0.0, "SELL orders not copied (COPY_SELL=false)"
        
        # Check trader-specific max
        if trader_config:
            if original_trade.side == "BUY" and not trader_config.copy_buys:
                return 0.0, "BUY orders not copied for this trader"
            if original_trade.side == "SELL" and not trader_config.copy_sells:
                return 0.0, "SELL orders not copied for this trader"
        
        # Calculate size based on mode
        if config.copy_mode == CopyMode.FIXED_AMOUNT:
            size = config.amount_to_copy
            reason = f"Fixed amount: ${size:.2f}"
        else:
            # Percentage mode
            pct = config.percentage_to_copy / 100.0
            size = original_trade.usdc_size * pct
            reason = f"{config.percentage_to_copy}% of ${original_trade.usdc_size:.2f} = ${size:.2f}"
        
        # Apply min/max limits
        if size < config.min_trade_size:
            return 0.0, f"Below minimum (${size:.2f} < ${config.min_trade_size})"
        
        if size > config.max_trade_size:
            size = config.max_trade_size
            reason = f"Capped at max: ${size:.2f}"
        
        # Check trader-specific max
        if trader_config and size > trader_config.max_position_size:
            size = trader_config.max_position_size
            reason = f"Capped at trader max: ${size:.2f}"
        
        return size, reason
    
    def get_market_info(self, condition_id: str) -> Optional[Dict[str, Any]]:
        """Get market info including tick size and neg_risk flag"""
        try:
            market = self.gamma_api.get_market_by_condition_id(condition_id)
            return market
        except Exception as e:
            print(f"[Executor] Error getting market info: {e}")
            return None
    
    def execute_copy_trade(
        self,
        original_trade: Trade,
        trader_config: Optional[TraderConfig] = None
    ) -> Dict[str, Any]:
        """
        Execute a copy trade
        
        Args:
            original_trade: The trade to copy
            trader_config: Optional trader-specific config
        
        Returns:
            Dict with execution result
        """
        result = {
            "success": False,
            "original_trade": original_trade,
            "copy_size_usdc": 0,
            "order_id": None,
            "error": None,
            "reason": None
        }
        
        try:
            # Calculate copy size
            copy_size, reason = self.calculate_copy_size(original_trade, trader_config)
            result["copy_size_usdc"] = copy_size
            result["reason"] = reason
            
            if copy_size <= 0:
                print(f"[Executor] Skipping trade: {reason}")
                return result
            
            print(f"[Executor] Copying trade: {reason}")
            print(f"  Original: {original_trade}")
            
            # Get token ID directly from trade (asset_id IS the token_id)
            token_id = original_trade.token_id
            
            if not token_id:
                result["error"] = "No token ID in trade data"
                print(f"[Executor] Error: {result['error']}")
                return result
            
            print(f"[Executor] Token ID: {token_id}")
            
            # Dry run check
            if self.dry_run:
                print(f"[Executor] DRY RUN - Would execute trade")
                result["success"] = True
                result["order_id"] = "DRY_RUN"
                return result
            
            # Get market info for tick size and neg_risk
            market_info = self.get_market_info(original_trade.condition_id)
            neg_risk = False
            tick_size = "0.01"
            
            if market_info:
                tick_size = market_info.get("minimum_tick_size", "0.01")
                neg_risk = market_info.get("neg_risk", False)
                print(f"[Executor] Market info: tick_size={tick_size}, neg_risk={neg_risk}")
            
            # Calculate order parameters
            order_type = self.copy_config.order_type
            side = original_trade.side
            
            # Get current price from original trade
            current_price = original_trade.price
            
            # Adjust price based on side for better fill
            if side == "BUY":
                price = min(current_price + 0.01, 0.99)
            else:
                price = max(current_price - 0.01, 0.01)
            
            # Round price to tick size
            tick = float(tick_size)
            price = round(price / tick) * tick
            price = max(tick, min(price, 1.0 - tick))

            # ---------------------------------------------------------------
            # Polymarket decimal rules (enforced by the API):
            #   maker_amount (token size) → max 2 decimal places
            #   taker_amount (USDC cost)  → max 5 decimal places
            #
            # Strategy:
            #   1. Round size DOWN to 2 dp  → guarantees maker_amount is valid
            #   2. Verify size * price ≤ 5 dp; if not, reduce size by 0.01
            #      until the product fits (max a handful of iterations)
            # ---------------------------------------------------------------
            from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

            # Round price to 4 dp (tick sizes are 0.01 or 0.001, never more)
            price_d = Decimal(str(price)).quantize(Decimal('0.0001'), rounding=ROUND_DOWN)

            # USDC we want to spend, rounded to 2 dp
            usdc_d = Decimal(str(copy_size)).quantize(Decimal('0.01'), rounding=ROUND_DOWN)

            # Token size = USDC / price, rounded DOWN to 2 dp
            size_d = (usdc_d / price_d).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
            if size_d <= Decimal('0'):
                size_d = Decimal('0.01')

            # Ensure taker_amount (size * price) fits in 5 dp
            # Reduce size by 0.01 at a time until the product is clean
            FIVE_DP = Decimal('0.00001')
            for _ in range(10):
                taker_d = (size_d * price_d).quantize(FIVE_DP, rounding=ROUND_DOWN)
                if taker_d == size_d * price_d or abs((size_d * price_d) - taker_d) < Decimal('0.000001'):
                    break
                size_d -= Decimal('0.01')
                if size_d <= Decimal('0'):
                    size_d = Decimal('0.01')
                    break

            # Final clean values
            price_f     = float(price_d)
            size_tokens = float(size_d)
            taker_f     = float((size_d * price_d).quantize(FIVE_DP, rounding=ROUND_DOWN))

            print(f"[Executor] Order params:")
            print(f"  Token ID: {token_id}")
            print(f"  Price: {price_f:.4f}")
            print(f"  Size: {size_tokens:.2f} tokens (~${float(usdc_d):.2f})")
            print(f"  Side: {side}")
            print(f"  Order Type: {order_type}")

            # Create and post order
            if order_type == "FAK":
                # MarketOrderArgs: market order spending a fixed USDC amount (max 2 dp)
                try:
                    order_args = MarketOrderArgs(
                        token_id=token_id,
                        amount=float(usdc_d),
                        side=side
                    )
                    signed_order = self.client.create_market_order(order_args)
                    response = self.client.post_order(signed_order, OrderType.FAK)
                except Exception as e:
                    print(f"[Executor] FAK market order failed ({e}), falling back to FOK limit order")
                    order_args = OrderArgs(
                        token_id=token_id,
                        price=price_f,
                        size=size_tokens,
                        side=side
                    )
                    signed_order = self.client.create_order(order_args)
                    response = self.client.post_order(signed_order, OrderType.FOK)

            else:
                # FOK limit order — price + size with strict decimal compliance
                order_args = OrderArgs(
                    token_id=token_id,
                    price=price_f,
                    size=size_tokens,
                    side=side
                )
                signed_order = self.client.create_order(order_args)
                response = self.client.post_order(signed_order, OrderType.FOK)
            
            # Check response
            if response:
                order_id = response.get("orderID") or response.get("order_id") or response.get("id")
                result["success"] = True
                result["order_id"] = order_id
                self.executed_trades.append(result)
                
                print(f"[Executor] Order placed successfully!")
                print(f"  Order ID: {order_id}")
            else:
                result["error"] = "No response from API"
                self.failed_trades.append(result)
                print(f"[Executor] No response from API")
            
        except Exception as e:
            result["error"] = str(e)
            self.failed_trades.append(result)
            print(f"[Executor] Error executing trade: {e}")
            import traceback
            traceback.print_exc()
        
        return result
    
    def get_open_orders(self) -> list:
        """Get list of open orders"""
        try:
            return self.client.get_orders()
        except Exception as e:
            print(f"[Executor] Error getting orders: {e}")
            return []
    
    def cancel_all_orders(self) -> bool:
        """Cancel all open orders"""
        try:
            self.client.cancel_all()
            print("[Executor] Cancelled all orders")
            return True
        except Exception as e:
            print(f"[Executor] Error cancelling orders: {e}")
            return False
    
    def get_balances(self) -> Dict[str, float]:
        """Get USDC and token balances"""
        try:
            balance_info = self.client.get_balance_allowance()
            return balance_info
        except Exception as e:
            print(f"[Executor] Error getting balances: {e}")
            return {}


def test_executor():
    """Test the executor (dry run)"""
    from dotenv import load_dotenv
    load_dotenv()
    
    # Setup auth
    auth = PolymarketAuth(
        private_key=os.getenv("PRIVATE_KEY"),
        funder_address=os.getenv("FUNDER_ADDRESS"),
        signature_type=int(os.getenv("SIGNATURE_TYPE", "1"))
    )
    
    # Create executor in dry run mode
    config = CopyTradeConfig.from_env()
    executor = OrderExecutor(auth=auth, copy_config=config, dry_run=True)
    
    # Create a fake trade for testing
    fake_trade = Trade(
        trader_address="0x1234...",
        condition_id="0xtest",
        asset_id="123456789",  # This IS the token_id
        side="BUY",
        size=100,
        price=0.55,
        usdc_size=55.0,
        timestamp=int(time.time()),
        outcome="YES",
        outcome_index=0,
        title="Test Market",
        slug="test-market"
    )
    
    print("=" * 50)
    print("Testing Order Executor (Dry Run)")
    print("=" * 50)
    
    result = executor.execute_copy_trade(fake_trade)
    
    print("\nResult:")
    print(f"  Success: {result['success']}")
    print(f"  Copy Size: ${result['copy_size_usdc']:.2f}")
    print(f"  Reason: {result['reason']}")


if __name__ == "__main__":
    test_executor()