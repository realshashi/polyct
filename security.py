import os
from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv
import base64

load_dotenv()

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
if ENCRYPTION_KEY is None:
    raise ValueError("ENCRYPTION_KEY not set in .env file!")

fernet = Fernet(ENCRYPTION_KEY)

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
