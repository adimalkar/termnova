"""Durable original-document storage with local and S3-compatible backends."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from termnova.config import Settings, get_settings


class DocumentStorage:
    """Store and materialize uploaded originals without coupling workers to web disks."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def _s3_client(self):
        import boto3

        return boto3.client(
            "s3",
            endpoint_url=self.settings.STORAGE_ENDPOINT_URL,
            region_name=self.settings.STORAGE_REGION,
            aws_access_key_id=self.settings.STORAGE_ACCESS_KEY_ID,
            aws_secret_access_key=self.settings.STORAGE_SECRET_ACCESS_KEY,
        )

    async def put(self, object_key: str, content: bytes) -> None:
        """Persist bytes under an opaque object key."""
        if self.settings.STORAGE_BACKEND == "s3":
            if not self.settings.STORAGE_BUCKET:
                raise RuntimeError("STORAGE_BUCKET is required when STORAGE_BACKEND=s3")
            client = self._s3_client()
            await asyncio.to_thread(
                client.put_object,
                Bucket=self.settings.STORAGE_BUCKET,
                Key=object_key,
                Body=content,
            )
            return
        target = self.settings.upload_path / object_key
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_bytes, content)

    async def materialize(self, object_key: str, suffix: str = "") -> tuple[Path, bool]:
        """Return a worker-readable path and whether the caller must delete it."""
        if self.settings.STORAGE_BACKEND == "local":
            return self.settings.upload_path / object_key, False
        if not self.settings.STORAGE_BUCKET:
            raise RuntimeError("STORAGE_BUCKET is required when STORAGE_BACKEND=s3")
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            path = Path(tmp.name)
        client = self._s3_client()
        await asyncio.to_thread(
            client.download_file,
            self.settings.STORAGE_BUCKET,
            object_key,
            str(path),
        )
        return path, True

    async def delete(self, object_key: str) -> None:
        """Delete a stored original if present."""
        if self.settings.STORAGE_BACKEND == "s3":
            if self.settings.STORAGE_BUCKET:
                await asyncio.to_thread(
                    self._s3_client().delete_object,
                    Bucket=self.settings.STORAGE_BUCKET,
                    Key=object_key,
                )
            return
        path = self.settings.upload_path / object_key
        if path.exists():
            await asyncio.to_thread(path.unlink)
