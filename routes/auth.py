import json
import hashlib
import smtplib
import re
from datetime import timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib.parse import urljoin, urlsplit, urlunsplit

from flask import Blueprint, abort, current_app, flash, g, jsonify, make_response, redirect, render_template, request, session, url_for
from flask_login import login_user, logout_user, login_required, current_user
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from sqlalchemy import func

from captcha_helper import (
    build_login_captcha,
    invalidate_login_captcha,
    render_login_captcha_svg,
    validate_login_captcha,
)
from error_handling import capture_error, flash_safe_error
from models import AuthLockout, Kullanici, PasskeyCredential, get_tr_now
from extensions import audit_log, db, limiter, log_kaydet
from decorators import (
    can_use_role_switch,
    clear_role_override,
    get_effective_role_label,
    get_role_switch_options,
    role_home_endpoint,
    set_role_override,
)
from passkey_helper import (
    PasskeyError,
    b64url_decode,
    b64url_encode,
    consume_authentication_state,
    consume_registration_state,
    create_challenge,
    is_passkey_enabled,
    resolve_rp_id,
    store_authentication_state,
    store_registration_state,
    validate_registration_response,
    verify_authentication_response,
)

auth_bp = Blueprint('auth', __name__)

PASSWORD_RESET_SALT = 'sifre-sifirlama-tuzu'
PASSWORD_RESET_PATTERN = re.compile(r"^(?=.*\d)(?=.*[a-z])(?=.*[A-Z])(?=.*?[#?!@$%^&*-]).{8,}$")

# --- YARDIMCI FONKSİYONLAR ---


def _captcha_feedback_message(captcha_state):
    if captcha_state in {"expired", "stale", "used"}:
        return "Önceki doğrulama artık geçersiz. Yeni kod yüklendi; lütfen ekrandaki güncel kodu girin."
    if captcha_state == "missing":
        return "Devam etmek için ekrandaki doğrulama kodunu girin."
    return "Doğrulamayı tamamlamak için ekrandaki güncel kodu tekrar girin."


def _render_login_page(status_code=200, force_new=False, captcha_feedback=None):
    response = make_response(
        render_template(
            'login.html',
            login_captcha=build_login_captcha(force_new=force_new),
            login_captcha_feedback=captcha_feedback,
        ),
        status_code,
    )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["Vary"] = "Cookie"
    return response


def _expire_cookie(response, name, *, path="/", domain=None):
    response.delete_cookie(name, path=path or "/", domain=domain)
    if domain:
        response.delete_cookie(name, path=path or "/")
    return response


def _clear_auth_cookies(response):
    session_cookie_name = current_app.config.get("SESSION_COOKIE_NAME", "session")
    remember_cookie_name = current_app.config.get("REMEMBER_COOKIE_NAME", "remember_token")
    session_cookie_path = current_app.config.get("SESSION_COOKIE_PATH") or "/"
    remember_cookie_path = current_app.config.get("REMEMBER_COOKIE_PATH") or "/"

    _expire_cookie(
        response,
        session_cookie_name,
        path=session_cookie_path,
        domain=current_app.config.get("SESSION_COOKIE_DOMAIN"),
    )
    _expire_cookie(
        response,
        remember_cookie_name,
        path=remember_cookie_path,
        domain=current_app.config.get("REMEMBER_COOKIE_DOMAIN"),
    )
    return response


def _require_passkey_feature():
    if not is_passkey_enabled():
        abort(404)


def _passkey_json_error(message="Biyometrik giriş şu an tamamlanamadı.", status_code=400):
    response = jsonify({"status": "error", "message": message})
    return response, status_code


def _passkey_success_redirect_url(user):
    return url_for(role_home_endpoint(user))


def _passkey_remember_value(payload):
    return bool((payload or {}).get("remember_me"))


def _passkey_transports_from_json(raw_value):
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _format_passkey_timestamp(value):
    if not value:
        return ""
    try:
        return value.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(value)


def _default_passkey_friendly_name():
    user_agent = (request.user_agent.string or "").strip()
    if not user_agent:
        return "Kayıtlı Cihaz"
    compact = user_agent.replace("\n", " ").strip()
    if len(compact) > 80:
        compact = compact[:77].rstrip() + "..."
    return compact or "Kayıtlı Cihaz"

