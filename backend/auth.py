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

def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if DEV_AUTH:
            g.user_id = "dev-user"
            g.user_email = "dev@localhost"
            return fn(*args, **kwargs)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing Bearer token"}), 401

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
            return jsonify({"error": "Invalid token", "detail": str(e)}), 401

        g.user_id = claims["sub"]
        g.user_email = claims.get("email")
        return fn(*args, **kwargs)

    return wrapper

