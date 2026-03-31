from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from flask import current_app


@dataclass
class StoredObject:
    storage_key: str
    public_url: str
    absolute_path: str


class BaseStorageAdapter:
    name = "base"

    def save_upload(self, upload, folder, filename):
        raise NotImplementedError

    def read_bytes(self, storage_key):
        raise NotImplementedError

    def storage_key_from_public_url(self, public_url):
        return None


def _build_storage_key(folder, filename):
    folder_part = str(folder or "").strip("/")
    filename_part = str(filename or "").strip().lstrip("/")
    if folder_part:
        return f"{folder_part}/{filename_part}".strip("/")
    return filename_part


class LocalStorageAdapter(BaseStorageAdapter):
    name = "local"

    def _root(self):
        configured = current_app.config.get("LOCAL_UPLOAD_ROOT")
        if configured:
            return Path(configured)
        return Path(current_app.root_path) / "static" / "uploads"

    def _public_prefix(self):
        prefix = (current_app.config.get("LOCAL_UPLOAD_URL_PREFIX") or "/static/uploads").strip() or "/static/uploads"
        return prefix.rstrip("/")

    def save_upload(self, upload, folder, filename):
        target_dir = self._root() / folder
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / filename
        upload.save(target_path)
        storage_key = _build_storage_key(folder, filename)
        public_url = f"{self._public_prefix()}/{storage_key}"
        return StoredObject(
            storage_key=storage_key,
            public_url=public_url,
            absolute_path=str(target_path),
        )

    def _path_for_storage_key(self, storage_key):
        root = self._root().resolve()
        target_path = (root / str(storage_key or "")).resolve()
        try:
            target_path.relative_to(root)
        except ValueError as exc:
            raise FileNotFoundError("Geçersiz storage key.") from exc
        return target_path

    def read_bytes(self, storage_key):
        return self._path_for_storage_key(storage_key).read_bytes()

    def storage_key_from_public_url(self, public_url):
        parsed = urlparse(str(public_url or "").strip())
        candidate = parsed.path if parsed.scheme or parsed.netloc else str(public_url or "").strip()
        prefix = f"{self._public_prefix()}/"
        if candidate.startswith(prefix):
            return unquote(candidate[len(prefix):])
        return None


class GCSStorageAdapter(BaseStorageAdapter):
    name = "gcs"

    def _bucket_name(self):
        return (current_app.config.get("GCS_BUCKET_NAME") or "").strip()

    def _project_id(self):
        return (current_app.config.get("GCS_PROJECT_ID") or "").strip() or None

    def _upload_prefix(self):
        return (current_app.config.get("GCS_UPLOAD_PREFIX") or "").strip().strip("/")

    def _public_base_url(self):
        return (current_app.config.get("GCS_PUBLIC_BASE_URL") or "").strip().rstrip("/")

    def _client(self):
        try:
            from google.cloud import storage as gcs
        except ImportError as exc:  # pragma: no cover - import path only
            raise RuntimeError("google-cloud-storage paketi kurulu değil.") from exc

        project_id = self._project_id()
        return gcs.Client(project=project_id) if project_id else gcs.Client()

    def _public_url(self, storage_key):
        encoded_key = quote(storage_key, safe="/")
        public_base = self._public_base_url()
        if public_base:
            return f"{public_base}/{encoded_key}"
        return f"https://storage.googleapis.com/{self._bucket_name()}/{encoded_key}"

    def save_upload(self, upload, folder, filename):
        bucket_name = self._bucket_name()
        if not bucket_name:
            raise RuntimeError("GCS storage backend aktif ancak GCS_BUCKET_NAME tanımlı değil.")

        folder_name = "/".join(
            part for part in [self._upload_prefix(), str(folder or "").strip("/")] if part
        )
        storage_key = _build_storage_key(folder_name, filename)
        blob = self._client().bucket(bucket_name).blob(storage_key)

        cache_control = (current_app.config.get("GCS_CACHE_CONTROL") or "").strip()
        if cache_control:
            blob.cache_control = cache_control

        stream = getattr(upload, "stream", None)
        if stream is None:
            raise RuntimeError("Yükleme akışı okunamadı.")
        try:
            stream.seek(0)
        except Exception:
            pass

        blob.upload_from_file(
            stream,
            rewind=True,
            content_type=(upload.mimetype or None),
        )

        if current_app.config.get("GCS_MAKE_UPLOADS_PUBLIC", False):
            blob.make_public()

        return StoredObject(
            storage_key=storage_key,
            public_url=self._public_url(storage_key),
            absolute_path=f"gs://{bucket_name}/{storage_key}",
        )

    def read_bytes(self, storage_key):
        bucket_name = self._bucket_name()
        if not bucket_name:
            raise RuntimeError("GCS storage backend aktif ancak GCS_BUCKET_NAME tanımlı değil.")
        blob = self._client().bucket(bucket_name).blob(storage_key)
        return blob.download_as_bytes()

    def storage_key_from_public_url(self, public_url):
        parsed = urlparse(str(public_url or "").strip())
        if not parsed.scheme or not parsed.netloc:
            return None
        normalized_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        public_base = self._public_base_url()
        if public_base:
            prefix = f"{public_base}/"
            if normalized_url.startswith(prefix):
                return unquote(normalized_url[len(prefix):])
        bucket_name = self._bucket_name()
        storage_prefix = f"https://storage.googleapis.com/{bucket_name}/"
        if normalized_url.startswith(storage_prefix):
            return unquote(normalized_url[len(storage_prefix):])
        return None


def get_storage_adapter():
    backend = str(current_app.config.get("STORAGE_BACKEND") or "local").strip().lower()
    if backend == "local":
        return LocalStorageAdapter()
    if backend == "gcs":
        return GCSStorageAdapter()
    raise RuntimeError(f"Desteklenmeyen storage backend: {backend}")
