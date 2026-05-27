"""TLS pinning utilities with SPKI (public key) pinning.

Production-grade TLS verification using SubjectPublicKeyInfo hashing instead of
leaf certificate fingerprints. SPKI pins survive certificate renewals as long as
the public key remains the same.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import ssl
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    from cryptography import x509
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import serialization
    _HAS_CRYPTOGRAPHY = True
except ImportError:
    _HAS_CRYPTOGRAPHY = False


class TlsPinningError(RuntimeError):
    """Non-fatal TLS pinning error.
    
    This exception should be caught and converted into trust degradation
    rather than crashing the service.
    """
    pass


def _normalize_hash(value: str) -> str:
    """Normalize a SHA-256 hash to lowercase hex without colons."""
    v = value.strip().lower().replace(":", "")
    if any(c not in "0123456789abcdef" for c in v):
        raise ValueError("Hash must be hex")
    if len(v) != 64:
        raise ValueError("SHA-256 hash must be 64 hex chars")
    return v


def fetch_spki_sha256(host: str, port: int, *, server_hostname: Optional[str] = None, timeout: float = 10.0) -> str:
    """Fetch SPKI SHA-256 hash for a server's public key.
    
    Returns the SHA-256 hash of the DER-encoded SubjectPublicKeyInfo (SPKI) from
    the server's leaf certificate. This hash is stable across certificate renewals
    as long as the same public key is reused.
    
    Args:
        host: Server hostname or IP
        port: Server port
        server_hostname: SNI hostname (defaults to host)
        timeout: Connection timeout in seconds
        
    Returns:
        Lowercase hex SHA-256 hash (64 chars, no colons)
        
    Raises:
        TlsPinningError: On connection, SSL, or parsing errors (non-fatal)
    """
    if not _HAS_CRYPTOGRAPHY:
        raise TlsPinningError(
            "cryptography library required for SPKI pinning. "
            "Install with: pip install cryptography"
        )
    
    try:
        context = ssl.create_default_context()
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        
        sni = server_hostname or host
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=sni) as ssock:
                der_cert = ssock.getpeercert(binary_form=True)
        
        # Parse certificate and extract public key
        cert = x509.load_der_x509_certificate(der_cert, default_backend())
        public_key = cert.public_key()
        
        # Serialize public key to DER-encoded SubjectPublicKeyInfo
        spki_der = public_key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        
        # Hash the SPKI
        return hashlib.sha256(spki_der).hexdigest()
        
    except (socket.error, ssl.SSLError, OSError, ValueError, Exception) as exc:
        raise TlsPinningError(f"Failed to fetch SPKI for {host}:{port}: {exc}") from exc


def days_until_cert_expiry(host: str, port: int, *, server_hostname: Optional[str] = None, timeout: float = 10.0) -> int:
    """Return whole days until leaf cert expiry (UTC).
    
    Non-fatal: returns -1 on any error instead of raising.
    """
    try:
        context = ssl.create_default_context()
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        
        sni = server_hostname or host
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=sni) as ssock:
                cert = ssock.getpeercert()
        
        not_after = cert.get("notAfter")
        if not not_after:
            return -1
        
        # Example format: 'Apr 12 12:00:00 2026 GMT'
        expiry = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = expiry - now
        return int(delta.total_seconds() // 86400)
    except Exception:
        return -1


@dataclass(frozen=True)
class SpkiPin:
    """SPKI pin configuration for an exchange."""
    host: str
    port: int
    spki_sha256: str


def load_spki_pins(path: Path) -> dict[str, SpkiPin]:
    """Load SPKI pins from JSON config.
    
    Expected format:
    {
      "binance": {
        "host": "stream.binance.com",
        "port": 9443,
        "spki_sha256": "abc123..."
      }
    }
    
    Returns empty dict on any error (non-fatal).
    Skips exchanges with placeholder or invalid pins (logs warning but continues).
    """
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        out: dict[str, SpkiPin] = {}
        for exchange_id, cfg in data.items():
            try:
                # Skip placeholder pins during loading (they'll be rejected during verification)
                raw_hash = str(cfg["spki_sha256"])
                if "PLACEHOLDER" in raw_hash.upper():
                    # Skip this exchange but continue loading others
                    continue
                
                out[exchange_id] = SpkiPin(
                    host=str(cfg["host"]),
                    port=int(cfg["port"]),
                    spki_sha256=_normalize_hash(raw_hash),
                )
            except (ValueError, KeyError) as exc:
                # Skip invalid pins for this exchange but continue loading others
                # This prevents one bad pin from breaking all TLS verification
                continue
        return out
    except Exception:
        return {}


def verify_spki_pin(*, exchange_id: str, pins_path: Path, timeout: float = 10.0) -> tuple[bool, str]:
    """Verify SPKI pin for an exchange (non-fatal).
    
    Returns:
        (success: bool, reason: str)
        - (True, "ok") if pin matches
        - (False, reason) if pin missing, mismatch, or error
        
    Never raises — all errors are converted to (False, reason).
    """
    try:
        pins = load_spki_pins(pins_path)
        
        if not pins:
            return (False, "no_pins_file_or_empty")
        
        if exchange_id not in pins:
            return (False, f"no_pin_configured_for_{exchange_id}")
        
        pin = pins[exchange_id]
        
        # Reject placeholder pins
        if "PLACEHOLDER" in pin.spki_sha256.upper():
            return (False, f"placeholder_pin_not_valid")
        
        actual = fetch_spki_sha256(pin.host, pin.port, timeout=timeout)
        
        if actual != pin.spki_sha256:
            return (False, f"spki_mismatch_expected={pin.spki_sha256[:16]}_actual={actual[:16]}")
        
        return (True, "ok")
        
    except TlsPinningError as exc:
        return (False, f"tls_error: {exc}")
    except Exception as exc:
        return (False, f"unexpected_error: {exc}")


def pins_path_from_env(default: Path) -> Path:
    """Get TLS pins path from env or use default."""
    raw = os.getenv("TLS_PINS_PATH")
    return Path(raw) if raw else default
