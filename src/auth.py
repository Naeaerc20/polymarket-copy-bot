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
    api_secret: str
    api_passphrase: str
    
    def to_dict(self) -> Dict[str, str]:
        """Convert to dict format expected by ClobClient"""
        return {
            "apiKey": self.api_key,
            "secret": self.api_secret,
            "passphrase": self.api_passphrase
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "PolymarketCredentials":
        """Create from stored dict (supports both naming conventions)"""
        return cls(
            api_key=data.get("api_key") or data.get("apiKey", ""),
            api_secret=data.get("api_secret") or data.get("secret", ""),
            api_passphrase=data.get("api_passphrase") or data.get("passphrase", "")
        )
    
    @classmethod
    def from_api_creds(cls, creds: ApiCreds) -> "PolymarketCredentials":
        """Create from py_clob_client ApiCreds object"""
        return cls(
            api_key=creds.api_key,
            api_secret=creds.api_secret,
            api_passphrase=creds.api_passphrase
        )
    
    def to_storage_dict(self) -> Dict[str, str]:
        """Convert to dict for JSON storage"""
        return {
            "api_key": self.api_key,
            "api_secret": self.api_secret,
            "api_passphrase": self.api_passphrase
        }


class PolymarketAuth:
    """
    Handles Polymarket authentication (L1 and L2)
    
    Authentication Flow:
    1. L1: Use private key to sign EIP-712 message and create/derive API credentials
    2. L2: Use API credentials (apiKey, secret, passphrase) for HMAC-SHA256 auth
    
    Signature Types:
    - 0: EOA (Externally Owned Account - MetaMask)
    - 1: POLY_PROXY (Magic Link email/Google login) - MOST COMMON
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
        # Ensure private key has 0x prefix
        if not private_key.startswith("0x"):
            private_key = "0x" + private_key
        
        self.private_key = private_key
        self.funder_address = funder_address.lower() if funder_address else None
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
            json.dump(creds.to_storage_dict(), f, indent=2)
        # Set restrictive permissions
        os.chmod(self.creds_file, 0o600)
    
    def _create_l1_client(self) -> ClobClient:
        """Create ClobClient configured for L1 authentication (create/derive creds)"""
        return ClobClient(
            host=self.CLOB_HOST,
            key=self.private_key,
            chain_id=self.CHAIN_ID,
            signature_type=self.signature_type,
            funder=self.funder_address
        )
    
    def create_credentials(self) -> PolymarketCredentials:
        """
        Create NEW API credentials using L1 authentication
        
        Use this if you've never generated API keys before.
        """
        print("Creating new API credentials...")
        client = self._create_l1_client()
        
        creds: ApiCreds = client.create_api_key()
        
        credentials = PolymarketCredentials.from_api_creds(creds)
        self._save_credentials(credentials)
        self._credentials = credentials
        
        return credentials
    
    def derive_credentials(self) -> PolymarketCredentials:
        """
        Derive EXISTING API credentials using L1 authentication
        
        Use this if you've already created API keys before.
        """
        print("Deriving existing API credentials...")
        client = self._create_l1_client()
        
        creds: ApiCreds = client.derive_api_key()
        
        credentials = PolymarketCredentials.from_api_creds(creds)
        self._save_credentials(credentials)
        self._credentials = credentials
        
        return credentials
    
    def create_or_derive_credentials(self) -> PolymarketCredentials:
        """
        Create new or derive existing API credentials using L1 authentication
        
        This automatically tries to derive first (for existing users),
        and falls back to creating new credentials if needed.
        
        Returns:
            PolymarketCredentials object with api_key, api_secret, api_passphrase
        """
        # Try to load existing credentials from file
        existing = self._load_credentials()
        if existing:
            print("Found stored credentials, verifying...")
            try:
                # Verify they work by getting server time
                client = self.get_trading_client(existing)
                server_time = client.get_server_time()
                print(f"✓ Stored credentials valid. Server time: {server_time}")
                self._credentials = existing
                return existing
            except Exception as e:
                print(f"Stored credentials invalid: {e}")
                print("Attempting to derive fresh credentials...")
        
        # Try to create or derive from the API
        client = self._create_l1_client()
        
        try:
            # This method handles both create and derive automatically
            creds: ApiCreds = client.create_or_derive_api_creds()
            
            credentials = PolymarketCredentials.from_api_creds(creds)
            self._save_credentials(credentials)
            self._credentials = credentials
            
            print("✓ Credentials created/derived successfully")
            return credentials
            
        except Exception as e:
            error_msg = str(e).lower()
            
            # If create fails, try derive
            if "could not create" in error_msg or "already" in error_msg:
                print(f"Create failed ({e}), trying to derive...")
                try:
                    creds: ApiCreds = client.derive_api_key()
                    credentials = PolymarketCredentials.from_api_creds(creds)
                    self._save_credentials(credentials)
                    self._credentials = credentials
                    print("✓ Credentials derived successfully")
                    return credentials
                except Exception as e2:
                    print(f"Derive also failed: {e2}")
                    raise
            
            raise
    
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
        
        # Create client with L2 credentials for trading
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
    - FUNDER_ADDRESS: Proxy wallet address (for POLY_PROXY accounts)
    - SIGNATURE_TYPE: 0, 1, or 2 (default: 1 for POLY_PROXY)
    """
    from dotenv import load_dotenv
    load_dotenv()
    
    private_key = os.getenv("PRIVATE_KEY")
    funder_address = os.getenv("FUNDER_ADDRESS", "")
    signature_type = int(os.getenv("SIGNATURE_TYPE", "1"))
    
    if not private_key:
        raise ValueError("PRIVATE_KEY not set in environment")
    
    # For POLY_PROXY (type 1), funder_address is required
    if signature_type == 1 and not funder_address:
        print("WARNING: FUNDER_ADDRESS not set. This is required for POLY_PROXY accounts.")
        print("Your funder address is the proxy wallet address shown on Polymarket.com")
    
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
    
    print(f"\nFunder Address: {auth.funder_address or 'Not set'}")
    print(f"Signature Type: {auth.signature_type}")
    
    print("\nCreating/deriving credentials...")
    creds = auth.create_or_derive_credentials()
    print(f"API Key: {creds.api_key[:16]}...")
    print(f"API Secret: {creds.api_secret[:16]}...")
    print(f"API Passphrase: {creds.api_passphrase[:16]}...")
    
    print("\nVerifying connection...")
    if auth.verify_connection():
        print("\n✓ Authentication successful!")
    else:
        print("\n✗ Authentication failed!")
