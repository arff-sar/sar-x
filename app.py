import json
import logging
import os
import re
import time
import uuid
from datetime import datetime
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv
from flask import Flask, abort, g, jsonify, make_response, redirect, render_template, request, send_file, send_from_directory, url_for
from flask_wtf.csrf import CSRFError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException

from config import DevelopmentConfig, config_by_name
from extensions import csrf, db, executor, limiter, login_manager, migrate
from error_handling import capture_error, format_user_error_message, resolve_error_code
from routes.admin import admin_bp
from routes.api import api_bp
from routes.auth import auth_bp
from routes.content import content_bp
from routes.inventory import inventory_bp
from routes.maintenance import maintenance_bp
from routes.parts import parts_bp
from routes.reports import reports_bp
from scheduler import start_scheduler
from decorators import (
    build_sidebar_groups,
    can_use_role_switch,
    get_effective_role,
    get_effective_role_label,
    get_effective_permissions,
    get_legacy_compatible_role,
    get_role_descriptions,
    get_role_labels,
    get_role_switch_options,
    has_permission,
    is_impersonation_mode,
    is_role_switch_active,
    is_editor_only,
    role_home_endpoint,
    sanitize_role_override,
    should_block_control_plane,
    sync_authorization_registry,
)
from extensions import table_exists

load_dotenv()


def _normalize_config_name(value):
    return str(value or "").strip().lower()


def _resolve_runtime_config_name(config_name=None):
    explicit_name = _normalize_config_name(config_name)
    runtime_name = _normalize_config_name(os.getenv("APP_ENV") or os.getenv("FLASK_ENV"))
    selected_name = explicit_name or runtime_name
    if selected_name:
        if selected_name not in config_by_name:
            raise RuntimeError(
                "Geçersiz uygulama ortamı tanımı. "
                "APP_ENV/FLASK_ENV veya create_app(config_name) değeri "
                "'development', 'testing' veya 'production' olmalıdır."
            )
        return selected_name

    if os.getenv("FLASK_RUN_FROM_CLI"):
        return "development"

    return "production"


