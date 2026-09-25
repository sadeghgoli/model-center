import base64
import hashlib

from cryptography.fernet import Fernet

from mc_shared.settings import get_settings


def _fernet() -> Fernet:
    secret = get_settings().ai_platform_secret
    if not secret:
        raise RuntimeError("AI_PLATFORM_SECRET is required to encrypt runtime credentials.")
    try:
        return Fernet(secret.encode())
    except ValueError:
        digest = hashlib.sha256(secret.encode()).digest()
        return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    return _fernet().decrypt(value.encode()).decode()
