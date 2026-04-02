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
            "ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION": "1",
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
    assert "passkey_credential" in tables
    assert "asset_spare_part_link" in tables
    assert "email_change_token" in tables
    assert "user_notification_preference" in tables
    assert "push_device_subscription" in tables
    assert "airport_message" in tables
    assert "error_report" in tables
    assert "islem_log_archive" in tables
    assert "ppe_assignment_record" in tables
    assert "ppe_assignment_item" in tables

    with sqlite3.connect(db_path) as connection:
        passkey_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(passkey_credential)").fetchall()
        }
    assert {"friendly_name", "is_active", "revoked_at"} <= passkey_columns

    with sqlite3.connect(db_path) as connection:
        islem_log_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(islem_log)").fetchall()
        }
    assert "resolved" in islem_log_columns
    assert "resolution_note" in islem_log_columns
    assert "havalimani_id" in islem_log_columns

    with sqlite3.connect(db_path) as connection:
        kullanici_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(kullanici)").fetchall()
        }
        ppe_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(ppe_record)").fetchall()
        }
        ppe_assignment_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(ppe_assignment_record)").fetchall()
        }
    assert {"kan_grubu_harf", "kan_grubu_rh", "boy_cm", "kilo_kg", "ayak_numarasi", "beden", "ust_beden", "alt_beden"} <= kullanici_columns
    assert {
        "category",
        "subcategory",
        "brand",
        "model_name",
        "serial_no",
        "apparel_size",
        "shoe_size",
        "production_date",
        "expiry_date",
        "physical_condition",
        "is_active",
        "manufacturer_url",
        "signed_document_key",
        "signed_document_url",
        "signed_document_name",
        "ppe_assignment_id",
    } <= ppe_columns
    assert {
        "assignment_no",
        "delivered_by_name",
        "recipient_user_id",
        "signed_document_drive_file_id",
        "signed_document_drive_folder_id",
    } <= ppe_assignment_columns

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
    assert current_revision == "c6d8e2f4a1b3"


def test_drifted_a7_database_recovers_missing_ppe_assignment_link_column(app):
    project_root = Path(app.root_path)
    db_path = project_root / "instance" / "test_migration_ppe_assignment_link_repair.db"
    if db_path.exists():
        db_path.unlink()

    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        connection.execute(
            "INSERT INTO alembic_version (version_num) VALUES (?)",
            ("a7b1c3d5e9f1",),
        )
        connection.execute(
            """
            CREATE TABLE ppe_assignment_record (
                id INTEGER NOT NULL PRIMARY KEY,
                assignment_no VARCHAR(40) NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE ppe_record (
                id INTEGER NOT NULL PRIMARY KEY,
                user_id INTEGER,
                airport_id INTEGER,
                assignment_id INTEGER
            )
            """
        )
        connection.commit()

    env = _build_production_env(db_path)
    upgrade = _run_upgrade(project_root, env)
    assert upgrade.returncode == 0, upgrade.stderr

    with sqlite3.connect(db_path) as connection:
        ppe_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(ppe_record)").fetchall()
        }
        ppe_indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(ppe_record)").fetchall()
        }
        current_revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0]

    assert "ppe_assignment_id" in ppe_columns
    assert "ix_ppe_record_ppe_assignment_id" in ppe_indexes
    assert current_revision == "c6d8e2f4a1b3"


