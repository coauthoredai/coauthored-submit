"""The object store: a local directory in dev/tests, a GCS bucket in production.

arxiv-base's `arxiv.files.object_store` stores are read-only; this wraps them and adds the
writes that submit and announce need. Every write is atomic for readers: local files are
written to a temporary name and renamed, GCS object writes are atomic by design.
Keys are the same in both (`staging/...`, `ftp/arxiv/papers/...`, `orig/arxiv/papers/...`,
and `reasons.json` at the root, which browse requires; see `ensure_reasons_json`).
"""
import io
import os
import shutil
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO, Iterator

from arxiv.files import FileObj
from arxiv.files.object_store import GsObjectStore, LocalObjectStore


class Store(ABC):
    @abstractmethod
    def obj(self, key: str) -> FileObj: ...

    @abstractmethod
    def put(self, key: str, data: BinaryIO, content_type: str = "application/pdf") -> None: ...

    @abstractmethod
    def put_if_absent(self, key: str, data: bytes, content_type: str) -> bool:
        """Create `key` only if nothing is there (atomically). True if it was created."""

    @abstractmethod
    def copy(self, src: str, dst: str) -> None: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    def exists(self, key: str) -> bool:
        return self.obj(key).exists()

    def read_chunks(self, key: str, size: int = 1024 * 1024) -> Iterator[bytes]:
        with self.obj(key).open("rb") as fh:
            while chunk := fh.read(size):
                yield chunk


class LocalStore(Store):
    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._reader = LocalObjectStore(str(self.root))

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError(f"key escapes the store: {key!r}")
        return path

    def obj(self, key: str) -> FileObj:
        self._path(key)
        return self._reader.to_obj(key)

    def put(self, key: str, data: BinaryIO, content_type: str = "application/pdf") -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as out:
                shutil.copyfileobj(data, out)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def put_if_absent(self, key: str, data: bytes, content_type: str) -> bool:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as out:
                out.write(data)
            os.link(tmp, path)  # fails if the key exists: never overwrites
            return True
        except FileExistsError:
            return False
        finally:
            Path(tmp).unlink(missing_ok=True)

    def copy(self, src: str, dst: str) -> None:
        with open(self._path(src), "rb") as fh:
            self.put(dst, fh)

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def __repr__(self) -> str:
        return f"<LocalStore {self.root}>"


class GcsStore(Store):
    def __init__(self, bucket_name: str, client: object | None = None):
        from google.cloud import storage
        self.client = client or storage.Client()
        self.bucket = self.client.bucket(bucket_name)
        self._reader = GsObjectStore(self.bucket)

    def obj(self, key: str) -> FileObj:
        return self._reader.to_obj(key)

    def put(self, key: str, data: BinaryIO, content_type: str = "application/pdf") -> None:
        self.bucket.blob(key).upload_from_file(data, content_type=content_type, rewind=True)

    def put_if_absent(self, key: str, data: bytes, content_type: str) -> bool:
        from google.api_core.exceptions import PreconditionFailed
        try:
            self.bucket.blob(key).upload_from_file(io.BytesIO(data), content_type=content_type,
                                                   if_generation_match=0)
            return True
        except PreconditionFailed:
            return False

    def copy(self, src: str, dst: str) -> None:
        self.bucket.copy_blob(self.bucket.blob(src), self.bucket, dst)

    def delete(self, key: str) -> None:
        from google.api_core.exceptions import NotFound
        try:
            self.bucket.blob(key).delete()
        except NotFound:
            pass

    def __repr__(self) -> str:
        return f"<GcsStore gs://{self.bucket.name}>"


REASONS_KEY = "reasons.json"


def ensure_reasons_json(store: Store) -> bool:
    """Write `{}` to reasons.json at the store root if it is missing (CONTRACT.md: browse
    refuses to serve papers without it). Never overwrites an existing file."""
    return store.put_if_absent(REASONS_KEY, b"{}", "application/json")


def make_store(prefix: str) -> Store:
    if prefix.startswith("gs://"):
        bucket = prefix.removeprefix("gs://").rstrip("/")
        if not bucket or "/" in bucket:
            raise ValueError("STORAGE_PREFIX must be gs://BUCKET (the bucket root, as browse reads it)")
        return GcsStore(bucket)
    return LocalStore(prefix)
