"""
Security primitives — secrets, password hashing, tokens and biometric encryption.

Everything security-sensitive that is not request/route specific lives here so
it can be reviewed in one place:

  - Server secrets      : loaded from env, or generated once into instance/ (0600)
  - Password / PIN hash : scrypt (memory-hard), per-hash random salt, versioned
                          format, constant-time verification, transparent
                          upgrade of legacy unsalted SHA-256 hashes
  - Session tokens      : 256-bit random, only a SHA-256 digest is stored
  - CSRF tokens         : HMAC of the session token (stateless, per session)
  - Face templates      : AES-256-GCM, student_id bound as associated data so a
                          ciphertext cannot be swapped onto another student
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re
import secrets
import string
from pathlib import Path

from config.settings import security as cfg

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# SERVER SECRETS
# ─────────────────────────────────────────────

def _instance_dir() -> Path:
    path = Path(cfg.instance_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_or_create_key(env_name: str, file_name: str) -> bytes:
    """
    Return a 32-byte key from env (base64) or from instance/<file_name>.
    The file is created on first use with owner-only permissions.
    """
    raw = os.getenv(env_name, "").strip()
    if raw:
        key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        if len(key) != 32:
            raise RuntimeError(f"{env_name} must be 32 bytes, base64 encoded.")
        return key

    path = _instance_dir() / file_name
    if path.exists():
        key = base64.urlsafe_b64decode(path.read_text(encoding="ascii").strip())
        if len(key) != 32:
            raise RuntimeError(f"{path} is corrupt (expected a 32-byte key).")
        return key

    key = secrets.token_bytes(32)
    # O_EXCL avoids clobbering a key another process created concurrently.
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return _load_or_create_key(env_name, file_name)
    with os.fdopen(fd, "w", encoding="ascii") as fh:
        fh.write(base64.urlsafe_b64encode(key).decode("ascii"))
    logger.warning(
        "Generated new %s at %s — back this file up; it is required to %s.",
        env_name, path,
        "decrypt stored face templates" if "DATA" in env_name else "validate sessions",
    )
    return key


_secret_key: bytes | None = None
_data_key: bytes | None = None


def secret_key() -> bytes:
    """HMAC key for CSRF tokens and other server-side MACs."""
    global _secret_key
    if _secret_key is None:
        _secret_key = _load_or_create_key("ATTENDX_SECRET_KEY", "secret.key")
    return _secret_key


def data_key() -> bytes:
    """AES-256 key for biometric templates at rest."""
    global _data_key
    if _data_key is None:
        _data_key = _load_or_create_key("ATTENDX_DATA_KEY", "data.key")
    return _data_key


# ─────────────────────────────────────────────
# PASSWORD / PIN HASHING (scrypt)
# ─────────────────────────────────────────────
# Format: scrypt$<log2 N>$<r>$<p>$<salt b64>$<hash b64>
# N=2^15, r=8 → 32 MiB of memory per guess, which makes GPU/ASIC cracking of a
# stolen database far more expensive than with plain SHA-256.

_SCRYPT_LOG_N = 15
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_SCRYPT_MAXMEM = 64 * 1024 * 1024
_LEGACY_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def hash_secret(secret: str) -> str:
    """Hash a password or PIN. CPU-heavy: call via asyncio.to_thread in async code."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        secret.encode("utf-8"),
        salt=salt,
        n=1 << _SCRYPT_LOG_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        maxmem=_SCRYPT_MAXMEM,
        dklen=_SCRYPT_DKLEN,
    )
    return f"scrypt${_SCRYPT_LOG_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_secret(secret: str, stored: str | None) -> bool:
    """
    Constant-time verification. Accepts the current scrypt format and legacy
    unsalted SHA-256 hex digests (so old databases keep working until the
    caller re-hashes on successful login — see needs_rehash()).
    """
    if not stored:
        # Still burn comparable CPU so "no such user" is not distinguishable
        # from "wrong password" by timing.
        _dummy_verify(secret)
        return False

    if stored.startswith("scrypt$"):
        try:
            _, log_n, r, p, salt_b64, hash_b64 = stored.split("$")
            expected = _unb64(hash_b64)
            candidate = hashlib.scrypt(
                secret.encode("utf-8"),
                salt=_unb64(salt_b64),
                n=1 << int(log_n),
                r=int(r),
                p=int(p),
                maxmem=_SCRYPT_MAXMEM,
                dklen=len(expected),
            )
        except (ValueError, TypeError):
            logger.error("Malformed password hash encountered.")
            return False
        return hmac.compare_digest(candidate, expected)

    if _LEGACY_SHA256.match(stored):
        candidate = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        return hmac.compare_digest(candidate, stored)

    _dummy_verify(secret)
    return False


def needs_rehash(stored: str | None) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        return True
    try:
        _, log_n, r, p, *_ = stored.split("$")
        return (int(log_n), int(r), int(p)) != (_SCRYPT_LOG_N, _SCRYPT_R, _SCRYPT_P)
    except ValueError:
        return True


_DUMMY_HASH: str | None = None


def _dummy_verify(secret: str) -> None:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_secret(secrets.token_urlsafe(16))
    verify_secret(secret, _DUMMY_HASH)


