# decorators.py
from functools import wraps
from flask import abort
from flask_login import current_user

def rol_gerekli(*roller):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated or current_user.rol not in roller:
                abort(403) # Yetkisiz Erişim Hatası
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def havalimani_filtreli_sorgu(model_sinifi):
    """Veri izolasyonu sağlar."""
    if current_user.rol in ['sahip', 'genel_mudurluk']:
        return model_sinifi.query
    return model_sinifi.query.filter_by(havalimani_id=current_user.havalimani_id)