def _configure_logging(app):
    log_level = getattr(logging, str(app.config.get("LOG_LEVEL", "INFO")).upper(), logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    root_logger = logging.getLogger()
    if not root_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
    else:
        for handler in root_logger.handlers:
            handler.setFormatter(formatter)

    root_logger.setLevel(log_level)
    app.logger.setLevel(log_level)


def _is_secret_key_strong(secret_key):
    if not secret_key or not isinstance(secret_key, str):
        return False
    if len(secret_key.strip()) < 32:
        return False
    weak_values = {"changeme", "secret", "default", "123456", "password"}
    return secret_key.strip().lower() not in weak_values


def _is_sqlite_url(database_url):
    return bool(database_url and str(database_url).startswith("sqlite:"))


def _bool_env(name):
    raw = os.getenv(name)
    if raw is None:
        return None
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _redact_runtime_value(value):
    if value in [None, ""]:
        return value

    text = str(value)
    if "://" not in text:
        return text

    try:
        parsed = urlsplit(text)
    except Exception:
        return text

    if parsed.username is None and parsed.password is None:
        return text

    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    if parsed.username:
        auth = parsed.username
        if parsed.password is not None:
            auth = f"{auth}:***"
        netloc = f"{auth}@{netloc}" if netloc else f"{auth}@"

    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _log_production_runtime_risks(app):
    if str(app.config.get("ENV") or "").lower() != "production":
        return

    if str(app.config.get("STORAGE_BACKEND") or "local").strip().lower() == "local":
        app.logger.warning(
            "Production ortamında local storage backend aktif. "
            "Cloud Run dosya sistemi kalıcı değildir; medya dosyaları için Cloud Storage tercih edilmelidir."
        )
    elif not (app.config.get("GCS_BUCKET_NAME") or "").strip():
        app.logger.warning(
            "Production ortamında GCS storage backend seçilmiş ancak GCS_BUCKET_NAME tanımlı değil."
        )

    if app.config.get("DEMO_TOOLS_ENABLED"):
        app.logger.warning("Production ortamında demo araçları aktif. DEMO_TOOLS_ENABLED kapatılmalıdır.")

    if app.config.get("ALLOW_SQLITE_IN_PRODUCTION"):
        app.logger.warning(
            "Production ortamında sqlite override aktif. "
            "Bu ayar sadece geçici smoke/kurtarma senaryoları için kullanılmalıdır."
        )

    if app.config.get("ENABLE_SCHEDULER"):
        app.logger.warning(
            "Production ortamında web servis içinde scheduler aktif. "
            "Cloud Run web serviste scheduler yerine Cloud Run Jobs/Cloud Scheduler önerilir."
        )


def _is_local_passkey_host(host):
    normalized = str(host or "").strip().lower()
    return normalized in {"localhost", "127.0.0.1", "::1", "[::1]"} or normalized.endswith(".localhost")


def _validate_passkey_runtime_config(app, *, selected_env):
    if not app.config.get("PASSKEY_ENABLED"):
        return

    rp_id = str(app.config.get("PASSKEY_RP_ID") or "").strip().lower()
    raw_origins = []
    for key in ("PASSKEY_ALLOWED_ORIGINS", "PASSKEY_ORIGIN"):
        raw_value = app.config.get(key)
        if not raw_value:
            continue
        raw_origins.extend(part.strip().rstrip("/") for part in str(raw_value).split(",") if part.strip())

    if selected_env == "production":
        if not rp_id:
            raise RuntimeError(
                "PASSKEY_ENABLED açıksa production ortamında PASSKEY_RP_ID zorunludur."
            )
        if not raw_origins:
            raise RuntimeError(
                "PASSKEY_ENABLED açıksa production ortamında PASSKEY_ORIGIN veya "
                "PASSKEY_ALLOWED_ORIGINS zorunludur."
            )

    if not raw_origins:
        return

    for origin in raw_origins:
        parsed = urlsplit(origin)
        scheme = str(parsed.scheme or "").strip().lower()
        host = str(parsed.hostname or "").strip().lower()
        if scheme not in {"http", "https"} or not host:
            raise RuntimeError("Passkey origin ayarı geçersiz.")
        if scheme != "https" and not _is_local_passkey_host(host):
            raise RuntimeError("Passkey origin ayarı production rollout için güvenli değil.")
        if rp_id and not (host == rp_id or host.endswith(f".{rp_id}")):
            raise RuntimeError("Passkey origin host değeri PASSKEY_RP_ID ile uyumlu değil.")


def _apply_runtime_env_overrides(app):
    # SECRET_KEY değerini her create_app çağrısında çalışma zamanı env'den al.
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")

    runtime_database_url = os.getenv("DATABASE_URL")
    if runtime_database_url is not None:
        app.config["DATABASE_URL"] = runtime_database_url
        app.config["SQLALCHEMY_DATABASE_URI"] = runtime_database_url

    testing_database_url = os.getenv("TEST_DATABASE_URL")
    if app.config.get("ENV") == "testing" and testing_database_url:
        app.config["SQLALCHEMY_DATABASE_URI"] = testing_database_url

    direct_keys = [
        "MAIL_HOST",
        "MAIL_USERNAME",
        "MAIL_FROM_EMAIL",
        "MAIL_REPLY_TO",
        "MAIL_SECRET_PROJECT_ID",
        "MAIL_PASSWORD_SECRET_NAME",
        "MAIL_PASSWORD_SECRET_VERSION",
        "SMTP_PASSWORD",
        "REDIS_URL",
        "RATELIMIT_STORAGE_URI",
        "LOG_LEVEL",
        "STORAGE_BACKEND",
        "LOCAL_UPLOAD_ROOT",
        "LOCAL_UPLOAD_URL_PREFIX",
        "GCS_BUCKET_NAME",
        "GCS_PROJECT_ID",
        "GCS_UPLOAD_PREFIX",
        "GCS_PUBLIC_BASE_URL",
        "GCS_CACHE_CONTROL",
        "SESSION_COOKIE_SAMESITE",
        "REMEMBER_COOKIE_SAMESITE",
        "PASSKEY_RP_ID",
        "PASSKEY_RP_NAME",
        "PASSKEY_ORIGIN",
        "PASSKEY_ALLOWED_ORIGINS",
    ]
    for key in direct_keys:
        value = os.getenv(key)
        if value is None:
            continue
        app.config[key] = value

    int_keys = {
        "MAIL_PORT": 587,
        "REMEMBER_COOKIE_DURATION_DAYS": 7,
        "PERMANENT_SESSION_LIFETIME_MINUTES": 120,
        "PASSKEY_CHALLENGE_TTL_SECONDS": 180,
        "MAX_CONTENT_LENGTH": 16 * 1024 * 1024,
        "MAX_FORM_MEMORY_SIZE": 2 * 1024 * 1024,
        "MAX_FORM_PARTS": 200,
        "AUTH_LOCKOUT_ATTEMPTS": 5,
        "AUTH_LOCKOUT_MINUTES": 15,
    }
    for env_key, default in int_keys.items():
        raw = os.getenv(env_key)
        if raw is None:
            continue
        try:
            parsed = int(raw)
        except ValueError:
            parsed = default
        if env_key == "PERMANENT_SESSION_LIFETIME_MINUTES":
            from datetime import timedelta

            app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=parsed)
        elif env_key == "REMEMBER_COOKIE_DURATION_DAYS":
            from datetime import timedelta

            app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=parsed)
        else:
            app.config[env_key] = parsed

    bool_keys = [
        "SESSION_COOKIE_SECURE",
        "SESSION_COOKIE_HTTPONLY",
        "REMEMBER_COOKIE_SECURE",
        "REMEMBER_COOKIE_HTTPONLY",
        "ENABLE_SCHEDULER",
        "AUTO_CREATE_TABLES",
        "ALLOW_SQLITE_IN_PRODUCTION",
        "MAIL_USE_TLS",
        "HOMEPAGE_EDITOR_CAN_PUBLISH",
        "DEMO_TOOLS_ENABLED",
        "GCS_MAKE_UPLOADS_PUBLIC",
        "ALLOW_CLOUD_RUN_WEB_SCHEDULER",
        "ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION",
        "PASSKEY_ENABLED",
    ]
    for key in bool_keys:
        parsed = _bool_env(key)
        if parsed is not None:
            app.config[key] = parsed

    if app.config.get("RATELIMIT_STORAGE_URI"):
        app.config["RATELIMIT_STORAGE_URI"] = app.config.get("RATELIMIT_STORAGE_URI")
    elif app.config.get("REDIS_URL"):
        app.config["RATELIMIT_STORAGE_URI"] = app.config.get("REDIS_URL")


def _wants_json_response():
    if request.path.startswith("/api/"):
        return True
    best = request.accept_mimetypes.best_match(["application/json", "text/html"])
    return best == "application/json" and request.accept_mimetypes[best] > request.accept_mimetypes["text/html"]


def _append_vary_header(response, value):
    existing = [item.strip() for item in (response.headers.get("Vary") or "").split(",") if item.strip()]
    if value.lower() not in {item.lower() for item in existing}:
        existing.append(value)
        response.headers["Vary"] = ", ".join(existing)
    return response


def _response_requires_private_cache_busting():
    endpoint = request.endpoint or ""
    if endpoint == "static" or request.path.startswith("/static/"):
        return False
    if endpoint in {
        "serve_manifest",
        "serve_site_manifest",
        "serve_sw",
        "serve_robots",
        "serve_favicon_ico",
        "serve_favicon_png",
        "serve_apple_touch_icon",
        "serve_apple_touch_icon_precomposed",
        "serve_assetlinks",
        "health",
        "ready",
    }:
        return False
    if endpoint.startswith("auth."):
        return True

    try:
        from flask_login import current_user

        return bool(current_user.is_authenticated)
    except Exception:
        return False


def _apply_private_no_store_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return _append_vary_header(response, "Cookie")


def _error_response(status_code, message):
    if _wants_json_response():
        return jsonify({"status": "error", "message": message, "code": status_code}), status_code
    return render_template("hata.html", kod=status_code, mesaj=message), status_code


