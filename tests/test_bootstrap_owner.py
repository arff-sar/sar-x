from kurulum import veritabani_besle
from extensions import db
from models import Kullanici


def test_bootstrap_owner_preserves_existing_password_and_reactivates_user(app, monkeypatch):
    with app.app_context():
        monkeypatch.delenv("SEED_SAMPLE_USERS", raising=False)
        monkeypatch.delenv("BOOTSTRAP_OWNER_FORCE_PASSWORD_RESET", raising=False)
        user = Kullanici(
            kullanici_adi="  MehmetCinocevi@Gmail.com ",
            tam_ad="Mehmet Cinocevi",
            rol="sahip",
            is_deleted=True,
        )
        user.sifre_set("EskiGirisSifresi1!")
        db.session.add(user)
        db.session.commit()

        monkeypatch.setenv("BOOTSTRAP_OWNER_EMAIL", "mehmetcinocevi@gmail.com")
        monkeypatch.setenv("BOOTSTRAP_OWNER_PASSWORD", "YeniBootstrapSifresi1!")

        veritabani_besle(app)

        db.session.expire_all()
        stored = Kullanici.query.filter_by(id=user.id).first()
        assert stored is not None
        assert stored.kullanici_adi == "mehmetcinocevi@gmail.com"
        assert stored.is_deleted is False
        assert stored.sifre_kontrol("EskiGirisSifresi1!")
        assert not stored.sifre_kontrol("YeniBootstrapSifresi1!")


def test_bootstrap_owner_creates_missing_user_once(app, monkeypatch):
    with app.app_context():
        monkeypatch.delenv("SEED_SAMPLE_USERS", raising=False)
        monkeypatch.delenv("BOOTSTRAP_OWNER_FORCE_PASSWORD_RESET", raising=False)
        monkeypatch.setenv("BOOTSTRAP_OWNER_EMAIL", " mehmetcinocevi@gmail.com ")
        monkeypatch.setenv("BOOTSTRAP_OWNER_PASSWORD", "BootstrapSifresi1!")

        veritabani_besle(app)

        stored = Kullanici.query.filter_by(kullanici_adi="mehmetcinocevi@gmail.com").first()
        assert stored is not None
        assert stored.rol == "sahip"
        assert stored.is_deleted is False
        assert stored.sifre_kontrol("BootstrapSifresi1!")
