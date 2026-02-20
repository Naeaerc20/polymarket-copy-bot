#!/usr/bin/env python3
"""
Quick setup script for the Polymarket Copy Trading Bot

This script helps you:
1. Create .env file from template
2. Add traders from leaderboard
3. Verify configuration
"""

import os
import sys
import json
import shutil
from pathlib import Path
import requests


def create_env_file():
    """Create .env file from template"""
    env_path = Path(".env")
    example_path = Path(".env.example")
    
    if env_path.exists():
        print("⚠️  .env file already exists")
        return False
    
    if example_path.exists():
        shutil.copy(example_path, env_path)
        print("✓ Created .env file from template")
        print("  Please edit .env and add your credentials")
        return True
    else:
        print("✗ .env.example not found")
        return False


def fetch_leaderboard_traders(limit=20):
    """Fetch top traders from leaderboard"""
    print(f"\nFetching top {limit} traders from Polymarket...")
    
    try:
        response = requests.get(
            "https://data-api.polymarket.com/leaderboard",
            params={"limit": limit, "sortBy": "pnl", "timeFrame": "30d"}
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"✗ Error fetching leaderboard: {e}")
        return []


def display_traders(traders):
    """Display traders in a table"""
    print("\n" + "=" * 80)
    print(f"{'#':<4} {'Address':<44} {'PnL (30d)':<15} {'Volume':<15}")
    print("=" * 80)
    
    for i, trader in enumerate(traders[:20]):
        addr = trader.get("address", trader.get("proxyWallet", ""))
        pnl = trader.get("pnl", trader.get("totalPnl", 0))
        vol = trader.get("volume", trader.get("totalVolume", 0))
        
        print(f"{i+1:<4} {addr:<44} ${pnl:>12,.2f} ${vol:>12,.2f}")
    
    print("=" * 80)


def create_traders_config(traders, selected_indices=None):
    """Create traders.json with selected traders"""
    config_path = Path("config/traders.json")
    
    if selected_indices is None:
        # Default to top 3
        selected_indices = [0, 1, 2]
    
    selected = [traders[i] for i in selected_indices if i < len(traders)]
    
    traders_config = []
    for trader in selected:
        addr = trader.get("address", trader.get("proxyWallet", ""))
        pnl = trader.get("pnl", trader.get("totalPnl", 0))
        
        traders_config.append({
            "address": addr,
            "nickname": f"TopTrader_{addr[:8]}",
            "enabled": False,  # Disabled by default for safety
            "copy_buys": True,
            "copy_sells": True,
            "max_position_size": 100,
            "notes": f"PnL 30d: ${pnl:,.2f}"
        })
    
    config = {
        "traders": traders_config,
        "global_settings": {
            "enabled": True,
            "copy_delay_seconds": 1,
            "max_concurrent_trades": 3,
            "stop_on_error": False,
            "notification_webhook": None
        }
    }
    
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    
    print(f"\n✓ Created config/traders.json with {len(traders_config)} traders")
    print("  Traders are DISABLED by default for safety")
    print("  Edit config/traders.json to enable them")


def verify_configuration():
    """Verify the configuration is ready"""
    print("\n" + "=" * 50)
    print("VERIFICATION")
    print("=" * 50)
    
    issues = []
    
    # Check .env
    if not Path(".env").exists():
        issues.append("Missing .env file")
    else:
        # Check required fields
        from dotenv import load_dotenv
        load_dotenv()
        
        if not os.getenv("PRIVATE_KEY"):
            issues.append("PRIVATE_KEY not set in .env")
        if not os.getenv("FUNDER_ADDRESS"):
            issues.append("FUNDER_ADDRESS not set in .env")
    
    # Check traders.json
    if not Path("config/traders.json").exists():
        issues.append("Missing config/traders.json")
    else:
        with open("config/traders.json") as f:
            config = json.load(f)
        
        enabled = [t for t in config.get("traders", []) if t.get("enabled")]
        if not enabled:
            issues.append("No traders enabled in config/traders.json")
    
    if issues:
        print("\n⚠️  Issues found:")
        for issue in issues:
            print(f"  - {issue}")
        return False
    else:
        print("\n✓ Configuration looks good!")
        return True


def main():
    print("""
╔═══════════════════════════════════════════════════════════╗
║     POLYMARKET COPY TRADING BOT - SETUP WIZARD           ║
╚═══════════════════════════════════════════════════════════╝
""")
    
    # Step 1: Create .env
    print("\n[Step 1] Setting up environment...")
    create_env_file()
    
    # Step 2: Fetch and display leaderboard
    print("\n[Step 2] Fetching top traders...")
    traders = fetch_leaderboard_traders(20)
    
    if traders:
        display_traders(traders)
        
        # Ask user which traders to add
        print("\nWould you like to add traders to your config?")
        print("Enter numbers separated by commas (e.g., 1,2,5) or 'all' for top 5")
        print("Press Enter to skip")
        
        try:
            selection = input("> ").strip()
            
            if selection.lower() == "all" or selection == "":
                indices = [0, 1, 2, 3, 4] if selection.lower() == "all" else []
            else:
                indices = [int(x.strip()) - 1 for x in selection.split(",")]
            
            if indices:
                create_traders_config(traders, indices)
        except (ValueError, KeyboardInterrupt):
            print("\nSkipping trader selection")
    
    # Step 3: Verify
    print("\n[Step 3] Verifying configuration...")
    verify_configuration()
    
    # Final instructions
    print("""
╔═══════════════════════════════════════════════════════════╗
║                    NEXT STEPS                            ║
╚═══════════════════════════════════════════════════════════╝

1. Edit .env file with your credentials:
   - PRIVATE_KEY: Your wallet private key
   - FUNDER_ADDRESS: Your Polymarket proxy address

2. Edit config/traders.json:
   - Set "enabled": true for traders you want to follow
   - Adjust max_position_size as needed

3. Run the bot in dry-run mode first:
   python main.py --dry-run

4. When ready, run for real:
   python main.py

⚠️  IMPORTANT: Never share your PRIVATE_KEY or commit .env to git!
""")


if __name__ == "__main__":
    main()