NOISE_404_EXACT_PATHS = {
    "/.env",
    "/.env.local",
    "/.env.production",
    "/.git",
    "/.git/config",
    "/.git/heads/master",
    "/wp-login.php",
    "/xmlrpc.php",
}
NOISE_404_PREFIXES = (
    "/.well-known/",
    "/wp-",
    "/wordpress",
    "/phpmyadmin",
    "/cgi-bin/",
    "/vendor/",
    "/boaform/",
)
NOISE_404_PATTERNS = (
    re.compile(r"/\.git(?:/|$)", re.IGNORECASE),
    re.compile(r"/\.env(?:\.|$)", re.IGNORECASE),
    re.compile(r"/(?:composer|package)\.(json|lock)$", re.IGNORECASE),
    re.compile(r"\.(php|asp|aspx|jsp)$", re.IGNORECASE),
)


def _is_noise_404_request():
    path = str(request.path or "").strip().lower()
    if not path:
        return False
    if path in NOISE_404_EXACT_PATHS:
        return True
    if any(path.startswith(prefix) for prefix in NOISE_404_PREFIXES):
        return True
    return any(pattern.search(path) for pattern in NOISE_404_PATTERNS)


def _sqlite_column_names(table_name):
    if not table_exists(table_name):
        return set()
    try:
        rows = db.session.execute(text(f"PRAGMA table_info({table_name})")).mappings().all()
    except SQLAlchemyError:
        return set()
    return {row.get("name") for row in rows if row.get("name")}


def _ensure_runtime_schema_compatibility(app):
    database_url = app.config.get("SQLALCHEMY_DATABASE_URI") or ""
    if not _is_sqlite_url(database_url):
        return
    if not table_exists("kullanici"):
        return

    mevcut_kolonlar = _sqlite_column_names("kullanici")
    if "telefon_numarasi" in mevcut_kolonlar:
        pass
    else:
        db.session.execute(text("ALTER TABLE kullanici ADD COLUMN telefon_numarasi VARCHAR(32)"))
        db.session.commit()
        app.logger.warning("Legacy sqlite şeması güncellendi: kullanici.telefon_numarasi eklendi.")

    if not table_exists("islem_log"):
        return

    islem_log_kolonlari = _sqlite_column_names("islem_log")
    required_columns = {
        "error_code": "ALTER TABLE islem_log ADD COLUMN error_code VARCHAR(32)",
        "title": "ALTER TABLE islem_log ADD COLUMN title VARCHAR(180)",
        "user_message": "ALTER TABLE islem_log ADD COLUMN user_message VARCHAR(255)",
        "owner_message": "ALTER TABLE islem_log ADD COLUMN owner_message TEXT",
        "module": "ALTER TABLE islem_log ADD COLUMN module VARCHAR(24)",
        "severity": "ALTER TABLE islem_log ADD COLUMN severity VARCHAR(20)",
        "exception_type": "ALTER TABLE islem_log ADD COLUMN exception_type VARCHAR(120)",
        "exception_message": "ALTER TABLE islem_log ADD COLUMN exception_message TEXT",
        "traceback_summary": "ALTER TABLE islem_log ADD COLUMN traceback_summary TEXT",
        "route": "ALTER TABLE islem_log ADD COLUMN route VARCHAR(255)",
        "method": "ALTER TABLE islem_log ADD COLUMN method VARCHAR(12)",
        "request_id": "ALTER TABLE islem_log ADD COLUMN request_id VARCHAR(64)",
        "user_email": "ALTER TABLE islem_log ADD COLUMN user_email VARCHAR(150)",
        "resolved": "ALTER TABLE islem_log ADD COLUMN resolved BOOLEAN DEFAULT 0",
        "resolution_note": "ALTER TABLE islem_log ADD COLUMN resolution_note TEXT",
        "ip_address": "ALTER TABLE islem_log ADD COLUMN ip_address VARCHAR(45)",
        "havalimani_id": "ALTER TABLE islem_log ADD COLUMN havalimani_id INTEGER",
    }
    added_columns = []
    for column_name, ddl in required_columns.items():
        if column_name in islem_log_kolonlari:
            continue
        db.session.execute(text(ddl))
        added_columns.append(column_name)
    if added_columns:
        db.session.commit()
        app.logger.warning("Legacy sqlite şeması güncellendi: islem_log alanları eklendi: %s", ", ".join(added_columns))

    if not table_exists("ppe_record"):
        return

    ppe_columns = _sqlite_column_names("ppe_record")
    required_ppe_columns = {
        "category": "ALTER TABLE ppe_record ADD COLUMN category VARCHAR(80)",
        "subcategory": "ALTER TABLE ppe_record ADD COLUMN subcategory VARCHAR(120)",
        "brand": "ALTER TABLE ppe_record ADD COLUMN brand VARCHAR(120)",
        "model_name": "ALTER TABLE ppe_record ADD COLUMN model_name VARCHAR(120)",
        "serial_no": "ALTER TABLE ppe_record ADD COLUMN serial_no VARCHAR(120)",
        "apparel_size": "ALTER TABLE ppe_record ADD COLUMN apparel_size VARCHAR(16)",
        "shoe_size": "ALTER TABLE ppe_record ADD COLUMN shoe_size VARCHAR(16)",
        "production_date": "ALTER TABLE ppe_record ADD COLUMN production_date DATE",
        "expiry_date": "ALTER TABLE ppe_record ADD COLUMN expiry_date DATE",
        "physical_condition": "ALTER TABLE ppe_record ADD COLUMN physical_condition VARCHAR(30) DEFAULT 'iyi'",
        "is_active": "ALTER TABLE ppe_record ADD COLUMN is_active BOOLEAN DEFAULT 1",
        "manufacturer_url": "ALTER TABLE ppe_record ADD COLUMN manufacturer_url VARCHAR(500)",
        "signed_document_key": "ALTER TABLE ppe_record ADD COLUMN signed_document_key VARCHAR(255)",
        "signed_document_url": "ALTER TABLE ppe_record ADD COLUMN signed_document_url VARCHAR(500)",
        "signed_document_name": "ALTER TABLE ppe_record ADD COLUMN signed_document_name VARCHAR(255)",
    }
    added_ppe_columns = []
    for column_name, ddl in required_ppe_columns.items():
        if column_name in ppe_columns:
            continue
        db.session.execute(text(ddl))
        added_ppe_columns.append(column_name)
    if added_ppe_columns:
        db.session.commit()
        app.logger.warning("Legacy sqlite şeması güncellendi: ppe_record alanları eklendi: %s", ", ".join(added_ppe_columns))


