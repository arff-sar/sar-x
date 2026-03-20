import pytest
import os
from unittest.mock import patch
from sqlalchemy.pool import NullPool
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
    db_path = os.path.join(os.getcwd(), "instance", "test_suite.db")
    previous_test_db = os.environ.get("TEST_DATABASE_URL")
    os.environ["TEST_DATABASE_URL"] = f"sqlite:///{db_path}"
    if os.path.exists(db_path):
        os.remove(db_path)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    app = create_app("testing")
    app.config.update(
        {
            "TESTING": True,
            "SQLALCHEMY_ENGINE_OPTIONS": {
                "connect_args": {"check_same_thread": False},
                "poolclass": NullPool,
            },
            "WTF_CSRF_ENABLED": False,
            "SECRET_KEY": "test-key-for-sarx",
        }
    )

    with app.app_context():
        _db.drop_all()
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()
    if os.path.exists(db_path):
        os.remove(db_path)
    if previous_test_db is None:
        os.environ.pop("TEST_DATABASE_URL", None)
    else:
        os.environ["TEST_DATABASE_URL"] = previous_test_db

@pytest.fixture
def client(app):
    return app.test_client()
