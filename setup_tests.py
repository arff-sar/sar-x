import os

def create_test_suite():
    # 1. Klasör Oluşturma
    if not os.path.exists('tests'):
        os.makedirs('tests')
        print("✅ 'tests' klasörü oluşturuldu.")

    # 2. conftest.py İçeriği
    conftest_content = """import pytest
from app import create_app
from extensions import db as _db

@pytest.fixture
def app():
    app = create_app()
    app.config.update({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "WTF_CSRF_ENABLED": False,
        "SECRET_KEY": "test-key"
    })

    with app.app_context():
        _db.create_all()
        yield app
        _db.drop_all()

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def runner(app):
    return app.test_cli_runner()
"""

    # 3. factories.py İçeriği
    factories_content = """import factory
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
    havalimani = factory.LazyAttribute(lambda o: o.kutu.havalimani)
"""

    # 4. test_auth.py İçeriği
    test_auth_content = """import pytest
from tests.factories import KullaniciFactory

def test_login_page_loads(client):
    response = client.get('/login')
    assert response.status_code == 200
    assert b"Giri\xc5\x9f" in response.data

def test_login_success(client, app):
    user = KullaniciFactory(kullanici_adi="admin@sarx.com")
    response = client.post('/login', data={
        'kullanici_adi': 'admin@sarx.com',
        'sifre': '123456'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"Dashboard" in response.data

def test_deleted_user_cannot_login(client, app):
    user = KullaniciFactory(kullanici_adi="deleted@sarx.com", is_deleted=True)
    response = client.post('/login', data={
        'kullanici_adi': 'deleted@sarx.com',
        'sifre': '123456'
    })
    assert b"Hatal\xc4\xb1 giri\xc5\x9f denemesi" in response.data
"""

    # 5. test_inventory.py İçeriği
    test_inventory_content = """import pytest
from tests.factories import MalzemeFactory, KullaniciFactory

def test_envanter_access_required_login(client):
    response = client.get('/envanter')
    assert response.status_code == 302 # Login'e yönlendirmeli

def test_envanter_list_active_only(client, app):
    # Aktif ve Silinmiş malzeme oluştur
    m1 = MalzemeFactory(ad="Aktif Cihaz", is_deleted=False)
    m2 = MalzemeFactory(ad="Silinmis Cihaz", is_deleted=True)
    
    # Giriş yap
    user = KullaniciFactory(rol="sahip")
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
    
    response = client.get('/envanter')
    assert b"Aktif Cihaz" in response.data
    assert b"Silinmis Cihaz" not in response.data
"""

    # Dosyaları Yazma İşlemi
    files = {
        "tests/conftest.py": conftest_content,
        "tests/factories.py": factories_content,
        "tests/test_auth.py": test_auth_content,
        "tests/test_inventory.py": test_inventory_content
    }

    for path, content in files.items():
        with open(path, "w", encoding="utf-8") as f:
            f.write(content.strip())
        print(f"📄 {path} dosyası oluşturuldu.")

    print("\\n🚀 Test altyapısı hazır! Çalıştırmak için: pytest")

if __name__ == "__main__":
    create_test_suite()