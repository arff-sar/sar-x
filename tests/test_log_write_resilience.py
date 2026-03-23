from sqlalchemy import text

from extensions import db, log_kaydet, reset_schema_cache


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
