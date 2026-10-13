"""Where the original image for a STEM image is kept.

Everything that stores or reads an original goes through `get_store()`. Today the bytes live in the
`stem_images` table (`DbImageStore`). If use grows, add an object-storage class with the same four
methods and switch `IMAGE_STORE`; callers and API responses do not change.

The store never commits: the caller commits, so a STEM image and its image are saved (or rolled
back) together.
"""
import base64
import binascii
import os
import re
import uuid

from backend.db import db
from backend.models import Flowchart, LongDescription, StemImage

ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp", "image/gif", "image/svg+xml"}
MAX_IMAGE_BYTES = int(os.environ.get("MAX_STEM_IMAGE_BYTES", str(8 * 1024 * 1024)))
_DATA_URL = re.compile(r"^data:(?P<mime>[a-z]+/[a-z0-9.+-]+);base64,(?P<b64>.*)$", re.DOTALL | re.IGNORECASE)


class ImageError(ValueError):
    """The image is not acceptable. The message is safe to show to the person."""


def parse_data_url(data_url):
    """'data:image/png;base64,...' -> (bytes, mime). Raises ImageError."""
    if not isinstance(data_url, str):
        raise ImageError("image_data_url must be text")
    m = _DATA_URL.match(data_url.strip())
    if not m:
        raise ImageError("image_data_url must be a base64 image data: URL")
    mime = m.group("mime").lower()
    if mime not in ALLOWED_MIME:
        raise ImageError("Only PNG, JPEG, WebP, GIF and SVG images can be kept")
    try:
        data = base64.b64decode(m.group("b64"), validate=True)
    except (binascii.Error, ValueError):
        raise ImageError("The image data could not be decoded")
    if not data:
        raise ImageError("The image is empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError(f"The image is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
    return data, mime


def to_data_url(data, mime):
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


class DbImageStore:
    def put(self, owner_id, data, mime):
        """Store the bytes and return the new opaque image id. Flushes; does not commit."""
        row = StemImage(image_id=str(uuid.uuid4()), owner_id=owner_id, mime=mime,
                        size_bytes=len(data), data=data)
        db.session.add(row)
        db.session.flush()
        return row.image_id

    def get(self, image_id, owner_id=None):
        """(bytes, mime) or None. With owner_id, only that owner's image is returned."""
        if not image_id:
            return None
        q = StemImage.query.filter_by(image_id=image_id)
        if owner_id is not None:
            q = q.filter_by(owner_id=owner_id)
        row = q.first()
        return (row.data, row.mime) if row else None

    def delete(self, image_id):
        """Remove the bytes. Returns True if there was something to remove. Does not commit."""
        if not image_id:
            return False
        return StemImage.query.filter_by(image_id=image_id).delete() > 0


def get_store():
    kind = os.environ.get("IMAGE_STORE", "db")
    if kind == "db":
        return DbImageStore()
    raise RuntimeError(f"Unknown IMAGE_STORE: {kind}")


def flowchart_image_data_url(r):
    """The original as a data: URL, from the store or from the legacy inline column. None if none.
    Works for any row with image_id and image_data_url columns (Flowchart, LongDescription)."""
    if getattr(r, "image_id", None):
        got = get_store().get(r.image_id)
        if got:
            return to_data_url(*got)
    return getattr(r, "image_data_url", None) or None


def set_flowchart_image(r, image_data_url):
    """Keep `image_data_url` as the original for row `r` (a Flowchart or LongDescription), replacing
    any earlier one. None or "" removes it. Raises ImageError. Does not commit."""
    store = get_store()
    old = r.image_id
    has_mime = hasattr(type(r), "image_mime")  # LongDescription has no mime column
    if not image_data_url:
        r.image_id = None
        r.image_data_url = None
        if has_mime:
            r.image_mime = None
    else:
        data, mime = parse_data_url(image_data_url)
        r.image_id = store.put(r.owner_id, data, mime)
        if has_mime:
            r.image_mime = mime
        r.image_data_url = None
    if old and old != r.image_id:
        store.delete(old)


def migrate_legacy_images(dry_run=False, batch=50):
    """Move inline `Flowchart.image_data_url` values into the store. Idempotent: rows that already
    have an image_id are skipped, and a row whose data cannot be parsed is left as it is and
    counted. Returns {"moved": n, "skipped_unreadable": n}."""
    counts = {"moved": 0, "skipped_unreadable": 0}
    pending = 0
    rows = []
    for model in (Flowchart, LongDescription):
        rows += model.query.filter(model.image_id.is_(None), model.image_data_url.isnot(None)).all()
    store = get_store()
    for r in rows:
        try:
            data, mime = parse_data_url(r.image_data_url)
        except ImageError:
            counts["skipped_unreadable"] += 1
            continue
        counts["moved"] += 1
        if dry_run:
            continue
        r.image_id = store.put(r.owner_id, data, mime)
        if hasattr(type(r), "image_mime"):
            r.image_mime = mime
        r.image_data_url = None
        pending += 1
        if pending >= batch:
            db.session.commit()
            pending = 0
    if not dry_run:
        db.session.commit()
    return counts
