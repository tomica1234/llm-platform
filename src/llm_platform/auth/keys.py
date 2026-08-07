import base64
import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from llm_platform.common.errors import AuthenticationError, AuthorizationError

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1


def key_prefix(api_key: str) -> str:
    return api_key[:8]


def hash_api_key(api_key: str, *, salt: bytes | None = None) -> str:
    if len(api_key) < 16:
        raise ValueError("API key must contain at least 16 characters")
    salt_value = salt or os.urandom(16)
    digest = hashlib.scrypt(
        api_key.encode(), salt=salt_value, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32
    )
    salt_text = base64.urlsafe_b64encode(salt_value).decode()
    digest_text = base64.urlsafe_b64encode(digest).decode()
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt_text}${digest_text}"


def verify_api_key(api_key: str, encoded: str) -> bool:
    try:
        name, n_text, r_text, p_text, salt_text, expected_text = encoded.split("$")
        if name != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_text)
        expected = base64.urlsafe_b64decode(expected_text)
        candidate = hashlib.scrypt(
            api_key.encode(),
            salt=salt,
            n=int(n_text),
            r=int(r_text),
            p=int(p_text),
            dklen=len(expected),
        )
        return hmac.compare_digest(candidate, expected)
    except (ValueError, TypeError):
        return False


@dataclass(frozen=True, slots=True)
class ApiPrincipal:
    user_id: str
    scopes: frozenset[str]
    model_permissions: frozenset[str]
    max_concurrency: int = 1

    def require_scope(self, scope: str) -> None:
        if scope not in self.scopes:
            raise AuthorizationError(f"scope required: {scope}")


@dataclass(slots=True)
class KeyRecord:
    key_id: str
    prefix: str
    encoded_hash: str
    principal: ApiPrincipal
    expires_at: datetime | None = None
    revoked_at: datetime | None = None


class KeyStore(Protocol):
    async def candidates(self, prefix: str) -> list[KeyRecord]: ...


class InMemoryKeyStore:
    def __init__(self, records: list[KeyRecord] | None = None) -> None:
        self.records = records or []

    async def candidates(self, prefix: str) -> list[KeyRecord]:
        return [record for record in self.records if hmac.compare_digest(record.prefix, prefix)]


async def authenticate(
    api_key: str, store: KeyStore, *, now: datetime | None = None
) -> ApiPrincipal:
    current = now or datetime.now().astimezone()
    records = await store.candidates(key_prefix(api_key))
    selected: KeyRecord | None = None
    for record in records:
        matches = verify_api_key(api_key, record.encoded_hash)
        if matches and selected is None:
            selected = record
    if selected is None or selected.revoked_at is not None:
        raise AuthenticationError()
    if selected.expires_at is not None and selected.expires_at <= current:
        raise AuthenticationError("API key has expired")
    return selected.principal
