import os
from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv
import base64

load_dotenv()

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
if ENCRYPTION_KEY is None:
    raise ValueError("ENCRYPTION_KEY not set in .env file!")

# Strip whitespace and remove quotes if present
ENCRYPTION_KEY = ENCRYPTION_KEY.strip().strip('"').strip("'")

# Validate key format before creating Fernet instance
try:
    # Try to decode as base64 to validate format
    decoded = base64.urlsafe_b64decode(ENCRYPTION_KEY.encode())
    if len(decoded) != 32:
        raise ValueError(
            f"Fernet key must be 32 bytes when decoded, got {len(decoded)} bytes. "
            f"Your key is {len(ENCRYPTION_KEY)} characters long. "
            f"First 20 chars: {ENCRYPTION_KEY[:20]}...\n"
            f"Generate a new key with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )
except Exception as e:
    raise ValueError(
        f"Invalid Fernet key format in .env file: {e}\n"
        f"Key length: {len(ENCRYPTION_KEY)}, First 20 chars: {ENCRYPTION_KEY[:20] if len(ENCRYPTION_KEY) >= 20 else ENCRYPTION_KEY}...\n"
        f"Generate a new key with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
    )

try:
    fernet = Fernet(ENCRYPTION_KEY)
except ValueError as e:
    raise ValueError(
        f"Failed to initialize Fernet with ENCRYPTION_KEY: {e}\n"
        f"Key length: {len(ENCRYPTION_KEY)} characters. "
        f"Please check your .env file and ensure the key is properly formatted."
    )

def encrypt_data(data: str) -> str:
    """Encrypts string data. Returns base64-encoded, encrypted string."""
    encrypted = fernet.encrypt(data.encode())
    # Return base64 string to avoid issues with binary storage
    return base64.urlsafe_b64encode(encrypted).decode()

def decrypt_data(encrypted_data: str) -> str:
    """Decrypts base64-encoded, encrypted string to plaintext."""
    try:
        encrypted_bytes = base64.urlsafe_b64decode(encrypted_data.encode())
        return fernet.decrypt(encrypted_bytes).decode()
    except (InvalidToken, base64.binascii.Error):
        raise ValueError("Failed to decrypt data. Key is wrong or data is corrupted.")
