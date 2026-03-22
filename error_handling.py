import re
import smtplib
import traceback
from dataclasses import dataclass

from flask import current_app, flash, g, request
from flask_login import current_user
from flask_wtf.csrf import CSRFError
from itsdangerous import BadSignature, SignatureExpired
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError, SQLAlchemyError
from werkzeug.exceptions import HTTPException

from extensions import log_kaydet


@dataclass(frozen=True)
class ErrorSpec:
    error_code: str
    title: str
    user_message: str
    owner_message: str
    module: str
    severity: str
    status_code: int
    possible_cause: str = ""


ERROR_REGISTRY = {
    "SAR-X-AUTH-1101": ErrorSpec(
        error_code="SAR-X-AUTH-1101",
        title="Geçersiz E-posta Biçimi",
        user_message="E-posta adresi biçimi geçersiz.",
        owner_message="Form akışında beklenen e-posta biçimi doğrulaması başarısız oldu.",
        module="AUTH",
        severity="warning",
        status_code=400,
        possible_cause="Kullanıcı girdisi beklenen e-posta düzeniyle eşleşmiyor.",
    ),
    "SAR-X-AUTH-1201": ErrorSpec(
        error_code="SAR-X-AUTH-1201",
        title="Güvenlik Doğrulama Süresi Doldu",
        user_message="Güvenlik doğrulama süresi doldu.",
        owner_message="Captcha veya zaman duyarlı doğrulama tokenı süresini aştı.",
        module="AUTH",
        severity="warning",
        status_code=400,
        possible_cause="Captcha süresi doldu veya eski token ile istek gönderildi.",
    ),
    "SAR-X-AUTH-1202": ErrorSpec(
        error_code="SAR-X-AUTH-1202",
        title="Güvenlik Doğrulaması Başarısız",
        user_message="Güvenlik doğrulaması başarısız oldu.",
        owner_message="Captcha ya da CSRF doğrulaması beklenen kuralları sağlamadı.",
        module="AUTH",
        severity="warning",
        status_code=400,
        possible_cause="Captcha yanlış girildi, token tazelendi veya CSRF doğrulaması geçmedi.",
    ),
    "SAR-X-AUTH-1301": ErrorSpec(
        error_code="SAR-X-AUTH-1301",
        title="Geçersiz Şifre Sıfırlama Bağlantısı",
        user_message="Şifre sıfırlama bağlantısı geçersiz veya süresi dolmuş.",
        owner_message="Şifre sıfırlama tokenı doğrulanamadı ya da daha önce geçersizleşti.",
        module="AUTH",
        severity="warning",
        status_code=400,
        possible_cause="Token süresi doldu, bozuldu veya eski şifre durumuyla eşleşmiyor.",
    ),
    "SAR-X-AUTH-6101": ErrorSpec(
        error_code="SAR-X-AUTH-6101",
        title="Kimlik Doğrulama Gerekli",
        user_message="Bu işlem için giriş yapmanız gerekiyor.",
        owner_message="Anonim kullanıcı korumalı kaynağa erişmeye çalıştı.",
        module="AUTH",
        severity="warning",
        status_code=401,
        possible_cause="Oturum süresi doldu veya kullanıcı giriş yapmadı.",
    ),
    "SAR-X-AUTH-6102": ErrorSpec(
        error_code="SAR-X-AUTH-6102",
        title="Erişim Yetkisi Yok",
        user_message="Bu işlemi görüntüleme yetkiniz bulunmuyor.",
        owner_message="Kimliği doğrulanmış kullanıcı yetkisiz kaynağa erişmeye çalıştı.",
        module="AUTH",
        severity="warning",
        status_code=403,
        possible_cause="Rol veya permission seti ilgili işlemi kapsamıyor.",
    ),
    "SAR-X-SYSTEM-1101": ErrorSpec(
        error_code="SAR-X-SYSTEM-1101",
        title="Geçersiz İstek",
        user_message="Geçersiz istek. Lütfen form alanlarını kontrol edin.",
        owner_message="İstek gövdesi veya beklenen parametreler doğrulanamadı.",
        module="SYSTEM",
        severity="warning",
        status_code=400,
        possible_cause="Eksik alan, bozuk payload veya beklenmeyen form verisi gönderildi.",
    ),
    "SAR-X-MAIL-4101": ErrorSpec(
        error_code="SAR-X-MAIL-4101",
        title="E-posta Gönderimi Başarısız",
        user_message="Şifre sıfırlama isteği şu an gönderilemedi.",
        owner_message="Mail akışı kullanıcıya reset e-postasını iletemedi.",
        module="MAIL",
        severity="error",
        status_code=502,
        possible_cause="SMTP erişimi, bağlantı veya gönderim aşaması başarısız oldu.",
    ),
    "SAR-X-MAIL-4102": ErrorSpec(
        error_code="SAR-X-MAIL-4102",
        title="SMTP Kimlik Doğrulama Hatası",
        user_message="Bildirim e-postası şu an gönderilemedi.",
        owner_message="SMTP kimlik doğrulaması başarısız oldu.",
        module="MAIL",
        severity="critical",
        status_code=502,
        possible_cause="SMTP kullanıcı adı/şifre yanlış, secret erişilemedi veya sağlayıcı reddetti.",
    ),
    "SAR-X-DB-2101": ErrorSpec(
        error_code="SAR-X-DB-2101",
        title="Veritabanı Bağlantı Hatası",
        user_message="Sistem bağlantı hatası oluştu.",
        owner_message="Veritabanı bağlantısı kurulamadı ya da işlem sırasında koptu.",
        module="DB",
        severity="critical",
        status_code=503,
        possible_cause="Cloud SQL bağlantısı, ağ, havuz veya servis erişimi başarısız oldu.",
    ),
    "SAR-X-DB-2103": ErrorSpec(
        error_code="SAR-X-DB-2103",
        title="Şema Uyuşmazlığı",
        user_message="Sistem geçici olarak hazır değil.",
        owner_message="Beklenen tablo veya kolon bulunamadı; kısmi migration ya da eksik şema tespit edildi.",
        module="DB",
        severity="critical",
        status_code=503,
        possible_cause="Migration eksik, tablo oluşturulmamış veya kısmi deploy yaşanmış olabilir.",
    ),
    "SAR-X-CMS-3101": ErrorSpec(
        error_code="SAR-X-CMS-3101",
        title="İçerik Yükleme Hatası",
        user_message="İstenen içerik şu an yüklenemedi.",
        owner_message="CMS veya public içerik kaynağı beklenen şekilde okunamadı.",
        module="CMS",
        severity="error",
        status_code=500,
        possible_cause="İçerik sorgusu, yayın durumu veya içerik tablosu akışı hata verdi.",
    ),
    "SAR-X-PUBLIC-3201": ErrorSpec(
        error_code="SAR-X-PUBLIC-3201",
        title="İçerik Bulunamadı",
        user_message="İstenen içerik bulunamadı.",
        owner_message="Public sayfada istenen içerik kaydı mevcut değil ya da yayında değil.",
        module="PUBLIC",
        severity="warning",
        status_code=404,
        possible_cause="Slug hatalı, kayıt silinmiş veya içerik yayında değil.",
    ),
    "SAR-X-ADMIN-6101": ErrorSpec(
        error_code="SAR-X-ADMIN-6101",
        title="Yönetim Erişimi Reddedildi",
        user_message="Yönetim paneline erişim yetkiniz yok.",
        owner_message="Kullanıcı yönetim alanına yeterli yetki olmadan erişmeye çalıştı.",
        module="ADMIN",
        severity="warning",
        status_code=403,
        possible_cause="Rol veya permission seti ilgili yönetim ekranına izin vermiyor.",
    ),
    "SAR-X-MEDIA-7101": ErrorSpec(
        error_code="SAR-X-MEDIA-7101",
        title="Dosya Boyutu Aşıldı",
        user_message="Yüklenen dosya sistem limitini aşıyor.",
        owner_message="İstek boyutu medya/form limiti üzerinde geldi.",
        module="MEDIA",
        severity="warning",
        status_code=413,
        possible_cause="Dosya veya form yükü tanımlı limitlerden büyük.",
    ),
    "SAR-X-SYSTEM-5101": ErrorSpec(
        error_code="SAR-X-SYSTEM-5101",
        title="Beklenmeyen Sunucu Hatası",
        user_message="İşlem tamamlanamadı.",
        owner_message="Beklenmeyen exception global fallback tarafından yakalandı.",
        module="SYSTEM",
        severity="critical",
        status_code=500,
        possible_cause="Unhandled exception veya beklenmeyen runtime durumu oluştu.",
    ),
    "SAR-X-SYSTEM-5103": ErrorSpec(
        error_code="SAR-X-SYSTEM-5103",
        title="İstek Hızı Sınırı Aşıldı",
        user_message="Çok fazla istek gönderdiniz. Lütfen kısa süre sonra tekrar deneyin.",
        owner_message="Rate limit kuralı isteği engelledi.",
        module="SYSTEM",
        severity="warning",
        status_code=429,
        possible_cause="Aynı istemci kısa sürede çok fazla istek gönderdi.",
    ),
}


