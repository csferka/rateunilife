import os
import re
import time
import uuid
from urllib.parse import urlparse

from flask import current_app
from werkzeug.utils import secure_filename

from models import Tag, UNIVERSITY_TAG_PREFIX, db

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
ALLOWED_VIDEO_EXTENSIONS = {"mp4", "webm", "mov", "m4v"}
RATE_LIMIT_ATTEMPTS = {}


def get_media_kind(filename):
    if not filename or "." not in filename:
        return None

    extension = filename.rsplit(".", 1)[1].lower()
    if extension in ALLOWED_IMAGE_EXTENSIONS:
        return "image", extension
    if extension in ALLOWED_VIDEO_EXTENSIONS:
        return "video", extension
    return None


def save_uploaded_media(file_storage, upload_folder):
    if not file_storage or not file_storage.filename:
        return None, None

    kind_info = get_media_kind(file_storage.filename)
    if not kind_info:
        return None, None

    media_type, extension = kind_info
    filename = secure_filename(f"{uuid.uuid4().hex}.{extension}")
    absolute_path = os.path.join(upload_folder, filename)
    file_storage.save(absolute_path)
    return f"uploads/{filename}", media_type


def remove_media_file(media_path, app_root):
    if not media_path:
        return

    absolute_path = os.path.join(app_root, "static", media_path)
    if os.path.exists(absolute_path):
        os.remove(absolute_path)


def normalize_university_slug(raw_value):
    cleaned = raw_value.strip().lower()
    if not cleaned:
        return None
    normalized = re.sub(r"[^a-z0-9]+", "-", cleaned).strip("-")
    return normalized or None


def sync_post_tags(post, raw_tags, university_slug):
    tag_names = []
    seen = set()
    for value in raw_tags.split(","):
        cleaned = value.strip().lower().lstrip("#")
        if cleaned.startswith(UNIVERSITY_TAG_PREFIX):
            continue
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            tag_names.append(cleaned)

    if university_slug:
        university_tag_name = f"{UNIVERSITY_TAG_PREFIX}{university_slug}"
        if university_tag_name not in seen:
            tag_names.insert(0, university_tag_name)

    post.tags.clear()
    for tag_name in tag_names:
        tag = Tag.query.filter_by(name=tag_name).first()
        if not tag:
            tag = Tag(name=tag_name)
            db.session.add(tag)
            db.session.flush()
        post.tags.append(tag)


def is_safe_next_url(target):
    if not target:
        return False
    parsed = urlparse(target)
    return parsed.netloc == "" and not parsed.scheme


def available_languages():
    return current_app.config.get("LANGUAGES", {"en": "EN", "uz": "UZ"})


def is_rate_limited(key, limit=7, window_seconds=300):
    now = time.time()
    attempts = RATE_LIMIT_ATTEMPTS.get(key, [])
    recent_attempts = [stamp for stamp in attempts if now - stamp < window_seconds]
    RATE_LIMIT_ATTEMPTS[key] = recent_attempts
    return len(recent_attempts) >= limit


def record_failed_attempt(key):
    RATE_LIMIT_ATTEMPTS.setdefault(key, []).append(time.time())


def clear_failed_attempts(key):
    RATE_LIMIT_ATTEMPTS.pop(key, None)


def university_label_from_slug(slug):
    if not slug:
        return None
    return slug.replace("-", " ").title()
