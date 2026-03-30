from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user
from flask import current_app, request, jsonify, has_app_context, has_request_context
from sqlalchemy import MetaData, Table, create_engine, inspect
from sqlalchemy.pool import NullPool

# --- GÜVENLİK VE YARDIMCI KÜTÜPHANELER ---
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import bleach
import mimetypes
import pytz
from flask_executor import Executor
from flask_migrate import Migrate  # ✅ YENİ: Veri kaybını önleyen göç sistemi
from werkzeug.utils import secure_filename

# --- BİLEŞENLERİ BAŞLATMA ---
db = SQLAlchemy()

login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = "Lütfen önce sisteme giriş yapın."
login_manager.login_message_category = "danger"

# Güvenlik, Göç ve Arka Plan Bileşenleri
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address)
executor = Executor()
migrate = Migrate()  # ✅ YENİ: Artık tabloları silip kurmaya son!
TR_TZ = pytz.timezone("Europe/Istanbul")

# --- SİSTEM FONKSİYONLARI ---

def _schema_cache():
    if not has_app_context():
        return {"tables": {}, "columns": {}}
    return current_app.extensions.setdefault(
        "schema_cache",
        {"tables": {}, "columns": {}},
    )


def reset_schema_cache():
    if has_app_context():
        current_app.extensions["schema_cache"] = {"tables": {}, "columns": {}}


def _inspection_target():
    return db.engine


def _session_in_transaction():
    try:
        session = db.session()
        return bool(session.in_transaction())
    except Exception:
        return False


def _supports_isolated_inspection():
    try:
        engine = db.engine
        return not (
            engine.dialect.name == "sqlite"
            and str(getattr(engine.url, "database", "") or "") in {"", ":memory:"}
        )
    except Exception:
        return False


def _get_inspector():
    temp_engine = None
    target = _inspection_target()
    try:
        if _session_in_transaction() and _supports_isolated_inspection():
            runtime_url = db.engine.url.render_as_string(hide_password=False)
            temp_engine = create_engine(runtime_url, poolclass=NullPool)
            target = temp_engine
        return inspect(target), temp_engine
    except Exception:
        if temp_engine is not None:
            temp_engine.dispose()
        raise

def table_exists(table_name):
    try:
        if not has_app_context():
            return False
        cache = _schema_cache()
        if cache["tables"].get(table_name) is True:
            return cache["tables"][table_name]
        inspector, temp_engine = _get_inspector()
        try:
            exists = inspector.has_table(table_name)
        finally:
            if temp_engine is not None:
                temp_engine.dispose()
        cache["tables"][table_name] = exists
        if exists and table_name in cache["columns"]:
            cache["columns"].pop(table_name, None)
        return exists
    except Exception:
        return False


def column_exists(table_name, column_name):
    try:
        if not has_app_context():
            return False
        cache = _schema_cache()
        if cache["columns"].get(table_name) is None or column_name not in cache["columns"].get(table_name, set()):
            inspector, temp_engine = _get_inspector()
            try:
                cache["columns"][table_name] = {
                    column.get("name") for column in inspector.get_columns(table_name)
                }
            finally:
                if temp_engine is not None:
                    temp_engine.dispose()
        return column_name in cache["columns"][table_name]
    except Exception:
        return False


def _runtime_table(table_name):
    metadata = MetaData()
    return Table(table_name, metadata, autoload_with=db.engine)


def _safe_request_remote_addr():
    if not has_request_context():
        return None
    try:
        return request.remote_addr
    except Exception:
        return None


def _safe_request_user_agent():
    if not has_request_context():
        return None
    try:
        value = request.user_agent.string
        return value or None
    except Exception:
        return None


def _log_timestamp_now():
    return datetime.now(TR_TZ)


