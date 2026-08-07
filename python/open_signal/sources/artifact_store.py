"""Content-addressed artifact store (spec §95, §115, OS-006).

- SHA-256 content addressing with deduplication (same hash stored once)
- separate public / private buckets
- retention metadata on the raw_artifacts row
- signed access (HMAC-token URLs locally, presigned URLs on S3)

LocalArtifactStore is the default for development and fixtures;
S3ArtifactStore wraps boto3 (optional ``aws`` extra).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

PUBLIC_BUCKET = "public"
PRIVATE_BUCKET = "private"


class ArtifactStore(ABC):
    """Low-level byte store. Keys are ``<bucket>/<sha256>``."""

    @abstractmethod
    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> None: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def sign_url(self, key: str, expires_in: int = 3600) -> str: ...


class LocalArtifactStore(ArtifactStore):
    """Filesystem store. ``base_dir/public`` and ``base_dir/private``."""

    def __init__(self, base_dir: str | Path, secret: str = "dev-secret") -> None:
        self.base_dir = Path(base_dir)
        self.public_dir = self.base_dir / PUBLIC_BUCKET
        self.private_dir = self.base_dir / PRIVATE_BUCKET
        self.secret = secret.encode()
        self.public_dir.mkdir(parents=True, exist_ok=True)
        self.private_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        bucket, name = key.split("/", 1)
        if bucket not in (PUBLIC_BUCKET, PRIVATE_BUCKET):
            raise ValueError(f"unknown bucket {bucket!r}")
        base = self.public_dir if bucket == PUBLIC_BUCKET else self.private_dir
        return base / name

    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def sign_url(self, key: str, expires_in: int = 3600) -> str:
        """HMAC-signed URL token (development form)."""
        if not self.exists(key):
            raise FileNotFoundError(key)
        expires = int(time.time()) + expires_in
        message = f"{key}:{expires}".encode()
        token = hmac.new(self.secret, message, hashlib.sha256).hexdigest()
        return f"local://{key}?expires={expires}&sig={token}"

    def verify_signed_url(self, url: str) -> bool:
        try:
            _, query = url.split("?", 1)
            parts = dict(p.split("=", 1) for p in query.split("&"))
            key = url.split("//", 1)[1].split("?", 1)[0]
            expected = hmac.new(
                self.secret,
                f"{key}:{parts['expires']}".encode(),
                hashlib.sha256,
            ).hexdigest()
            return hmac.compare_digest(parts["sig"], expected) and int(parts["expires"]) >= int(time.time())
        except (KeyError, ValueError):
            return False


class S3ArtifactStore(ArtifactStore):
    """S3-compatible store using presigned URLs (optional ``aws`` extra)."""

    def __init__(self, bucket: str, *, endpoint_url: str | None = None, **client_kwargs: Any) -> None:
        try:
            import boto3  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("S3ArtifactStore requires 'boto3' (install with pip install boto3)") from exc
        self.bucket = bucket
        self._client = boto3.client("s3", endpoint_url=endpoint_url, **client_kwargs)

    def _key(self, key: str) -> str:
        # S3 keys may not contain the bucket prefix; use bucket as prefix.
        return key

    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        self._client.put_object(Bucket=self.bucket, Key=self._key(key), Body=data, **extra)

    def get(self, key: str) -> bytes:
        resp = self._client.get_object(Bucket=self.bucket, Key=self._key(key))
        return resp["Body"].read()

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=self._key(key))
            return True
        except Exception:  # noqa: BLE001
            return False

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=self._key(key))

    def sign_url(self, key: str, expires_in: int = 3600) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": self._key(key)},
            ExpiresIn=expires_in,
        )


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
