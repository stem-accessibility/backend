import os
import jwt
from jwt import PyJWKClient
from functools import wraps
from flask import request, jsonify, g

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_JWT_ISSUER = os.environ.get("SUPABASE_JWT_ISSUER")

# AUTH_MODE=dev skips token verification and treats every request as one fixed local
# user, so contributors can run the API without a Supabase project. It must never be
# enabled on a deployed service, so refuse to start on Cloud Run (K_SERVICE is set there).
DEV_AUTH = os.environ.get("AUTH_MODE") == "dev"
if DEV_AUTH and os.environ.get("K_SERVICE"):
    raise RuntimeError("AUTH_MODE=dev is not allowed on a deployed service")

if DEV_AUTH:
    _jwk_client = None
else:
    if not SUPABASE_URL or not SUPABASE_JWT_ISSUER:
        raise RuntimeError(
            "Missing SUPABASE_URL or SUPABASE_JWT_ISSUER (or set AUTH_MODE=dev for local use)"
        )
    JWKS_URL = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
    _jwk_client = PyJWKClient(JWKS_URL)

class AuthError(Exception):
    """A request could not be tied to a signed-in user. `payload` is the JSON body to return."""

    def __init__(self, message, detail=None):
        super().__init__(message)
        self.payload = {"error": message}
        if detail is not None:
            self.payload["detail"] = detail


def _identify():
    """Return (user_id, email) for the request, or raise AuthError."""
    if DEV_AUTH:
        return "dev-user", "dev@localhost"

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise AuthError("Missing Bearer token")

    token = auth_header.split(" ", 1)[1].strip()

    try:
        header = jwt.get_unverified_header(token)
        alg = header.get("alg")
        if alg not in ("ES256", "RS256"):
            raise RuntimeError(f"Unsupported JWT alg: {alg}")

        signing_key = _jwk_client.get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=[alg],
            audience="authenticated",
            issuer=SUPABASE_JWT_ISSUER,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
    except Exception as e:
        raise AuthError("Invalid token", str(e))

    return claims["sub"], claims.get("email")


def optional_user():
    """The signed-in user's id, or None. For routes that work for anyone but treat a signed-in
    caller differently; a bad or missing token is simply "not signed in", never an error."""
    try:
        return _identify()[0]
    except AuthError:
        return None


def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            g.user_id, g.user_email = _identify()
        except AuthError as e:
            return jsonify(e.payload), 401
        return fn(*args, **kwargs)

    return wrapper
