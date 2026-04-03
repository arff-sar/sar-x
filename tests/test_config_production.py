import pytest

from app import create_app


def test_production_requires_strong_secret_key(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("ALLOW_SQLITE_IN_PRODUCTION", "1")
    monkeypatch.setenv("ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION", "1")
    monkeypatch.delenv("SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app("production")


def test_production_rejects_sqlite_without_override(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("ALLOW_SQLITE_IN_PRODUCTION", "0")
    monkeypatch.setenv("ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION", "1")

    with pytest.raises(RuntimeError, match="sqlite"):
        create_app("production")


def test_production_scheduler_disabled_by_default(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("ALLOW_SQLITE_IN_PRODUCTION", "1")
    monkeypatch.setenv("ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION", "1")
    monkeypatch.delenv("ENABLE_SCHEDULER", raising=False)

    app = create_app("production")
    assert app.config["ENABLE_SCHEDULER"] is False


def test_production_defaults_to_memory_rate_limit_storage_when_unset(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("ALLOW_SQLITE_IN_PRODUCTION", "1")
    monkeypatch.delenv("RATELIMIT_STORAGE_URI", raising=False)
    monkeypatch.delenv("ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION", raising=False)

    with pytest.raises(RuntimeError, match="ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION"):
        create_app("production")


def test_production_uses_explicit_rate_limit_storage_uri(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("ALLOW_SQLITE_IN_PRODUCTION", "1")
    monkeypatch.setenv("RATELIMIT_STORAGE_URI", "memory://")
    monkeypatch.setenv("ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION", "1")

    app = create_app("production")
    assert app.config["RATELIMIT_STORAGE_URI"] == "memory://"


def test_production_passkey_requires_explicit_rp_id(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("ALLOW_SQLITE_IN_PRODUCTION", "1")
    monkeypatch.setenv("ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION", "1")
    monkeypatch.setenv("PASSKEY_ENABLED", "1")
    monkeypatch.delenv("PASSKEY_RP_ID", raising=False)
    monkeypatch.delenv("PASSKEY_ORIGIN", raising=False)
    monkeypatch.delenv("PASSKEY_ALLOWED_ORIGINS", raising=False)

    with pytest.raises(RuntimeError, match="PASSKEY_RP_ID"):
        create_app("production")


def test_production_passkey_rejects_insecure_origin(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("ALLOW_SQLITE_IN_PRODUCTION", "1")
    monkeypatch.setenv("ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION", "1")
    monkeypatch.setenv("PASSKEY_ENABLED", "1")
    monkeypatch.setenv("PASSKEY_RP_ID", "example.com")
    monkeypatch.setenv("PASSKEY_ORIGIN", "http://example.com")
    monkeypatch.delenv("PASSKEY_ALLOWED_ORIGINS", raising=False)

    with pytest.raises(RuntimeError, match="güvenli değil"):
        create_app("production")


def test_production_passkey_rejects_origin_host_mismatch(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("ALLOW_SQLITE_IN_PRODUCTION", "1")
    monkeypatch.setenv("ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION", "1")
    monkeypatch.setenv("PASSKEY_ENABLED", "1")
    monkeypatch.setenv("PASSKEY_RP_ID", "example.com")
    monkeypatch.setenv("PASSKEY_ORIGIN", "https://login.other-example.com")
    monkeypatch.delenv("PASSKEY_ALLOWED_ORIGINS", raising=False)

    with pytest.raises(RuntimeError, match="PASSKEY_RP_ID ile uyumlu değil"):
        create_app("production")


def test_production_passkey_accepts_valid_rollout_config(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("ALLOW_SQLITE_IN_PRODUCTION", "1")
    monkeypatch.setenv("ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION", "1")
    monkeypatch.setenv("PASSKEY_ENABLED", "1")
    monkeypatch.setenv("PASSKEY_RP_ID", "example.com")
    monkeypatch.setenv("PASSKEY_ORIGIN", "https://login.example.com")
    monkeypatch.delenv("PASSKEY_ALLOWED_ORIGINS", raising=False)

    app = create_app("production")

    assert app.config["PASSKEY_ENABLED"] is True
    assert app.config["PASSKEY_RP_ID"] == "example.com"


def test_production_rejects_demo_tools_enabled(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("ALLOW_SQLITE_IN_PRODUCTION", "1")
    monkeypatch.setenv("DEMO_TOOLS_ENABLED", "1")
    monkeypatch.setenv("ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION", "1")

    with pytest.raises(RuntimeError, match="DEMO_TOOLS_ENABLED"):
        create_app("production")


def test_production_rejects_memory_rate_limit_storage_for_non_sqlite(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/sarx")
    monkeypatch.delenv("RATELIMIT_STORAGE_URI", raising=False)
    monkeypatch.setenv("DEMO_TOOLS_ENABLED", "0")

    with pytest.raises(RuntimeError, match="memory rate-limit storage"):
        create_app("production")


def test_production_rejects_local_storage_for_non_sqlite_without_override(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/sarx")
    monkeypatch.setenv("RATELIMIT_STORAGE_URI", "redis://localhost:6379/0")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.delenv("ALLOW_LOCAL_STORAGE_IN_PRODUCTION", raising=False)

    with pytest.raises(RuntimeError, match="local storage backend"):
        create_app("production")
