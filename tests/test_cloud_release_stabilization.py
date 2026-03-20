import io
import logging
import sys
from types import ModuleType
from pathlib import Path

from scheduler import start_scheduler
from storage import get_storage_adapter


class _DummyUpload:
    def __init__(self, payload=b"payload", mimetype="image/png"):
        self.stream = io.BytesIO(payload)
        self.mimetype = mimetype


def test_gcs_storage_adapter_saves_upload_with_public_url(app, monkeypatch):
    recorded = {}

    class FakeBlob:
        def __init__(self, key):
            self.key = key
            self.cache_control = None

        def upload_from_file(self, stream, rewind=False, content_type=None):
            if rewind:
                stream.seek(0)
            recorded["payload"] = stream.read()
            recorded["content_type"] = content_type
            recorded["cache_control"] = self.cache_control

        def make_public(self):
            recorded["made_public"] = True

    class FakeBucket:
        def blob(self, key):
            recorded["storage_key"] = key
            return FakeBlob(key)

    class FakeClient:
        def __init__(self, project=None):
            recorded["project"] = project

        def bucket(self, name):
            recorded["bucket"] = name
            return FakeBucket()

    google_module = ModuleType("google")
    cloud_module = ModuleType("google.cloud")
    storage_module = ModuleType("google.cloud.storage")
    storage_module.Client = FakeClient
    cloud_module.storage = storage_module
    google_module.cloud = cloud_module

    monkeypatch.setitem(sys.modules, "google", google_module)
    monkeypatch.setitem(sys.modules, "google.cloud", cloud_module)
    monkeypatch.setitem(sys.modules, "google.cloud.storage", storage_module)

    with app.app_context():
        app.config.update(
            {
                "STORAGE_BACKEND": "gcs",
                "GCS_BUCKET_NAME": "sarx-media",
                "GCS_PROJECT_ID": "demo-project",
                "GCS_UPLOAD_PREFIX": "uploads",
                "GCS_PUBLIC_BASE_URL": "https://cdn.example.com",
                "GCS_CACHE_CONTROL": "public, max-age=60",
                "GCS_MAKE_UPLOADS_PUBLIC": False,
            }
        )
        stored = get_storage_adapter().save_upload(_DummyUpload(), folder="cms", filename="hero.png")

    assert recorded["bucket"] == "sarx-media"
    assert recorded["project"] == "demo-project"
    assert recorded["storage_key"] == "uploads/cms/hero.png"
    assert recorded["content_type"] == "image/png"
    assert recorded["cache_control"] == "public, max-age=60"
    assert stored.storage_key == "uploads/cms/hero.png"
    assert stored.public_url == "https://cdn.example.com/uploads/cms/hero.png"
    assert stored.absolute_path == "gs://sarx-media/uploads/cms/hero.png"


def test_scheduler_is_blocked_in_cloud_run_web_service(monkeypatch):
    class DummyApp:
        def __init__(self):
            self.config = {
                "ENABLE_SCHEDULER": True,
                "ALLOW_CLOUD_RUN_WEB_SCHEDULER": False,
                "TESTING": False,
            }
            self.logger = logging.getLogger("tests.scheduler")
            self.debug = False

    monkeypatch.setenv("K_SERVICE", "sarx-web")
    monkeypatch.delenv("CLOUD_RUN_JOB", raising=False)
    monkeypatch.delenv("CLOUD_RUN_EXECUTION", raising=False)

    result = start_scheduler(DummyApp())

    assert result is None

    monkeypatch.delenv("K_SERVICE", raising=False)


def test_dockerfile_installs_dejavu_fonts_for_pdf_rendering(app):
    dockerfile = Path(app.root_path) / "Dockerfile"
    content = dockerfile.read_text(encoding="utf-8")

    assert "fonts-dejavu-core" in content
