"""
Try-it (guest) support: a visitor with no account can make one public STEM image.

A guest is identified only by a random token the browser keeps (sent as X-Guest-Token). The server
stores a hash of it as the owner (`guest:<hash>`), so the token is the only proof of ownership and
the database never holds it. Guests cannot use the image pipeline or any AI route, always share
publicly, and get one image. Limits here keep that open door from being used for spam.
"""
import hashlib
import re
import threading
import time
from functools import wraps

from flask import g, jsonify, request

GUEST_PREFIX = "guest:"
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")

# Size limits for what a guest can store.
MAX_NODES = 200
MAX_EDGES = 400
MAX_LABEL = 200
MAX_TITLE = 120
MAX_ALT = 1000
MAX_SUMMARY = 20000
MAX_JSON_BYTES = 200_000

# Writes allowed per rolling hour.
LIMIT_PER_TOKEN = 120
LIMIT_PER_IP = 300
LIMIT_REPORTS_PER_IP = 10


def is_guest_owner(owner_id) -> bool:
    return bool(owner_id) and str(owner_id).startswith(GUEST_PREFIX)


def guest_owner_id(token: str) -> str:
    return GUEST_PREFIX + hashlib.sha256(token.encode("utf-8")).hexdigest()[:48]


def client_ip() -> str:
    fwd = request.headers.get("X-Forwarded-For", "")
    return (fwd.split(",")[0].strip() if fwd else request.remote_addr) or "unknown"


class _Window:
    """Sliding-window counter. Per process: a deployment with several instances multiplies the
    limits, which is acceptable for abuse damping (not for billing or security decisions)."""

    def __init__(self):
        self._hits = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, seconds: int = 3600) -> bool:
        now = time.time()
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if now - t < seconds]
            if len(hits) >= limit:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits
            return True

    def reset(self):
        with self._lock:
            self._hits.clear()


limiter = _Window()


def require_guest(fn):
    """Read the guest token, set g.guest_owner, and rate-limit writes."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = request.headers.get("X-Guest-Token", "").strip()
        if not _TOKEN_RE.match(token):
            return jsonify({"error": "Missing or invalid X-Guest-Token"}), 400
        g.guest_owner = guest_owner_id(token)
        if request.method in ("PUT", "POST", "DELETE"):
            if not limiter.allow("tok:" + g.guest_owner, LIMIT_PER_TOKEN) or not limiter.allow(
                "ip:" + client_ip(), LIMIT_PER_IP
            ):
                return jsonify({"error": "Too many changes. Please wait a while and try again."}), 429
        return fn(*args, **kwargs)

    return wrapper


def validate_payload(data: dict):
    """Return (clean_fields, error). Only the fields a guest may set are kept."""
    import json

    json_data = data.get("json_data")
    if not isinstance(json_data, dict):
        return None, "json_data must be an object with nodes and edges"
    nodes = json_data.get("nodes")
    edges = json_data.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return None, "json_data needs nodes and edges lists"
    if len(nodes) > MAX_NODES or len(edges) > MAX_EDGES:
        return None, f"Too large: at most {MAX_NODES} nodes and {MAX_EDGES} edges"
    for n in nodes:
        if not isinstance(n, dict) or len(str(n.get("label", ""))) > MAX_LABEL:
            return None, f"Each label can be at most {MAX_LABEL} characters"
    if len(json.dumps(json_data)) > MAX_JSON_BYTES:
        return None, "Too large"

    def text(name, limit):
        v = data.get(name, "")
        if v is None:
            v = ""
        if not isinstance(v, str):
            raise ValueError(f"{name} must be text")
        if len(v) > limit:
            raise ValueError(f"{name} can be at most {limit} characters")
        return v

    try:
        clean = {
            "json_data": json_data,
            "title": text("title", MAX_TITLE),
            "short_alt": text("short_alt", MAX_ALT),
            "summary": text("summary", MAX_SUMMARY),
            "flowchart_type": text("flowchart_type", 16) or "flowchart",
        }
    except ValueError as e:
        return None, str(e)
    return clean, None
