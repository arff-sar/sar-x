import os

from app import create_app
from extensions import db
from models import Kullanici


APP_ENV = (os.getenv("APP_ENV") or os.getenv("FLASK_ENV") or "development").lower()
app = create_app(APP_ENV)


def _bool_env(name, default=False):
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def recover_account():
    if not _bool_env("ALLOW_ACCOUNT_RECOVERY", False):
        raise RuntimeError("Hesap kurtarma için ALLOW_ACCOUNT_RECOVERY=1 olmalıdır.")
    if app.config.get("ENV") == "production" and not _bool_env("ALLOW_PROD_ACCOUNT_RECOVERY", False):
        raise RuntimeError("Production hesap kurtarma için ALLOW_PROD_ACCOUNT_RECOVERY=1 olmalıdır.")

    email = (os.getenv("RECOVERY_EMAIL") or "").strip().lower()
    new_password = os.getenv("RECOVERY_NEW_PASSWORD") or ""
    if not email:
        raise RuntimeError("RECOVERY_EMAIL tanımlı olmalıdır.")
    if len(new_password) < 12:
        raise RuntimeError("RECOVERY_NEW_PASSWORD en az 12 karakter olmalıdır.")

    with app.app_context():
        user = Kullanici.query.filter_by(kullanici_adi=email).first()
        if not user:
            raise RuntimeError("Belirtilen e-posta ile kullanıcı bulunamadı.")

        user.rol = "sahip"
        user.is_deleted = False
        user.deleted_at = None
        user.sifre_set(new_password)
        db.session.commit()
        print(f"Hesap kurtarma tamamlandı: {email}")


if __name__ == "__main__":
    recover_account()
