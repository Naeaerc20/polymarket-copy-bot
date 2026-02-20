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


@dataclass
class PolymarketCredentials:
    """Holds API credentials for L2 authentication"""
    api_key: str
    secret: str
    passphrase: str
    
    def to_dict(self) -> Dict[str, str]:
        return {
            "apiKey": self.api_key,
            "secret": self.secret,
            "passphrase": self.passphrase
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "PolymarketCredentials":
        return cls(
            api_key=data.get("apiKey", ""),
            secret=data.get("secret", ""),
            passphrase=data.get("passphrase", "")
        )


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
        creds_dir: str = "."
    ):
        """
        Initialize authentication handler
        
        Args:
            private_key: Wallet private key (0x prefixed hex)
            funder_address: Proxy wallet address (shown on Polymarket.com)
            signature_type: 0=EOA, 1=POLY_PROXY, 2=GNOSIS_SAFE
            creds_dir: Directory to store credentials
        """
        self.private_key = private_key
        self.funder_address = funder_address
        self.signature_type = signature_type
        self.creds_dir = Path(creds_dir)
        self.creds_file = self.creds_dir / self.CREDENTIALS_FILE
        
        self._client: Optional[ClobClient] = None
        self._credentials: Optional[PolymarketCredentials] = None
    
    def _load_credentials(self) -> Optional[PolymarketCredentials]:
        """Load credentials from file if they exist"""
        if self.creds_file.exists():
            try:
                with open(self.creds_file, "r") as f:
                    data = json.load(f)
                return PolymarketCredentials.from_dict(data)
            except Exception as e:
                print(f"Warning: Could not load credentials: {e}")
        return None
    
    def _save_credentials(self, creds: PolymarketCredentials) -> None:
        """Save credentials to file"""
        self.creds_dir.mkdir(parents=True, exist_ok=True)
        with open(self.creds_file, "w") as f:
            json.dump(creds.to_dict(), f, indent=2)
        # Set restrictive permissions
        os.chmod(self.creds_file, 0o600)
    
    def create_or_derive_credentials(self) -> PolymarketCredentials:
        """
        Create new or derive existing API credentials using L1 authentication
        
        Returns:
            PolymarketCredentials object with apiKey, secret, passphrase
        """
        # Try to load existing credentials first
        existing = self._load_credentials()
        if existing:
            print("Found existing credentials, deriving...")
            return self._derive_credentials()
        
        # Create new credentials
        print("Creating new API credentials...")
        return self._create_credentials()
    
    def _create_credentials(self) -> PolymarketCredentials:
        """Create new API credentials with L1 auth"""
        client = ClobClient(
            host=self.CLOB_HOST,
            key=self.private_key,
            chain_id=self.CHAIN_ID
        )
        
        creds = client.create_api_key()
        
        credentials = PolymarketCredentials(
            api_key=creds.get("apiKey", creds.get("api_key", "")),
            secret=creds.get("secret", ""),
            passphrase=creds.get("passphrase", "")
        )
        
        self._save_credentials(credentials)
        return credentials
    
    def _derive_credentials(self) -> PolymarketCredentials:
        """Derive existing API credentials with L1 auth"""
        client = ClobClient(
            host=self.CLOB_HOST,
            key=self.private_key,
            chain_id=self.CHAIN_ID
        )
        
        creds = client.derive_api_key()
        
        credentials = PolymarketCredentials(
            api_key=creds.get("apiKey", creds.get("api_key", "")),
            secret=creds.get("secret", ""),
            passphrase=creds.get("passphrase", "")
        )
        
        self._save_credentials(credentials)
        return credentials
    
    def get_trading_client(self, credentials: Optional[PolymarketCredentials] = None) -> ClobClient:
        """
        Get authenticated CLOB client for trading operations
        
        Args:
            credentials: Optional credentials object. If None, uses stored credentials.
        
        Returns:
            ClobClient instance ready for L2 operations
        """
        if credentials is None:
            credentials = self._credentials or self.create_or_derive_credentials()
        
        self._credentials = credentials
        
        # Create client with L2 credentials
        client = ClobClient(
            host=self.CLOB_HOST,
            key=self.private_key,
            chain_id=self.CHAIN_ID,
            creds=credentials.to_dict(),
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
            # Try to get server time as a simple test
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
    def credentials(self) -> PolymarketCredentials:
        """Get current credentials"""
        if self._credentials is None:
            self._credentials = self.create_or_derive_credentials()
        return self._credentials


def setup_auth_from_env() -> PolymarketAuth:
    """
    Create PolymarketAuth instance from environment variables
    
    Required env vars:
    - PRIVATE_KEY: Wallet private key
    - FUNDER_ADDRESS: Proxy wallet address
    - SIGNATURE_TYPE: 0, 1, or 2
    """
    from dotenv import load_dotenv
    load_dotenv()
    
    private_key = os.getenv("PRIVATE_KEY")
    funder_address = os.getenv("FUNDER_ADDRESS")
    signature_type = int(os.getenv("SIGNATURE_TYPE", "1"))
    
    if not private_key:
        raise ValueError("PRIVATE_KEY not set in environment")
    if not funder_address:
        raise ValueError("FUNDER_ADDRESS not set in environment")
    
    return PolymarketAuth(
        private_key=private_key,
        funder_address=funder_address,
        signature_type=signature_type
    )


if __name__ == "__main__":
    # Test authentication
    auth = setup_auth_from_env()
    
    print("=" * 50)
    print("Polymarket Authentication Test")
    print("=" * 50)
    
    print(f"\nFunder Address: {auth.funder_address}")
    print(f"Signature Type: {auth.signature_type}")
    
    print("\nCreating/deriving credentials...")
    creds = auth.create_or_derive_credentials()
    print(f"API Key: {creds.api_key[:8]}...")
    print(f"Secret: {creds.secret[:8]}...")
    print(f"Passphrase: {creds.passphrase[:8]}...")
    
    print("\nVerifying connection...")
    if auth.verify_connection():
        print("\n✓ Authentication successful!")
    else:
        print("\n✗ Authentication failed!")