_SECRET_PATTERNS = [
    (re.compile(r"(?i)(password|passwd|smtp_password|secret|token|api[_-]?key)(\s*[=:]\s*)([^,\s]+)"), r"\1\2***"),
    (re.compile(r"(?i)(postgres(?:ql)?://[^:\s]+:)([^@/\s]+)@"), r"\1***@"),
    (re.compile(r"(?i)(mysql://[^:\s]+:)([^@/\s]+)@"), r"\1***@"),
    (re.compile(r"(?i)(reset[_-]?token=)([^&\s]+)"), r"\1***"),
]


def get_error_spec(error_code):
    return ERROR_REGISTRY.get(error_code, ERROR_REGISTRY["SAR-X-SYSTEM-5101"])


def mask_sensitive_text(raw_value, limit=1800):
    if raw_value in (None, ""):
        return ""
    cleaned = str(raw_value)
    for pattern, replacement in _SECRET_PATTERNS:
        cleaned = pattern.sub(replacement, cleaned)
    cleaned = cleaned.replace("\x00", "")
    cleaned = cleaned.strip()
    if len(cleaned) > limit:
        return cleaned[: limit - 3] + "..."
    return cleaned


def _request_id():
    return str(getattr(g, "request_id", "") or "").strip()


def _request_route():
    try:
        return request.path
    except Exception:
        return ""


