import os

from app import create_app
from extensions import db
from models import Havalimani, Kullanici, SiteAyarlari


def _bool_env(name, default=False):
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _resolve_app_env():
    return (os.getenv("APP_ENV") or os.getenv("FLASK_ENV") or "development").lower()


def _is_production(app):
    return app.config.get("ENV") == "production"


def _validate_password(password, field_name):
    if not password or len(password) < 12:
        raise RuntimeError(f"{field_name} en az 12 karakter olmalıdır.")


def _normalize_email(value):
    return (value or "").strip().lower()


def _find_user_by_email(email):
    normalized = _normalize_email(email)
    if not normalized:
        return None
    for user in Kullanici.query.all():
        if _normalize_email(user.kullanici_adi) == normalized:
            return user
    return None


def _ensure_bootstrap_owner():
    owner_email = _normalize_email(os.getenv("BOOTSTRAP_OWNER_EMAIL"))
    owner_password = os.getenv("BOOTSTRAP_OWNER_PASSWORD") or ""
    force_password_reset = _bool_env("BOOTSTRAP_OWNER_FORCE_PASSWORD_RESET", False)

    if not owner_email:
        print("BOOTSTRAP_OWNER_EMAIL tanımlı değil, owner hesabı oluşturulmadı.")
        return

    owner = _find_user_by_email(owner_email)
    if not owner:
        _validate_password(owner_password, "BOOTSTRAP_OWNER_PASSWORD")
        owner = Kullanici(kullanici_adi=owner_email, tam_ad="Sistem Sahibi", rol="sahip", havalimani_id=None)
        owner.sifre_set(owner_password)
        owner.is_deleted = False
        owner.deleted_at = None
        db.session.add(owner)
        print("Bootstrap owner hesabı oluşturuldu.")
        return

    owner.kullanici_adi = owner_email
    owner.is_deleted = False
    owner.deleted_at = None
    if force_password_reset:
        _validate_password(owner_password, "BOOTSTRAP_OWNER_PASSWORD")
        owner.sifre_set(owner_password)
        print("Bootstrap owner hesabının parolası zorla güncellendi.")
    else:
        print("Bootstrap owner hesabı mevcut; parola korunuyor.")


def veritabani_besle(app=None):
    app = app or create_app(_resolve_app_env())
    with app.app_context():
        print("Sistem veri besleme işlemi başlatıldı...")

        airports = [
            {"ad": "Ankara Esenboğa Havalimanı", "kodu": "ESB"},
            {"ad": "İstanbul Sabiha Gökçen Havalimanı", "kodu": "SAW"},
            {"ad": "İzmir Adnan Menderes Havalimanı", "kodu": "ADB"},
        ]
        for airport in airports:
            if not Havalimani.query.filter_by(kodu=airport["kodu"]).first():
                db.session.add(Havalimani(ad=airport["ad"], kodu=airport["kodu"]))

        _ensure_bootstrap_owner()

        # Örnek kullanıcılar sadece development/staging amaçlı ve açıkça env ile etkin.
        if _bool_env("SEED_SAMPLE_USERS", False):
            if _is_production(app):
                raise RuntimeError("SEED_SAMPLE_USERS production ortamında kullanılamaz.")
            sample_password = os.getenv("SEED_SAMPLE_PASSWORD") or ""
            _validate_password(sample_password, "SEED_SAMPLE_PASSWORD")
            if not Kullanici.query.filter_by(kullanici_adi="gm@sarx.com").first():
                gm = Kullanici(kullanici_adi="gm@sarx.com", tam_ad="GM Denetçi", rol="genel_mudurluk")
                gm.sifre_set(sample_password)
                db.session.add(gm)
                print("Örnek Genel Müdürlük hesabı eklendi.")

        if not SiteAyarlari.query.first():
            db.session.add(
                SiteAyarlari(
                    baslik="SAR-X ARFF",
                    alt_metin="Havalimanı Envanter ve Bakım Yönetim Sistemi",
                )
            )

        db.session.commit()
        print("Veri besleme tamamlandı.")


if __name__ == "__main__":
    veritabani_besle()
