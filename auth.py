"""Per-family password auth for the shared deployment (specs/06-deployment.md).

Three passwords (FAMILY1_PASSWORD / FAMILY2_PASSWORD / FAMILY3_PASSWORD) —
whichever one matches identifies the family, so login doubles as "who is
prompting". A signed cookie carries the identity:

    trip_auth=<family>.<expires_unix>.<hmac_sha256(family.expires, COOKIE_SECRET)>

Passwords and the cookie secret come from the environment (Secret Manager in
prod, .env locally) and are never logged or echoed. When no family passwords
are configured at all (bare local dev), the gate is DISABLED and every
request is treated as Family 1 — the deployed service always configures them.
"""
import hmac
import hashlib
import os
import time

COOKIE_NAME = "trip_auth"
COOKIE_MAX_AGE_S = 14 * 24 * 3600  # the trip is 8 days; 14 covers it

FAMILIES = ("family-1", "family-2", "family-3")
FAMILY_LABELS = {"family-1": "Family 1", "family-2": "Family 2", "family-3": "Family 3"}

# Paths reachable without a cookie. Everything else — /run_sse, ADK session
# APIs, /api/*, /ui, /tmp, dev-ui — requires login. (/api/health, not
# /healthz: Google's frontend reserves /healthz on run.app and never
# forwards it to the container.)
PUBLIC_PATHS = ("/login", "/api/health", "/favicon.ico")


def _family_passwords() -> dict:
    """family -> password, for families that have one configured."""
    out = {}
    for i, family in enumerate(FAMILIES, start=1):
        password = os.getenv(f"FAMILY{i}_PASSWORD")
        if password:
            out[family] = password
    return out


def auth_enabled() -> bool:
    return bool(_family_passwords())


def _cookie_secret() -> bytes:
    secret = os.getenv("COOKIE_SECRET")
    if not secret:
        # Random per-process fallback: cookies stop working across restarts,
        # but auth never silently weakens. Deployment always sets it.
        secret = os.environ.setdefault("_COOKIE_SECRET_FALLBACK", os.urandom(32).hex())
    return secret.encode()


def _sign(payload: str) -> str:
    return hmac.new(_cookie_secret(), payload.encode(), hashlib.sha256).hexdigest()


def check_password(password: str) -> str | None:
    """Returns the family the password belongs to, or None.

    Compares against every configured password (constant-time per compare)
    so timing does not reveal which family a guess was close to.
    """
    matched = None
    for family, expected in _family_passwords().items():
        if hmac.compare_digest(password.encode(), expected.encode()):
            matched = family
    return matched


def make_cookie_value(family: str, now: float | None = None) -> str:
    now = time.time() if now is None else now
    expires = int(now + COOKIE_MAX_AGE_S)
    payload = f"{family}.{expires}"
    return f"{payload}.{_sign(payload)}"


def verify_cookie_value(value: str | None, now: float | None = None) -> str | None:
    """Returns the family for a valid, unexpired cookie; otherwise None."""
    if not value:
        return None
    parts = value.split(".")
    if len(parts) != 3:
        return None
    family, expires_s, signature = parts
    if family not in FAMILIES:
        return None
    payload = f"{family}.{expires_s}"
    if not hmac.compare_digest(signature, _sign(payload)):
        return None
    now = time.time() if now is None else now
    try:
        if int(expires_s) < now:
            return None
    except ValueError:
        return None
    return family


def request_family(request) -> str | None:
    """Family for an incoming request; 'family-1' when the gate is disabled."""
    if not auth_enabled():
        return "family-1"
    return verify_cookie_value(request.cookies.get(COOKIE_NAME))


def is_public_path(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in PUBLIC_PATHS)
