from sqlalchemy import text

from extensions import audit_log, db, log_kaydet, reset_schema_cache


def test_log_kaydet_uses_runtime_schema_without_poisoning_transaction(app):
    with app.app_context():
        db.session.execute(text("DROP TABLE IF EXISTS islem_log"))
        db.session.execute(
            text(
                """
                CREATE TABLE islem_log (
                    id INTEGER PRIMARY KEY,
                    kullanici_id INTEGER,
                    islem_tipi VARCHAR(50) NOT NULL,
                    detay TEXT,
                    ip_adresi VARCHAR(45),
                    user_agent VARCHAR(200),
                    zaman DATETIME
                )
                """
            )
        )
        db.session.commit()
        reset_schema_cache()

        with app.test_request_context("/__test-log"):
            log_kaydet(
                "Sistem",
                "Legacy islem_log semasina yazildi.",
                commit=False,
                error_code="SAR-X-TEST-0001",
                resolved=False,
            )
            db.session.commit()

        count = db.session.execute(text("SELECT COUNT(*) FROM islem_log")).scalar_one()

    assert count == 1


def test_log_kaydet_without_request_context_uses_safe_fallbacks(app):
    with app.app_context():
        db.session.execute(text("DROP TABLE IF EXISTS islem_log"))
        db.session.execute(
            text(
                """
                CREATE TABLE islem_log (
                    id INTEGER PRIMARY KEY,
                    kullanici_id INTEGER,
                    islem_tipi VARCHAR(50) NOT NULL,
                    detay TEXT,
                    ip_adresi VARCHAR(45),
                    user_agent VARCHAR(200),
                    zaman DATETIME
                )
                """
            )
        )
        db.session.commit()
        reset_schema_cache()

        log_kaydet("Sistem", "Request context olmadan da log yazilabilir.")

        row = db.session.execute(
            text("SELECT ip_adresi, user_agent FROM islem_log ORDER BY id DESC LIMIT 1")
        ).one()

    assert row.ip_adresi is None
    assert row.user_agent is None


def test_audit_log_outside_app_context_is_noop():
    audit_log("test_event", actor="system")
