"""
Utility Scripts for Polymarket Copy Trading Bot

This module contains helper scripts and utilities:
- Find top traders from leaderboard
- Validate configuration
- Check balances and allowances
- Test API connections
"""

import os
import sys
import json
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
import requests


def get_leaderboard(
    limit: int = 50,
    sort_by: str = "pnl",
    time_frame: str = "30d"
) -> List[Dict[str, Any]]:
    """
    Fetch Polymarket leaderboard
    
    Args:
        limit: Number of traders to fetch
        sort_by: Sort field (pnl, volume, trades)
        time_frame: Time period (7d, 30d, all)
    
    Returns:
        List of trader data
    """
    base_url = "https://data-api.polymarket.com/leaderboard"
    
    params = {
        "limit": limit,
        "sortBy": sort_by,
        "timeFrame": time_frame
    }
    
    response = requests.get(base_url, params=params)
    response.raise_for_status()
    
    return response.json()


def get_trader_stats(address: str) -> Dict[str, Any]:
    """
    Get statistics for a specific trader
    
    Args:
        address: Trader's wallet address
    
    Returns:
        Trader statistics and recent activity
    """
    base_url = "https://data-api.polymarket.com"
    
    # Get positions
    positions = requests.get(
        f"{base_url}/positions",
        params={"user": address}
    ).json()
    
    # Get recent activity
    activity = requests.get(
        f"{base_url}/activity",
        params={"user": address, "limit": 20}
    ).json()
    
    return {
        "address": address,
        "positions": positions,
        "recent_activity": activity
    }


def generate_traders_config(
    addresses: List[str],
    output_path: str = "config/traders.json"
) -> None:
    """
    Generate a traders.json config file from a list of addresses
    """
    traders = []
    
    for i, address in enumerate(addresses):
        traders.append({
            "address": address,
            "nickname": f"Trader_{i+1}",
            "enabled": True,
            "copy_buys": True,
            "copy_sells": True,
            "max_position_size": 500,
            "notes": "Add from leaderboard"
        })
    
    config = {
        "traders": traders,
        "global_settings": {
            "enabled": True,
            "copy_delay_seconds": 1,
            "max_concurrent_trades": 5,
            "stop_on_error": False,
            "notification_webhook": None
        }
    }
    
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w") as f:
        json.dump(config, f, indent=2)
    
    print(f"✓ Created config with {len(traders)} traders at {output_path}")


def validate_env_file(env_path: str = ".env") -> Dict[str, Any]:
    """
    Validate the .env configuration file
    
    Returns:
        Dict with validation results
    """
    load_dotenv(env_path)
    
    results = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "config": {}
    }
    
    # Check required fields
    required = ["PRIVATE_KEY", "FUNDER_ADDRESS"]
    for field in required:
        value = os.getenv(field)
        if not value:
            results["errors"].append(f"Missing required field: {field}")
            results["valid"] = False
        else:
            results["config"][field] = value[:10] + "..." if field == "PRIVATE_KEY" else value
    
    # Check private key format
    private_key = os.getenv("PRIVATE_KEY", "")
    if private_key:
        if not private_key.startswith("0x"):
            results["warnings"].append("PRIVATE_KEY should start with '0x'")
        if len(private_key) != 66:  # 0x + 64 hex chars
            results["warnings"].append(f"PRIVATE_KEY has unexpected length: {len(private_key)}")
    
    # Check funder address format
    funder = os.getenv("FUNDER_ADDRESS", "")
    if funder:
        if not funder.startswith("0x"):
            results["errors"].append("FUNDER_ADDRESS should start with '0x'")
            results["valid"] = False
        if len(funder) != 42:  # 0x + 40 hex chars
            results["warnings"].append(f"FUNDER_ADDRESS has unexpected length: {len(funder)}")
    
    # Check signature type
    sig_type = os.getenv("SIGNATURE_TYPE", "1")
    try:
        sig_type_int = int(sig_type)
        if sig_type_int not in [0, 1, 2]:
            results["warnings"].append(f"Invalid SIGNATURE_TYPE: {sig_type} (should be 0, 1, or 2)")
    except ValueError:
        results["errors"].append(f"SIGNATURE_TYPE must be a number: {sig_type}")
        results["valid"] = False
    
    # Check numeric fields
    numeric_fields = ["AMOUNT_TO_COPY", "MIN_TRADE_SIZE", "MAX_TRADE_SIZE"]
    for field in numeric_fields:
        value = os.getenv(field)
        if value:
            try:
                float(value)
            except ValueError:
                results["errors"].append(f"{field} must be a number: {value}")
                results["valid"] = False
    
    return results