CRITICAL_RUNTIME_TABLES = (
    "kullanici",
    "site_ayarlari",
    "auth_lockout",
    "login_visual_challenge",
)


def _missing_runtime_tables():
    return [table_name for table_name in CRITICAL_RUNTIME_TABLES if not table_exists(table_name)]


def _site_settings_seed_ready():
    if not table_exists("site_ayarlari"):
        return False
    row = db.session.execute(text("SELECT 1 FROM site_ayarlari LIMIT 1")).first()
    return row is not None


def create_app(config_name=None):
    app = Flask(__name__)

    selected_env = _resolve_runtime_config_name(config_name)
    config_class = config_by_name[selected_env]
    app.config.from_object(config_class)
    _apply_runtime_env_overrides(app)

    _configure_logging(app)

    if selected_env == "testing" and not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = "test-secret-key-only"

    if selected_env != "testing" and not _is_secret_key_strong(app.config.get("SECRET_KEY")):
        raise RuntimeError(
            "Güçlü bir SECRET_KEY zorunludur. "
            "Lütfen en az 32 karakterlik SECRET_KEY tanımlayın."
        )

    database_url = app.config.get("SQLALCHEMY_DATABASE_URI")
    if not database_url:
        raise RuntimeError("SQLALCHEMY_DATABASE_URI/DATABASE_URL tanımlı olmalıdır.")

    if (
        selected_env == "production"
        and _is_sqlite_url(database_url)
        and not app.config.get("ALLOW_SQLITE_IN_PRODUCTION", False)
    ):
        raise RuntimeError(
            "Production ortamında sqlite kullanılamaz. "
            "Cloud SQL/PostgreSQL için DATABASE_URL tanımlayın."
        )

    rate_limit_storage = str(app.config.get("RATELIMIT_STORAGE_URI", ""))
    if rate_limit_storage.startswith("memory://"):
        if selected_env == "production":
            if app.config.get("ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION"):
                app.logger.warning(
                    "Production ortamında rate-limit storage memory:// olarak açık override ile çalışıyor. "
                    "Bu yapı tek-instance/smoke senaryoları dışında önerilmez."
                )
            else:
                raise RuntimeError(
                    "Production ortamında memory:// rate-limit storage kullanılamaz. "
                    "REDIS_URL veya RATELIMIT_STORAGE_URI tanımlayın; "
                    "zorunlu tek-instance/smoke senaryosu için ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION=1 kullanın."
                )
        elif selected_env != "testing":
            app.logger.warning(
                "REDIS_URL tanımlı değil. Development ortamında memory rate-limit storage ile devam ediliyor."
            )

    _validate_passkey_runtime_config(app, selected_env=selected_env)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    executor.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        from models import Kullanici

        if user_id is None or str(user_id) == "None":
            return None
        try:
            return db.session.get(Kullanici, int(user_id))
        except (ValueError, TypeError, SQLAlchemyError):
            return None

    def _normalize_public_site_settings(row):
        if row is None:
            return None
        return SimpleNamespace(
            id=getattr(row, "id", None),
            baslik=getattr(row, "baslik", "") or "",
            alt_metin=getattr(row, "alt_metin", "") or "",
            iletisim_notu=getattr(row, "iletisim_notu", "") or "",
        )

    def _parse_public_site_meta(ayarlar):
        raw_value = getattr(ayarlar, "iletisim_notu", "") if ayarlar else ""
        if not raw_value:
            return {}
        try:
            parsed = json.loads(raw_value)
            if isinstance(parsed, dict):
                return parsed
        except (TypeError, ValueError):
            pass
        legacy_note = str(raw_value).strip()
        return {"public_contact_note": legacy_note} if legacy_note else {}

    def _empty_public_site_snapshot():
        return {"ayarlar": None, "site_meta": {}}

    def _load_public_site_snapshot(force_refresh=False):
        cache_ttl = max(int(app.config.get("PUBLIC_SITE_CACHE_TTL_SECONDS", 90)), 5)
        cache = app.extensions.setdefault(
            "public_site_snapshot_cache",
            {"snapshot": _empty_public_site_snapshot(), "fetched_at": 0.0},
        )
        now = time.monotonic()
        cached_snapshot = cache.get("snapshot") or _empty_public_site_snapshot()
        cache_is_fresh = (now - float(cache.get("fetched_at") or 0.0)) < cache_ttl
        if (
            not force_refresh
            and cache_is_fresh
        ):
            if cached_snapshot.get("ayarlar") is not None:
                return cached_snapshot
            if not table_exists("site_ayarlari"):
                return cached_snapshot

        try:
            if not table_exists("site_ayarlari"):
                snapshot = _empty_public_site_snapshot()
            else:
                from models import SiteAyarlari

                row = SiteAyarlari.query.first()
                ayarlar = _normalize_public_site_settings(row)
                snapshot = {
                    "ayarlar": ayarlar,
                    "site_meta": _parse_public_site_meta(ayarlar),
                }
            cache["snapshot"] = snapshot
            cache["fetched_at"] = now
            return snapshot
        except Exception:
            db.session.rollback()
            return cache.get("snapshot") or _empty_public_site_snapshot()

    app.extensions["public_site_snapshot_loader"] = _load_public_site_snapshot

    @app.context_processor
    def inject_user_info():
        from flask_login import current_user
        unread_notifications = []
        unread_notification_count = 0
        try:
            snapshot = _load_public_site_snapshot()
        except Exception:
            snapshot = _empty_public_site_snapshot()
        ayarlar = snapshot.get("ayarlar")
        site_meta = snapshot.get("site_meta") or {}
        public_logo = str(site_meta.get("public_logo_url") or "").strip()
        demo_logo = str(site_meta.get("homepage_demo_logo_url") or "").strip()
        public_contact_note = str(site_meta.get("public_contact_note") or site_meta.get("site_notu") or "").strip()
        demo_contact_note = str(site_meta.get("homepage_demo_contact_note") or "").strip()
        shared_context = {
            "public_site_settings": ayarlar,
            "site_meta": site_meta,
            "site_logo_url": public_logo or demo_logo,
            "homepage_demo_logo_url": demo_logo,
            "site_contact_note": public_contact_note or demo_contact_note,
            "homepage_demo_contact_note": demo_contact_note,
        }
        passkey_shared = {
            "passkey_enabled": bool(app.config.get("PASSKEY_ENABLED")),
            "passkey_login_begin_url": url_for("auth.login_passkey_begin"),
            "passkey_login_finish_url": url_for("auth.login_passkey_finish"),
            "passkey_register_begin_url": url_for("auth.passkey_register_begin"),
            "passkey_register_finish_url": url_for("auth.passkey_register_finish"),
        }

        if current_user.is_authenticated:
            rol_etiketleri = get_role_labels()
            rol_aciklamalari = get_role_descriptions()
            effective_role = get_effective_role(current_user)
            effective_role_label = get_effective_role_label(current_user)
            role_switch_enabled = can_use_role_switch(current_user)
            role_switch_active = is_role_switch_active(current_user)
            impersonation_mode = is_impersonation_mode(current_user)
            if table_exists("notification"):
                try:
                    from models import Notification

                    unread_notifications = (
                        Notification.query.filter_by(user_id=current_user.id, is_read=False)
                        .order_by(Notification.created_at.desc())
                        .limit(5)
                        .all()
                    )
                    unread_notification_count = Notification.query.filter_by(
                        user_id=current_user.id,
                        is_read=False,
                    ).count()
                except Exception:
                    db.session.rollback()
                    unread_notifications = []
                    unread_notification_count = 0
            permissions = sorted(get_effective_permissions(current_user))
            return {
                "rol": get_legacy_compatible_role(current_user),
                "canonical_rol": effective_role,
                "rol_etiketi": effective_role_label or rol_etiketleri.get(effective_role, effective_role),
                "rol_etiketleri": rol_etiketleri,
                "rol_aciklamalari": rol_aciklamalari,
                "kullanici_ad": current_user.tam_ad,
                "giren_user": current_user,
                "effective_permissions": permissions,
                "sidebar_groups": build_sidebar_groups(current_user),
                "has_permission": has_permission,
                "home_endpoint": role_home_endpoint(current_user),
                "role_switch_enabled": role_switch_enabled,
                "role_switch_active": role_switch_active,
                "role_switch_options": get_role_switch_options(current_user) if role_switch_enabled else [],
                "base_role_label": rol_etiketleri.get(current_user.rol, current_user.rol),
                "impersonation_mode": impersonation_mode,
                "unread_notifications": unread_notifications,
                "unread_notification_count": unread_notification_count,
                **shared_context,
                **passkey_shared,
            }
        return {
            "rol": None,
            "rol_etiketi": None,
            "rol_etiketleri": {},
            "rol_aciklamalari": {},
            "kullanici_ad": None,
            "giren_user": None,
            "effective_permissions": [],
            "sidebar_groups": [],
            "has_permission": has_permission,
            "home_endpoint": "inventory.dashboard",
            "role_switch_enabled": False,
            "role_switch_active": False,
            "role_switch_options": [],
            "base_role_label": None,
            "impersonation_mode": False,
            "unread_notifications": [],
            "unread_notification_count": 0,
            **shared_context,
            **passkey_shared,
        }

    app.register_blueprint(auth_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(maintenance_bp)
    app.register_blueprint(content_bp)
    app.register_blueprint(parts_bp)
    app.register_blueprint(reports_bp)

    @app.before_request
    def ensure_request_session_hygiene():
        try:
            if db.session.is_active is False:
                db.session.rollback()
        except Exception:
            pass
        return None

    @app.before_request
    def assign_request_id():
        incoming = str(request.headers.get("X-Request-ID") or "").strip()
        g.request_id = incoming[:64] if incoming else f"sarx-{uuid.uuid4().hex[:20]}"
        return None

    @app.before_request
    def apply_role_override_guard():
        from flask_login import current_user

        if not current_user.is_authenticated:
            return None
        sanitize_role_override(current_user)
        if should_block_control_plane(current_user):
            abort(403)
        return None

    @app.before_request
    def hydrate_authorization_registry():
        if table_exists("role") and table_exists("permission"):
            state = app.extensions.setdefault("authorization_registry_state", {"hydrated": False})
            if state.get("hydrated"):
                return None
            try:
                sync_result = sync_authorization_registry()
                if sync_result is None:
                    return None
                if sync_result:
                    db.session.commit()
                state["hydrated"] = True
            except Exception:
                db.session.rollback()
        return None

    @app.before_request
    def restrict_editor_scope():
        from flask_login import current_user

        if not current_user.is_authenticated or not is_editor_only(current_user):
            return None

        endpoint = request.endpoint or ""
        if (
            endpoint.startswith("content.")
            or endpoint.startswith("auth.")
            or endpoint in ["ana_sayfa", "serve_manifest", "serve_sw", "static", "health", "ready"]
        ):
            return None
        return redirect(url_for("content.homepage_dashboard"))

    @app.after_request
    def apply_security_headers(response):
        response.headers.setdefault("X-Request-ID", str(getattr(g, "request_id", "") or ""))
        response.headers.setdefault("Content-Security-Policy", app.config.get("CSP_POLICY"))
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if _response_requires_private_cache_busting():
            response = _apply_private_no_store_headers(response)
        if app.config.get("SESSION_COOKIE_SECURE"):
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    def _render_safe_error(error_code, status_code=None, exception=None, retry_after=None):
        payload = capture_error(exception=exception, error_code=error_code, status_code=status_code)
        spec = payload["spec"]
        resolved_status = int(status_code or payload["status_code"] or spec.status_code)
        user_message = format_user_error_message(spec.error_code)
        if _wants_json_response():
            response = jsonify(
                {
                    "status": "error",
                    "message": spec.user_message,
                    "error_code": spec.error_code,
                    "request_id": str(getattr(g, "request_id", "") or ""),
                }
            )
            if retry_after:
                response.headers["Retry-After"] = str(int(retry_after))
            return response, resolved_status
        if resolved_status == 413:
            return render_template(
                "413.html",
                kod=resolved_status,
                mesaj=spec.user_message,
                error_code=spec.error_code,
                request_id=str(getattr(g, "request_id", "") or ""),
                support_note="Sorun devam ederse bu kodu bildiriniz.",
            ), resolved_status
        if resolved_status == 429:
            response = make_response(
                render_template(
                    "429.html",
                    kod=resolved_status,
                    mesaj=spec.user_message,
                    error_code=spec.error_code,
                    request_id=str(getattr(g, "request_id", "") or ""),
                    support_note="Sorun devam ederse bu kodu bildiriniz.",
                ),
                resolved_status,
            )
            if retry_after:
                response.headers["Retry-After"] = str(int(retry_after))
            return response
        template_name = "csrf_hata.html" if isinstance(exception, CSRFError) else "hata.html"
        return render_template(
            template_name,
            kod=resolved_status,
            mesaj=spec.user_message,
            error_code=spec.error_code,
            request_id=str(getattr(g, "request_id", "") or ""),
            support_note="Sorun devam ederse bu kodu bildiriniz.",
            full_message=user_message,
        ), resolved_status

    @app.errorhandler(400)
    def bad_request(error):
        return _render_safe_error(resolve_error_code(status_code=400), status_code=400, exception=error)

    @app.errorhandler(401)
    def unauthorized(error):
        return _render_safe_error("SAR-X-AUTH-6101", status_code=401, exception=error)

    @app.errorhandler(403)
    def forbidden(error):
        return _render_safe_error(resolve_error_code(status_code=403), status_code=403, exception=error)

    @app.errorhandler(404)
    def not_found(error):
        if _is_noise_404_request():
            app.logger.info("Probe/static 404 isteği sessiz işlendi: %s", request.path)
            if _wants_json_response():
                return jsonify({"status": "error", "message": "Not Found"}), 404
            return "", 404
        return _render_safe_error("SAR-X-PUBLIC-3201", status_code=404, exception=error)

    @app.errorhandler(413)
    def request_too_large(error):
        return _render_safe_error("SAR-X-MEDIA-7101", status_code=413, exception=error)

    @app.errorhandler(429)
    def too_many_requests(error):
        return _render_safe_error(
            "SAR-X-SYSTEM-5103",
            status_code=429,
            exception=error,
            retry_after=getattr(error, "retry_after", None),
        )

    @app.errorhandler(500)
    def internal_server_error(error):
        original = getattr(error, "original_exception", None) or error
        return _render_safe_error("SAR-X-SYSTEM-5101", status_code=500, exception=original)

    @app.errorhandler(CSRFError)
    def handle_csrf_error(error):
        return _render_safe_error("SAR-X-AUTH-1202", status_code=400, exception=error)

    @app.errorhandler(Exception)
    def handle_unexpected_exception(error):
        if isinstance(error, HTTPException):
            return error
        return _render_safe_error(resolve_error_code(exception=error), exception=error)

    @app.route("/")
    def ana_sayfa():
        from models import (
            Announcement,
            ContentWorkflow,
            DocumentResource,
            Havalimani,
            Haber,
            HomeQuickLink,
            HomeSection,
            HomeSlider,
            HomeStatCard,
            InventoryAsset,
            Kullanici,
            NavMenu,
            SiteAyarlari,
            SliderResim,
        )
        from homepage_demo import filter_homepage_demo_items, homepage_demo_is_active

        def _workflow_status_map(entity_type):
            if not table_exists("content_workflow"):
                return {}
            try:
                rows = ContentWorkflow.query.filter_by(entity_type=entity_type).all()
            except SQLAlchemyError:
                db.session.rollback()
                return {}
            return {row.entity_id: row.status for row in rows}

        def _filter_by_workflow(items, entity_type):
            status_map = _workflow_status_map(entity_type)
            if not status_map:
                return items
            filtered = []
            for item in items:
                status = status_map.get(item.id)
                if status is None or status == "published":
                    filtered.append(item)
            return filtered

        def _format_public_count(value):
            return f"{int(value):,}".replace(",", ".")

        def _safe_public_collection(required_tables, factory, fallback=None):
            if any(not table_exists(table_name) for table_name in required_tables):
                return [] if fallback is None else fallback
            try:
                return factory()
            except SQLAlchemyError:
                db.session.rollback()
                return [] if fallback is None else fallback

        def _safe_public_count(required_tables, factory):
            if any(not table_exists(table_name) for table_name in required_tables):
                return 0
            try:
                return int(factory())
            except (SQLAlchemyError, TypeError, ValueError):
                db.session.rollback()
                return 0

        def _build_public_stats(configured_cards, metric_registry):
            metrics = list(metric_registry.values())
            unused_keys = [metric["key"] for metric in metrics]

            def _resolve_metric(card):
                text = f"{card.title or ''} {card.subtitle or ''}".lower()
                keyword_map = [
                    ("total_assets", ("malzeme", "ekipman", "envanter", "varlik", "varlık")),
                    ("total_personnel", ("personel", "kullanici", "kullanıcı", "gonullu", "gönüllü", "ekip")),
                    ("total_airports", ("havalimani", "havalimanı", "lokasyon", "birim")),
                    ("published_announcements", ("duyuru", "guncel", "güncel", "haber", "paylasim", "paylaşım")),
                    ("training_modules", ("egitim", "eğitim", "gelisim", "gelişim")),
                    ("exercise_modules", ("tatbikat", "senaryo", "operasyon")),
                ]
                for key, keywords in keyword_map:
                    if any(keyword in text for keyword in keywords):
                        return key
                return unused_keys[0] if unused_keys else metrics[0]["key"]

            resolved = []
            for index, card in enumerate(configured_cards):
                metric_key = _resolve_metric(card)
                if metric_key in unused_keys:
                    unused_keys.remove(metric_key)
                metric = metric_registry[metric_key]
                resolved.append(
                    SimpleNamespace(
                        metric_key=metric_key,
                        title=card.title or metric["label"],
                        value_text=_format_public_count(metric["value"]),
                        subtitle=card.subtitle or metric["subtitle"],
                        icon=card.icon or metric["icon"],
                        order_index=index,
                    )
                )

            if resolved:
                return resolved

            return [
                SimpleNamespace(
                    metric_key=metric["key"],
                    title=metric["label"],
                    value_text=_format_public_count(metric["value"]),
                    subtitle=metric["subtitle"],
                    icon=metric["icon"],
                    order_index=index,
                )
                for index, metric in enumerate(metrics)
            ]

        ayarlar = None
        menuler = []
        homepage_demo_active = homepage_demo_is_active()

        sliders = _safe_public_collection(
            ("home_slider",),
            lambda: HomeSlider.query.filter_by(is_active=True).order_by(
                HomeSlider.order_index.asc(), HomeSlider.id.asc()
            ).all(),
        )
        sliders = _filter_by_workflow(sliders, "slider")
        sliders = filter_homepage_demo_items(sliders)
        if not sliders and not homepage_demo_active:
            legacy_sliders = _safe_public_collection(("slider_resim",), lambda: SliderResim.query.all())
            sliders = [
                SimpleNamespace(
                    title=slider.baslik or "Operasyonel Hazırlık",
                    subtitle=slider.alt_yazi or "Kurumsal acil müdahale koordinasyonu",
                    description=slider.alt_yazi or "",
                    image_url=slider.resim_url,
                    button_text="Detaylı Bilgi",
                    button_link="#hakkimizda",
                )
                for slider in legacy_sliders
            ]

        sections = _safe_public_collection(
            ("home_section",),
            lambda: HomeSection.query.filter_by(is_active=True).order_by(
                HomeSection.order_index.asc(), HomeSection.id.asc()
            ).all(),
        )
        sections = _filter_by_workflow(sections, "section")
        sections = filter_homepage_demo_items(sections)

        about_card_defaults = [
            {
                "key": "about",
                "anchor_id": "biz-kimiz",
                "menu_label": "Ekip Yapısı",
                "title": "Biz Kimiz",
                "description": "ARFF özel arama kurtarma gönüllülerinin birlikte hareket ettiği, sahaya yakın bir ekip yapısı.",
            },
            {
                "key": "mission",
                "anchor_id": "misyon",
                "menu_label": "Odak",
                "title": "Misyon",
                "description": "Hazırlığı canlı tutmak, sahada birbirimize destek olmak ve ihtiyaç anında hızlıca organize olmak.",
            },
            {
                "key": "vision",
                "anchor_id": "vizyon",
                "menu_label": "Bakış",
                "title": "Vizyon",
                "description": "Güven, gönüllülük, şeffaflık ve ekip dayanışmasını koruyarak güçlü bir saha kültürü oluşturmak.",
            },
            {
                "key": "ethics",
                "anchor_id": "etik-degerler",
                "menu_label": "İlke",
                "title": "Etik Değerler",
                "description": "Sahada saygı, sorumluluk, güven ve gönüllülük çizgisini birlikte korumak.",
            },
        ]

        assigned_section_ids = set()

        def _pick_about_section(preferred_key):
            for item in sections:
                if item.section_key == preferred_key and item.id not in assigned_section_ids:
                    assigned_section_ids.add(item.id)
                    return item
            for item in sections:
                if item.id not in assigned_section_ids:
                    assigned_section_ids.add(item.id)
                    return item
            return None

        about_cards = []
        for config in about_card_defaults:
            source = _pick_about_section(config["key"])
            about_cards.append(
                SimpleNamespace(
                    anchor_id=config["anchor_id"],
                    menu_label=config["menu_label"],
                    title=config["title"],
                    description=(
                        source.content
                        if source and source.content
                        else source.subtitle
                        if source and source.subtitle
                        else config["description"]
                    ),
                )
            )

        announcement_pool = _safe_public_collection(
            ("announcement",),
            lambda: Announcement.query.filter_by(is_published=True).order_by(
                Announcement.published_at.desc(), Announcement.id.desc()
            ).all(),
        )
        announcement_pool = _filter_by_workflow(announcement_pool, "announcement")
        announcement_pool = filter_homepage_demo_items(announcement_pool)
        announcement_count = len(announcement_pool)
        announcements = announcement_pool[:6]
        if not announcement_pool and not homepage_demo_active:
            legacy_news = _safe_public_collection(
                ("haber",),
                lambda: Haber.query.order_by(Haber.tarih.desc()).limit(6).all(),
            )
            announcement_pool = [
                SimpleNamespace(
                    title=item.baslik,
                    slug="",
                    summary=(item.icerik[:160] + "...") if item.icerik and len(item.icerik) > 160 else item.icerik,
                    content=item.icerik,
                    cover_image="",
                    published_at=item.tarih,
                )
                for item in legacy_news
            ]
            announcement_count = len(announcement_pool)
            announcements = announcement_pool[:6]

        documents = _safe_public_collection(
            ("document_resource",),
            lambda: DocumentResource.query.filter_by(is_active=True).order_by(
                DocumentResource.order_index.asc(), DocumentResource.id.asc()
            ).all(),
        )
        documents = _filter_by_workflow(documents, "document")
        documents = filter_homepage_demo_items(documents)
        quick_links = _safe_public_collection(
            ("home_quick_link",),
            lambda: HomeQuickLink.query.filter_by(is_active=True).order_by(
                HomeQuickLink.order_index.asc(), HomeQuickLink.id.asc()
            ).all(),
        )
        quick_links = _filter_by_workflow(quick_links, "quicklink")
        quick_links = filter_homepage_demo_items(quick_links)

        completed_training_count = sum(
            1 for item in sections if item.section_key in {"training", "exercise", "operation"}
        )
        stats = [
            SimpleNamespace(
                metric_key="total_assets",
                title="Toplam Malzeme",
                value_text=_format_public_count(
                    _safe_public_count(("inventory_asset",), lambda: InventoryAsset.query.filter_by(is_deleted=False).count())
                ),
                subtitle="Tüm havalimanlarında kayıtlı ekipman ve varlık sayısı.",
                icon="◈",
                order_index=0,
            ),
            SimpleNamespace(
                metric_key="total_personnel",
                title="Toplam Personel",
                value_text=_format_public_count(
                    _safe_public_count(("kullanici",), lambda: Kullanici.query.filter_by(is_deleted=False).count())
                ),
                subtitle="Sistemde görevli ARFF personeli ve ekip üyeleri.",
                icon="◎",
                order_index=1,
            ),
            SimpleNamespace(
                metric_key="total_airports",
                title="Aktif Havalimanı",
                value_text=_format_public_count(
                    _safe_public_count(("havalimani",), lambda: Havalimani.query.filter_by(is_deleted=False).count())
                ),
                subtitle="Envanter ve operasyon takibi yapılan lokasyon sayısı.",
                icon="◇",
                order_index=2,
            ),
            SimpleNamespace(
                metric_key="completed_trainings",
                title="Tamamlanan Eğitimler",
                value_text=_format_public_count(completed_training_count),
                subtitle="Sistem kayıtlarına işlenmiş eğitim ve hazırlık çalışması sayısı.",
                icon="✦",
                order_index=3,
            ),
        ]

        return render_template(
            "index.html",
            ayarlar=ayarlar,
            menuler=menuler,
            sliders=sliders,
            sections=sections,
            about_cards=about_cards,
            announcements=announcements,
            announcement_carousel_items=[
                {
                    "title": item.title,
                    "date_label": item.published_at.strftime("%d.%m.%Y") if item.published_at else "Yakında",
                    "summary": (
                        item.summary
                        or ((item.content[:190] + "...") if item.content and len(item.content) > 190 else item.content)
                        or "Yeni paylaşımlar eklendiğinde bu kartta kısa özet görünür."
                    ),
                    "image_url": item.cover_image or "",
                    "badge_label": item.title,
                    "link_url": url_for("content.public_announcement_detail", slug=item.slug)
                    if getattr(item, "slug", None)
                    else url_for("content.public_announcements"),
                }
                for item in announcements
            ],
            documents=documents,
            stats=stats,
            quick_links=quick_links,
        )

    @app.route("/health")
    def health():
        return jsonify(
            {
                "status": "ok",
                "time": datetime.utcnow().isoformat() + "Z",
                "service": "sar-x",
            }
        ), 200

    @app.route("/ready")
    def ready():
        missing_tables = []
        site_settings_seed_ready = False
        try:
            db.session.execute(text("SELECT 1"))
            missing_tables = _missing_runtime_tables()
            if not missing_tables:
                site_settings_seed_ready = _site_settings_seed_ready()
            db_status = "ok" if (not missing_tables and site_settings_seed_ready) else "schema_incomplete"
            http_status = 200 if db_status == "ok" else 503
        except Exception:
            db.session.rollback()
            db_status = "error"
            http_status = 503
            app.logger.exception("Ready check sırasında veritabanı doğrulaması başarısız.")
        return jsonify(
            {
                "status": "ready" if db_status == "ok" else "degraded",
                "database": db_status,
                "missing_tables": missing_tables,
                "seed_ready": site_settings_seed_ready,
                "scheduler_enabled": bool(app.config.get("ENABLE_SCHEDULER")),
            }
        ), http_status

    @app.route("/manifest.json")
    def serve_manifest():
        return send_file("static/manifest.json")

    @app.route("/site.webmanifest")
    def serve_site_manifest():
        return send_file("static/manifest.json", mimetype="application/manifest+json")

    @app.route("/sw.js")
    def serve_sw():
        return send_file("static/sw.js", mimetype="application/javascript")

    @app.route("/robots.txt")
    def serve_robots():
        return send_from_directory("static", "robots.txt", mimetype="text/plain")

    @app.route("/favicon.ico")
    def serve_favicon_ico():
        return send_from_directory("static", "favicon.png", mimetype="image/png")

    @app.route("/favicon.png")
    def serve_favicon_png():
        return send_from_directory("static", "favicon.png", mimetype="image/png")

    @app.route("/apple-touch-icon.png")
    def serve_apple_touch_icon():
        return send_from_directory("static", "favicon.png", mimetype="image/png")

    @app.route("/apple-touch-icon-precomposed.png")
    def serve_apple_touch_icon_precomposed():
        return send_from_directory("static", "favicon.png", mimetype="image/png")

    @app.route("/.well-known/assetlinks.json")
    def serve_assetlinks():
        return jsonify([])

    if app.config.get("AUTO_CREATE_TABLES", False):
        with app.app_context():
            try:
                db.create_all()
                _ensure_runtime_schema_compatibility(app)
                sync_authorization_registry()
                db.session.commit()
                app.logger.info("AUTO_CREATE_TABLES etkin: tablolar kontrol edilip oluşturuldu.")
            except SQLAlchemyError:
                app.logger.exception("Veritabanı tabloları hazırlanırken hata oluştu.")
    else:
        app.logger.info("AUTO_CREATE_TABLES devre dışı: migration tabanlı akış bekleniyor.")

    _log_production_runtime_risks(app)
    start_scheduler(app)

    app.logger.info(
        "Uygulama başlatıldı | env=%s | config=%s | db=%s | rate_limit_storage=%s | scheduler=%s",
        selected_env,
        config_class.__name__,
        _redact_runtime_value(app.config.get("SQLALCHEMY_DATABASE_URI")),
        _redact_runtime_value(app.config.get("RATELIMIT_STORAGE_URI")),
        app.config.get("ENABLE_SCHEDULER"),
    )
    return app


if __name__ == "__main__":
    app = create_app(os.getenv("APP_ENV") or os.getenv("FLASK_ENV") or "development")
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
        debug=bool(app.config.get("DEBUG", False)),
    )
