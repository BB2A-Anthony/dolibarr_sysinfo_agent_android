"""Encryption helpers for storing the API key at rest.

On Android (Termux) there is no DPAPI. The key is stored encrypted with
the `cryptography` package using a device-specific key derived from
Android system properties (signed with HMAC-SHA256), so the config.json
only ever stores "aes:<base64 nonce|ciphertext>", never the plaintext.

If the `cryptography` package is unavailable, encryption is disabled
and the plaintext key is stored as-is (like off-Windows in the Windows
agent).
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import subprocess

logger = logging.getLogger("agent.crypto")

_PREFIX = "aes:"
_KEY_SIZE = 32
_SALT_SIZE = 16


def _device_secret():
    """Derive a device-specific secret from Android system properties."""
    parts = []
    for prop in (
        "ro.build.fingerprint",
        "ro.serialno",
        "ro.boot.serialno",
        "ro.boot.hardware",
        "ro.product.model",
    ):
        value = _getprop_value(prop)
        if value:
            parts.append(value)
    hostname = os.uname().nodename if hasattr(os, "uname") else ""
    parts.append(hostname)
    return "\n".join(parts).encode("utf-8")


def _getprop_value(name):
    try:
        result = subprocess.run(
            ["getprop", name],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        value = result.stdout.decode("utf-8", errors="ignore").strip()
        return value or None
    except (OSError, subprocess.SubprocessError):
        return None


def _derive_key(salt):
    """Derive the AES key from the device secret and salt (HKDF-style)."""
    secret = _device_secret()
    key = hashlib.pbkdf2_hmac("sha256", secret, salt, iterations=100000, dklen=_KEY_SIZE)
    return key


def encrypt(value):
    """Encrypt a secret with AES-GCM. Returns 'aes:<base64>' or None."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        return None
    try:
        salt = os.urandom(_SALT_SIZE)
        nonce = os.urandom(12)
        key = _derive_key(salt)
        ciphertext = AESGCM(key).encrypt(nonce, value.encode("utf-8"), None)
        blob = salt + nonce + ciphertext
        return _PREFIX + base64.b64encode(blob).decode("ascii")
    except Exception:
        logger.exception("AES encryption failed")
        return None


def decrypt(stored):
    """Decrypt an 'aes:<base64>' value back to plaintext, or None."""
    if not stored or not stored.startswith(_PREFIX):
        return None
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        logger.warning("cryptography indisponible : cle API non dechiffrable")
        return None
    try:
        blob = base64.b64decode(stored[len(_PREFIX):].encode("ascii"))
        salt = blob[:_SALT_SIZE]
        nonce = blob[_SALT_SIZE:_SALT_SIZE + 12]
        ciphertext = blob[_SALT_SIZE + 12:]
        key = _derive_key(salt)
        return AESGCM(key).decrypt(nonce, ciphertext, None).decode("utf-8")
    except Exception:
        logger.exception("AES decryption failed")
        return None


def migrate_config(config, path):
    """Encrypt a plaintext api_key and remove it from the file.

    Called after load_config: if config contains a plaintext api_key and
    encryption is available, replace it with api_key_encrypted on disk.
    """
    plaintext = config.get("api_key")
    if not plaintext:
        return config
    encrypted = encrypt(plaintext)
    if not encrypted:
        return config
    config["api_key_encrypted"] = encrypted
    config.pop("api_key", None)
    try:
        with open(path, "r", encoding="utf-8") as f:
            on_disk = json.load(f)
        on_disk["api_key_encrypted"] = encrypted
        on_disk.pop("api_key", None)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(on_disk, f, indent=4)
        logger.info("Cle API migree : stockage chiffre (AES), Clair supprime")
    except OSError:
        logger.warning("Cle API chiffree en memoire mais non persistee")
    return config
