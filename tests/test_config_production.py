import pytest

from app import create_app


def test_production_requires_strong_secret_key(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("ALLOW_SQLITE_IN_PRODUCTION", "1")
    monkeypatch.delenv("SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app("production")


def test_production_rejects_sqlite_without_override(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("ALLOW_SQLITE_IN_PRODUCTION", "0")

    with pytest.raises(RuntimeError, match="sqlite"):
        create_app("production")


def test_production_scheduler_disabled_by_default(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("ALLOW_SQLITE_IN_PRODUCTION", "1")
    monkeypatch.delenv("ENABLE_SCHEDULER", raising=False)

    app = create_app("production")
    assert app.config["ENABLE_SCHEDULER"] is False


def test_production_logs_clear_warning_when_redis_is_missing(monkeypatch, caplog):
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("ALLOW_SQLITE_IN_PRODUCTION", "1")
    monkeypatch.delenv("REDIS_URL", raising=False)

    caplog.set_level("WARNING")
    create_app("production")

    assert "REDIS_URL tanımlı değil" in caplog.text
    assert "memory:// fallback" in caplog.text
