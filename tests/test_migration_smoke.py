import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def _build_production_env(db_path):
    env = os.environ.copy()
    env.update(
        {
            "APP_ENV": "production",
            "DATABASE_URL": f"sqlite:///{db_path}",
            "ALLOW_SQLITE_IN_PRODUCTION": "1",
            "SECRET_KEY": "test-release-stabilization-secret-key-123456",
        }
    )
    return env


def _run_upgrade(project_root, env):
    return subprocess.run(
        [sys.executable, "-m", "flask", "--app", "app:create_app", "db", "upgrade"],
        cwd=str(project_root),
        env=env,
        capture_output=True,
        text=True,
    )


def test_fresh_database_can_upgrade_with_migrations(app, monkeypatch):
    project_root = Path(app.root_path)
    db_path = project_root / "instance" / "test_migration_smoke.db"
    if db_path.exists():
        db_path.unlink()

    env = _build_production_env(db_path)
    first_upgrade = _run_upgrade(project_root, env)
    assert first_upgrade.returncode == 0, first_upgrade.stderr

    # Aynı migration zinciri ikinci kez çalıştırıldığında da hata vermemeli (idempotent davranış).
    second_upgrade = _run_upgrade(project_root, env)
    assert second_upgrade.returncode == 0, second_upgrade.stderr

    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    assert "inventory_asset" in tables
    assert "work_order" in tables
    assert "notification" in tables
    assert "site_ayarlari" in tables
    assert "auth_lockout" in tables
    assert "login_visual_challenge" in tables
    assert "asset_spare_part_link" in tables

    with sqlite3.connect(db_path) as connection:
        islem_log_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(islem_log)").fetchall()
        }
    assert "resolved" in islem_log_columns
    assert "resolution_note" in islem_log_columns

    with sqlite3.connect(db_path) as connection:
        havalimani_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(havalimani)").fetchall()
        }
    assert "drive_folder_id" in havalimani_columns

    with sqlite3.connect(db_path) as connection:
        site_settings_count = connection.execute("SELECT COUNT(*) FROM site_ayarlari").fetchone()[0]
    assert site_settings_count >= 1

    for key, value in env.items():
        monkeypatch.setenv(key, value)

    from app import create_app

    runtime_app = create_app("production")
    with runtime_app.test_client() as client:
        ready_response = client.get("/ready")
    ready_payload = ready_response.get_json()

    assert ready_response.status_code == 200
    assert ready_payload["status"] == "ready"
    assert ready_payload["database"] == "ok"
    assert ready_payload["missing_tables"] == []
    assert ready_payload["seed_ready"] is True


def test_drifted_database_recovers_missing_havalimani_drive_folder_column(app):
    project_root = Path(app.root_path)
    db_path = project_root / "instance" / "test_migration_drive_folder_repair.db"
    if db_path.exists():
        db_path.unlink()

    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        connection.execute(
            "INSERT INTO alembic_version (version_num) VALUES (?)",
            ("a4c2e8b1d9f0",),
        )
        connection.execute(
            """
            CREATE TABLE havalimani (
                id INTEGER NOT NULL PRIMARY KEY,
                kodu VARCHAR(20),
                adi VARCHAR(120)
            )
            """
        )
        connection.commit()

    env = _build_production_env(db_path)
    upgrade = _run_upgrade(project_root, env)
    assert upgrade.returncode == 0, upgrade.stderr

    with sqlite3.connect(db_path) as connection:
        havalimani_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(havalimani)").fetchall()
        }
        havalimani_indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(havalimani)").fetchall()
        }
        current_revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0]

    assert "drive_folder_id" in havalimani_columns
    assert "ix_havalimani_drive_folder_id" in havalimani_indexes
    assert current_revision == "e8c4a1f7d2b0"
