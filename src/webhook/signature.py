import hashlib
import hmac


def verify_signature(body: bytes, secret: str, header: str | None) -> bool:
    """Verify GitHub webhook HMAC-SHA256 signature using constant-time comparison."""
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    received = header.removeprefix("sha256=")
    return hmac.compare_digest(expected, received)