def test_runtime_sqlite_schema_compat_repairs_drifted_user_and_passkey_columns(app, monkeypatch):
    project_root = Path(app.root_path)
    db_path = project_root / "instance" / "test_runtime_schema_compat.db"
    if db_path.exists():
        db_path.unlink()

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE kullanici (
                id INTEGER NOT NULL PRIMARY KEY,
                kullanici_adi VARCHAR(50) NOT NULL UNIQUE,
                sifre_hash VARCHAR(256),
                tam_ad VARCHAR(100) NOT NULL,
                rol VARCHAR(20) NOT NULL DEFAULT 'personel',
                havalimani_id INTEGER,
                kayit_tarihi DATETIME,
                created_at DATETIME,
                updated_at DATETIME,
                is_deleted BOOLEAN DEFAULT 0,
                deleted_at DATETIME
            )
            """
        )
        connection.execute(
            """
            INSERT INTO kullanici (id, kullanici_adi, tam_ad, rol, is_deleted)
            VALUES (1, 'mehmetcinocevi@gmail.com', 'Mehmet', 'sahip', 0)
            """
        )
        connection.execute(
            """
            CREATE TABLE passkey_credential (
                id INTEGER NOT NULL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                credential_id VARCHAR(255) NOT NULL,
                public_key TEXT NOT NULL,
                algorithm INTEGER NOT NULL,
                sign_count INTEGER NOT NULL DEFAULT 0,
                transports_json TEXT,
                backup_eligible BOOLEAN DEFAULT 0,
                backup_state BOOLEAN DEFAULT 0,
                last_used_at DATETIME,
                created_at DATETIME,
                updated_at DATETIME
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE havalimani (
                id INTEGER NOT NULL PRIMARY KEY,
                ad VARCHAR(100) NOT NULL,
                kodu VARCHAR(10) NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE equipment_template (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(120) NOT NULL,
                category VARCHAR(80),
                brand VARCHAR(80),
                model_code VARCHAR(80),
                maintenance_period_days INTEGER,
                is_active BOOLEAN DEFAULT 1
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE inventory_asset (
                id INTEGER NOT NULL PRIMARY KEY,
                equipment_template_id INTEGER NOT NULL,
                havalimani_id INTEGER NOT NULL,
                serial_no VARCHAR(120),
                qr_code VARCHAR(150),
                asset_tag VARCHAR(120),
                unit_count INTEGER DEFAULT 1,
                status VARCHAR(30) DEFAULT 'aktif',
                maintenance_period_days INTEGER,
                created_at DATETIME,
                updated_at DATETIME,
                is_deleted BOOLEAN DEFAULT 0,
                deleted_at DATETIME
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE kutu (
                id INTEGER NOT NULL PRIMARY KEY,
                kodu VARCHAR(50) NOT NULL,
                konum VARCHAR(100),
                havalimani_id INTEGER NOT NULL,
                created_at DATETIME,
                updated_at DATETIME,
                is_deleted BOOLEAN DEFAULT 0,
                deleted_at DATETIME
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE assignment_record (
                id INTEGER NOT NULL PRIMARY KEY,
                assignment_no VARCHAR(40) NOT NULL,
                assignment_date DATE,
                delivered_by_id INTEGER,
                airport_id INTEGER,
                note TEXT,
                status VARCHAR(20),
                created_by_id INTEGER,
                signed_document_key VARCHAR(255),
                signed_document_url VARCHAR(500),
                signed_document_name VARCHAR(180),
                created_at DATETIME,
                updated_at DATETIME,
                is_deleted BOOLEAN DEFAULT 0,
                deleted_at DATETIME
            )
            """
        )
        connection.commit()

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SECRET_KEY", "test-runtime-schema-compat-secret-key-123456")

    from app import create_app
    from extensions import db
    from models import Kullanici

    runtime_app = create_app("development")

    with sqlite3.connect(db_path) as connection:
        kullanici_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(kullanici)").fetchall()
        }
        passkey_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(passkey_credential)").fetchall()
        }
        havalimani_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(havalimani)").fetchall()
        }
        equipment_template_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(equipment_template)").fetchall()
        }
        inventory_asset_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(inventory_asset)").fetchall()
        }
        kutu_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(kutu)").fetchall()
        }
        assignment_record_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(assignment_record)").fetchall()
        }

    assert {
        "telefon_numarasi",
        "kan_grubu_harf",
        "kan_grubu_rh",
        "boy_cm",
        "kilo_kg",
        "ayak_numarasi",
        "beden",
        "ust_beden",
        "alt_beden",
        "sertifika_tarihi",
        "uzmanlik_alani",
    } <= kullanici_columns
    assert {"friendly_name", "is_active", "revoked_at"} <= passkey_columns
    assert {"drive_folder_id"} <= havalimani_columns
    assert {"maintenance_period_months"} <= equipment_template_columns
    assert {
        "asset_type",
        "is_demirbas",
        "calibration_required",
        "calibration_period_days",
        "maintenance_period_months",
        "manual_url",
    } <= inventory_asset_columns
    assert {"marka"} <= kutu_columns
    assert {"delivered_by_name"} <= assignment_record_columns

    with runtime_app.app_context():
        user = db.session.get(Kullanici, 1)

    assert user is not None
    assert user.kullanici_adi == "mehmetcinocevi@gmail.com"
