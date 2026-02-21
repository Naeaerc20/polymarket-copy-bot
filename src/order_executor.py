"""
Order Executor Module

Handles:
- Creating and posting orders to Polymarket CLOB
- Copy trade logic (amount/percentage calculations)
- Order type handling (FOK / FAK / GTC)

Order type behavior:
  FOK — Fill-Or-Kill:   executes immediately at market price or cancels entirely
  FAK — Fill-And-Kill:  executes what it can immediately, cancels remainder
  GTC — Good-Till-Cancelled: posts at EXACT original price, stays in order book
        until filled. Auto-cancels after GTC_TIMEOUT_SECONDS if not filled.
"""

import os
import time
import threading
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
from decimal import Decimal, ROUND_DOWN

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
    FIXED_AMOUNT = "fixed"
    PERCENTAGE   = "percentage"


@dataclass
class CopyTradeConfig:
    """Configuration for copy trading behavior"""
    amount_to_copy:      float           = 50.0
    percentage_to_copy:  Optional[float] = 100.0
    copy_sell:           bool            = True
    order_type:          str             = "FOK"      # FOK | FAK | GTC
    min_trade_size:      float           = 1.0
    max_trade_size:      float           = 1000.0
    gtc_timeout_seconds: int             = 60         # auto-cancel GTC after N seconds

    @classmethod
    def from_env(cls) -> "CopyTradeConfig":
        from dotenv import load_dotenv
        load_dotenv()

        pct_str    = os.getenv("PERCENTAGE_TO_COPY", "100")
        percentage = None if pct_str.lower() == "null" else float(pct_str)

        return cls(
            amount_to_copy      = float(os.getenv("AMOUNT_TO_COPY",        "50")),
            percentage_to_copy  = percentage,
            copy_sell           = os.getenv("COPY_SELL", "true").lower() == "true",
            order_type          = os.getenv("TYPE_ORDER", "FOK").upper(),
            min_trade_size      = float(os.getenv("MIN_TRADE_SIZE",         "1")),
            max_trade_size      = float(os.getenv("MAX_TRADE_SIZE",         "1000")),
            gtc_timeout_seconds = int(os.getenv("GTC_TIMEOUT_SECONDS",     "60")),
        )

    @property
    def copy_mode(self) -> CopyMode:
        if self.percentage_to_copy is None:
            return CopyMode.FIXED_AMOUNT
        return CopyMode.PERCENTAGE


# ── Decimal rounding helper ────────────────────────────────────────────────────

