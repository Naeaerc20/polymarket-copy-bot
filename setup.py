#!/usr/bin/env python3
"""
Polymarket Copy Trading Bot - Setup Wizard

This script will:
1. Collect your credentials (private key, funder address)
2. Generate/derive API credentials from Polymarket
3. Save everything to .env file
4. Validate traders configuration
5. Test the complete setup
"""

import os
import sys
import json
import time
import getpass
from pathlib import Path
from typing import Optional, Dict, Any

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds
except ImportError:
    print("Installing py-clob-client...")
    os.system("pip install py-clob-client -q")
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds

try:
    import requests
except ImportError:
    print("Installing requests...")
    os.system("pip install requests -q")
    import requests


class Colors:
    """Terminal colors for pretty output"""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'


def print_header(text: str):
    """Print a formatted header"""
    width = 60
    print()
    print(f"{Colors.CYAN}{'=' * width}{Colors.END}")
    print(f"{Colors.CYAN}║{Colors.BOLD}{text.center(width - 2)}{Colors.END}{Colors.CYAN}║{Colors.END}")
    print(f"{Colors.CYAN}{'=' * width}{Colors.END}")
    print()


def print_step(step: int, total: int, text: str):
    """Print a step indicator"""
    print(f"\n{Colors.BLUE}[{step}/{total}] {text}{Colors.END}")
    print("-" * 50)


def print_success(text: str):
    print(f"{Colors.GREEN}✓ {text}{Colors.END}")


def print_error(text: str):
    print(f"{Colors.RED}✗ {text}{Colors.END}")


def print_warning(text: str):
    print(f"{Colors.YELLOW}⚠ {text}{Colors.END}")


def print_info(text: str):
    print(f"  {text}")


def validate_private_key(key: str) -> bool:
    """Validate private key format"""
    if not key:
        return False
    if key.startswith('0x'):
        key = key[2:]
    return len(key) == 64 and all(c in '0123456789abcdefABCDEF' for c in key)


def validate_address(address: str) -> bool:
    """Validate Ethereum address format"""
    if not address:
        return False
    if address.startswith('0x'):
        address = address[2:]
    return len(address) == 40 and all(c in '0123456789abcdefABCDEF' for c in address)


