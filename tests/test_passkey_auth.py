import hashlib
import json
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from extensions import db
from models import PasskeyCredential
from tests.factories import KullaniciFactory
from tests.test_auth import _extract_challenge_answer


def _b64url_encode(value):
    import base64

    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _captcha_token(client):
    with client.session_transaction() as session:
        return session.get("login_visual_captcha_token")


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def _origin(base_url="http://localhost"):
    return base_url.rstrip("/")


def _cbor_encode_length(major_type, length):
    if length < 24:
        return bytes([(major_type << 5) | length])
    if length < 256:
        return bytes([(major_type << 5) | 24, length])
    if length < 65536:
        return bytes([(major_type << 5) | 25]) + length.to_bytes(2, "big")
    if length < 4294967296:
        return bytes([(major_type << 5) | 26]) + length.to_bytes(4, "big")
    return bytes([(major_type << 5) | 27]) + length.to_bytes(8, "big")


def _cbor_encode(value):
    if isinstance(value, bool):
        return b"\xf5" if value else b"\xf4"
    if value is None:
        return b"\xf6"
    if isinstance(value, int):
        if value >= 0:
            return _cbor_encode_length(0, value)
        return _cbor_encode_length(1, (-1 - value))
    if isinstance(value, bytes):
        return _cbor_encode_length(2, len(value)) + value
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        return _cbor_encode_length(3, len(encoded)) + encoded
    if isinstance(value, (list, tuple)):
        return _cbor_encode_length(4, len(value)) + b"".join(_cbor_encode(item) for item in value)
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            parts.append(_cbor_encode(key))
            parts.append(_cbor_encode(item))
        return _cbor_encode_length(5, len(value)) + b"".join(parts)
    raise TypeError(f"Unsupported CBOR value: {type(value)!r}")


def _ec2_cose_key(public_key):
    numbers = public_key.public_numbers()
    return {
        1: 2,
        3: -7,
        -1: 1,
        -2: numbers.x.to_bytes(32, "big"),
        -3: numbers.y.to_bytes(32, "big"),
    }


def _registration_authenticator_data(rp_id, credential_id, public_key, sign_count=0):
    rp_id_hash = hashlib.sha256(rp_id.encode("utf-8")).digest()
    flags = bytes([0x45])
    counter = int(sign_count).to_bytes(4, "big")
    aaguid = b"\x00" * 16
    credential_length = len(credential_id).to_bytes(2, "big")
    credential_public_key = _cbor_encode(_ec2_cose_key(public_key))
    return rp_id_hash + flags + counter + aaguid + credential_length + credential_id + credential_public_key


def _attestation_object(rp_id, credential_id, public_key, sign_count=0, *, fmt="none", att_stmt=None):
    return _cbor_encode(
        {
            "fmt": fmt,
            "attStmt": {} if att_stmt is None else att_stmt,
            "authData": _registration_authenticator_data(rp_id, credential_id, public_key, sign_count=sign_count),
        }
    )


def _authentication_authenticator_data(rp_id, sign_count=1, user_verified=True):
    rp_id_hash = hashlib.sha256(rp_id.encode("utf-8")).digest()
    flags_value = 0x01 | (0x04 if user_verified else 0)
    return rp_id_hash + bytes([flags_value]) + int(sign_count).to_bytes(4, "big")