def check_api_status() -> Dict[str, bool]:
    """
    Check if Polymarket APIs are accessible
    """
    apis = {
        "Gamma API": "https://gamma-api.polymarket.com/markets?limit=1",
        "CLOB API": "https://clob.polymarket.com/time",
        "Data API": "https://data-api.polymarket.com/leaderboard?limit=1"
    }
    
    status = {}
    
    for name, url in apis.items():
        try:
            response = requests.get(url, timeout=10)
            status[name] = response.status_code == 200
        except Exception as e:
            status[name] = False
    
    return status


def cli_main():
    """Command-line interface for utilities"""
    parser = argparse.ArgumentParser(
        description="Polymarket Copy Trading Bot Utilities"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Leaderboard command
    leaderboard_parser = subparsers.add_parser(
        "leaderboard",
        help="Fetch and display top traders"
    )
    leaderboard_parser.add_argument("--limit", type=int, default=20)
    leaderboard_parser.add_argument("--sort-by", default="pnl")
    leaderboard_parser.add_argument("--output", help="Save to traders.json")
    
    # Validate command
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate .env configuration"
    )
    validate_parser.add_argument("--env-file", default=".env")
    
    # Status command
    subparsers.add_parser("status", help="Check API status")
    
    # Trader info command
    info_parser = subparsers.add_parser(
        "info",
        help="Get info about a specific trader"
    )
    info_parser.add_argument("address", help="Trader's wallet address")
    
    args = parser.parse_args()
    
    if args.command == "leaderboard":
        print("Fetching leaderboard...")
        traders = get_leaderboard(args.limit, args.sort_by)
        
        print(f"\nTop {len(traders)} traders by {args.sort_by}:")
        print("-" * 80)
        
        for i, trader in enumerate(traders[:args.limit]):
            addr = trader.get("address", trader.get("proxyWallet", "N/A"))
            pnl = trader.get("pnl", trader.get("totalPnl", 0))
            volume = trader.get("volume", trader.get("totalVolume", 0))
            
            print(f"{i+1}. {addr[:10]}... | PnL: ${pnl:,.2f} | Vol: ${volume:,.2f}")
        
        if args.output:
            addresses = [t.get("address", t.get("proxyWallet", "")) for t in traders[:args.limit]]
            generate_traders_config(addresses, args.output)
    
    elif args.command == "validate":
        print(f"Validating {args.env_file}...\n")
        results = validate_env_file(args.env_file)
        
        if results["valid"]:
            print("✓ Configuration is valid")
        else:
            print("✗ Configuration has errors:")
            for error in results["errors"]:
                print(f"  ERROR: {error}")
        
        if results["warnings"]:
            print("\nWarnings:")
            for warning in results["warnings"]:
                print(f"  WARNING: {warning}")
        
        print("\nConfiguration summary:")
        for key, value in results["config"].items():
            print(f"  {key}: {value}")
    
    elif args.command == "status":
        print("Checking API status...\n")
        status = check_api_status()
        
        for api, is_up in status.items():
            status_str = "✓ UP" if is_up else "✗ DOWN"
            print(f"  {api}: {status_str}")
    
    elif args.command == "info":
        print(f"Fetching info for {args.address}...\n")
        stats = get_trader_stats(args.address)
        
        print(f"Address: {stats['address']}")
        print(f"Open positions: {len(stats['positions'])}")
        print(f"Recent activity: {len(stats['recent_activity'])} trades")
        
        if stats['recent_activity']:
            print("\nLast 5 trades:")
            for activity in stats['recent_activity'][:5]:
                side = activity.get("side", "?")
                size = activity.get("size", 0)
                price = activity.get("price", 0)
                title = activity.get("title", "Unknown")[:40]
                print(f"  {side} {size} @ ${price:.4f} - {title}...")
    
    else:
        parser.print_help()


if __name__ == "__main__":
    cli_main()
