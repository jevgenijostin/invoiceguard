"""Self-issuable demo gate, not payment enforcement or a security boundary."""

import hashlib
import hmac

DEMO_SECRET = b"invoiceguard-public-demo-secret-v1"


def issue_license(license_id: str) -> str:
    if not license_id or "." in license_id:
        raise ValueError("license id must be nonempty and contain no dots")
    signature = hmac.new(DEMO_SECRET, license_id.encode(), hashlib.sha256).hexdigest()
    return f"{license_id}.{signature}"


def valid_license(key: str | None) -> bool:
    if not key or "." not in key:
        return False
    license_id, signature = key.rsplit(".", 1)
    if not license_id or "." in license_id:
        return False
    return hmac.compare_digest(issue_license(license_id), key) if key.isascii() else False
