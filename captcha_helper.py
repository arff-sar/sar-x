import random
import secrets
from datetime import timedelta
from html import escape

from flask import current_app, session, url_for

from extensions import db, table_exists
from models import LoginVisualChallenge, get_tr_now

LOGIN_CAPTCHA_SESSION_KEY = "login_visual_captcha_token"
LOGIN_CAPTCHA_DEFAULT_TTL = 45
LOGIN_CAPTCHA_CODE_LENGTH = 5
LOGIN_CAPTCHA_CHARSET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _now():
    return get_tr_now().replace(tzinfo=None)


def _ttl_seconds():
    try:
        return max(int(current_app.config.get("LOGIN_CAPTCHA_TTL_SECONDS", LOGIN_CAPTCHA_DEFAULT_TTL)), 30)
    except Exception:
        return LOGIN_CAPTCHA_DEFAULT_TTL


def _normalize_code(value):
    return "".join(ch for ch in str(value or "").upper().strip() if ch.isalnum())


def _store():
    return current_app.extensions.setdefault("login_visual_challenge_store", {})


def _use_db_store():
    return table_exists("login_visual_challenge")


def _invalidate_extension_record(token):
    record = _store().get(token)
    if not record:
        return
    record["invalidated_at"] = _now()


def _invalidate_db_record(token):
    record = LoginVisualChallenge.query.filter_by(token=token).first()
    if not record or record.invalidated_at:
        return
    record.invalidated_at = _now()


def invalidate_login_captcha(token=None, clear_session=False):
    token = token or session.get(LOGIN_CAPTCHA_SESSION_KEY)
    if not token:
        return
    if _use_db_store():
        _invalidate_db_record(token)
        db.session.commit()
    else:
        _invalidate_extension_record(token)
    if clear_session:
        session.pop(LOGIN_CAPTCHA_SESSION_KEY, None)


def _create_db_record():
    code = "".join(secrets.choice(LOGIN_CAPTCHA_CHARSET) for _ in range(LOGIN_CAPTCHA_CODE_LENGTH))
    token = secrets.token_urlsafe(24)
    record = LoginVisualChallenge(
        token=token,
        code=code,
        expires_at=_now() + timedelta(seconds=_ttl_seconds()),
    )
    db.session.add(record)
    db.session.commit()
    return record


def _create_extension_record():
    token = secrets.token_urlsafe(24)
    record = {
        "token": token,
        "code": "".join(secrets.choice(LOGIN_CAPTCHA_CHARSET) for _ in range(LOGIN_CAPTCHA_CODE_LENGTH)),
        "expires_at": _now() + timedelta(seconds=_ttl_seconds()),
        "invalidated_at": None,
        "last_rendered_at": None,
    }
    _store()[token] = record
    return record


def _get_record(token):
    if not token:
        return None
    if _use_db_store():
        return LoginVisualChallenge.query.filter_by(token=token).first()
    return _store().get(token)


def _record_is_active(record):
    if not record:
        return False
    invalidated_at = getattr(record, "invalidated_at", None) if not isinstance(record, dict) else record.get("invalidated_at")
    expires_at = getattr(record, "expires_at", None) if not isinstance(record, dict) else record.get("expires_at")
    return bool(expires_at and not invalidated_at and expires_at > _now())


def _serialize_record(record):
    if not record:
        return None
    token = getattr(record, "token", None) if not isinstance(record, dict) else record.get("token")
    expires_at = getattr(record, "expires_at", None) if not isinstance(record, dict) else record.get("expires_at")
    if not token or not expires_at:
        return None
    expires_at = expires_at.replace(microsecond=0)
    return {
        "token": token,
        "image_url": url_for("auth.login_captcha_image", token=token, v=int(expires_at.timestamp())),
        "expires_at_iso": expires_at.isoformat(),
        "expires_at_epoch": int(expires_at.timestamp()),
        "remaining_seconds": max(int((expires_at - _now()).total_seconds()), 0),
        "ttl_seconds": _ttl_seconds(),
    }


def build_login_captcha(force_new=False):
    current_token = session.get(LOGIN_CAPTCHA_SESSION_KEY)
    current_record = _get_record(current_token)

    if force_new or not _record_is_active(current_record):
        if current_token:
            invalidate_login_captcha(current_token, clear_session=True)
        current_record = _create_db_record() if _use_db_store() else _create_extension_record()
        session[LOGIN_CAPTCHA_SESSION_KEY] = getattr(current_record, "token", None) or current_record.get("token")

    payload = _serialize_record(current_record)
    if payload:
        payload["refresh_url"] = url_for("auth.login_captcha_refresh")
    return payload


