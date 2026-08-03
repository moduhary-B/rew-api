from __future__ import annotations

import hashlib
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from rew_api.config import Settings
from rew_api.models import ApiKey, Project, utcnow


API_KEY_PREFIX = "rew_live_"


def generate_api_key() -> str:
    return API_KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(raw_key: str, settings: Settings) -> str:
    value = f"{settings.api_key_pepper}:{raw_key}".encode()
    return hashlib.sha256(value).hexdigest()


def create_api_key(
    session: Session,
    project: Project,
    *,
    name: str,
    settings: Settings,
) -> tuple[ApiKey, str]:
    raw_key = generate_api_key()
    record = ApiKey(
        project=project,
        name=name,
        key_prefix=raw_key[:20],
        key_hash=hash_api_key(raw_key, settings),
    )
    session.add(record)
    session.flush()
    return record, raw_key


def authenticate_api_key(
    session: Session,
    raw_key: str,
    settings: Settings,
) -> Project | None:
    if not raw_key.startswith(API_KEY_PREFIX):
        return None

    key_hash = hash_api_key(raw_key, settings)
    record = session.scalar(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
    )
    if record is None or not record.project.is_active:
        return None

    record.last_used_at = utcnow()
    session.commit()
    return record.project