def log_kaydet(
    tip,
    detay,
    event_key=None,
    target_model=None,
    target_id=None,
    outcome="success",
    commit=True,
    **extra_fields,
):
    """Sistemdeki işlemleri IP ve Cihaz bilgisiyle Kara Kutuya kaydeder."""
    if not table_exists("islem_log"):
        return
    
    try:
        k_id = extra_fields.get("user_id")
        if k_id is None and current_user.is_authenticated:
            k_id = current_user.id
    except Exception:
        k_id = extra_fields.get("user_id")
    try:
        user_email = extra_fields.get("user_email")
        if not user_email and current_user.is_authenticated:
            user_email = getattr(current_user, "kullanici_adi", None)
    except Exception:
        user_email = extra_fields.get("user_email")
    if not user_email and k_id is not None:
        try:
            from models import Kullanici

            actor = db.session.get(Kullanici, int(k_id))
            user_email = getattr(actor, "kullanici_adi", None)
        except Exception:
            user_email = user_email or None
    try:
        airport_id = extra_fields.get("havalimani_id")
        if airport_id is None and current_user.is_authenticated:
            airport_id = getattr(current_user, "havalimani_id", None)
    except Exception:
        airport_id = extra_fields.get("havalimani_id")
    
    payload = {
        "kullanici_id": k_id,
        "havalimani_id": airport_id,
        "islem_tipi": tip,
        "detay": detay,
        "ip_adresi": _safe_request_remote_addr(),
        "user_agent": _safe_request_user_agent(),
    }
    optional_fields = {
        "event_key": event_key,
        "target_model": target_model,
        "target_id": target_id,
        "outcome": outcome,
        "error_code": extra_fields.get("error_code"),
        "title": extra_fields.get("title"),
        "user_message": extra_fields.get("user_message"),
        "owner_message": extra_fields.get("owner_message"),
        "module": extra_fields.get("module"),
        "severity": extra_fields.get("severity"),
        "exception_type": extra_fields.get("exception_type"),
        "exception_message": extra_fields.get("exception_message"),
        "traceback_summary": extra_fields.get("traceback_summary"),
        "route": extra_fields.get("route"),
        "method": extra_fields.get("method"),
        "request_id": extra_fields.get("request_id"),
        "user_email": user_email,
        "ip_address": extra_fields.get("ip_address"),
        "resolved": extra_fields.get("resolved", False),
        "resolution_note": extra_fields.get("resolution_note"),
    }
    for field_name, value in optional_fields.items():
        if column_exists("islem_log", field_name):
            payload[field_name] = value
    if column_exists("islem_log", "zaman"):
        payload["zaman"] = extra_fields.get("zaman") or _log_timestamp_now()
    if column_exists("islem_log", "kullanici_id") and extra_fields.get("user_id") is not None:
        payload["kullanici_id"] = extra_fields.get("user_id")
    if column_exists("islem_log", "havalimani_id") and extra_fields.get("havalimani_id") is not None:
        payload["havalimani_id"] = extra_fields.get("havalimani_id")
    if column_exists("islem_log", "ip_address") and extra_fields.get("ip_address"):
        payload["ip_address"] = extra_fields.get("ip_address")
    if column_exists("islem_log", "user_agent") and extra_fields.get("user_agent"):
        payload["user_agent"] = extra_fields.get("user_agent")
    try:
        try:
            from models import IslemLog

            model_table = IslemLog.__table__
            model_columns = {column.name for column in model_table.columns}
            runtime_columns = {
                str(column.get("name") or "").strip()
                for column in inspect(db.engine).get_columns("islem_log")
                if column.get("name")
            }
            runtime_table = model_table if runtime_columns == model_columns else _runtime_table("islem_log")
        except Exception:
            runtime_table = _runtime_table("islem_log")
            runtime_columns = {column.name for column in runtime_table.columns}
        safe_payload = {key: value for key, value in payload.items() if key in runtime_columns}

        if commit:
            db.session.execute(runtime_table.insert().values(**safe_payload))
            db.session.commit()
        else:
            with db.session.no_autoflush:
                db.session.execute(runtime_table.insert().values(**safe_payload))
    except Exception:
        try:
            if commit or db.session.is_active is False:
                db.session.rollback()
        except Exception:
            pass
        if has_app_context():
            current_app.logger.exception("İşlem logu yazılamadı: %s", tip)

def guvenli_metin(metin):
    """XSS ve HTML Injection saldırılarına karşı metni temizler."""
    if not metin:
        return metin
    return bleach.clean(metin, tags=[], attributes={}, strip=True)

def api_yanit(basari=True, mesaj="", veri=None, kod=200):
    """Tüm JSON yanıtları için kurumsal standart sarmalayıcı."""
    return jsonify({
        "status": "success" if basari else "error",
        "message": mesaj,
        "data": veri
    }), kod


def audit_log(event, outcome="success", **context):
    """Yapılandırılmış denetim logu için hafif yardımcı."""
    if not has_app_context():
        return
    context_parts = [f"{key}={value}" for key, value in context.items() if value is not None]
    details = " ".join(context_parts)
    current_app.logger.info("audit event=%s outcome=%s %s", event, outcome, details)


