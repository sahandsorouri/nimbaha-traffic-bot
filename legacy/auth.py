"""
Credential encryption/decryption.

Each user's username and password are encrypted with Fernet symmetric
encryption using the MASTER_KEY from the environment.  The raw credentials
are never written to disk; only their ciphertext is stored in the database.

Even if the database file is leaked, credentials cannot be recovered without
the MASTER_KEY — which only lives in the server's environment.
"""

import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

_master_key: bytes | None = None


def _get_fernet() -> Fernet:
    global _master_key
    if _master_key is None:
        key = os.getenv("MASTER_KEY")
        if not key:
            raise RuntimeError(
                "MASTER_KEY is not set. "
                "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        _master_key = key.encode()
    return Fernet(_master_key)


def encrypt(plaintext: str) -> str:
    """Encrypt a string and return a URL-safe base64 ciphertext string."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a ciphertext string produced by `encrypt`."""
    return _get_fernet().decrypt(ciphertext.encode()).decode()