def gizli_sifreyi_getir():
    # 1) Secret Manager erişimi yoksa/kapalıysa env üzerinden devam et.
    env_password = (current_app.config.get("SMTP_PASSWORD") or "").strip()
    if env_password:
        return env_password

    project_id = (current_app.config.get("MAIL_SECRET_PROJECT_ID") or "").strip()
    secret_name = (current_app.config.get("MAIL_PASSWORD_SECRET_NAME") or "").strip()
    secret_version = (current_app.config.get("MAIL_PASSWORD_SECRET_VERSION") or "latest").strip() or "latest"
    if not project_id or not secret_name:
        current_app.logger.warning(
            "Mail secret ayarları eksik (MAIL_SECRET_PROJECT_ID / MAIL_PASSWORD_SECRET_NAME)."
        )
        return None

    try:
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        ad = f"projects/{project_id}/secrets/{secret_name}/versions/{secret_version}"
        cevap = client.access_secret_version(request={"name": ad})
        return cevap.payload.data.decode("UTF-8")
    except Exception:
        current_app.logger.warning("Secret Manager erişim hatası oluştu.")
        return None


def _client_ip():
    forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return forwarded or (request.remote_addr or "unknown")


def _normalize_login_email(raw_value):
    return (raw_value or "").strip().lower()


def _looks_like_email(value):
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value or ""))


def _auth_identifier(username):
    normalized = _normalize_login_email(username)
    return f"{normalized}|{_client_ip()}"[:170]


def _find_active_user_by_email(email):
    normalized = _normalize_login_email(email)
    if not normalized:
        return None
    return (
        Kullanici.query.filter(
            Kullanici.is_deleted.is_(False),
            func.lower(func.trim(Kullanici.kullanici_adi)) == normalized,
        )
        .order_by(Kullanici.id.asc())
        .first()
    )


def _get_lock_record(identifier):
    return AuthLockout.query.filter_by(identifier=identifier).first()


def _register_failed_login(identifier):
    attempts_limit = max(int(current_app.config.get("AUTH_LOCKOUT_ATTEMPTS", 5)), 1)
    lock_minutes = max(int(current_app.config.get("AUTH_LOCKOUT_MINUTES", 15)), 1)

    record = _get_lock_record(identifier) or AuthLockout(identifier=identifier, failed_attempts=0)
    now = get_tr_now().replace(tzinfo=None)

    if record.locked_until and record.locked_until > now:
        return record

    record.failed_attempts = (record.failed_attempts or 0) + 1
    record.last_failed_at = now
    record.last_ip = _client_ip()

    if record.failed_attempts >= attempts_limit:
        record.locked_until = now + timedelta(minutes=lock_minutes)
        record.failed_attempts = 0

    db.session.add(record)
    db.session.commit()
    return record


def _reset_failed_login(identifier):
    record = _get_lock_record(identifier)
    if not record:
        return
    record.failed_attempts = 0
    record.locked_until = None
    db.session.commit()


def _is_locked(record):
    now = get_tr_now().replace(tzinfo=None)
    return bool(record and record.locked_until and record.locked_until > now)


def _get_password_reset_serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'])


def _get_password_reset_token_max_age():
    try:
        return max(int(current_app.config.get("PASSWORD_RESET_TOKEN_MAX_AGE_SECONDS", 3600)), 1)
    except (TypeError, ValueError):
        return 3600


def _get_password_reset_base_url():
    configured_base_url = (
        current_app.config.get("PASSWORD_RESET_BASE_URL")
        or current_app.config.get("PUBLIC_BASE_URL")
        or ""
    ).strip()
    if configured_base_url:
        return configured_base_url.rstrip("/") + "/"

    script_root = (request.script_root or "").strip("/")
    path_prefix = f"/{script_root}" if script_root else ""

    host = (request.host or "").split(":", 1)[0].strip().lower()
    local_hosts = {"localhost", "127.0.0.1", "::1", "[::1]"}
    if host in local_hosts or host.endswith(".localhost"):
        return f"{request.host_url.rstrip('/')}{path_prefix}/"

    raise RuntimeError(
        "PASSWORD_RESET_BASE_URL veya PUBLIC_BASE_URL tanımlı değil; "
        "güvenli şifre sıfırlama bağlantısı üretilemedi."
    )

def _build_password_reset_link(token):
    reset_path = url_for('auth.sifre_yenile', token=token)
    return urljoin(_get_password_reset_base_url(), reset_path.lstrip("/"))


def _safe_redirect_target(raw_target, fallback_target):
    fallback = str(fallback_target or "/").strip() or "/"
    target = str(raw_target or "").strip()
    if not target:
        return fallback
    if target.startswith("//"):
        return fallback

    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc:
        request_origin = urlsplit(request.host_url)
        if (parsed.scheme or "").lower() != (request_origin.scheme or "").lower():
            return fallback
        if (parsed.hostname or "").lower() != (request_origin.hostname or "").lower():
            return fallback
        request_port = request_origin.port
        parsed_port = parsed.port
        if (request_port or None) != (parsed_port or None):
            return fallback
        safe_path = parsed.path if str(parsed.path or "").startswith("/") else f"/{parsed.path or ''}"
        return urlunsplit(("", "", safe_path or "/", parsed.query, parsed.fragment))

    if not target.startswith("/"):
        return fallback
    return target