def _request_method():
    try:
        return request.method
    except Exception:
        return ""


def _request_ip():
    try:
        forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        return forwarded or (request.remote_addr or "")
    except Exception:
        return ""


def _request_user_agent():
    try:
        return (request.user_agent.string or "")[:200]
    except Exception:
        return ""


def _current_user_id():
    try:
        if current_user.is_authenticated:
            return current_user.id
    except Exception:
        return None
    return None


def _current_user_email():
    try:
        if current_user.is_authenticated:
            return str(getattr(current_user, "kullanici_adi", "") or "")[:150]
    except Exception:
        return ""
    return ""


def _is_admin_route():
    endpoint = str(getattr(request, "endpoint", "") or "")
    path = _request_route()
    return endpoint.startswith("admin.") or path.startswith("/admin") or path in {
        "/kullanicilar",
        "/roller",
        "/yetkiler",
        "/site-yonetimi",
        "/islem-loglari",
        "/hata-kayitlari",
    }


def resolve_error_code(exception=None, status_code=None, fallback_code=None):
    if fallback_code:
        return fallback_code

    source = getattr(exception, "original_exception", None) or exception
    status = status_code or getattr(exception, "code", None)
    message = mask_sensitive_text(getattr(source, "orig", source) or "")
    lowered = message.lower()

    if isinstance(source, CSRFError):
        return "SAR-X-AUTH-1202"
    if isinstance(source, SignatureExpired):
        return "SAR-X-AUTH-1301"
    if isinstance(source, BadSignature):
        return "SAR-X-AUTH-1301"
    if isinstance(source, smtplib.SMTPAuthenticationError):
        return "SAR-X-MAIL-4102"
    if isinstance(source, smtplib.SMTPException):
        return "SAR-X-MAIL-4101"
    if isinstance(source, (OperationalError, DBAPIError)):
        if any(item in lowered for item in ("no such table", "undefined table", "no such column", "undefined column")):
            return "SAR-X-DB-2103"
        return "SAR-X-DB-2101"
    if isinstance(source, ProgrammingError):
        if any(item in lowered for item in ("no such table", "undefined table", "no such column", "undefined column")):
            return "SAR-X-DB-2103"
        return "SAR-X-DB-2101"
    if isinstance(source, SQLAlchemyError):
        if any(item in lowered for item in ("no such table", "undefined table", "no such column", "undefined column")):
            return "SAR-X-DB-2103"
        return "SAR-X-DB-2101"
    if status == 401:
        return "SAR-X-AUTH-6101"
    if status == 400:
        return "SAR-X-SYSTEM-1101"
    if status == 403:
        return "SAR-X-ADMIN-6101" if _is_admin_route() else "SAR-X-AUTH-6102"
    if status == 404:
        return "SAR-X-PUBLIC-3201"
    if status == 413:
        return "SAR-X-MEDIA-7101"
    if status == 429:
        return "SAR-X-SYSTEM-5103"
    return "SAR-X-SYSTEM-5101"