def create_notification(user_id, notification_type, title, message, link_url=None, severity="info", commit=True):
    from models import Notification

    if not table_exists("notification"):
        return None
    try:
        payload = {
            "user_id": user_id,
            "type": notification_type,
            "title": title,
            "message": message,
            "link_url": link_url,
            "severity": severity,
            "is_read": False,
        }
        if commit:
            item = Notification(**payload)
            db.session.add(item)
            db.session.commit()
        else:
            with db.session.no_autoflush:
                result = db.session.execute(Notification.__table__.insert().values(**payload))
            item = Notification(**payload)
            inserted_primary_key = getattr(result, "inserted_primary_key", None) or ()
            if inserted_primary_key:
                item.id = inserted_primary_key[0]
        return item
    except Exception:
        if commit:
            db.session.rollback()
        if has_app_context():
            current_app.logger.exception("Bildirim olusturulamadi: %s", notification_type)
        return None


def create_notification_once(user_id, notification_type, title, message, link_url=None, severity="info", commit=True):
    from models import Notification

    if not table_exists("notification"):
        return None
    try:
        with db.session.no_autoflush:
            existing = Notification.query.filter_by(
                user_id=user_id,
                type=notification_type,
                title=title,
                link_url=link_url,
                is_read=False,
            ).first()
        if existing:
            return existing
    except Exception:
        try:
            if commit:
                db.session.rollback()
        except Exception:
            pass
    return create_notification(
        user_id,
        notification_type,
        title,
        message,
        link_url=link_url,
        severity=severity,
        commit=commit,
    )


def create_approval_request(
    approval_type,
    target_model,
    target_id,
    requested_by_id,
    request_payload,
    review_note=None,
    commit=True,
):
    from models import ApprovalRequest

    if not table_exists("approval_request"):
        return None
    try:
        payload = {
            "approval_type": approval_type,
            "target_model": target_model,
            "target_id": target_id,
            "requested_by_id": requested_by_id,
            "request_payload": request_payload,
            "review_note": review_note,
            "status": "pending",
        }
        if commit:
            item = ApprovalRequest(**payload)
            db.session.add(item)
            db.session.commit()
        else:
            with db.session.no_autoflush:
                result = db.session.execute(ApprovalRequest.__table__.insert().values(**payload))
            item = ApprovalRequest(**payload)
            inserted_primary_key = getattr(result, "inserted_primary_key", None) or ()
            if inserted_primary_key:
                item.id = inserted_primary_key[0]
        return item
    except Exception:
        if commit:
            db.session.rollback()
        if has_app_context():
            current_app.logger.exception("Approval request olusturulamadi: %s", approval_type)
        return None


def secure_upload_filename(raw_name):
    """Güvenli dosya adı üretir."""
    sanitized = secure_filename(raw_name or "")
    return sanitized[:180] if sanitized else ""


def is_allowed_file(filename, allowed_extensions):
    if not filename or "." not in filename:
        return False
    extension = filename.rsplit(".", 1)[1].lower()
    return extension in {ext.lower() for ext in allowed_extensions}


def _detect_upload_mime(upload):
    stream = getattr(upload, "stream", None)
    if stream is None:
        return None

    try:
        position = stream.tell()
    except Exception:
        position = None

    try:
        header = stream.read(16)
    except Exception:
        header = b""
    finally:
        try:
            if position is not None:
                stream.seek(position)
            else:
                stream.seek(0)
        except Exception:
            pass

    if header.startswith(b"%PDF-"):
        return "application/pdf"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if header[:6] in {b"GIF87a", b"GIF89a"}:
        return "image/gif"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    return None


def is_allowed_mime(filename, allowed_mime_prefixes=None, upload=None):
    detected_mime = _detect_upload_mime(upload) if upload is not None else None
    if detected_mime:
        guessed_mime = detected_mime
    elif upload is not None and (allowed_mime_prefixes and any(prefix in {"application/pdf", "image/"} for prefix in allowed_mime_prefixes)):
        return False
    else:
        guessed_mime, _ = mimetypes.guess_type(filename or "")
        if not guessed_mime:
            return False
    if not allowed_mime_prefixes:
        allowed_mime_prefixes = ("application/pdf", "image/", "text/")
    return any(guessed_mime.startswith(prefix) for prefix in allowed_mime_prefixes)
