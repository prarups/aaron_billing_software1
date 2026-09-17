import base64
import json
import logging
import os
import time
from typing import Dict, Any, Tuple, Optional
from django.conf import settings
from django.core.cache import cache
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

SENSITIVE_KEYS = {
    'password', 'pass', 'pwd', 'secret', 'token', 'authorization',
    'encrypted_credentials', 'credit_card', 'cc_number', 'cvv'
}

def derive_aes_key(salt: bytes, context_token: str) -> bytes:
    """
    Derives a 256-bit AES key using PBKDF2 with SHA-256 HMAC
    from PAYLOAD_ENCRYPTION_KEY combined with context_token (e.g., CSRF token).
    """
    client_secret = getattr(settings, 'PAYLOAD_ENCRYPTION_KEY', 'dev-secret-key-aaron-billing')
    secret = (client_secret + context_token).encode('utf-8')
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=1000,
    )
    return kdf.derive(secret)


def encrypt_credentials_payload(payload_dict: Dict[str, Any], csrf_token: str) -> str:
    """
    Encrypts dictionary payload into a Base64 string using AES-GCM 256.
    """
    salt = os.urandom(16)
    key = derive_aes_key(salt, csrf_token)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    data = json.dumps(payload_dict).encode('utf-8')
    ciphertext = aesgcm.encrypt(nonce, data, None)
    combined = salt + nonce + ciphertext
    return base64.b64encode(combined).decode('utf-8')


def decrypt_credentials_payload(encrypted_b64: str, csrf_token: str) -> Optional[Dict[str, Any]]:
    """
    Decrypts Base64 AES-GCM payload using context CSRF token.
    Returns dictionary payload if valid, or None if decryption/integrity fails.
    """
    try:
        raw_bytes = base64.b64decode(encrypted_b64)
        if len(raw_bytes) < 28:  # 16 salt + 12 nonce = 28 min
            return None
        salt = raw_bytes[:16]
        nonce = raw_bytes[16:28]
        ciphertext = raw_bytes[28:]
        key = derive_aes_key(salt, csrf_token)
        aesgcm = AESGCM(key)
        decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, None)
        return json.loads(decrypted_bytes.decode('utf-8'))
    except Exception as e:
        logger = logging.getLogger('users.security')
        logger.warning("Payload decryption failed: %s", str(e))
        return None


class SensitiveDataScrubber(logging.Filter):
    """
    Scrubs sensitive parameters (passwords, tokens, credentials) from server logs
    and error tracking tracebacks.
    """
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self.scrub_text(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: ('[REDACTED]' if k.lower() in SENSITIVE_KEYS else v) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self.scrub_text(str(a)) if isinstance(a, str) else a for a in record.args)
        return True

    @staticmethod
    def scrub_text(text: str) -> str:
        if not text:
            return text
        import re
        for key in SENSITIVE_KEYS:
            pattern = re.compile(rf'({key}\s*[:=]\s*)([\'"][^\'"]+[\'"]|[^\s&,]+)', re.IGNORECASE)
            text = pattern.sub(r'\1[REDACTED]', text)
        return text


class BruteForceLimiter:
    """
    Tracks failed authentication attempts per client IP and username.
    Locks out IP after exceeding maximum allowed attempts within a window.
    """
    MAX_ATTEMPTS = 5
    LOCKOUT_TIME_SECONDS = 900  # 15 minutes

    @classmethod
    def get_ip_cache_key(cls, ip_address: str) -> str:
        return f"bf_lockout_ip:{ip_address}"

    @classmethod
    def get_attempt_count(cls, ip_address: str) -> int:
        return cache.get(cls.get_ip_cache_key(ip_address), 0)

    @classmethod
    def is_locked_out(cls, ip_address: str) -> Tuple[bool, int]:
        count = cls.get_attempt_count(ip_address)
        if count >= cls.MAX_ATTEMPTS:
            return True, cls.LOCKOUT_TIME_SECONDS
        return False, 0

    @classmethod
    def record_failed_attempt(cls, ip_address: str) -> int:
        key = cls.get_ip_cache_key(ip_address)
        try:
            count = cache.get(key, 0) + 1
            cache.set(key, count, timeout=cls.LOCKOUT_TIME_SECONDS)
            return count
        except Exception:
            return 1

    @classmethod
    def reset_attempts(cls, ip_address: str):
        key = cls.get_ip_cache_key(ip_address)
        cache.delete(key)


def get_client_ip(request) -> str:
    """
    Extracts client IP address safely from request headers.
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR', '127.0.0.1')
    return ip
