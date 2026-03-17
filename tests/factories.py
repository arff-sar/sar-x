import factory
from extensions import db
from models import Kullanici, Havalimani, Malzeme, Kutu

class HavalimaniFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = Havalimani
        sqlalchemy_session = db.session
    ad = factory.Sequence(lambda n: f"Birim {n}")
    kodu = factory.Sequence(lambda n: f"BRM{n}")

class KullaniciFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = Kullanici
        sqlalchemy_session = db.session
    kullanici_adi = factory.Sequence(lambda n: f"test{n}@sarx.com")
    tam_ad = "Test User"
    rol = "personel"
    is_deleted = False
    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        password = kwargs.pop("password", "123456")
        obj = model_class(*args, **kwargs)
        obj.sifre_set(password)
        return obj

class KutuFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = Kutu
        sqlalchemy_session = db.session
    kodu = factory.Sequence(lambda n: f"KUTU-{n}")
    havalimani = factory.SubFactory(HavalimaniFactory)

class MalzemeFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = Malzeme
        sqlalchemy_session = db.session
    ad = factory.Sequence(lambda n: f"Ekipman {n}")
    seri_no = factory.Sequence(lambda n: f"SN-{n}")
    is_deleted = False
    kutu = factory.SubFactory(KutuFactory)
    # Havalimanını kutudan otomatik al
    havalimani = factory.LazyAttribute(lambda o: o.kutu.havalimani)