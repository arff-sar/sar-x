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


def test_production_requires_explicit_override_when_redis_is_missing(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("ALLOW_SQLITE_IN_PRODUCTION", "1")
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("RATELIMIT_STORAGE_URI", raising=False)
    monkeypatch.delenv("ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION", raising=False)

    with pytest.raises(RuntimeError, match="memory:// rate-limit storage kullanılamaz"):
        create_app("production")


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
