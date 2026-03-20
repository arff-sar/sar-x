import os

from app import create_app
from extensions import db
from models import Havalimani, Kullanici, SiteAyarlari


APP_ENV = (os.getenv("APP_ENV") or os.getenv("FLASK_ENV") or "development").lower()
app = create_app(APP_ENV)


def _bool_env(name, default=False):
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _is_production():
    return app.config.get("ENV") == "production"


def _validate_password(password, field_name):
    if not password or len(password) < 12:
        raise RuntimeError(f"{field_name} en az 12 karakter olmalıdır.")


def veritabani_besle():
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

        owner_email = (os.getenv("BOOTSTRAP_OWNER_EMAIL") or "").strip().lower()
        owner_password = os.getenv("BOOTSTRAP_OWNER_PASSWORD") or ""
        if owner_email:
            _validate_password(owner_password, "BOOTSTRAP_OWNER_PASSWORD")
            owner = Kullanici.query.filter_by(kullanici_adi=owner_email).first()
            if not owner:
                owner = Kullanici(kullanici_adi=owner_email, tam_ad="Sistem Sahibi", rol="sahip", havalimani_id=None)
                db.session.add(owner)
            owner.sifre_set(owner_password)
            owner.is_deleted = False
            owner.deleted_at = None
            print("Bootstrap owner hesabı hazırlandı.")
        else:
            print("BOOTSTRAP_OWNER_EMAIL tanımlı değil, owner hesabı oluşturulmadı.")

        # Örnek kullanıcılar sadece development/staging amaçlı ve açıkça env ile etkin.
        if _bool_env("SEED_SAMPLE_USERS", False):
            if _is_production():
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
