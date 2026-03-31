from flask import g
from sqlalchemy import text

from error_handling import capture_error
from extensions import (
    audit_log,
    compact_log_detail,
    db,
    log_kaydet,
    reset_schema_cache,
    shorten_external_reference,
)
from models import IslemLog


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
            text("SELECT ip_adresi, user_agent, zaman FROM islem_log ORDER BY id DESC LIMIT 1")
        ).one()

    assert row.ip_adresi is None
    assert row.user_agent is None
    assert row.zaman is not None


def test_audit_log_outside_app_context_is_noop():
    audit_log("test_event", actor="system")


def test_shorten_external_reference_keeps_only_small_visible_portion():
    assert shorten_external_reference("drive-folder-reference-1234567890") == "dri...567890"
    assert shorten_external_reference("shortid") == "shortid"


def test_compact_log_detail_masks_urls_paths_and_truncates():
    compacted = compact_log_detail(
        "https://example.com/very/long/path /Users/shared/private/report.pdf  "
        "Google Drive error body with extra whitespace",
        limit=60,
    )

    assert "https://example.com" not in compacted
    assert "/Users/shared/private/report.pdf" not in compacted
    assert "[url]" in compacted
    assert "[path]" in compacted
    assert len(compacted) <= 60


def test_log_kaydet_normalizes_user_agent_to_short_summary(app):
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

        with app.test_request_context(
            "/__test-log",
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/123.0.6312.86 Safari/537.36"
                )
            },
        ):
            log_kaydet("Sistem", "Normalized user-agent logu.")
            row = db.session.execute(
                text("SELECT user_agent FROM islem_log ORDER BY id DESC LIMIT 1")
            ).one()

    assert row.user_agent == "Chrome | Windows | Desktop"


def test_capture_error_minimizes_exception_payload_but_keeps_error_class(app):
    with app.app_context():
        db.session.query(IslemLog).delete()
        db.session.commit()

        def _explode():
            raise RuntimeError(
                "https://example.com/reset?reset_token=secret-token "
                "password=hunter2 /Users/shared/private/report.pdf\n"
                "SELECT * FROM users WHERE email='user@example.com'"
            )

        with app.test_request_context(
            "/__test-error",
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 "
                    "Mobile/15E148 Safari/604.1"
                )
            },
        ):
            g.request_id = "sarx-log-min-1"
            try:
                _explode()
            except RuntimeError as exc:
                payload = capture_error(exception=exc, error_code="SAR-X-SYSTEM-5101")

        row = IslemLog.query.filter_by(request_id="sarx-log-min-1").order_by(IslemLog.id.desc()).first()

    assert row is not None
    assert payload["exception_message"] == row.exception_message
    assert payload["traceback_summary"] == row.traceback_summary
    assert "secret-token" not in row.exception_message
    assert "https://example.com" not in row.exception_message
    assert "/Users/shared/private/report.pdf" not in row.exception_message
    assert "SELECT * FROM users" not in row.exception_message
    assert "[url]" in row.exception_message
    assert "[path]" in row.exception_message
    assert "password=***" in row.exception_message
    assert "RuntimeError" in row.traceback_summary
    assert "frames=" in row.traceback_summary
    assert "_explode" in row.traceback_summary
    assert "https://example.com" not in row.traceback_summary
    assert "/Users/shared/private/report.pdf" not in row.traceback_summary
    assert row.user_agent == "Safari | iOS | Mobile"
    assert len(row.exception_message) <= 240
    assert len(row.traceback_summary) <= 400