def _client_data(challenge, origin, operation_type, *, cross_origin=False):
    payload = {
        "type": operation_type,
        "challenge": challenge,
        "origin": origin,
        "crossOrigin": bool(cross_origin),
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _ec_keypair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key_der = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_key, public_key_der


def _register_passkey(client, app, user, *, base_url="http://localhost"):
    app.config["PASSKEY_ENABLED"] = True
    _login(client, user.id)
    begin = client.post("/passkey/register/begin", base_url=base_url)
    payload = begin.get_json()
    challenge = payload["public_key"]["challenge"]
    rp_id = payload["public_key"]["rp"]["id"]
    private_key, public_key_der = _ec_keypair()
    public_key = private_key.public_key()
    credential_id = b"credential-passkey-1"
    registration_payload = {
        "id": _b64url_encode(credential_id),
        "rawId": _b64url_encode(credential_id),
        "type": "public-key",
        "response": {
            "clientDataJSON": _b64url_encode(_client_data(challenge, _origin(base_url), "webauthn.create")),
            "attestationObject": _b64url_encode(_attestation_object(rp_id, credential_id, public_key)),
            "transports": ["internal"],
        },
    }
    finish = client.post("/passkey/register/finish", json=registration_payload, base_url=base_url)
    assert finish.status_code == 200
    with app.app_context():
        credential = PasskeyCredential.query.filter_by(user_id=user.id).first()
        assert credential is not None
    return private_key, credential


def test_passkey_feature_flag_off_keeps_legacy_behavior(client):
    response = client.get("/login")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Biyometrik / Passkey ile Giriş" not in html
    assert client.post("/login/passkey/begin").status_code == 404


def test_passkey_registration_flow_creates_credential(client, app):
    app.config["PASSKEY_ENABLED"] = True
    user = KullaniciFactory(is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()

    _login(client, user.id)
    begin = client.post("/passkey/register/begin")
    payload = begin.get_json()
    challenge = payload["public_key"]["challenge"]
    rp_id = payload["public_key"]["rp"]["id"]
    private_key, public_key_der = _ec_keypair()
    public_key = private_key.public_key()
    credential_id = b"credential-passkey-2"

    finish = client.post(
        "/passkey/register/finish",
        json={
            "id": _b64url_encode(credential_id),
            "rawId": _b64url_encode(credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": _b64url_encode(_client_data(challenge, "http://localhost", "webauthn.create")),
                "attestationObject": _b64url_encode(_attestation_object(rp_id, credential_id, public_key)),
                "transports": ["internal"],
            },
        },
    )

    assert begin.status_code == 200
    assert "no-store" in begin.headers["Cache-Control"]
    assert finish.status_code == 200
    with app.app_context():
        credential = PasskeyCredential.query.filter_by(user_id=user.id).first()
        assert credential is not None
        assert credential.credential_id == _b64url_encode(credential_id)
        assert credential.public_key == _b64url_encode(public_key_der)


def test_passkey_registration_rejects_legacy_fake_public_key_payload(client, app):
    app.config["PASSKEY_ENABLED"] = True
    user = KullaniciFactory(kullanici_adi="legacy-fake-passkey@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()

    _login(client, user.id)
    begin = client.post("/passkey/register/begin")
    challenge = begin.get_json()["public_key"]["challenge"]
    rp_id = begin.get_json()["public_key"]["rp"]["id"]
    private_key, public_key_der = _ec_keypair()
    credential_id = b"legacy-fake-passkey"

    finish = client.post(
        "/passkey/register/finish",
        json={
            "id": _b64url_encode(credential_id),
            "rawId": _b64url_encode(credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": _b64url_encode(_client_data(challenge, "http://localhost", "webauthn.create")),
                "publicKey": _b64url_encode(public_key_der),
                "publicKeyAlgorithm": -7,
                "authenticatorData": _b64url_encode(_registration_authenticator_data(rp_id, credential_id, private_key.public_key())),
            },
        },
    )

    assert finish.status_code == 400
    with app.app_context():
        assert PasskeyCredential.query.filter_by(user_id=user.id).count() == 0


def test_passkey_registration_rejects_malformed_attestation_object(client, app):
    app.config["PASSKEY_ENABLED"] = True
    user = KullaniciFactory(kullanici_adi="malformed-attestation@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()

    _login(client, user.id)
    begin = client.post("/passkey/register/begin")
    challenge = begin.get_json()["public_key"]["challenge"]
    credential_id = b"malformed-attestation"

    finish = client.post(
        "/passkey/register/finish",
        json={
            "id": _b64url_encode(credential_id),
            "rawId": _b64url_encode(credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": _b64url_encode(_client_data(challenge, "http://localhost", "webauthn.create")),
                "attestationObject": _b64url_encode(b"\xa3\x63fmt"),
            },
        },
    )

    assert finish.status_code == 400


def test_passkey_registration_rejects_truncated_attestation_object(client, app):
    app.config["PASSKEY_ENABLED"] = True
    user = KullaniciFactory(kullanici_adi="truncated-attestation@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()

    _login(client, user.id)
    begin = client.post("/passkey/register/begin")
    challenge = begin.get_json()["public_key"]["challenge"]
    rp_id = begin.get_json()["public_key"]["rp"]["id"]
    private_key, _public_key_der = _ec_keypair()
    credential_id = b"truncated-attestation"
    attestation_object = _attestation_object(rp_id, credential_id, private_key.public_key())

    finish = client.post(
        "/passkey/register/finish",
        json={
            "id": _b64url_encode(credential_id),
            "rawId": _b64url_encode(credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": _b64url_encode(_client_data(challenge, "http://localhost", "webauthn.create")),
                "attestationObject": _b64url_encode(attestation_object[:-8]),
            },
        },
    )

    assert finish.status_code == 400


def test_passkey_registration_rejects_wrong_origin(client, app):
    app.config["PASSKEY_ENABLED"] = True
    user = KullaniciFactory(kullanici_adi="register-origin@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()

    _login(client, user.id)
    begin = client.post("/passkey/register/begin")
    challenge = begin.get_json()["public_key"]["challenge"]
    rp_id = begin.get_json()["public_key"]["rp"]["id"]
    private_key, _public_key_der = _ec_keypair()
    credential_id = b"register-origin"

    finish = client.post(
        "/passkey/register/finish",
        json={
            "id": _b64url_encode(credential_id),
            "rawId": _b64url_encode(credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": _b64url_encode(_client_data(challenge, "https://evil.example", "webauthn.create")),
                "attestationObject": _b64url_encode(_attestation_object(rp_id, credential_id, private_key.public_key())),
            },
        },
    )

    assert finish.status_code == 400


def test_passkey_registration_rejects_wrong_challenge(client, app):
    app.config["PASSKEY_ENABLED"] = True
    user = KullaniciFactory(kullanici_adi="register-challenge@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()

    _login(client, user.id)
    begin = client.post("/passkey/register/begin")
    rp_id = begin.get_json()["public_key"]["rp"]["id"]
    private_key, _public_key_der = _ec_keypair()
    credential_id = b"register-challenge"

    finish = client.post(
        "/passkey/register/finish",
        json={
            "id": _b64url_encode(credential_id),
            "rawId": _b64url_encode(credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": _b64url_encode(_client_data("wrong-challenge", "http://localhost", "webauthn.create")),
                "attestationObject": _b64url_encode(_attestation_object(rp_id, credential_id, private_key.public_key())),
            },
        },
    )

    assert finish.status_code == 400


def test_passkey_registration_rejects_wrong_rp_id_hash(client, app):
    app.config["PASSKEY_ENABLED"] = True
    user = KullaniciFactory(kullanici_adi="register-rpid@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()

    _login(client, user.id)
    begin = client.post("/passkey/register/begin")
    challenge = begin.get_json()["public_key"]["challenge"]
    private_key, _public_key_der = _ec_keypair()
    credential_id = b"register-rpid"

    finish = client.post(
        "/passkey/register/finish",
        json={
            "id": _b64url_encode(credential_id),
            "rawId": _b64url_encode(credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": _b64url_encode(_client_data(challenge, "http://localhost", "webauthn.create")),
                "attestationObject": _b64url_encode(_attestation_object("evil.example", credential_id, private_key.public_key())),
            },
        },
    )

    assert finish.status_code == 400


def test_passkey_begin_does_not_break_password_fallback(client, app):
    app.config["PASSKEY_ENABLED"] = True
    user = KullaniciFactory(kullanici_adi="fallback-passkey@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()

    answer = _extract_challenge_answer(client, app)
    token = _captcha_token(client)
    begin = client.post("/login/passkey/begin", json={"remember_me": True})
    response = client.post(
        "/login",
        data={
            "kullanici_adi": user.kullanici_adi,
            "sifre": "123456",
            "remember_me": "on",
            "security_verification": answer,
            "security_verification_token": token,
        },
        follow_redirects=True,
    )

    assert begin.status_code == 200
    assert response.status_code == 200
    assert response.request.path == "/dashboard"


def test_password_login_sets_passkey_auto_prompt_for_users_without_passkey(client, app):
    app.config["PASSKEY_ENABLED"] = True
    user = KullaniciFactory(kullanici_adi="auto-prompt-no-passkey@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()

    answer = _extract_challenge_answer(client, app)
    token = _captcha_token(client)
    response = client.post(
        "/login",
        data={
            "kullanici_adi": user.kullanici_adi,
            "sifre": "123456",
            "remember_me": "on",
            "security_verification": answer,
            "security_verification_token": token,
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    with client.session_transaction() as session:
        assert session.get("passkey_auto_prompt_after_password_login") is True


def test_password_login_skips_passkey_auto_prompt_when_credential_exists(client, app):
    app.config["PASSKEY_ENABLED"] = True
    user = KullaniciFactory(kullanici_adi="auto-prompt-has-passkey@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()
    _private_key, _credential = _register_passkey(client, app, user)

    client.post("/logout")
    answer = _extract_challenge_answer(client, app)
    token = _captcha_token(client)
    response = client.post(
        "/login",
        data={
            "kullanici_adi": user.kullanici_adi,
            "sifre": "123456",
            "remember_me": "on",
            "security_verification": answer,
            "security_verification_token": token,
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    with client.session_transaction() as session:
        assert session.get("passkey_auto_prompt_after_password_login") is None


def test_login_passkey_begin_uses_private_no_store_headers(client, app):
    app.config["PASSKEY_ENABLED"] = True

    response = client.post("/login/passkey/begin", json={"remember_me": True})

    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-store, no-cache, must-revalidate, max-age=0, private"
    assert response.headers.get("Pragma") == "no-cache"
    assert response.headers.get("Expires") == "0"
    assert "Cookie" in response.headers.get("Vary", "")


def test_login_passkey_begin_filters_allow_credentials_for_login_identifier(client, app):
    app.config["PASSKEY_ENABLED"] = True
    user = KullaniciFactory(kullanici_adi="allow-credentials@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()
    _private_key, credential = _register_passkey(client, app, user)

    client.post("/logout")
    begin = client.post("/login/passkey/begin", json={"login_identifier": user.kullanici_adi})
    payload = begin.get_json()
    allow_credentials = payload["public_key"]["allowCredentials"]

    assert begin.status_code == 200
    assert len(allow_credentials) == 1
    assert allow_credentials[0]["id"] == credential.credential_id
    assert allow_credentials[0]["type"] == "public-key"


def test_login_passkey_begin_rejects_identifier_without_active_passkey(client, app):
    app.config["PASSKEY_ENABLED"] = True
    user = KullaniciFactory(kullanici_adi="no-passkey-login@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()

    begin = client.post("/login/passkey/begin", json={"login_identifier": user.kullanici_adi})
    payload = begin.get_json()

    assert begin.status_code == 400
    assert payload["status"] == "error"
    assert "aktif biyometrik giriş kaydı bulunamadı" in payload["message"]


def test_passkey_authentication_flow_logs_user_in_and_updates_counter(client, app):
    app.config["PASSKEY_ENABLED"] = True
    user = KullaniciFactory(kullanici_adi="passkey-login@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()
    private_key, credential = _register_passkey(client, app, user)

    client.post("/logout")
    answer = _extract_challenge_answer(client, app)
    token = _captcha_token(client)
    begin = client.post("/login/passkey/begin", json={"remember_me": True})
    payload = begin.get_json()
    challenge = payload["public_key"]["challenge"]
    rp_id = payload["public_key"]["rpId"]
    auth_data = _authentication_authenticator_data(rp_id, sign_count=5)
    client_data = _client_data(challenge, "http://localhost", "webauthn.get")
    signature = private_key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))

    finish = client.post(
        "/login/passkey/finish",
        json={
            "id": credential.credential_id,
            "rawId": credential.credential_id,
            "type": "public-key",
            "response": {
                "clientDataJSON": _b64url_encode(client_data),
                "authenticatorData": _b64url_encode(auth_data),
                "signature": _b64url_encode(signature),
                "userHandle": "",
            },
            "security_verification": answer,
            "security_verification_token": token,
        },
    )

    assert finish.status_code == 200
    assert finish.get_json()["redirect_url"] == "/dashboard"
    with client.session_transaction() as session:
        assert session["_user_id"] == str(user.id)
    with app.app_context():
        refreshed = db.session.get(PasskeyCredential, credential.id)
        assert refreshed.sign_count == 5


def test_passkey_finish_rejects_wrong_origin(client, app):
    app.config["PASSKEY_ENABLED"] = True
    user = KullaniciFactory(kullanici_adi="origin-passkey@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()
    private_key, credential = _register_passkey(client, app, user)

    client.post("/logout")
    answer = _extract_challenge_answer(client, app)
    token = _captcha_token(client)
    begin = client.post("/login/passkey/begin")
    challenge = begin.get_json()["public_key"]["challenge"]
    rp_id = begin.get_json()["public_key"]["rpId"]
    auth_data = _authentication_authenticator_data(rp_id, sign_count=2)
    client_data = _client_data(challenge, "https://evil.example", "webauthn.get")
    signature = private_key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))

    finish = client.post(
        "/login/passkey/finish",
        json={
            "id": credential.credential_id,
            "rawId": credential.credential_id,
            "type": "public-key",
            "response": {
                "clientDataJSON": _b64url_encode(client_data),
                "authenticatorData": _b64url_encode(auth_data),
                "signature": _b64url_encode(signature),
                "userHandle": "",
            },
            "security_verification": answer,
            "security_verification_token": token,
        },
    )

    assert finish.status_code == 400
    assert finish.get_json()["status"] == "error"
    with client.session_transaction() as session:
        assert "_user_id" not in session


def test_passkey_finish_rejects_cross_origin_client_data(client, app):
    app.config["PASSKEY_ENABLED"] = True
    user = KullaniciFactory(kullanici_adi="cross-origin-passkey@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()
    private_key, credential = _register_passkey(client, app, user)

    client.post("/logout")
    answer = _extract_challenge_answer(client, app)
    token = _captcha_token(client)
    begin = client.post("/login/passkey/begin")
    challenge = begin.get_json()["public_key"]["challenge"]
    rp_id = begin.get_json()["public_key"]["rpId"]
    auth_data = _authentication_authenticator_data(rp_id, sign_count=2)
    client_data = _client_data(challenge, "http://localhost", "webauthn.get", cross_origin=True)
    signature = private_key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))

    finish = client.post(
        "/login/passkey/finish",
        json={
            "id": credential.credential_id,
            "rawId": credential.credential_id,
            "type": "public-key",
            "response": {
                "clientDataJSON": _b64url_encode(client_data),
                "authenticatorData": _b64url_encode(auth_data),
                "signature": _b64url_encode(signature),
                "userHandle": "",
            },
            "security_verification": answer,
            "security_verification_token": token,
        },
    )

    assert finish.status_code == 400
    assert finish.get_json()["status"] == "error"


def test_passkey_finish_rejects_wrong_challenge_and_replay(client, app):
    app.config["PASSKEY_ENABLED"] = True
    user = KullaniciFactory(kullanici_adi="challenge-passkey@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()
    private_key, credential = _register_passkey(client, app, user)

    client.post("/logout")
    answer = _extract_challenge_answer(client, app)
    token = _captcha_token(client)
    begin = client.post("/login/passkey/begin")
    rp_id = begin.get_json()["public_key"]["rpId"]
    auth_data = _authentication_authenticator_data(rp_id, sign_count=2)
    client_data = _client_data("wrong-challenge", "http://localhost", "webauthn.get")
    signature = private_key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
    payload = {
        "id": credential.credential_id,
        "rawId": credential.credential_id,
        "type": "public-key",
        "response": {
            "clientDataJSON": _b64url_encode(client_data),
            "authenticatorData": _b64url_encode(auth_data),
            "signature": _b64url_encode(signature),
            "userHandle": "",
        },
        "security_verification": answer,
        "security_verification_token": token,
    }

    wrong_challenge = client.post("/login/passkey/finish", json=payload)
    replay = client.post("/login/passkey/finish", json=payload)

    assert wrong_challenge.status_code == 400
    assert replay.status_code == 400


def test_passkey_finish_fails_closed_for_insecure_production_origin_config(client, app):
    app.config["PASSKEY_ENABLED"] = True
    user = KullaniciFactory(kullanici_adi="insecure-origin-passkey@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()
    private_key, credential = _register_passkey(client, app, user)

    client.post("/logout")
    app.config["ENV"] = "production"
    app.config["PASSKEY_RP_ID"] = "example.com"
    app.config["PASSKEY_ORIGIN"] = "http://example.com"
    app.config["PASSKEY_ALLOWED_ORIGINS"] = ""

    answer = _extract_challenge_answer(client, app)
    token = _captcha_token(client)
    begin = client.post("/login/passkey/begin", base_url="http://example.com")
    challenge = begin.get_json()["public_key"]["challenge"]
    rp_id = begin.get_json()["public_key"]["rpId"]
    auth_data = _authentication_authenticator_data(rp_id, sign_count=2)
    client_data = _client_data(challenge, "http://example.com", "webauthn.get")
    signature = private_key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))

    finish = client.post(
        "/login/passkey/finish",
        base_url="http://example.com",
        json={
            "id": credential.credential_id,
            "rawId": credential.credential_id,
            "type": "public-key",
            "response": {
                "clientDataJSON": _b64url_encode(client_data),
                "authenticatorData": _b64url_encode(auth_data),
                "signature": _b64url_encode(signature),
                "userHandle": "",
            },
            "security_verification": answer,
            "security_verification_token": token,
        },
    )

    assert begin.status_code == 200
    assert finish.status_code == 400
    assert finish.get_json()["status"] == "error"


def test_passkey_finish_rejects_unknown_credential(client, app):
    app.config["PASSKEY_ENABLED"] = True
    user = KullaniciFactory(kullanici_adi="unknown-passkey@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()

    answer = _extract_challenge_answer(client, app)
    token = _captcha_token(client)
    begin = client.post("/login/passkey/begin")
    challenge = begin.get_json()["public_key"]["challenge"]
    rp_id = begin.get_json()["public_key"]["rpId"]
    private_key, _public_key_der = _ec_keypair()
    unknown_credential_id = b"unknown-passkey-credential"
    auth_data = _authentication_authenticator_data(rp_id, sign_count=1)
    client_data = _client_data(challenge, "http://localhost", "webauthn.get")
    signature = private_key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))

    finish = client.post(
        "/login/passkey/finish",
        json={
            "id": _b64url_encode(unknown_credential_id),
            "rawId": _b64url_encode(unknown_credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": _b64url_encode(client_data),
                "authenticatorData": _b64url_encode(auth_data),
                "signature": _b64url_encode(signature),
                "userHandle": "",
            },
            "security_verification": answer,
            "security_verification_token": token,
        },
    )

    assert finish.status_code == 400
    assert finish.get_json()["status"] == "error"


def test_passkey_finish_works_without_captcha_when_passkey_verified(client, app):
    app.config["PASSKEY_ENABLED"] = True
    user = KullaniciFactory(kullanici_adi="captcha-passkey@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()
    private_key, credential = _register_passkey(client, app, user)

    client.post("/logout")
    begin = client.post("/login/passkey/begin")
    challenge = begin.get_json()["public_key"]["challenge"]
    rp_id = begin.get_json()["public_key"]["rpId"]
    auth_data = _authentication_authenticator_data(rp_id, sign_count=2)
    client_data = _client_data(challenge, "http://localhost", "webauthn.get")
    signature = private_key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))

    finish = client.post(
        "/login/passkey/finish",
        json={
            "id": credential.credential_id,
            "rawId": credential.credential_id,
            "type": "public-key",
            "response": {
                "clientDataJSON": _b64url_encode(client_data),
                "authenticatorData": _b64url_encode(auth_data),
                "signature": _b64url_encode(signature),
                "userHandle": "",
            },
            "security_verification": "",
            "security_verification_token": "",
        },
    )

    assert finish.status_code == 200
    assert finish.get_json()["status"] == "success"
    with client.session_transaction() as session:
        assert session.get("_user_id") == str(user.id)


def test_logout_after_passkey_login_clears_session(client, app):
    app.config["PASSKEY_ENABLED"] = True
    user = KullaniciFactory(kullanici_adi="logout-passkey@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()
    private_key, credential = _register_passkey(client, app, user)

    client.post("/logout")
    answer = _extract_challenge_answer(client, app)
    token = _captcha_token(client)
    begin = client.post("/login/passkey/begin")
    challenge = begin.get_json()["public_key"]["challenge"]
    rp_id = begin.get_json()["public_key"]["rpId"]
    auth_data = _authentication_authenticator_data(rp_id, sign_count=3)
    client_data = _client_data(challenge, "http://localhost", "webauthn.get")
    signature = private_key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
    finish = client.post(
        "/login/passkey/finish",
        json={
            "id": credential.credential_id,
            "rawId": credential.credential_id,
            "type": "public-key",
            "response": {
                "clientDataJSON": _b64url_encode(client_data),
                "authenticatorData": _b64url_encode(auth_data),
                "signature": _b64url_encode(signature),
                "userHandle": "",
            },
            "security_verification": answer,
            "security_verification_token": token,
        },
    )
    logout_response = client.post("/logout", follow_redirects=False)
    blocked = client.get("/dashboard", follow_redirects=False)

    assert finish.status_code == 200
    assert logout_response.status_code == 302
    assert blocked.status_code == 302
    assert "/login" in blocked.headers.get("Location", "")


def test_feature_enabled_login_page_renders_passkey_trigger(client, app):
    app.config["PASSKEY_ENABLED"] = True

    response = client.get("/login")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert 'id="passkeyLoginButton"' in html
    assert "static/passkey.js" in html


def test_passkey_sign_counter_zero_anomaly_rejected(client, app):
    app.config["PASSKEY_ENABLED"] = True
    user = KullaniciFactory(kullanici_adi="counter-anomaly@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()
    private_key, credential = _register_passkey(client, app, user)

    with app.app_context():
        stored = db.session.get(PasskeyCredential, credential.id)
        stored.sign_count = 5
        db.session.commit()

    client.post("/logout")
    answer = _extract_challenge_answer(client, app)
    token = _captcha_token(client)
    begin = client.post("/login/passkey/begin")
    challenge = begin.get_json()["public_key"]["challenge"]
    rp_id = begin.get_json()["public_key"]["rpId"]
    auth_data = _authentication_authenticator_data(rp_id, sign_count=0)
    client_data = _client_data(challenge, "http://localhost", "webauthn.get")
    signature = private_key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))

    finish = client.post(
        "/login/passkey/finish",
        json={
            "id": credential.credential_id,
            "rawId": credential.credential_id,
            "type": "public-key",
            "response": {
                "clientDataJSON": _b64url_encode(client_data),
                "authenticatorData": _b64url_encode(auth_data),
                "signature": _b64url_encode(signature),
                "userHandle": "",
            },
            "security_verification": answer,
            "security_verification_token": token,
        },
    )

    assert finish.status_code == 400
    assert finish.get_json()["status"] == "error"


def test_passkey_credentials_list_and_revoke(client, app):
    app.config["PASSKEY_ENABLED"] = True
    user = KullaniciFactory(kullanici_adi="manage-passkey@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()
    _private_key, _credential = _register_passkey(client, app, user)

    listed = client.get("/passkey/credentials")
    listed_payload = listed.get_json()
    assert listed.status_code == 200
    assert listed_payload["status"] == "success"
    assert len(listed_payload["credentials"]) == 1
    credential_id = listed_payload["credentials"][0]["id"]

    revoked = client.post("/passkey/credentials/revoke", json={"credential_id": credential_id})
    assert revoked.status_code == 200
    assert revoked.get_json()["status"] == "success"

    with app.app_context():
        stored = PasskeyCredential.query.filter_by(user_id=user.id).first()
        assert stored is not None
        assert stored.is_active is False
        assert stored.revoked_at is not None


def test_revoked_passkey_credential_is_rejected_on_login(client, app):
    app.config["PASSKEY_ENABLED"] = True
    user = KullaniciFactory(kullanici_adi="revoked-passkey@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()
    private_key, credential = _register_passkey(client, app, user)

    credentials = client.get("/passkey/credentials").get_json()["credentials"]
    assert credentials
    revoke_response = client.post("/passkey/credentials/revoke", json={"credential_id": credentials[0]["id"]})
    assert revoke_response.status_code == 200

    client.post("/logout")
    answer = _extract_challenge_answer(client, app)
    token = _captcha_token(client)
    begin = client.post("/login/passkey/begin")
    challenge = begin.get_json()["public_key"]["challenge"]
    rp_id = begin.get_json()["public_key"]["rpId"]
    auth_data = _authentication_authenticator_data(rp_id, sign_count=4)
    client_data = _client_data(challenge, "http://localhost", "webauthn.get")
    signature = private_key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))

    finish = client.post(
        "/login/passkey/finish",
        json={
            "id": credential.credential_id,
            "rawId": credential.credential_id,
            "type": "public-key",
            "response": {
                "clientDataJSON": _b64url_encode(client_data),
                "authenticatorData": _b64url_encode(auth_data),
                "signature": _b64url_encode(signature),
                "userHandle": "",
            },
            "security_verification": answer,
            "security_verification_token": token,
        },
    )

    assert finish.status_code == 400
    assert finish.get_json()["status"] == "error"


def test_passkey_finish_rejects_stale_challenge(client, app):
    app.config["PASSKEY_ENABLED"] = True
    user = KullaniciFactory(kullanici_adi="stale-passkey@sarx.com", is_deleted=False, rol="sahip")
    db.session.add(user)
    db.session.commit()
    private_key, credential = _register_passkey(client, app, user)

    client.post("/logout")
    answer = _extract_challenge_answer(client, app)
    token = _captcha_token(client)
    begin = client.post("/login/passkey/begin")
    challenge = begin.get_json()["public_key"]["challenge"]
    rp_id = begin.get_json()["public_key"]["rpId"]
    auth_data = _authentication_authenticator_data(rp_id, sign_count=6)
    client_data = _client_data(challenge, "http://localhost", "webauthn.get")
    signature = private_key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))

    with client.session_transaction() as session:
        created_at = int(session["passkey_authentication_state"]["created_at"])
    expired_now = created_at + int(app.config.get("PASSKEY_CHALLENGE_TTL_SECONDS", 180)) + 1

    with patch("passkey_helper.time.time", return_value=expired_now):
        finish = client.post(
            "/login/passkey/finish",
            json={
                "id": credential.credential_id,
                "rawId": credential.credential_id,
                "type": "public-key",
                "response": {
                    "clientDataJSON": _b64url_encode(client_data),
                    "authenticatorData": _b64url_encode(auth_data),
                    "signature": _b64url_encode(signature),
                    "userHandle": "",
                },
                "security_verification": answer,
                "security_verification_token": token,
            },
        )

    assert finish.status_code == 400
    assert finish.get_json()["status"] == "error"
