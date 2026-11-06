import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote
from django.conf import settings


def generate_base32_secret(length: int = 20) -> str:
    """تولید کلید مخفی ۱۶۰ بیتی Base32 منطبق با RFC 6238 و Google Authenticator"""
    random_bytes = secrets.token_bytes(length)
    return base64.b32encode(random_bytes).decode('utf-8').rstrip('=')


def _derive_key_stream(nonce: bytes, length: int) -> bytes:
    master = settings.TOTP_ENCRYPTION_KEY.encode('utf-8')
    out = b''
    counter = 0
    while len(out) < length:
        block = hmac.new(master, nonce + struct.pack('>I', counter), hashlib.sha256).digest()
        out += block
        counter += 1
    return out[:length]


def encrypt_totp_secret(raw_secret: str) -> str:
    """رمزنگاری احراز هویت‌شده (Authenticated Encryption) برای ذخیره امن کلید TOTP در دیتابیس"""
    plaintext = raw_secret.encode('utf-8')
    nonce = secrets.token_bytes(16)
    keystream = _derive_key_stream(nonce, len(plaintext))
    ciphertext = bytes(a ^ b for a, b in zip(plaintext, keystream))
    mac = hmac.new(settings.TOTP_ENCRYPTION_KEY.encode('utf-8'), nonce + ciphertext, hashlib.sha256).digest()
    payload = nonce + mac + ciphertext
    return base64.urlsafe_b64encode(payload).decode('utf-8')


def decrypt_totp_secret(encrypted_payload: str) -> str:
    raw = base64.urlsafe_b64decode(encrypted_payload.encode('utf-8'))
    nonce, mac, ciphertext = raw[:16], raw[16:48], raw[48:]
    expected_mac = hmac.new(settings.TOTP_ENCRYPTION_KEY.encode('utf-8'), nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected_mac):
        raise ValueError('امضای رمزنگاری کلید TOTP نامعتبر است.')
    keystream = _derive_key_stream(nonce, len(ciphertext))
    plaintext = bytes(a ^ b for a, b in zip(ciphertext, keystream))
    return plaintext.decode('utf-8')


def _hotp(secret: str, counter: int, digits: int = 6) -> str:
    padded = secret.upper() + '=' * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(padded.encode('utf-8'), casefold=True)
    msg = struct.pack('>Q', counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = (struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code_int).zfill(digits)


def verify_totp_code(secret: str, code: str, last_used_counter=None, step: int = 30, window: int = 1):
    """
    بررسی کد ۶ رقمی TOTP در پنجره زمانی فعلی (±1 گام ۳۰ ثانیه‌ای) و جلوگیری از مصرف مجدد (Replay).
    خروجی: (is_valid: bool, matched_counter: int | None)
    """
    if not code or not code.isdigit() or len(code) != 6:
        return False, None

    current_counter = int(time.time() // step)
    for offset in range(-window, window + 1):
        candidate_counter = current_counter + offset
        if last_used_counter is not None and candidate_counter <= last_used_counter:
            continue
        expected = _hotp(secret, candidate_counter)
        if hmac.compare_digest(expected, code):
            return True, candidate_counter
    return False, None


def get_current_totp_code(secret: str, step: int = 30) -> str:
    """صرفاً جهت استفاده در تست‌های خودکار واحد (Unit Tests)"""
    return _hotp(secret, int(time.time() // step))


def build_otpauth_uri(secret: str, account_label: str, issuer: str = 'ToranjAcademy') -> str:
    label = quote(f"{issuer}:{account_label}")
    issuer_param = quote(issuer)
    return f"otpauth://totp/{label}?secret={secret}&issuer={issuer_param}&algorithm=SHA1&digits=6&period=30"