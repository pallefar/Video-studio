"""The ONE storage interface. All artefact I/O goes through ObjectStore.

Nothing outside this module touches boto3, and no worker code opens job
artefacts from local paths — MinIO locally, S3/R2 remotely, same code either
way. There is deliberately no ACL parameter on any method: objects can never
be made public through this interface (compliance C5 by construction).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pipeline_core.settings import Settings


class ObjectStore:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or Settings()
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client(
                "s3",
                endpoint_url=self.settings.s3_endpoint or None,
                aws_access_key_id=self.settings.s3_access_key,
                aws_secret_access_key=self.settings.s3_secret_key,
                region_name=self.settings.s3_region,
            )
        return self._client

    @property
    def bucket(self) -> str:
        return self.settings.s3_bucket

    def ensure_bucket(self) -> None:
        import botocore.exceptions

        try:
            self.client.head_bucket(Bucket=self.bucket)
        except botocore.exceptions.ClientError:
            self.client.create_bucket(Bucket=self.bucket)

    def uri_for(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"

    @staticmethod
    def parse_uri(uri: str) -> tuple[str, str]:
        if not uri.startswith("s3://"):
            raise ValueError(f"not an s3 uri: {uri!r}")
        bucket, _, key = uri[len("s3://") :].partition("/")
        if not bucket or not key:
            raise ValueError(f"malformed s3 uri: {uri!r}")
        return bucket, key

    def put_bytes(self, key: str, data: bytes, content_type: Optional[str] = None) -> str:
        extra = {"ContentType": content_type} if content_type else {}
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, **extra)
        return self.uri_for(key)

    def get_bytes(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def put_file(self, key: str, path: Path) -> str:
        import mimetypes

        content_type, _ = mimetypes.guess_type(key)
        extra = {"ContentType": content_type} if content_type else {}
        self.client.upload_file(str(path), self.bucket, key, ExtraArgs=extra)
        return self.uri_for(key)

    def get_file(self, key: str, path: Path) -> Path:
        self.client.download_file(self.bucket, key, str(path))
        return path

    def exists(self, key: str) -> bool:
        import botocore.exceptions

        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except botocore.exceptions.ClientError:
            return False

    def list_keys(self, prefix: str = "") -> list[str]:
        keys: list[str] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys.extend(obj["Key"] for obj in page.get("Contents", []))
        return keys

    def usage(self, prefix: str = "") -> dict:
        """Object count and total bytes under a prefix — the dashboard's
        storage tile. One listing pass; fine at single-user scale."""
        objects = 0
        total_bytes = 0
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                objects += 1
                total_bytes += obj.get("Size", 0)
        return {"objects": objects, "bytes": total_bytes}

    def presign_get(self, key: str, expires_seconds: int = 3600) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_seconds,
        )