def _traceback_summary(exception):
    source = getattr(exception, "original_exception", None) or exception
    if source is None:
        return ""
    try:
        rendered = "".join(traceback.format_exception(type(source), source, source.__traceback__))
    except Exception:
        rendered = str(source)
    return mask_sensitive_text(rendered, limit=4000)


def format_user_error_message(error_code):
    spec = get_error_spec(error_code)
    return f"{spec.user_message} Hata kodu: {spec.error_code}"


def flash_safe_error(error_code, category="danger", include_help_note=True):
    message = format_user_error_message(error_code)
    if include_help_note:
        message = f"{message} Sorun devam ederse bu kodu bildiriniz."
    flash(message, category)
    return message


def capture_error(exception=None, error_code=None, status_code=None, commit=True, detail=None):
    resolved_code = resolve_error_code(exception=exception, status_code=status_code, fallback_code=error_code)
    spec = get_error_spec(resolved_code)
    source = getattr(exception, "original_exception", None) or exception
    exception_type = type(source).__name__ if source is not None else ""
    exception_message = mask_sensitive_text(str(source), limit=800) if source is not None else ""
    trace_summary = _traceback_summary(source)
    detail_text = detail or f"{spec.user_message} | Hata kodu: {spec.error_code}"

    logger = getattr(current_app, "logger", None)
    if logger:
        log_line = "error_code=%s module=%s route=%s request_id=%s"
        args = (spec.error_code, spec.module, _request_route(), _request_id())
        if spec.severity == "critical" and source is not None and not isinstance(source, HTTPException):
            logger.exception(log_line, *args)
        elif spec.severity in {"error", "critical"}:
            logger.error(log_line, *args)
        else:
            logger.warning(log_line, *args)

    log_kaydet(
        _module_log_label(spec.module),
        detail_text,
        event_key=f"error.{spec.error_code.lower()}",
        outcome="failed",
        commit=commit,
        error_code=spec.error_code,
        title=spec.title,
        user_message=spec.user_message,
        owner_message=spec.owner_message,
        module=spec.module,
        severity=spec.severity,
        exception_type=exception_type,
        exception_message=exception_message,
        traceback_summary=trace_summary,
        route=_request_route(),
        method=_request_method(),
        request_id=_request_id(),
        user_id=_current_user_id(),
        user_email=_current_user_email(),
        ip_address=_request_ip(),
        user_agent=_request_user_agent(),
    )

    return {
        "spec": spec,
        "status_code": status_code or spec.status_code,
        "exception_type": exception_type,
        "exception_message": exception_message,
        "traceback_summary": trace_summary,
    }


def _module_log_label(module):
    return {
        "AUTH": "Güvenlik",
        "MAIL": "Sistem",
        "DB": "Sistem",
        "CMS": "İçerik",
        "PUBLIC": "İçerik",
        "ADMIN": "Yetki",
        "MEDIA": "İçerik",
        "SYSTEM": "Sistem",
    }.get(module, "Sistem")
