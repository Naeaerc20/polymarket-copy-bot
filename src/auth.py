"""
Polymarket L1/L2 Authentication Module

Handles:
- L1 authentication with private key (EIP-712 signing)
- L2 authentication with API credentials (HMAC-SHA256)
- Credential derivation and storage
"""

import os
import json
import time
from typing import Optional, Dict, Any
from dataclasses import dataclass
from pathlib import Path

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds
except ImportError:
    print("Installing py-clob-client...")
    os.system("pip install py-clob-client")
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds


class PolymarketAuth:
    """
    Handles Polymarket authentication (L1 and L2)
    
    Authentication Flow:
    1. L1: Use private key to sign EIP-712 message and create/derive API credentials
    2. L2: Use API credentials (apiKey, secret, passphrase) for HMAC-SHA256 auth
    
    Signature Types:
    - 0: EOA (Externally Owned Account - MetaMask)
    - 1: POLY_PROXY (Magic Link email/Google login)
    - 2: GNOSIS_SAFE (Gnosis Safe multisig)
    """
    
    CLOB_HOST = "https://clob.polymarket.com"
    CHAIN_ID = 137  # Polygon mainnet
    CREDENTIALS_FILE = "credentials.json"
    
    def __init__(
        self,
        private_key: str,
        funder_address: str,
        signature_type: int = 1,
        creds_dir: str = ".",
        api_key: str = None,
        api_secret: str = None,
        api_passphrase: str = None
    ):
        """
        Initialize authentication handler
        
        Args:
            private_key: Wallet private key (0x prefixed hex)
            funder_address: Proxy wallet address (shown on Polymarket.com)
            signature_type: 0=EOA, 1=POLY_PROXY, 2=GNOSIS_SAFE
            creds_dir: Directory to store credentials
            api_key: Pre-existing API key (from .env)
            api_secret: Pre-existing API secret (from .env)
            api_passphrase: Pre-existing API passphrase (from .env)
        """
        # Ensure proper format
        self.private_key = private_key if private_key.startswith('0x') else '0x' + private_key
        self.funder_address = funder_address if funder_address.startswith('0x') else '0x' + funder_address
        self.signature_type = signature_type
        self.creds_dir = Path(creds_dir)
        self.creds_file = self.creds_dir / self.CREDENTIALS_FILE
        
        # Pre-existing credentials from .env
        self.pre_existing_creds = None
        if api_key and api_secret and api_passphrase:
            self.pre_existing_creds = ApiCreds(
                api_key=api_key,
                api_secret=api_secret,
                api_passphrase=api_passphrase
            )
        
        self._client: Optional[ClobClient] = None
        self._credentials: Optional[ApiCreds] = None
    
    def _load_credentials(self) -> Optional[ApiCreds]:
        """Load credentials from file if they exist"""
        if self.creds_file.exists():
            try:
                with open(self.creds_file, "r") as f:
                    data = json.load(f)
                return ApiCreds(
                    api_key=data.get("api_key", data.get("apiKey", "")),
                    api_secret=data.get("api_secret", data.get("secret", "")),
                    api_passphrase=data.get("api_passphrase", data.get("passphrase", ""))
                )
            except Exception as e:
                print(f"Warning: Could not load credentials: {e}")
        return None
    
    def _save_credentials(self, creds: ApiCreds) -> None:
        """Save credentials to file"""
        self.creds_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "api_key": creds.api_key,
            "api_secret": creds.api_secret,
            "api_passphrase": creds.api_passphrase,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        with open(self.creds_file, "w") as f:
            json.dump(data, f, indent=2)
        # Set restrictive permissions
        os.chmod(self.creds_file, 0o600)
    
    def get_credentials(self) -> ApiCreds:
        """
        Get API credentials, creating if necessary
        
        Priority:
        1. Pre-existing credentials from .env (POLY_API_KEY, etc.)
        2. Stored credentials from credentials.json
        3. Derive from Polymarket using L1 auth
        
        Returns:
            ApiCreds object with api_key, api_secret, api_passphrase
        """
        # 1. Use pre-existing from .env
        if self.pre_existing_creds:
            print("Using API credentials from .env")
            self._credentials = self.pre_existing_creds
            return self._credentials
        
        # 2. Try stored credentials
        stored = self._load_credentials()
        if stored:
            print("Using stored credentials from credentials.json")
            self._credentials = stored
            return self._credentials
        
        # 3. Derive from Polymarket
        print("Deriving API credentials from Polymarket...")
        return self.derive_credentials()
    
    def derive_credentials(self) -> ApiCreds:
        """Derive API credentials from Polymarket using L1 auth"""
        client = ClobClient(
            host=self.CLOB_HOST,
            key=self.private_key,
            chain_id=self.CHAIN_ID,
            signature_type=self.signature_type,
            funder=self.funder_address
        )
        
        # Try create_or_derive first (handles both cases)
        if hasattr(client, 'create_or_derive_api_creds'):
            creds = client.create_or_derive_api_creds()
        else:
            # Try derive first, then create
            try:
                creds = client.derive_api_key()
                print("Derived existing API credentials")
            except Exception:
                creds = client.create_api_key()
                print("Created new API credentials")
        
        self._save_credentials(creds)
        self._credentials = creds
        return creds
    
    def create_credentials(self) -> ApiCreds:
        """Create new API credentials (forces new creation)"""
        client = ClobClient(
            host=self.CLOB_HOST,
            key=self.private_key,
            chain_id=self.CHAIN_ID,
            signature_type=self.signature_type,
            funder=self.funder_address
        )
        
        creds = client.create_api_key()
        self._save_credentials(creds)
        self._credentials = creds
        return creds
    
    def get_trading_client(self) -> ClobClient:
        """
        Get authenticated CLOB client for trading operations
        
        Returns:
            ClobClient instance ready for L2 operations
        """
        creds = self._credentials or self.get_credentials()
        
        # Create client with L2 credentials
        client = ClobClient(
            host=self.CLOB_HOST,
            key=self.private_key,
            chain_id=self.CHAIN_ID,
            creds=creds,
            signature_type=self.signature_type,
            funder=self.funder_address
        )
        
        self._client = client
        return client
    
    def get_readonly_client(self) -> ClobClient:
        """
        Get read-only CLOB client (no authentication required)
        
        Returns:
            ClobClient instance for read-only operations
        """
        return ClobClient(host=self.CLOB_HOST)
    
    def verify_connection(self) -> bool:
        """Verify the connection and credentials are working"""
        try:
            client = self.get_trading_client()
            server_time = client.get_server_time()
            print(f"✓ Connected to CLOB. Server time: {server_time}")
            return True
        except Exception as e:
            print(f"✗ Connection failed: {e}")
            return False
    
    @property
    def client(self) -> ClobClient:
        """Get the current client, initializing if necessary"""
        if self._client is None:
            self._client = self.get_trading_client()
        return self._client
    
    @property
    def credentials(self) -> ApiCreds:
        """Get current credentials"""
        if self._credentials is None:
            self._credentials = self.get_credentials()
        return self._credentials