def validate_login_captcha(answer):
    token = session.get(LOGIN_CAPTCHA_SESSION_KEY)
    record = _get_record(token)
    if not record:
        return False, "missing"
    if not _record_is_active(record):
        invalidate_login_captcha(token, clear_session=True)
        return False, "expired"

    expected = getattr(record, "code", None) if not isinstance(record, dict) else record.get("code")
    if _normalize_code(answer) != _normalize_code(expected):
        return False, "invalid"
    return True, "valid"


def get_login_captcha_code_for_token(token):
    record = _get_record(token)
    if not record:
        return None
    return getattr(record, "code", None) if not isinstance(record, dict) else record.get("code")


def render_login_captcha_svg(token):
    active_token = session.get(LOGIN_CAPTCHA_SESSION_KEY)
    if active_token and token != active_token:
        return _build_placeholder_svg("YENILE", "Kod yenilendi")
    record = _get_record(token)
    if not _record_is_active(record):
        return _build_placeholder_svg("SURESI", "Süre doldu")

    code = getattr(record, "code", "") if not isinstance(record, dict) else record.get("code", "")
    if not code:
        return _build_placeholder_svg("YOK", "Kod bulunamadı")

    if _use_db_store():
        record.last_rendered_at = _now()
        db.session.commit()
    else:
        record["last_rendered_at"] = _now()

    return _build_captcha_svg(code, token)


def _build_placeholder_svg(title, subtitle):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="160" height="52" viewBox="0 0 160 52" role="img" aria-label="{escape(subtitle)}">
<rect width="160" height="52" rx="10" fill="#f8fafc"/>
<rect x="1" y="1" width="158" height="50" rx="9" fill="none" stroke="#cbd5e1"/>
<text x="16" y="24" font-size="18" font-family="monospace" font-weight="700" fill="#0f2d4a">{escape(title)}</text>
<text x="16" y="39" font-size="10" font-family="sans-serif" fill="#64748b">{escape(subtitle)}</text>
</svg>"""


def _build_captcha_svg(code, token):
    noise = random.Random(token)
    char_nodes = []
    for index, char in enumerate(code):
        x = 18 + (index * 26) + noise.randint(-2, 2)
        y = 30 + noise.randint(-4, 5)
        rotation = noise.randint(-18, 18)
        fill = noise.choice(["#0f2d4a", "#1d4ed8", "#f97316", "#334155"])
        char_nodes.append(
            f'<text x="{x}" y="{y}" font-size="24" font-family="JetBrains Mono, monospace" '
            f'font-weight="800" fill="{fill}" transform="rotate({rotation} {x} {y})">{escape(char)}</text>'
        )

    lines = []
    for _ in range(5):
        x1, y1 = noise.randint(0, 160), noise.randint(6, 46)
        x2, y2 = noise.randint(0, 160), noise.randint(6, 46)
        stroke = noise.choice(["#cbd5e1", "#fed7aa", "#bfdbfe", "#e2e8f0"])
        lines.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{noise.uniform(1, 1.8):.1f}" opacity="0.85"/>'
        )

    dots = []
    for _ in range(14):
        cx, cy = noise.randint(4, 156), noise.randint(6, 46)
        r = noise.uniform(0.8, 1.9)
        fill = noise.choice(["#94a3b8", "#cbd5e1", "#fdba74"])
        dots.append(f'<circle cx="{cx}" cy="{cy}" r="{r:.1f}" fill="{fill}" opacity="0.65"/>')

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="160" height="52" viewBox="0 0 160 52" role="img" aria-label="Güvenlik doğrulama kodu">
<defs>
  <linearGradient id="captchaBg" x1="0%" y1="0%" x2="100%" y2="100%">
    <stop offset="0%" stop-color="#ffffff"/>
    <stop offset="100%" stop-color="#f8fafc"/>
  </linearGradient>
</defs>
<rect width="160" height="52" rx="10" fill="url(#captchaBg)"/>
<rect x="1" y="1" width="158" height="50" rx="9" fill="none" stroke="#cbd5e1"/>
{''.join(lines)}
{''.join(dots)}
{''.join(char_nodes)}
</svg>"""