def _safe_order_params(price: float, copy_size: float, tick_size) -> Tuple[float, float]:
    """
    Return (price, size) guaranteed to satisfy Polymarket CLOB constraints:

        makerAmount = price * size  → MAX 2 decimal places
        takerAmount = size          → MAX 4 decimal places

    Iterates maker_cents downward from budget until price_d * size_d == maker_d
    exactly at 2dp precision. Converges within ≤ 200 steps.
    """
    tick_d  = Decimal(str(float(tick_size)))
    price_d = Decimal(str(price)).quantize(tick_d, rounding=ROUND_DOWN)
    price_d = max(Decimal("0.01"), min(price_d, Decimal("0.99")))

    budget_d     = Decimal(str(copy_size)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    budget_cents = int(budget_d * 100)

    for maker_cents in range(budget_cents, max(0, budget_cents - 200), -1):
        maker_d = Decimal(maker_cents) / Decimal("100")
        size_d  = (maker_d / price_d).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
        if size_d <= Decimal("0"):
            continue
        if (price_d * size_d).quantize(Decimal("0.01"), rounding=ROUND_DOWN) == maker_d:
            return float(price_d), float(size_d)

    size_d = (Decimal("0.01") / price_d).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
    return float(price_d), float(max(size_d, Decimal("0.0001")))


def _gtc_order_params(price: float, copy_size: float, tick_size) -> Tuple[float, float]:
    """
    Return (price, size) for a GTC order at the EXACT original price.

    Unlike _safe_order_params (which adds slippage), this snaps price to the
    nearest tick WITHOUT adding any buffer — preserving the trader's exact
    entry price.  The same 2dp/4dp decimal constraints still apply.
    """
    tick_d  = Decimal(str(float(tick_size)))
    # Snap to nearest tick (round, not floor) to stay as close as possible
    price_d = (Decimal(str(price)) / tick_d).to_integral_value(
                  rounding=ROUND_DOWN) * tick_d
    price_d = max(Decimal("0.01"), min(price_d, Decimal("0.99")))

    budget_d     = Decimal(str(copy_size)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    budget_cents = int(budget_d * 100)

    for maker_cents in range(budget_cents, max(0, budget_cents - 200), -1):
        maker_d = Decimal(maker_cents) / Decimal("100")
        size_d  = (maker_d / price_d).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
        if size_d <= Decimal("0"):
            continue
        if (price_d * size_d).quantize(Decimal("0.01"), rounding=ROUND_DOWN) == maker_d:
            return float(price_d), float(size_d)

    size_d = (Decimal("0.01") / price_d).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
    return float(price_d), float(max(size_d, Decimal("0.0001")))


# ── Order Executor ─────────────────────────────────────────────────────────────

class OrderExecutor:
    """
    Executes copy trades on Polymarket.

    Supported order types:
      FOK — immediate fill at market price or full cancel
      FAK — fill as much as possible immediately, cancel rest
      GTC — post at exact original price; auto-cancel after GTC_TIMEOUT_SECONDS
    """

    def __init__(
        self,
        auth:        PolymarketAuth,
        copy_config: Optional[CopyTradeConfig] = None,
        dry_run:     bool = False,
    ):
        self.auth        = auth
        self.copy_config = copy_config or CopyTradeConfig.from_env()
        self.dry_run     = dry_run

        self._client: Optional[ClobClient] = None
        self.gamma_api = GammaAPIClient()

        self.executed_trades: list = []
        self.failed_trades:   list = []

        # Track open GTC orders for timeout management: {order_id: cancel_timer}
        self._gtc_timers: Dict[str, threading.Timer] = {}

    @property
    def client(self) -> ClobClient:
        if self._client is None:
            self._client = self.auth.get_trading_client()
        return self._client

    # ── Size calculator ────────────────────────────────────────────────────────

    def calculate_copy_size(
        self,
        original_trade: Trade,
        trader_config:  Optional[TraderConfig] = None,
    ) -> Tuple[float, str]:
        config = self.copy_config

        if original_trade.side == "SELL" and not config.copy_sell:
            return 0.0, "SELL orders not copied (COPY_SELL=false)"

        if trader_config:
            if original_trade.side == "BUY"  and not trader_config.copy_buys:
                return 0.0, "BUY orders not copied for this trader"
            if original_trade.side == "SELL" and not trader_config.copy_sells:
                return 0.0, "SELL orders not copied for this trader"

        if config.copy_mode == CopyMode.FIXED_AMOUNT:
            size   = config.amount_to_copy
            reason = f"Fixed amount: ${size:.2f}"
        else:
            pct    = config.percentage_to_copy / 100.0
            size   = original_trade.usdc_size * pct
            reason = f"{config.percentage_to_copy}% of ${original_trade.usdc_size:.2f} = ${size:.2f}"

        if size < config.min_trade_size:
            return 0.0, f"Below minimum (${size:.2f} < ${config.min_trade_size})"

        if size > config.max_trade_size:
            size   = config.max_trade_size
            reason = f"Capped at max: ${size:.2f}"

        if trader_config and size > trader_config.max_position_size:
            size   = trader_config.max_position_size
            reason = f"Capped at trader max: ${size:.2f}"

        return size, reason

    # ── Market info ────────────────────────────────────────────────────────────

    def get_market_info(self, condition_id: str) -> Optional[Dict[str, Any]]:
        try:
            return self.gamma_api.get_market_by_condition_id(condition_id)
        except Exception as e:
            print(f"[Executor] Error getting market info: {e}")
            return None

    # ── GTC timeout / auto-cancel ──────────────────────────────────────────────

    def _schedule_gtc_cancel(self, order_id: str, timeout: int) -> None:
        """
        Schedule an automatic cancel for a GTC order after `timeout` seconds.
        Runs in a background thread so it never blocks the main loop.
        """
        def _cancel():
            print(f"[Executor][GTC] Timeout reached for order {order_id} — cancelling...")
            try:
                self.client.cancel(order_id)
                print(f"[Executor][GTC] Order {order_id} cancelled successfully.")
            except Exception as e:
                print(f"[Executor][GTC] Cancel failed for {order_id}: {e}")
            finally:
                self._gtc_timers.pop(order_id, None)

        timer = threading.Timer(timeout, _cancel)
        timer.daemon = True
        timer.start()
        self._gtc_timers[order_id] = timer
        print(f"[Executor][GTC] Auto-cancel scheduled in {timeout}s for order {order_id}")

    def cancel_gtc_order(self, order_id: str) -> bool:
        """Manually cancel a GTC order and clear its timer."""
        timer = self._gtc_timers.pop(order_id, None)
        if timer:
            timer.cancel()
        try:
            self.client.cancel(order_id)
            print(f"[Executor][GTC] Manually cancelled order {order_id}")
            return True
        except Exception as e:
            print(f"[Executor][GTC] Manual cancel failed for {order_id}: {e}")
            return False

    def cancel_all_gtc_orders(self) -> None:
        """Cancel all pending GTC orders and their timers."""
        for order_id in list(self._gtc_timers.keys()):
            self.cancel_gtc_order(order_id)

    # ── Order placement ────────────────────────────────────────────────────────

    def _place_fok_order(
        self, token_id: str, price_f: float, size_tokens: float, side: str
    ) -> Any:
        args   = OrderArgs(token_id=token_id, price=price_f, size=size_tokens, side=side)
        signed = self.client.create_order(args)
        return self.client.post_order(signed, OrderType.FOK)

    def _place_fak_order(
        self, token_id: str, price_f: float, size_tokens: float,
        side: str, copy_size: float
    ) -> Any:
        try:
            margs  = MarketOrderArgs(
                token_id = token_id,
                amount   = float(Decimal(str(copy_size)).quantize(
                               Decimal("0.01"), rounding=ROUND_DOWN)),
                side     = side,
            )
            signed = self.client.create_market_order(margs)
            return self.client.post_order(signed, OrderType.FAK)
        except Exception as fak_err:
            print(f"[Executor] FAK MarketOrderArgs failed ({fak_err}) — falling back to FOK")
            return self._place_fok_order(token_id, price_f, size_tokens, side)

    def _place_gtc_order(
        self, token_id: str, price_f: float, size_tokens: float, side: str
    ) -> Any:
        """
        Post a GTC limit order at the exact price.
        Returns the API response dict (contains order_id for timeout tracking).
        """
        args   = OrderArgs(token_id=token_id, price=price_f, size=size_tokens, side=side)
        signed = self.client.create_order(args)
        return self.client.post_order(signed, OrderType.GTC)

    # ── Main execute method ────────────────────────────────────────────────────

    def execute_copy_trade(
        self,
        original_trade: Trade,
        trader_config:  Optional[TraderConfig] = None,
    ) -> Dict[str, Any]:
        """
        Execute a copy trade using the configured order type (FOK / FAK / GTC).

        GTC specifics:
          - Uses the trader's EXACT price (no slippage added)
          - Order stays in the book until filled or timeout expires
          - Auto-cancels after GTC_TIMEOUT_SECONDS (default: 60s)

        Returns:
            Dict with keys: success, original_trade, copy_size_usdc,
                            order_id, error, reason, order_type
        """
        result = {
            "success":        False,
            "original_trade": original_trade,
            "copy_size_usdc": 0,
            "order_id":       None,
            "error":          None,
            "reason":         None,
            "order_type":     self.copy_config.order_type,
        }

        try:
            # ── 1. Calculate copy size ────────────────────────────────────
            copy_size, reason = self.calculate_copy_size(original_trade, trader_config)
            result["copy_size_usdc"] = copy_size
            result["reason"]         = reason

            if copy_size <= 0:
                print(f"[Executor] Skipping trade: {reason}")
                return result

            print(f"[Executor] Copying trade: {reason}")
            print(f"  Original: {original_trade}")

            # ── 2. Token ID ───────────────────────────────────────────────
            token_id = original_trade.token_id
            if not token_id:
                result["error"] = "No token ID in trade data"
                print(f"[Executor] Error: {result['error']}")
                return result

            print(f"[Executor] Token ID: {token_id}")

            # ── 3. Dry-run guard ──────────────────────────────────────────
            if self.dry_run:
                print("[Executor] DRY RUN - Would execute trade")
                result["success"]  = True
                result["order_id"] = "DRY_RUN"
                return result

            # ── 4. Market info ────────────────────────────────────────────
            market_info = self.get_market_info(original_trade.condition_id)
            tick_size   = "0.01"
            neg_risk    = False

            if market_info:
                tick_size = market_info.get("minimum_tick_size", "0.01")
                neg_risk  = market_info.get("neg_risk", False)
                print(f"[Executor] Market info: tick_size={tick_size}, neg_risk={neg_risk}")

            # ── 5. Price & size calculation (varies by order type) ────────
            order_type_str = self.copy_config.order_type   # FOK | FAK | GTC
            side           = original_trade.side
            raw_price      = original_trade.price
            tick           = float(tick_size)

            if order_type_str == "GTC":
                # ── GTC: use EXACT original price, no slippage ────────────
                price_f, size_tokens = _gtc_order_params(raw_price, copy_size, tick_size)

            else:
                # ── FOK / FAK: add slippage buffer for better fill chance ─
                if side == "BUY":
                    slippage_price = min(raw_price + 0.01, 0.99)
                else:
                    slippage_price = max(raw_price - 0.01, 0.01)

                snapped  = round(round(slippage_price / tick) * tick, 10)
                snapped  = max(tick, min(snapped, 1.0 - tick))
                price_f, size_tokens = _safe_order_params(snapped, copy_size, tick_size)

            print(f"[Executor] Order params:")
            print(f"  Token ID   : {token_id}")
            print(f"  Price      : {price_f:.4f}"
                  + (" (exact — no slippage)" if order_type_str == "GTC" else " (+slippage)"))
            print(f"  Size       : {size_tokens:.4f} tokens (~${price_f * size_tokens:.2f})")
            print(f"  Side       : {side}")
            print(f"  Order Type : {order_type_str}")

            # ── 6. Place order ────────────────────────────────────────────
            if order_type_str == "GTC":
                response = self._place_gtc_order(token_id, price_f, size_tokens, side)
            elif order_type_str == "FAK":
                response = self._place_fak_order(
                    token_id, price_f, size_tokens, side, copy_size)
            else:
                response = self._place_fok_order(token_id, price_f, size_tokens, side)

            # ── 7. Handle response ────────────────────────────────────────
            if response:
                order_id = (
                    response.get("orderID")
                    or response.get("order_id")
                    or response.get("id")
                )
                result["success"]  = True
                result["order_id"] = order_id
                self.executed_trades.append(result)
                print(f"[Executor] Order placed successfully! ID: {order_id}")

                # GTC: schedule auto-cancel timer
                if order_type_str == "GTC" and order_id:
                    self._schedule_gtc_cancel(
                        order_id,
                        self.copy_config.gtc_timeout_seconds,
                    )
            else:
                result["error"] = "No response from API"
                self.failed_trades.append(result)
                print("[Executor] No response from API")

        except Exception as e:
            result["error"] = str(e)
            self.failed_trades.append(result)
            print(f"[Executor] Error executing trade: {e}")
            import traceback
            traceback.print_exc()

        return result

    # ── Utility methods ────────────────────────────────────────────────────────

    def get_open_orders(self) -> list:
        try:
            return self.client.get_orders()
        except Exception as e:
            print(f"[Executor] Error getting orders: {e}")
            return []

    def cancel_all_orders(self) -> bool:
        try:
            self.cancel_all_gtc_orders()   # clear GTC timers first
            self.client.cancel_all()
            print("[Executor] Cancelled all orders")
            return True
        except Exception as e:
            print(f"[Executor] Error cancelling orders: {e}")
            return False

    def get_balances(self) -> Dict[str, float]:
        try:
            return self.client.get_balance_allowance()
        except Exception as e:
            print(f"[Executor] Error getting balances: {e}")
            return {}


# ── Smoke-test ─────────────────────────────────────────────────────────────────

def test_executor():
    from dotenv import load_dotenv
    load_dotenv()

    auth = PolymarketAuth(
        private_key    = os.getenv("PRIVATE_KEY"),
        funder_address = os.getenv("FUNDER_ADDRESS"),
        signature_type = int(os.getenv("SIGNATURE_TYPE", "1")),
    )

    config   = CopyTradeConfig.from_env()
    executor = OrderExecutor(auth=auth, copy_config=config, dry_run=True)

    fake_trade = Trade(
        trader_address = "0x1234...",
        condition_id   = "0xtest",
        asset_id       = "123456789",
        side           = "BUY",
        size           = 58.99,
        price          = 0.48,
        usdc_size      = 28.31,
        timestamp      = int(time.time()),
        outcome        = "Up",
        outcome_index  = 0,
        title          = "Ethereum Up or Down - Test",
        slug           = "eth-updown-test",
    )

    print("=" * 50)
    print("Testing Order Executor (Dry Run)")
    print("=" * 50)

    result = executor.execute_copy_trade(fake_trade)

    print("\nResult:")
    print(f"  Success    : {result['success']}")
    print(f"  Copy Size  : ${result['copy_size_usdc']:.2f}")
    print(f"  Order Type : {result['order_type']}")
    print(f"  Reason     : {result['reason']}")


if __name__ == "__main__":
    test_executor()