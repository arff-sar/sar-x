import pytest
from unittest.mock import patch
from sqlalchemy.pool import StaticPool
from app import create_app
from extensions import db as _db

@pytest.fixture(autouse=True)
def mock_external_services():
    with patch('routes.auth.gizli_sifreyi_getir') as mocked_secret, \
         patch('routes.auth.mail_gonder') as mocked_mail:
        mocked_secret.return_value = "test_sifresi_123"
        mocked_mail.return_value = True
        yield

@pytest.fixture
def app():
    app = create_app()
    app.config.update({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        # ✅ pool_size/max_overflow'u temizle, StaticPool koy
        "SQLALCHEMY_ENGINE_OPTIONS": {
            "connect_args": {"check_same_thread": False},
            "poolclass": StaticPool,
        },
        "WTF_CSRF_ENABLED": False,
        "SECRET_KEY": "test-key-for-sarx",
    })

    # ✅ Engine'i config değişikliğinden SONRA yeniden oluştur
    with app.app_context():
        _db.drop_all()
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()

@pytest.fixture
def client(app):
    return app.test_client()