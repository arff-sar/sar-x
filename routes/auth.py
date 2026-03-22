import hashlib
import smtplib
import re
from datetime import timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib.parse import urljoin

from flask import Blueprint, current_app, flash, jsonify, make_response, redirect, render_template, request, session, url_for
from flask_login import login_user, logout_user, login_required, current_user
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from sqlalchemy import func

from captcha_helper import (
    build_login_captcha,
    invalidate_login_captcha,
    render_login_captcha_svg,
    validate_login_captcha,
)
from models import AuthLockout, Kullanici, get_tr_now
from extensions import audit_log, db, limiter, log_kaydet
from decorators import role_home_endpoint

auth_bp = Blueprint('auth', __name__)

PASSWORD_RESET_SALT = 'sifre-sifirlama-tuzu'
PASSWORD_RESET_PATTERN = re.compile(r"^(?=.*\d)(?=.*[a-z])(?=.*[A-Z])(?=.*?[#?!@$%^&*-]).{8,}$")

# --- YARDIMCI FONKSİYONLAR ---


def _render_login_page(status_code=200, force_new=False):
    response = make_response(
        render_template('login.html', login_captcha=build_login_captcha(force_new=force_new)),
        status_code,
    )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["Vary"] = "Cookie"
    return response

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
    except Exception as e:
        current_app.logger.warning("Secret Manager erişim hatası: %s", e)
        return None


def _client_ip():
    forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return forwarded or (request.remote_addr or "unknown")


def _normalize_login_email(raw_value):
    return (raw_value or "").strip().lower()


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

    forwarded_host = (
        (request.headers.get("X-Forwarded-Host") or "")
        or (request.headers.get("X-Forwarded-Server") or "")
    ).split(",")[0].strip()
    if forwarded_host:
        forwarded_proto = (request.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip()
        scheme = forwarded_proto or request.scheme or "https"
        return f"{scheme}://{forwarded_host}{path_prefix}/"

    return f"{request.host_url.rstrip('/')}{path_prefix}/"


def _build_password_reset_link(token):
    reset_path = url_for('auth.sifre_yenile', token=token)
    return urljoin(_get_password_reset_base_url(), reset_path.lstrip("/"))


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
    except Exception as e:
        current_app.logger.warning("Mail gönderim hatası: %s", e)
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
                    flash("Güvenlik doğrulaması nedeniyle hesabınız geçici olarak kilitlendi. Lütfen daha sonra tekrar deneyin.", "danger")
                elif captcha_state == "expired":
                    flash("Güvenlik doğrulamasının süresi doldu. Lütfen yeni doğrulama kodu alın.", "danger")
                elif captcha_state == "missing":
                    flash("Güvenlik doğrulamasını tamamlayın ve tekrar deneyin.", "danger")
                elif captcha_state in {"stale", "used"}:
                    flash("Güvenlik doğrulaması doğrulanamadı. Lütfen yeni kod alın.", "danger")
                else:
                    flash("Güvenlik doğrulaması yanlış. Lütfen kodu yeniden girin.", "danger")
            except Exception:
                db.session.rollback()
                flash("Güvenlik doğrulaması doğrulanamadı. Lütfen yeni kod alın.", "danger")
            invalidate_login_captcha(clear_session=True)
            if captcha_state == "expired":
                event_key = "auth.login.captcha_expired"
            elif captcha_state in {"stale", "used"}:
                event_key = "auth.login.captcha_refresh_required"
            else:
                event_key = "auth.login.captcha_failed"
            log_kaydet("Güvenlik", f"Login captcha verification failed: {kullanici_adi}", event_key=event_key, outcome="failed")
            audit_log(event_key, outcome="failed", username=kullanici_adi, ip=_client_ip())
            return _render_login_page(status_code=400, force_new=True)

        user = _find_active_user_by_email(kullanici_adi)
        
        if user and user.sifre_kontrol(sifre):
            login_user(user, remember=remember_me)
            session.permanent = True
            invalidate_login_captcha(clear_session=True)
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
    logout_user()
    invalidate_login_captcha(clear_session=True)
    session.pop("_flashes", None)
    flash("Sistemden güvenli çıkış yapıldı.", "success")
    return redirect(url_for('auth.login'))


@auth_bp.route('/sifre-sifirla-talep', methods=['POST'])
@limiter.limit(lambda: current_app.config.get("RESET_RATE_LIMIT", "3 per minute"), methods=["POST"])
def sifre_sifirla_talep():
    k_ad = _normalize_login_email(request.form.get('kullanici_adi'))
    generic_message = "Şifre sıfırlama bağlantısı e-posta adresinize gönderildi."

    if not k_ad:
        flash(generic_message, "info")
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
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Şifre sıfırlama akışı hazırlanırken hata oluştu: %s", k_ad)
            audit_log("auth.password_reset.request", outcome="error", username=k_ad, ip=_client_ip())
    else:
        audit_log("auth.password_reset.request", outcome="user_not_found", username=k_ad, ip=_client_ip())

    flash(generic_message, "success")
    return redirect(url_for('auth.login'))


@auth_bp.route('/sifre-yenile/<token>', methods=['GET', 'POST'])
def sifre_yenile(token):
    try:
        user, email = _load_password_reset_user(token)
    except SignatureExpired:
        flash("Şifre sıfırlama bağlantısının süresi dolmuş. Lütfen yeni bir talep oluşturun.", "danger")
        return redirect(url_for('auth.login'))
    except BadSignature:
        flash("Geçersiz veya bozuk, süresi dolmuş ya da daha önce kullanılmış bir şifre sıfırlama bağlantısı.", "danger")
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
            flash("Şifre güncellenirken beklenmedik bir hata oluştu.", "danger")
            
    return render_template('sifre_yenile.html', token=token, email=email)