def get_wallet_info(funder_address: str) -> Dict[str, Any]:
    """Get wallet info from Polymarket Data API"""
    try:
        resp = requests.get(
            "https://data-api.polymarket.com/portfolio",
            params={"user": funder_address},
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return {}


def get_usdc_balance(funder_address: str) -> Optional[float]:
    """Get USDC balance from Polymarket"""
    try:
        resp = requests.get(
            "https://data-api.polymarket.com/collaterals",
            params={"user": funder_address},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                for item in data:
                    if item.get("asset") == "USDC" or item.get("symbol") == "USDC":
                        return float(item.get("balance", 0))
                # Try first item if no USDC found
                return float(data[0].get("balance", 0))
    except Exception:
        pass
    return None


def derive_api_credentials(
    private_key: str,
    funder_address: str,
    signature_type: int = 1
) -> Optional[ApiCreds]:
    """
    Derive API credentials from Polymarket using L1 auth
    
    Args:
        private_key: Wallet private key (with or without 0x)
        funder_address: Proxy wallet address
        signature_type: 0=EOA, 1=POLY_PROXY, 2=GNOSIS_SAFE
    
    Returns:
        ApiCreds object or None on failure
    """
    try:
        # Ensure proper format
        if not private_key.startswith('0x'):
            private_key = '0x' + private_key
        if not funder_address.startswith('0x'):
            funder_address = '0x' + funder_address
        
        print_info("Connecting to Polymarket CLOB...")
        
        # Create client with L1 auth
        client = ClobClient(
            host="https://clob.polymarket.com",
            key=private_key,
            chain_id=137,
            signature_type=signature_type,
            funder=funder_address
        )
        
        print_info("Deriving API credentials...")
        
        # Try derive first (for existing accounts)
        try:
            creds = client.derive_api_key()
            print_success("Credentials derived successfully!")
            return creds
        except Exception as derive_err:
            print_info(f"Derive failed: {derive_err}")
            print_info("Trying to create new credentials...")
            
            # Try create if derive fails
            try:
                creds = client.create_api_key()
                print_success("New credentials created successfully!")
                return creds
            except Exception as create_err:
                # Try create_or_derive_api_creds if available
                if hasattr(client, 'create_or_derive_api_creds'):
                    creds = client.create_or_derive_api_creds()
                    print_success("Credentials obtained successfully!")
                    return creds
                else:
                    raise create_err
                    
    except Exception as e:
        print_error(f"Failed to derive credentials: {e}")
        return None


def test_credentials(
    private_key: str,
    funder_address: str,
    creds: ApiCreds,
    signature_type: int
) -> bool:
    """Test that credentials work for trading"""
    try:
        # Ensure proper format
        if not private_key.startswith('0x'):
            private_key = '0x' + private_key
        if not funder_address.startswith('0x'):
            funder_address = '0x' + funder_address
        
        client = ClobClient(
            host="https://clob.polymarket.com",
            key=private_key,
            chain_id=137,
            creds=creds,
            signature_type=signature_type,
            funder=funder_address
        )
        
        # Test API connectivity
        server_time = client.get_server_time()
        print_success(f"Connected to CLOB server")
        
        # Try getting API info
        try:
            api_keys = client.get_api_keys()
            print_success(f"API key verified: {creds.api_key[:16]}...")
        except:
            pass
        
        return True
        
    except Exception as e:
        print_error(f"Credential test failed: {e}")
        return False


def create_env_file(
    private_key: str,
    funder_address: str,
    creds: ApiCreds,
    signature_type: int,
    config: Dict[str, Any]
) -> bool:
    """Create .env file with all configuration"""
    try:
        env_path = Path(__file__).parent / ".env"
        
        # Ensure proper format
        if not private_key.startswith('0x'):
            private_key = '0x' + private_key
        if not funder_address.startswith('0x'):
            funder_address = '0x' + funder_address
        
        content = f'''# ========================================
# Polymarket Copy Trading Bot Configuration
# ========================================
# Generated by setup.py on {time.strftime("%Y-%m-%d %H:%M:%S")}
#
# WARNING: NEVER share this file or commit to git!
# ========================================

# === WALLET CREDENTIALS ===
# Your wallet private key (keep secret!)
PRIVATE_KEY={private_key}

# Your Polymarket proxy wallet address
# (The address shown on your Polymarket portfolio page)
FUNDER_ADDRESS={funder_address}

# Signature type:
# 0 = EOA (MetaMask standard wallet)
# 1 = POLY_PROXY (Email/Google login - most common)
# 2 = GNOSIS_SAFE (Gnosis Safe multisig)
SIGNATURE_TYPE={signature_type}

# === API CREDENTIALS (Auto-generated) ===
# These were derived from your private key
POLY_API_KEY={creds.api_key}
POLY_API_SECRET={creds.api_secret}
POLY_API_PASSPHRASE={creds.api_passphrase}

# === COPY TRADING SETTINGS ===
# Amount in USDC to copy per trade (used if PERCENTAGE_TO_COPY is null)
AMOUNT_TO_COPY={config.get("amount_to_copy", 50)}

# Copy sell orders? (true/false)
COPY_SELL={str(config.get("copy_sell", True)).lower()}

# Percentage of original trade to copy (1-100)
# Set to "null" to use fixed AMOUNT_TO_COPY instead
PERCENTAGE_TO_COPY={config.get("percentage_to_copy", 100)}

# Order type:
# FOK = Fill or Kill (limit order, must fill completely)
# FAK = Fill and Kill (market order, partial fills allowed)
TYPE_ORDER={config.get("order_type", "FOK")}

# Minimum trade size in USDC
MIN_TRADE_SIZE={config.get("min_trade_size", 10)}

# Maximum trade size in USDC  
MAX_TRADE_SIZE={config.get("max_trade_size", 1000)}

# === MONITORING SETTINGS ===
# Poll interval in seconds (how often to check for new trades)
POLL_INTERVAL={config.get("poll_interval", 5)}

# === LOGGING ===
# Log to file
LOG_TO_FILE=true

# Log level: DEBUG, INFO, WARNING, ERROR
LOG_LEVEL=INFO

# === NOTIFICATIONS (Optional) ===
# Discord webhook URL (leave empty to disable)
DISCORD_WEBHOOK_URL=

# Telegram bot token (leave empty to disable)
TELEGRAM_BOT_TOKEN=

# Telegram chat ID (leave empty to disable)
TELEGRAM_CHAT_ID=
'''
        
        with open(env_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        # Set restrictive permissions
        try:
            os.chmod(env_path, 0o600)
        except:
            pass  # Windows doesn't support chmod the same way
        
        return True
        
    except Exception as e:
        print_error(f"Failed to create .env file: {e}")
        return False


def validate_traders_config() -> bool:
    """Validate the traders.json configuration"""
    traders_path = Path(__file__).parent / "config" / "traders.json"
    
    if not traders_path.exists():
        print_warning("No traders.json found. Creating template...")
        create_traders_template()
        return False
    
    try:
        with open(traders_path, 'r') as f:
            data = json.load(f)
        
        traders = data.get("traders", [])
        enabled_count = sum(1 for t in traders if t.get("enabled", True))
        
        print_info(f"Found {len(traders)} traders, {enabled_count} enabled")
        
        # Validate each trader
        for i, trader in enumerate(traders):
            address = trader.get("address", "")
            if not validate_address(address):
                print_warning(f"Trader {i+1}: Invalid address format")
            
        return enabled_count > 0
        
    except Exception as e:
        print_error(f"Error reading traders.json: {e}")
        return False


def create_traders_template():
    """Create a template traders.json file"""
    config_dir = Path(__file__).parent / "config"
    config_dir.mkdir(exist_ok=True)
    
    template = {
        "traders": [
            {
                "address": "0x_REPLACE_WITH_TRADER_ADDRESS",
                "nickname": "Trader Example",
                "enabled": False,
                "copy_buys": True,
                "copy_sells": True,
                "max_position_size": 500,
                "notes": "Find traders on polymarket.com/leaderboard"
            }
        ],
        "settings": {
            "max_concurrent_trades": 5,
            "stop_on_error": False
        }
    }
    
    traders_path = config_dir / "traders.json"
    with open(traders_path, 'w') as f:
        json.dump(template, f, indent=2)
    
    print_info(f"Created template at config/traders.json")


def interactive_setup() -> Dict[str, Any]:
    """Run interactive setup wizard"""
    print_header("POLYMARKET COPY TRADING BOT SETUP")
    
    print(f"""
{Colors.BOLD}This wizard will help you configure the bot.{Colors.END}

You will need:
  1. Your Polymarket private key
  2. Your Polymarket proxy wallet address
  
{Colors.YELLOW}⚠ Your private key is NEVER sent to any server except Polymarket.{Colors.END}
{Colors.YELLOW}⚠ All credentials are stored locally in .env file.{Colors.END}
""")
    
    total_steps = 5
    
    # Step 1: Collect wallet info
    print_step(1, total_steps, "WALLET CREDENTIALS")
    
    print("""
{Colors.BOLD}How to find your credentials:{Colors.END}
1. Go to polymarket.com and log in
2. Go to Settings → API (or portfolio page)
3. Your proxy address is shown there
4. For private key: Export from your wallet (MetaMask, etc.)
   - If you signed up with Email/Google, check Polymarket settings

{Colors.CYAN}Signature Types:{Colors.END}
  0 = EOA (MetaMask wallet)
  1 = POLY_PROXY (Email/Google login) ← Most common
  2 = GNOSIS_SAFE (Gnosis Safe multisig)
""".format(Colors=Colors))
    
    # Get private key
    while True:
        private_key = getpass.getpass(f"\n{Colors.BOLD}Enter your private key (hidden):{Colors.END} ")
        if validate_private_key(private_key):
            print_success("Private key format valid")
            break
        print_error("Invalid private key format. Should be 64 hex chars (with or without 0x)")
    
    # Get funder address
    while True:
        funder_address = input(f"\n{Colors.BOLD}Enter your proxy wallet address:{Colors.END} ").strip()
        if validate_address(funder_address):
            print_success("Address format valid")
            break
        print_error("Invalid address format. Should be 40 hex chars (with or without 0x)")
    
    # Get signature type
    print(f"\n{Colors.BOLD}Signature Type:{Colors.END}")
    print("  1 - POLY_PROXY (Email/Google login) [DEFAULT]")
    print("  0 - EOA (MetaMask)")
    print("  2 - GNOSIS_SAFE")
    
    sig_input = input(f"\n{Colors.BOLD}Enter signature type [1]:{Colors.END} ").strip()
    signature_type = int(sig_input) if sig_input in ['0', '1', '2'] else 1
    print_info(f"Using signature type: {signature_type}")
    
    # Step 2: Verify wallet
    print_step(2, total_steps, "WALLET VERIFICATION")
    
    print_info("Checking wallet on Polymarket...")
    balance = get_usdc_balance(funder_address)
    if balance is not None:
        print_success(f"Wallet found! USDC balance: ${balance:.2f}")
    else:
        print_warning("Could not verify balance (may need deposit)")
    
    # Step 3: Generate API credentials
    print_step(3, total_steps, "GENERATING API CREDENTIALS")
    
    creds = derive_api_credentials(private_key, funder_address, signature_type)
    
    if not creds:
        print_error("Failed to generate credentials. Please check your inputs.")
        return None
    
    print_success(f"API Key: {creds.api_key[:20]}...")
    print_success(f"API Secret: {creds.api_secret[:10]}...")
    print_success(f"Passphrase: {creds.api_passphrase[:10]}...")
    
    # Step 4: Test credentials
    print_step(4, total_steps, "TESTING CREDENTIALS")
    
    if test_credentials(private_key, funder_address, creds, signature_type):
        print_success("Credentials verified and working!")
    else:
        print_warning("Credentials generated but test failed")
        proceed = input("Continue anyway? [y/N]: ").strip().lower()
        if proceed != 'y':
            return None
    
    # Step 5: Copy trading config
    print_step(5, total_steps, "COPY TRADING SETTINGS")
    
    config = {}
    
    # Amount to copy
    amount_input = input(f"Fixed amount per trade in USDC [50]: ").strip()
    config["amount_to_copy"] = float(amount_input) if amount_input else 50
    
    # Percentage
    pct_input = input(f"Percentage of trade to copy (1-100, or 'null' for fixed) [100]: ").strip()
    if pct_input.lower() == 'null':
        config["percentage_to_copy"] = "null"
    else:
        config["percentage_to_copy"] = float(pct_input) if pct_input else 100
    
    # Copy sells
    sell_input = input(f"Copy sell orders? [Y/n]: ").strip().lower()
    config["copy_sell"] = sell_input != 'n'
    
    # Order type
    print(f"\n{Colors.BOLD}Order Type:{Colors.END}")
    print("  FOK - Fill or Kill (limit order, complete fill only)")
    print("  FAK - Fill and Kill (market order, partial fill allowed)")
    order_input = input(f"Order type [FOK]: ").strip().upper()
    config["order_type"] = order_input if order_input in ['FOK', 'FAK'] else 'FOK'
    
    # Poll interval
    poll_input = input(f"Poll interval in seconds [5]: ").strip()
    config["poll_interval"] = int(poll_input) if poll_input else 5
    
    # Min/Max
    min_input = input(f"Minimum trade size USDC [10]: ").strip()
    config["min_trade_size"] = float(min_input) if min_input else 10
    
    max_input = input(f"Maximum trade size USDC [1000]: ").strip()
    config["max_trade_size"] = float(max_input) if max_input else 1000
    
    return {
        "private_key": private_key,
        "funder_address": funder_address,
        "signature_type": signature_type,
        "creds": creds,
        "config": config
    }


def non_interactive_setup(
    private_key: str,
    funder_address: str,
    signature_type: int = 1
) -> bool:
    """Non-interactive setup using provided credentials"""
    print_header("POLYMARKET COPY TRADING BOT SETUP")
    print("Running in non-interactive mode...\n")
    
    # Validate inputs
    if not validate_private_key(private_key):
        print_error("Invalid private key format")
        return False
    
    if not validate_address(funder_address):
        print_error("Invalid funder address format")
        return False
    
    # Derive credentials
    creds = derive_api_credentials(private_key, funder_address, signature_type)
    
    if not creds:
        print_error("Failed to derive credentials")
        return False
    
    print_success(f"API Key: {creds.api_key[:20]}...")
    
    # Test credentials
    if not test_credentials(private_key, funder_address, creds, signature_type):
        print_warning("Credential test failed")
    
    # Create .env with defaults
    config = {
        "amount_to_copy": 50,
        "percentage_to_copy": 100,
        "copy_sell": True,
        "order_type": "FOK",
        "poll_interval": 5,
        "min_trade_size": 10,
        "max_trade_size": 1000
    }
    
    if create_env_file(private_key, funder_address, creds, signature_type, config):
        print_success(".env file created successfully")
        return True
    
    return False


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Polymarket Copy Trading Bot Setup")
    parser.add_argument("--private-key", help="Private key (non-interactive)")
    parser.add_argument("--funder-address", help="Funder address (non-interactive)")
    parser.add_argument("--signature-type", type=int, default=1, help="Signature type (0, 1, or 2)")
    parser.add_argument("--skip-traders", action="store_true", help="Skip traders config validation")
    args = parser.parse_args()
    
    # Check for existing .env
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        print_warning("Found existing .env file")
        overwrite = input("Overwrite? [y/N]: ").strip().lower()
        if overwrite != 'y':
            print_info("Setup cancelled")
            return
    
    # Run setup
    if args.private_key and args.funder_address:
        # Non-interactive mode
        success = non_interactive_setup(
            args.private_key,
            args.funder_address,
            args.signature_type
        )
    else:
        # Interactive mode
        result = interactive_setup()
        
        if result is None:
            print_error("\nSetup failed!")
            sys.exit(1)
        
        # Create .env file
        if create_env_file(
            result["private_key"],
            result["funder_address"],
            result["creds"],
            result["signature_type"],
            result["config"]
        ):
            print_success(".env file created successfully!")
            success = True
        else:
            success = False
    
    if success:
        # Validate traders config
        if not args.skip_traders:
            print()
            print_header("TRADERS CONFIGURATION")
            
            if validate_traders_config():
                print_success("Traders configuration valid")
            else:
                print_warning("Please edit config/traders.json to add traders")
        
        # Final success message
        print_header("SETUP COMPLETE!")
        
        print(f"""
{Colors.GREEN}✓ Configuration saved to .env{Colors.END}
{Colors.GREEN}✓ API credentials generated{Colors.END}
{Colors.GREEN}✓ Ready to run the bot{Colors.END}

{Colors.BOLD}Next steps:{Colors.END}
1. Edit config/traders.json to add traders to follow
   - Find traders at: polymarket.com/leaderboard
   
2. Test with dry-run mode:
   {Colors.CYAN}python main.py --dry-run{Colors.END}
   
3. Run for real:
   {Colors.CYAN}python main.py{Colors.END}

{Colors.YELLOW}⚠ Remember: Never share your .env file!{Colors.END}
""")
    else:
        print_error("\nSetup failed. Please check your credentials and try again.")
        sys.exit(1)


if __name__ == "__main__":
    main()