def _password_reset_state(user):
    payload = f"{user.id}:{user.kullanici_adi}:{user.sifre_hash or ''}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _build_password_reset_token(user):
    serializer = _get_password_reset_serializer()
    return serializer.dumps(
        {
            "user_id": user.id,
            "email": _normalize_login_email(user.kullanici_adi),
            "state": _password_reset_state(user),
        },
        salt=PASSWORD_RESET_SALT,
    )


def _load_password_reset_user(token):
    payload = _get_password_reset_serializer().loads(
        token,
        salt=PASSWORD_RESET_SALT,
        max_age=_get_password_reset_token_max_age(),
    )

    if isinstance(payload, str):
        email = _normalize_login_email(payload)
        return _find_active_user_by_email(email), email

    if not isinstance(payload, dict):
        raise BadSignature("Unsupported password reset payload.")

    user_id = payload.get("user_id")
    email = _normalize_login_email(payload.get("email"))
    state = str(payload.get("state") or "").strip()

    user = db.session.get(Kullanici, user_id) if user_id is not None else None
    if not user or user.is_deleted:
        raise BadSignature("Password reset user no longer exists.")
    if _normalize_login_email(user.kullanici_adi) != email:
        raise BadSignature("Password reset email mismatch.")
    if not state or state != _password_reset_state(user):
        raise BadSignature("Password reset token already used or superseded.")
    return user, email


def _validate_password_reset_value(password):
    if PASSWORD_RESET_PATTERN.match(password or ""):
        return None
    return (
        "Yeni şifre en az 8 karakter uzunluğunda olmalı; "
        "1 büyük harf, 1 küçük harf, 1 rakam ve 1 özel karakter içermelidir."
    )


def mail_gonder(alici_mail, konu, icerik):
    mail_host = (current_app.config.get("MAIL_HOST") or "").strip() or "smtp.gmail.com"
    mail_port = int(current_app.config.get("MAIL_PORT") or 587)
    mail_use_tls = bool(current_app.config.get("MAIL_USE_TLS", True))
    mail_username = (current_app.config.get("MAIL_USERNAME") or "").strip()
    gonderici_mail = (current_app.config.get("MAIL_FROM_EMAIL") or "").strip()
    reply_to = (current_app.config.get("MAIL_REPLY_TO") or "").strip()

    if not gonderici_mail:
        current_app.logger.error("MAIL_FROM_EMAIL tanımlı değil, e-posta gönderilemedi.")
        return False

    sifre = gizli_sifreyi_getir()
    if mail_username and not sifre:
        current_app.logger.error("MAIL_USERNAME kullanılıyor ancak SMTP şifresi alınamadı.")
        return False

    msg = MIMEMultipart()
    msg['From'] = f"SAR-X Sistem <{gonderici_mail}>"
    msg['To'] = alici_mail
    msg['Subject'] = konu
    if reply_to:
        msg.add_header('reply-to', reply_to)

    msg.attach(MIMEText(icerik, 'html', 'utf-8'))

    try:
        server = smtplib.SMTP(mail_host, mail_port, timeout=20)
        if mail_use_tls:
            server.starttls()
        if mail_username:
            server.login(mail_username, sifre)
        server.send_message(msg)
        server.quit()
        return True
    except smtplib.SMTPAuthenticationError as e:
        capture_error(e, error_code="SAR-X-MAIL-4102")
        current_app.logger.warning("Mail gönderim kimlik doğrulama hatası oluştu.")
        return False
    except Exception as e:
        capture_error(e, error_code="SAR-X-MAIL-4101")
        current_app.logger.warning("Mail gönderim hatası oluştu.")
        return False


# --- ROTALAR ---