def is_legacy_default(stored: str | None, principal_id: str) -> bool:
    """True when a legacy SHA-256 hash is just the user's own ID (old default)."""
    if not stored or not _LEGACY_SHA256.match(stored):
        return False
    return hmac.compare_digest(
        hashlib.sha256(principal_id.encode("utf-8")).hexdigest(), stored
    )


# ─────────────────────────────────────────────
# PASSWORD POLICY
# ─────────────────────────────────────────────

_COMMON_PASSWORDS = {
    "password", "password1", "password123", "1234567890", "12345678910",
    "qwertyuiop", "qwerty12345", "iloveyou12", "admin12345", "letmein123",
    "welcome123", "attendance", "attendx123", "iiitvadodara", "changeme123",
    "abcdefghij", "0987654321", "1111111111", "football12", "princess12",
}


def password_problems(password: str, principal_id: str = "") -> list[str]:
    """Return human-readable reasons a password is rejected (empty = OK)."""
    problems: list[str] = []
    if len(password) < cfg.password_min_length:
        problems.append(f"Use at least {cfg.password_min_length} characters.")
    if len(password) > cfg.password_max_length:
        problems.append(f"Use at most {cfg.password_max_length} characters.")
    if password.strip() != password:
        problems.append("Do not start or end with spaces.")
    classes = sum([
        any(c.islower() for c in password),
        any(c.isupper() for c in password),
        any(c.isdigit() for c in password),
        any(not c.isalnum() for c in password),
    ])
    if classes < 3:
        problems.append("Mix at least three of: lowercase, uppercase, digits, symbols.")
    lowered = password.lower()
    if lowered in _COMMON_PASSWORDS:
        problems.append("This password is too common.")
    if principal_id and principal_id.lower() in lowered:
        problems.append("Do not include your ID in the password.")
    if len(set(password)) < 5:
        problems.append("Use more distinct characters.")
    return problems


def pin_problems(pin: str) -> list[str]:
    problems: list[str] = []
    if not pin.isdigit():
        problems.append("PIN must contain digits only.")
    if not (cfg.pin_min_length <= len(pin) <= cfg.pin_max_length):
        problems.append(f"PIN must be {cfg.pin_min_length}-{cfg.pin_max_length} digits.")
    if pin and len(set(pin)) < 3:
        problems.append("PIN is too repetitive.")
    if pin in "01234567890123456789" or pin in "98765432109876543210":
        problems.append("PIN must not be a simple sequence.")
    return problems


def generate_temporary_password(length: int = 14) -> str:
    """Readable one-time password that always satisfies the policy."""
    alphabet = string.ascii_letters + string.digits
    while True:
        core = "".join(secrets.choice(alphabet) for _ in range(length - 2))
        candidate = f"{core[:6]}-{core[6:]}{secrets.choice('!@#%*')}"
        if not password_problems(candidate):
            return candidate


# ─────────────────────────────────────────────
# SESSION & CSRF TOKENS
# ─────────────────────────────────────────────

def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    """What we store server-side — a leaked DB row cannot be replayed as a cookie."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def csrf_for(session_token: str) -> str:
    mac = hmac.new(secret_key(), b"csrf:" + session_token.encode("utf-8"), hashlib.sha256)
    return base64.urlsafe_b64encode(mac.digest()).decode("ascii").rstrip("=")


def csrf_valid(session_token: str, presented: str | None) -> bool:
    if not presented:
        return False
    return hmac.compare_digest(csrf_for(session_token), presented)


# ─────────────────────────────────────────────
# BIOMETRIC TEMPLATE ENCRYPTION (AES-256-GCM)
# ─────────────────────────────────────────────
# Blob layout: b"AXF1" | 12-byte nonce | ciphertext+tag
# AAD = b"attendx-face:" + student_id

_FACE_MAGIC = b"AXF1"


def encrypt_face_template(student_id: str, raw: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = secrets.token_bytes(12)
    aad = b"attendx-face:" + student_id.encode("utf-8")
    return _FACE_MAGIC + nonce + AESGCM(data_key()).encrypt(nonce, raw, aad)


def decrypt_face_template(student_id: str, blob: bytes) -> bytes:
    """
    Decrypt a stored template. Legacy plaintext float32 blobs (written before
    encryption existed) are returned unchanged so they can be migrated.
    Raises ValueError on tampering or a wrong key.
    """
    if not blob.startswith(_FACE_MAGIC):
        return blob
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce, ciphertext = blob[4:16], blob[16:]
    aad = b"attendx-face:" + student_id.encode("utf-8")
    try:
        return AESGCM(data_key()).decrypt(nonce, ciphertext, aad)
    except InvalidTag as exc:
        raise ValueError("Face template failed integrity check.") from exc


def is_encrypted_template(blob: bytes | None) -> bool:
    return bool(blob) and blob.startswith(_FACE_MAGIC)


# ─────────────────────────────────────────────
# INPUT SHAPES
# ─────────────────────────────────────────────
# Identifiers are restricted to a conservative alphabet everywhere they enter
# the system (API bodies, CSV imports, path params).

ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,31}$"
_ID_RE = re.compile(ID_PATTERN)


def is_valid_id(value: str | None) -> bool:
    return bool(value) and bool(_ID_RE.match(value))