def setup_auth_from_env() -> PolymarketAuth:
    """
    Create PolymarketAuth instance from environment variables
    
    Required env vars:
    - PRIVATE_KEY: Wallet private key
    - FUNDER_ADDRESS: Proxy wallet address
    - SIGNATURE_TYPE: 0, 1, or 2
    
    Optional env vars (if provided, skip derivation):
    - POLY_API_KEY: API key
    - POLY_API_SECRET: API secret
    - POLY_API_PASSPHRASE: API passphrase
    """
    from dotenv import load_dotenv
    load_dotenv()
    
    private_key = os.getenv("PRIVATE_KEY")
    funder_address = os.getenv("FUNDER_ADDRESS")
    signature_type = int(os.getenv("SIGNATURE_TYPE", "1"))
    
    # Optional pre-existing credentials
    api_key = os.getenv("POLY_API_KEY")
    api_secret = os.getenv("POLY_API_SECRET")
    api_passphrase = os.getenv("POLY_API_PASSPHRASE")
    
    if not private_key:
        raise ValueError("PRIVATE_KEY not set in environment. Run setup.py first!")
    if not funder_address:
        raise ValueError("FUNDER_ADDRESS not set in environment. Run setup.py first!")
    
    return PolymarketAuth(
        private_key=private_key,
        funder_address=funder_address,
        signature_type=signature_type,
        api_key=api_key,
        api_secret=api_secret,
        api_passphrase=api_passphrase
    )


if __name__ == "__main__":
    # Test authentication
    auth = setup_auth_from_env()
    
    print("=" * 50)
    print("Polymarket Authentication Test")
    print("=" * 50)
    
    print(f"\nFunder Address: {auth.funder_address}")
    print(f"Signature Type: {auth.signature_type}")
    
    print("\nGetting credentials...")
    creds = auth.get_credentials()
    print(f"API Key: {creds.api_key[:16]}...")
    print(f"API Secret: {creds.api_secret[:8]}...")
    print(f"Passphrase: {creds.api_passphrase[:8]}...")
    
    print("\nVerifying connection...")
    if auth.verify_connection():
        print("\n✓ Authentication successful!")
    else:
        print("\n✗ Authentication failed!")