@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit(lambda: current_app.config.get("LOGIN_RATE_LIMIT", "5 per minute"), methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for(role_home_endpoint(current_user)))
        
    if request.method == 'POST':
        kullanici_adi = _normalize_login_email(request.form.get('kullanici_adi'))
        sifre = request.form.get('sifre') or ''
        remember_me = request.form.get('remember_me') == 'on'
        security_answer = request.form.get('security_verification')
        security_token = request.form.get('security_verification_token')
        identifier = _auth_identifier(kullanici_adi)

        try:
            lock_record = _get_lock_record(identifier)
        except Exception:
            db.session.rollback()
            lock_record = None

        if _is_locked(lock_record):
            now = get_tr_now().replace(tzinfo=None)
            remaining = max(int((lock_record.locked_until - now).total_seconds() // 60), 1)
            flash(f"Çok fazla başarısız giriş denemesi tespit edildi. Lütfen {remaining} dakika sonra tekrar deneyin.", "danger")
            audit_log("auth.login", outcome="locked", username=kullanici_adi, ip=_client_ip())
            return _render_login_page(status_code=429, force_new=True)

        captcha_valid, captcha_state = validate_login_captcha(security_answer, submitted_token=security_token)
        if not captcha_valid:
            try:
                record = _register_failed_login(identifier)
                now = get_tr_now().replace(tzinfo=None)
                if record.locked_until and record.locked_until > now:
                    flash_safe_error("SAR-X-AUTH-1202", include_help_note=True)
                else:
                    flash_safe_error("SAR-X-AUTH-1202", include_help_note=True)
            except Exception:
                db.session.rollback()
                flash_safe_error("SAR-X-AUTH-1202", include_help_note=True)
            invalidate_login_captcha(clear_session=True)
            if captcha_state == "expired":
                event_key = "auth.login.captcha_expired"
            elif captcha_state in {"stale", "used"}:
                event_key = "auth.login.captcha_refresh_required"
            else:
                event_key = "auth.login.captcha_failed"
            capture_error(
                error_code="SAR-X-AUTH-1202",
                status_code=400,
                detail=f"Login captcha failed | state={captcha_state or 'unknown'}",
            )
            log_kaydet("Güvenlik", f"Login captcha verification failed: {kullanici_adi}", event_key=event_key, outcome="failed")
            audit_log(event_key, outcome="failed", username=kullanici_adi, ip=_client_ip())
            return _render_login_page(
                status_code=400,
                force_new=True,
                captcha_feedback=_captcha_feedback_message(captcha_state),
            )

        user = _find_active_user_by_email(kullanici_adi)
        
        if user and user.sifre_kontrol(sifre):
            invalidate_login_captcha(clear_session=True)
            session.clear()
            login_user(user, remember=remember_me)
            session.permanent = True
            try:
                _reset_failed_login(identifier)
            except Exception:
                db.session.rollback()
            log_kaydet('Giriş', f'{user.kullanici_adi} sisteme giriş yaptı.')
            audit_log("auth.login", outcome="success", user_id=user.id, role=user.rol, ip=_client_ip())
            return redirect(url_for(role_home_endpoint(user)))

        try:
            record = _register_failed_login(identifier)
            now = get_tr_now().replace(tzinfo=None)
            if record.locked_until and record.locked_until > now:
                flash("Hesabınız geçici olarak kilitlendi. Lütfen bir süre sonra tekrar deneyin.", "danger")
            else:
                flash("Şifre veya Kullanıcı Adı yanlış.", "danger")
        except Exception:
            db.session.rollback()
            flash("Şifre veya Kullanıcı Adı yanlış.", "danger")

        audit_log("auth.login", outcome="failed", username=kullanici_adi, ip=_client_ip())
        return _render_login_page(force_new=True)
	        
    return _render_login_page(force_new=True)


@auth_bp.route("/passkey/register/begin", methods=["POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
def passkey_register_begin():
    _require_passkey_feature()

    try:
        rp_id = resolve_rp_id()
        challenge = create_challenge()
        store_registration_state(challenge=challenge, user_id=current_user.id)
    except PasskeyError:
        audit_log("auth.passkey.register.begin", outcome="blocked", user_id=current_user.id, ip=_client_ip())
        return _passkey_json_error("Passkey ayarları şu an tamamlanamadı.", 503)

    exclude_credentials = []
    for credential in current_user.passkey_credentials:
        if not getattr(credential, "is_active", True):
            continue
        transports = _passkey_transports_from_json(credential.transports_json)
        exclude_credentials.append(
            {
                "id": credential.credential_id,
                "type": "public-key",
                "transports": transports if isinstance(transports, list) else [],
            }
        )

    return jsonify(
        {
            "status": "success",
            "public_key": {
                "challenge": challenge,
                "rp": {
                    "id": rp_id,
                    "name": current_app.config.get("PASSKEY_RP_NAME", "SAR-X ARFF"),
                },
                "user": {
                    "id": b64url_encode(str(current_user.id).encode("utf-8")),
                    "name": current_user.kullanici_adi,
                    "displayName": current_user.tam_ad or current_user.kullanici_adi,
                },
                "pubKeyCredParams": [
                    {"type": "public-key", "alg": -7},
                    {"type": "public-key", "alg": -257},
                ],
                "timeout": 60000,
                "attestation": "none",
                "excludeCredentials": exclude_credentials,
                "authenticatorSelection": {
                    "residentKey": "required",
                    "requireResidentKey": True,
                    "userVerification": "required",
                },
            },
        }
    )


@auth_bp.route("/passkey/register/finish", methods=["POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
def passkey_register_finish():
    _require_passkey_feature()

    payload = request.get_json(silent=True) or {}
    try:
        state = consume_registration_state()
        if int(state.get("user_id") or 0) != int(current_user.id):
            raise PasskeyError("Passkey oturumu kullanıcı ile eşleşmiyor.")
        verified = validate_registration_response(
            payload,
            expected_challenge=str(state.get("challenge") or ""),
            expected_rp_id=str(state.get("rp_id") or ""),
        )
    except PasskeyError:
        audit_log("auth.passkey.register.finish", outcome="failed", user_id=current_user.id, ip=_client_ip())
        return _passkey_json_error("Biyometrik giriş bu cihaz için etkinleştirilemedi.", 400)

    existing = PasskeyCredential.query.filter_by(credential_id=verified["credential_id"]).first()
    if existing:
        if existing.user_id != current_user.id:
            audit_log("auth.passkey.register.finish", outcome="conflict", user_id=current_user.id, ip=_client_ip())
            return _passkey_json_error("Bu passkey başka bir hesap için kayıtlı.", 409)
        if getattr(existing, "is_active", True):
            audit_log("auth.passkey.register.finish", outcome="duplicate", user_id=current_user.id, ip=_client_ip())
            return jsonify({"status": "success", "message": "Bu cihaz zaten biyometrik giriş için kayıtlı."})

        existing.public_key = verified["public_key"]
        existing.algorithm = verified["algorithm"]
        existing.sign_count = verified["sign_count"]
        existing.friendly_name = (str(payload.get("device_name") or "").strip()[:120] or existing.friendly_name or _default_passkey_friendly_name())
        existing.transports_json = json.dumps(verified["transports"], ensure_ascii=True)
        existing.backup_eligible = verified["backup_eligible"]
        existing.backup_state = verified["backup_state"]
        existing.is_active = True
        existing.revoked_at = None
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            audit_log("auth.passkey.register.finish", outcome="error", user_id=current_user.id, ip=_client_ip())
            return _passkey_json_error("Biyometrik giriş bu cihaz için etkinleştirilemedi.", 500)
        log_kaydet("Güvenlik", f"{current_user.kullanici_adi} için kaldırılmış passkey yeniden etkinleştirildi.", event_key="auth.passkey.register", outcome="success")
        audit_log("auth.passkey.register.finish", outcome="reactivated", user_id=current_user.id, ip=_client_ip())
        return jsonify({"status": "success", "message": "Biyometrik giriş kaydı yeniden etkinleştirildi."})

    credential = PasskeyCredential(
        user_id=current_user.id,
        credential_id=verified["credential_id"],
        public_key=verified["public_key"],
        algorithm=verified["algorithm"],
        sign_count=verified["sign_count"],
        friendly_name=(str(payload.get("device_name") or "").strip()[:120] or _default_passkey_friendly_name()),
        is_active=True,
        revoked_at=None,
        transports_json=json.dumps(verified["transports"], ensure_ascii=True),
        backup_eligible=verified["backup_eligible"],
        backup_state=verified["backup_state"],
    )
    db.session.add(credential)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        audit_log("auth.passkey.register.finish", outcome="error", user_id=current_user.id, ip=_client_ip())
        return _passkey_json_error("Biyometrik giriş bu cihaz için etkinleştirilemedi.", 500)

    log_kaydet("Güvenlik", f"{current_user.kullanici_adi} için yeni bir passkey kaydedildi.", event_key="auth.passkey.register", outcome="success")
    audit_log("auth.passkey.register.finish", outcome="success", user_id=current_user.id, ip=_client_ip())
    return jsonify({"status": "success", "message": "Biyometrik giriş bu cihaz için etkinleştirildi."})


@auth_bp.route("/passkey/credentials", methods=["GET"])
@login_required
@limiter.limit("60 per minute", methods=["GET"])
def passkey_credentials():
    _require_passkey_feature()

    credentials = (
        PasskeyCredential.query.filter_by(user_id=current_user.id, is_active=True)
        .order_by(PasskeyCredential.last_used_at.desc(), PasskeyCredential.created_at.desc())
        .all()
    )
    payload = []
    for index, credential in enumerate(credentials, start=1):
        device_label = str(getattr(credential, "friendly_name", "") or "").strip() or f"Cihaz {index}"
        payload.append(
            {
                "id": credential.id,
                "label": device_label,
                "created_at": _format_passkey_timestamp(getattr(credential, "created_at", None)),
                "last_used_at": _format_passkey_timestamp(getattr(credential, "last_used_at", None)),
                "transports": _passkey_transports_from_json(getattr(credential, "transports_json", None)),
                "backup_eligible": bool(getattr(credential, "backup_eligible", False)),
                "backup_state": bool(getattr(credential, "backup_state", False)),
            }
        )
    return jsonify({"status": "success", "credentials": payload})


@auth_bp.route("/passkey/credentials/revoke", methods=["POST"])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
def passkey_credential_revoke():
    _require_passkey_feature()

    payload = request.get_json(silent=True) or {}
    try:
        credential_id = int(payload.get("credential_id") or 0)
    except Exception:
        credential_id = 0
    if credential_id <= 0:
        return _passkey_json_error("Geçersiz passkey kaydı.", 400)

    credential = (
        PasskeyCredential.query.filter_by(
            id=credential_id,
            user_id=current_user.id,
            is_active=True,
        ).first()
    )
    if not credential:
        return _passkey_json_error("Passkey kaydı bulunamadı.", 404)

    credential.is_active = False
    credential.revoked_at = get_tr_now().replace(tzinfo=None)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        audit_log("auth.passkey.revoke", outcome="error", user_id=current_user.id, credential_id=credential_id, ip=_client_ip())
        return _passkey_json_error("Passkey kaydı kaldırılamadı.", 500)

    log_kaydet("Güvenlik", f"{current_user.kullanici_adi} passkey kaydını kaldırdı.", event_key="auth.passkey.revoke", outcome="success")
    audit_log("auth.passkey.revoke", outcome="success", user_id=current_user.id, credential_id=credential_id, ip=_client_ip())
    return jsonify({"status": "success", "message": "Passkey kaydı kaldırıldı."})


@auth_bp.route("/login/passkey/begin", methods=["POST"])
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
def login_passkey_begin():
    _require_passkey_feature()
    if current_user.is_authenticated:
        return jsonify({"status": "success", "redirect_url": _passkey_success_redirect_url(current_user)})

    payload = request.get_json(silent=True) or {}
    try:
        challenge = create_challenge()
        store_authentication_state(challenge=challenge, remember_me=_passkey_remember_value(payload))
    except PasskeyError:
        audit_log("auth.passkey.login.begin", outcome="blocked", ip=_client_ip())
        return _passkey_json_error("Passkey ayarları şu an tamamlanamadı.", 503)

    return jsonify(
        {
            "status": "success",
            "public_key": {
                "challenge": challenge,
                "rpId": resolve_rp_id(),
                "timeout": 60000,
                "userVerification": "required",
                "allowCredentials": [],
            },
        }
    )


@auth_bp.route("/login/passkey/finish", methods=["POST"])
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
def login_passkey_finish():
    _require_passkey_feature()
    if current_user.is_authenticated:
        return jsonify({"status": "success", "redirect_url": _passkey_success_redirect_url(current_user)})

    payload = request.get_json(silent=True) or {}
    try:
        state = consume_authentication_state()
        credential_id = b64url_encode(b64url_decode(payload.get("rawId")))
    except PasskeyError:
        audit_log("auth.passkey.login.finish", outcome="failed", ip=_client_ip())
        return _passkey_json_error("Biyometrik giriş doğrulanamadı.", 400)

    credential = PasskeyCredential.query.filter_by(credential_id=credential_id, is_active=True).first()
    user = credential.user if credential and credential.user and not credential.user.is_deleted else None
    identifier_source = user.kullanici_adi if user else credential_id
    identifier = _auth_identifier(identifier_source)

    try:
        lock_record = _get_lock_record(identifier)
    except Exception:
        db.session.rollback()
        lock_record = None

    if _is_locked(lock_record):
        now = get_tr_now().replace(tzinfo=None)
        remaining = max(int((lock_record.locked_until - now).total_seconds() // 60), 1)
        audit_log("auth.passkey.login.finish", outcome="locked", username=getattr(user, "kullanici_adi", ""), ip=_client_ip())
        return _passkey_json_error(
            f"Çok fazla başarısız giriş denemesi tespit edildi. Lütfen {remaining} dakika sonra tekrar deneyin.",
            429,
        )

    captcha_valid, captcha_state = validate_login_captcha(
        payload.get("security_verification"),
        submitted_token=payload.get("security_verification_token"),
    )
    if not captcha_valid:
        try:
            _register_failed_login(identifier)
        except Exception:
            db.session.rollback()
        invalidate_login_captcha(clear_session=True)
        event_key = "auth.passkey.login.captcha_failed"
        if captcha_state == "expired":
            event_key = "auth.passkey.login.captcha_expired"
        elif captcha_state in {"stale", "used"}:
            event_key = "auth.passkey.login.captcha_refresh_required"
        capture_error(
            error_code="SAR-X-AUTH-1202",
            status_code=400,
            detail=f"Passkey login captcha failed | state={captcha_state or 'unknown'}",
        )
        audit_log(event_key, outcome="failed", username=getattr(user, "kullanici_adi", ""), ip=_client_ip())
        return _passkey_json_error("Güvenlik doğrulaması başarısız oldu.", 400)

    if not credential or not user:
        try:
            _register_failed_login(identifier)
        except Exception:
            db.session.rollback()
        audit_log("auth.passkey.login.finish", outcome="unknown_credential", ip=_client_ip())
        return _passkey_json_error("Biyometrik giriş doğrulanamadı.", 400)

    try:
        verified = verify_authentication_response(
            payload,
            credential_public_key=credential.public_key,
            expected_challenge=str(state.get("challenge") or ""),
            stored_sign_count=credential.sign_count,
            expected_rp_id=str(state.get("rp_id") or ""),
        )
    except PasskeyError:
        try:
            _register_failed_login(identifier)
        except Exception:
            db.session.rollback()
        audit_log("auth.passkey.login.finish", outcome="failed", user_id=user.id, ip=_client_ip())
        return _passkey_json_error("Biyometrik giriş doğrulanamadı.", 400)

    credential.sign_count = verified["sign_count"]
    credential.backup_eligible = verified["backup_eligible"]
    credential.backup_state = verified["backup_state"]
    credential.last_used_at = get_tr_now().replace(tzinfo=None)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        audit_log("auth.passkey.login.finish", outcome="error", user_id=user.id, ip=_client_ip())
        return _passkey_json_error("Biyometrik giriş doğrulanamadı.", 500)

    invalidate_login_captcha(clear_session=True)
    session.clear()
    login_user(user, remember=bool(state.get("remember_me")))
    session.permanent = True
    try:
        _reset_failed_login(identifier)
    except Exception:
        db.session.rollback()

    log_kaydet("Giriş", f"{user.kullanici_adi} passkey ile sisteme giriş yaptı.")
    audit_log("auth.passkey.login.finish", outcome="success", user_id=user.id, role=user.rol, ip=_client_ip())
    return jsonify({"status": "success", "redirect_url": _passkey_success_redirect_url(user)})


@auth_bp.route("/login/captcha/refresh", methods=["POST"])
@limiter.limit("30 per minute", methods=["POST"])
def login_captcha_refresh():
    payload = build_login_captcha(force_new=True)
    log_kaydet("Güvenlik", "Login captcha refreshed", event_key="auth.login.captcha_refresh", outcome="success")
    audit_log("auth.login.captcha_refresh", outcome="success", ip=_client_ip())
    response = jsonify({"status": "success", "captcha": payload})
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["Vary"] = "Cookie"
    return response


@auth_bp.route("/login/captcha/<string:token>.svg", methods=["GET"])
def login_captcha_image(token):
    svg = render_login_captcha_svg(token)
    response = make_response(svg, 200)
    response.headers["Content-Type"] = "image/svg+xml; charset=utf-8"
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["Vary"] = "Cookie"
    return response

@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    username = current_user.kullanici_adi
    log_kaydet('Çıkış', f'{username} sistemden güvenli çıkış yaptı.')
    audit_log("auth.logout", outcome="success", username=username, ip=_client_ip())
    clear_role_override(current_user)
    logout_user()
    invalidate_login_captcha(clear_session=True)
    session.clear()
    flash("Sistemden güvenli çıkış yapıldı.", "success")
    response = redirect(url_for('auth.login'))
    return _clear_auth_cookies(response)


@auth_bp.route('/role-switch', methods=['GET', 'POST'])
@login_required
def role_switch():
    if not can_use_role_switch(current_user):
        abort(403)

    if request.method == "GET":
        selected_options = get_role_switch_options(current_user)
        option_labels = {item["key"]: item.get("label") or item["key"] for item in selected_options}
        active_role = get_effective_role_label(current_user)
        base_role_key = (current_user.rol or "").strip()
        base_role_label = option_labels.get(base_role_key, active_role or base_role_key)
        return render_template(
            "role_switch.html",
            role_switch_options=selected_options,
            active_role_label=active_role,
            base_role_label=base_role_label,
            active_override=(session.get("temporary_role_override") or "").strip(),
        )

    fallback_target = url_for(role_home_endpoint(current_user))
    redirect_target = _safe_redirect_target(request.form.get("next") or request.referrer, fallback_target)
    selected_role = (request.form.get('role') or "").strip()
    selected_option_map = {item["key"]: item for item in get_role_switch_options(current_user)}

    if not selected_role or selected_role == "__default__":
        clear_role_override(current_user)
        flash("Geçici rol kaldırıldı. Varsayılan rolünüz yeniden etkin.", "success")
        audit_log(
            "auth.role_switch.ended",
            outcome="success",
            real_user_id=current_user.id,
            real_user_email=current_user.kullanici_adi,
            base_role=current_user.rol,
            acting_role=current_user.rol,
            effective_role=current_user.rol,
            request_id=str(getattr(g, "request_id", "") or ""),
            ip=_client_ip(),
        )
        return redirect(redirect_target)

    if selected_role not in selected_option_map:
        flash("Desteklenmeyen rol seçimi gönderildi.", "danger")
        return redirect(redirect_target)

    success, active_role = set_role_override(selected_role, current_user)
    if not success:
        flash("Geçici rol değiştirilemedi.", "danger")
        return redirect(redirect_target)

    event_key = "auth.role_switch.started"
    if selected_option_map.get(selected_role, {}).get("active"):
        event_key = "auth.role_switch.changed"
    flash(f"Geçici aktif rol güncellendi: {get_effective_role_label(current_user)}", "success")
    audit_log(
        event_key,
        outcome="success",
        real_user_id=current_user.id,
        real_user_email=current_user.kullanici_adi,
        base_role=current_user.rol,
        acting_role=active_role,
        effective_role=active_role,
        selected_role=active_role,
        request_id=str(getattr(g, "request_id", "") or ""),
        ip=_client_ip(),
    )
    return redirect(redirect_target)


@auth_bp.route('/sifre-sifirla-talep', methods=['POST'])
@limiter.limit(lambda: current_app.config.get("RESET_RATE_LIMIT", "3 per minute"), methods=["POST"])
def sifre_sifirla_talep():
    k_ad = _normalize_login_email(request.form.get('kullanici_adi'))
    generic_message = "Şifre sıfırlama bağlantısı e-posta adresinize gönderildi."

    if not k_ad:
        flash(generic_message, "info")
        return redirect(url_for('auth.login'))

    if not _looks_like_email(k_ad):
        capture_error(error_code="SAR-X-AUTH-1101", status_code=400, detail="Invalid password reset email format")
        flash_safe_error("SAR-X-AUTH-1101", include_help_note=True)
        return redirect(url_for('auth.login'))

    user = _find_active_user_by_email(k_ad)

    if user:
        try:
            token = _build_password_reset_token(user)
            reset_link = _build_password_reset_link(token)
            kullanici_ismi = getattr(user, 'tam_ad', 'Personel')
            konu = "SAR-X Şifre Sıfırlama Bağlantısı"
            icerik = render_template(
                'email/sifre_sifirla.html',
                kullanici_ismi=kullanici_ismi,
                reset_link=reset_link,
            )
            mail_sonuc = mail_gonder(k_ad, konu, icerik)
            if mail_sonuc:
                log_kaydet('Şifre Sıfırlama', f'{k_ad} için şifre sıfırlama bağlantısı gönderildi.')
                audit_log("auth.password_reset.request", outcome="success", username=k_ad, ip=_client_ip())
            else:
                current_app.logger.warning("Şifre sıfırlama e-postası gönderilemedi: %s", k_ad)
                audit_log("auth.password_reset.request", outcome="delivery_failed", username=k_ad, ip=_client_ip())
                capture_error(error_code="SAR-X-MAIL-4101", status_code=502, detail="Password reset email delivery failed")
                flash_safe_error("SAR-X-MAIL-4101", include_help_note=True)
                return redirect(url_for('auth.login'))
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Şifre sıfırlama akışı hazırlanırken hata oluştu: %s", k_ad)
            audit_log("auth.password_reset.request", outcome="error", username=k_ad, ip=_client_ip())
            capture_error(error_code="SAR-X-MAIL-4101", status_code=502)
            flash_safe_error("SAR-X-MAIL-4101", include_help_note=True)
            return redirect(url_for('auth.login'))
    else:
        audit_log("auth.password_reset.request", outcome="user_not_found", username=k_ad, ip=_client_ip())

    flash(generic_message, "success")
    return redirect(url_for('auth.login'))


@auth_bp.route('/sifre-yenile/<token>', methods=['GET', 'POST'])
def sifre_yenile(token):
    try:
        user, email = _load_password_reset_user(token)
    except SignatureExpired:
        capture_error(error_code="SAR-X-AUTH-1301", status_code=400, detail="Expired password reset token")
        flash_safe_error("SAR-X-AUTH-1301", include_help_note=True)
        return redirect(url_for('auth.login'))
    except BadSignature:
        capture_error(error_code="SAR-X-AUTH-1301", status_code=400, detail="Invalid password reset token")
        flash_safe_error("SAR-X-AUTH-1301", include_help_note=True)
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        yeni_sifre = request.form.get('yeni_sifre')

        password_error = _validate_password_reset_value(yeni_sifre)
        if password_error:
            flash(password_error, "warning")
            return render_template('sifre_yenile.html', token=token, email=email)

        if not user:
            flash("Kullanıcı bulunamadı.", "danger")
            return redirect(url_for('auth.login'))

        user.sifre_set(yeni_sifre)

        try:
            db.session.commit()
            log_kaydet('Şifre Yenileme', f'{email} şifresini başarıyla yeniledi.')
            audit_log("auth.password_reset.complete", outcome="success", user_id=user.id, ip=_client_ip())
            flash("Şifreniz başarıyla güncellendi! Giriş yapabilirsiniz.", "success")
            return redirect(url_for('auth.login'))
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Şifre yenileme kaydedilemedi: %s", email)
            audit_log("auth.password_reset.complete", outcome="error", username=email, ip=_client_ip())
            capture_error(error_code="SAR-X-SYSTEM-5101", status_code=500)
            flash_safe_error("SAR-X-SYSTEM-5101", include_help_note=True)
            
    return render_template('sifre_yenile.html', token=token, email=email)
