import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any, Optional, Union
from urllib.parse import urlparse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa, padding
from flask import current_app, request, session


PASSKEY_REGISTRATION_SESSION_KEY = "passkey_registration_state"
PASSKEY_AUTHENTICATION_SESSION_KEY = "passkey_authentication_state"

_USER_PRESENT = 0x01
_USER_VERIFIED = 0x04
_BACKUP_ELIGIBLE = 0x08
_BACKUP_STATE = 0x10
_ATTESTED_CREDENTIAL_DATA = 0x40
_EXTENSION_DATA_INCLUDED = 0x80

_COSE_KTY_OKP = 1
_COSE_KTY_EC2 = 2
_COSE_KTY_RSA = 3
_COSE_KEY_KTY = 1
_COSE_KEY_ALG = 3
_COSE_KEY_CRV = -1
_COSE_KEY_X = -2
_COSE_KEY_Y = -3
_COSE_RSA_N = -1
_COSE_RSA_E = -2
_COSE_CRV_P256 = 1
_COSE_CRV_ED25519 = 6
_SUPPORTED_COSE_ALGORITHMS = {-7, -8, -257}

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}


class PasskeyError(ValueError):
    pass


def is_passkey_enabled() -> bool:
    return bool(current_app.config.get("PASSKEY_ENABLED"))


def b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def b64url_decode(value: Optional[Union[str, bytes]]) -> bytes:
    if value is None:
        raise PasskeyError("Eksik passkey verisi.")
    normalized = str(value).strip()
    if not normalized:
        raise PasskeyError("Eksik passkey verisi.")
    padding_length = (-len(normalized)) % 4
    normalized += "=" * padding_length
    try:
        return base64.urlsafe_b64decode(normalized.encode("ascii"))
    except Exception as exc:
        raise PasskeyError("Geçersiz passkey verisi.") from exc


def create_challenge() -> str:
    return b64url_encode(secrets.token_bytes(32))


def _request_host() -> str:
    return (request.host or "").split(":", 1)[0].strip().lower()


def _is_local_host(host: str) -> bool:
    normalized = str(host or "").strip().lower()
    return normalized in _LOCAL_HOSTS or normalized.endswith(".localhost")


def resolve_rp_id() -> str:
    configured = str(current_app.config.get("PASSKEY_RP_ID") or "").strip().lower()
    if configured:
        return configured
    host = _request_host()
    if current_app.config.get("ENV") in {"development", "testing"} or _is_local_host(host):
        return host
    raise PasskeyError("Passkey RP ID ayarı eksik.")


def allowed_origins() -> set[str]:
    values = []
    raw_values = [
        current_app.config.get("PASSKEY_ALLOWED_ORIGINS"),
        current_app.config.get("PASSKEY_ORIGIN"),
    ]
    for raw in raw_values:
        if not raw:
            continue
        values.extend(part.strip().rstrip("/") for part in str(raw).split(",") if part.strip())
    if values:
        validated = set()
        for origin in values:
            parsed = urlparse(origin)
            host = str(parsed.hostname or "").strip().lower()
            if parsed.scheme not in {"http", "https"} or not host:
                raise PasskeyError("Geçersiz passkey origin ayarı.")
            if parsed.scheme != "https" and not _is_local_host(host):
                raise PasskeyError("Passkey origin ayarı güvenli değil.")
            validated.add(origin)
        return validated
    origin = request.host_url.rstrip("/")
    host = _request_host()
    if current_app.config.get("ENV") in {"development", "testing"} or _is_local_host(host):
        return {origin}
    raise PasskeyError("Passkey origin ayarı eksik.")


def challenge_ttl_seconds() -> int:
    try:
        return max(int(current_app.config.get("PASSKEY_CHALLENGE_TTL_SECONDS", 180)), 30)
    except Exception:
        return 180


def _read_cbor_length(data: bytes, offset: int, additional_info: int) -> tuple[int, int]:
    if additional_info < 24:
        return additional_info, offset
    if additional_info == 24:
        size = 1
    elif additional_info == 25:
        size = 2
    elif additional_info == 26:
        size = 4
    elif additional_info == 27:
        size = 8
    else:
        raise PasskeyError("Desteklenmeyen CBOR uzunluğu.")
    end = offset + size
    if end > len(data):
        raise PasskeyError("Eksik CBOR verisi.")
    return int.from_bytes(data[offset:end], "big"), end


def _decode_cbor_item(data: bytes, offset: int = 0) -> tuple[Any, int]:
    if offset >= len(data):
        raise PasskeyError("Eksik CBOR verisi.")
    initial = data[offset]
    offset += 1
    major_type = initial >> 5
    additional_info = initial & 0x1F

    if major_type == 0:
        value, offset = _read_cbor_length(data, offset, additional_info)
        return value, offset
    if major_type == 1:
        value, offset = _read_cbor_length(data, offset, additional_info)
        return -1 - value, offset
    if major_type in {2, 3}:
        length, offset = _read_cbor_length(data, offset, additional_info)
        end = offset + length
        if end > len(data):
            raise PasskeyError("Eksik CBOR verisi.")
        raw = data[offset:end]
        if major_type == 2:
            return raw, end
        try:
            return raw.decode("utf-8"), end
        except Exception as exc:
            raise PasskeyError("Geçersiz CBOR metin verisi.") from exc
    if major_type == 4:
        length, offset = _read_cbor_length(data, offset, additional_info)
        items = []
        for _ in range(length):
            item, offset = _decode_cbor_item(data, offset)
            items.append(item)
        return items, offset
    if major_type == 5:
        length, offset = _read_cbor_length(data, offset, additional_info)
        items = {}
        for _ in range(length):
            key, offset = _decode_cbor_item(data, offset)
            value, offset = _decode_cbor_item(data, offset)
            try:
                if key in items:
                    raise PasskeyError("Geçersiz CBOR harita verisi.")
                items[key] = value
            except TypeError as exc:
                raise PasskeyError("Geçersiz CBOR harita verisi.") from exc
        return items, offset
    if major_type == 7:
        if additional_info == 20:
            return False, offset
        if additional_info == 21:
            return True, offset
        if additional_info == 22:
            return None, offset
    raise PasskeyError("Desteklenmeyen CBOR verisi.")


def decode_cbor(data: bytes) -> Any:
    value, offset = _decode_cbor_item(data, 0)
    if offset != len(data):
        raise PasskeyError("Beklenmeyen ek CBOR verisi.")
    return value


def _require_bytes(value: Any, *, field_name: str) -> bytes:
    if not isinstance(value, (bytes, bytearray)):
        raise PasskeyError(f"Geçersiz {field_name} verisi.")
    return bytes(value)


def _require_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise PasskeyError(f"Geçersiz {field_name} verisi.")
    try:
        return int(value)
    except Exception as exc:
        raise PasskeyError(f"Geçersiz {field_name} verisi.") from exc


def parse_attestation_object(attestation_object_b64: str) -> dict[str, Any]:
    attestation_raw = b64url_decode(attestation_object_b64)
    attestation = decode_cbor(attestation_raw)
    if not isinstance(attestation, dict):
        raise PasskeyError("Geçersiz attestation verisi.")

    fmt = attestation.get("fmt")
    att_stmt = attestation.get("attStmt")
    auth_data = attestation.get("authData")
    if not isinstance(fmt, str) or not isinstance(att_stmt, dict):
        raise PasskeyError("Geçersiz attestation verisi.")
    auth_data_bytes = _require_bytes(auth_data, field_name="attestation authenticator")
    if fmt != "none":
        raise PasskeyError("Desteklenmeyen attestation biçimi.")
    if att_stmt:
        raise PasskeyError("Geçersiz attestation kanıtı.")
    return {
        "raw": attestation_raw,
        "fmt": fmt,
        "att_stmt": att_stmt,
        "auth_data": auth_data_bytes,
    }


def store_registration_state(*, challenge: str, user_id: int, remember_me: bool = False) -> None:
    session[PASSKEY_REGISTRATION_SESSION_KEY] = {
        "challenge": challenge,
        "user_id": int(user_id),
        "remember_me": bool(remember_me),
        "created_at": int(time.time()),
        "rp_id": resolve_rp_id(),
    }


def store_authentication_state(*, challenge: str, remember_me: bool = False) -> None:
    session[PASSKEY_AUTHENTICATION_SESSION_KEY] = {
        "challenge": challenge,
        "remember_me": bool(remember_me),
        "created_at": int(time.time()),
        "rp_id": resolve_rp_id(),
    }


def consume_registration_state() -> dict[str, Any]:
    return _consume_state(PASSKEY_REGISTRATION_SESSION_KEY)


def consume_authentication_state() -> dict[str, Any]:
    return _consume_state(PASSKEY_AUTHENTICATION_SESSION_KEY)


def _consume_state(session_key: str) -> dict[str, Any]:
    state = session.pop(session_key, None)
    if not state:
        raise PasskeyError("Passkey oturumu bulunamadı. Lütfen yeniden deneyin.")
    created_at = int(state.get("created_at") or 0)
    if created_at <= 0 or (time.time() - created_at) > challenge_ttl_seconds():
        raise PasskeyError("Passkey doğrulama süresi doldu. Lütfen yeniden deneyin.")
    return state


def parse_client_data(client_data_b64: str, *, expected_type: str, expected_challenge: str) -> bytes:
    client_data_raw = b64url_decode(client_data_b64)
    try:
        client_data = json.loads(client_data_raw.decode("utf-8"))
    except Exception as exc:
        raise PasskeyError("Geçersiz passkey istemci verisi.") from exc
    origin = str(client_data.get("origin") or "").strip().rstrip("/")
    if str(client_data.get("type") or "").strip() != expected_type:
        raise PasskeyError("Geçersiz passkey türü.")
    if client_data.get("crossOrigin") is True:
        raise PasskeyError("Cross-origin passkey çağrıları desteklenmiyor.")
    if not hmac.compare_digest(str(client_data.get("challenge") or "").strip(), expected_challenge):
        raise PasskeyError("Geçersiz passkey challenge değeri.")
    if origin not in allowed_origins():
        raise PasskeyError("Geçersiz passkey origin değeri.")
    return client_data_raw


def parse_authenticator_data(auth_data_value: Union[str, bytes, bytearray]) -> dict[str, Any]:
    auth_data = auth_data_value if isinstance(auth_data_value, (bytes, bytearray)) else b64url_decode(auth_data_value)
    auth_data = bytes(auth_data)
    if len(auth_data) < 37:
        raise PasskeyError("Geçersiz authenticator verisi.")
    flags = auth_data[32]
    offset = 37
    parsed = {
        "raw": auth_data,
        "rp_id_hash": auth_data[:32],
        "flags": flags,
        "sign_count": int.from_bytes(auth_data[33:37], "big"),
        "user_present": bool(flags & _USER_PRESENT),
        "user_verified": bool(flags & _USER_VERIFIED),
        "backup_eligible": bool(flags & _BACKUP_ELIGIBLE),
        "backup_state": bool(flags & _BACKUP_STATE),
        "credential_id": None,
        "credential_public_key": None,
    }
    if flags & _ATTESTED_CREDENTIAL_DATA:
        if len(auth_data) < offset + 18:
            raise PasskeyError("Eksik attested credential verisi.")
        parsed["aaguid"] = auth_data[offset:offset + 16]
        offset += 16
        credential_length = int.from_bytes(auth_data[offset:offset + 2], "big")
        offset += 2
        if credential_length <= 0:
            raise PasskeyError("Geçersiz credential kimliği verisi.")
        credential_start = offset
        credential_end = credential_start + credential_length
        if len(auth_data) < credential_end:
            raise PasskeyError("Eksik credential kimliği verisi.")
        parsed["credential_id"] = auth_data[credential_start:credential_end]
        offset = credential_end
        credential_public_key, offset = _decode_cbor_item(auth_data, offset)
        parsed["credential_public_key"] = credential_public_key
    if flags & _EXTENSION_DATA_INCLUDED:
        extensions, offset = _decode_cbor_item(auth_data, offset)
        parsed["extensions"] = extensions
    if offset != len(auth_data):
        raise PasskeyError("Beklenmeyen authenticator verisi.")
    return parsed


def verify_rp_id_hash(auth_data: dict[str, Any], *, rp_id: Optional[str] = None) -> None:
    effective_rp_id = str(rp_id or resolve_rp_id()).strip().lower()
    expected_hash = hashlib.sha256(effective_rp_id.encode("utf-8")).digest()
    if auth_data.get("rp_id_hash") != expected_hash:
        raise PasskeyError("Geçersiz RP doğrulaması.")


def cose_key_to_public_key(cose_key: Any) -> tuple[bytes, int]:
    if not isinstance(cose_key, dict):
        raise PasskeyError("Geçersiz credential public key verisi.")
    kty = _require_int(cose_key.get(_COSE_KEY_KTY), field_name="credential key türü")
    alg = _require_int(cose_key.get(_COSE_KEY_ALG), field_name="credential algoritması")
    if alg not in _SUPPORTED_COSE_ALGORITHMS:
        raise PasskeyError("Desteklenmeyen credential algoritması.")

    try:
        if kty == _COSE_KTY_EC2:
            if alg != -7:
                raise PasskeyError("Geçersiz EC credential algoritması.")
            crv = _require_int(cose_key.get(_COSE_KEY_CRV), field_name="EC eğrisi")
            if crv != _COSE_CRV_P256:
                raise PasskeyError("Desteklenmeyen EC eğrisi.")
            x = _require_bytes(cose_key.get(_COSE_KEY_X), field_name="EC x koordinatı")
            y = _require_bytes(cose_key.get(_COSE_KEY_Y), field_name="EC y koordinatı")
            if len(x) != 32 or len(y) != 32:
                raise PasskeyError("Geçersiz EC public key uzunluğu.")
            public_key = ec.EllipticCurvePublicNumbers(
                int.from_bytes(x, "big"),
                int.from_bytes(y, "big"),
                ec.SECP256R1(),
            ).public_key()
        elif kty == _COSE_KTY_RSA:
            if alg != -257:
                raise PasskeyError("Geçersiz RSA credential algoritması.")
            modulus = _require_bytes(cose_key.get(_COSE_RSA_N), field_name="RSA modulus")
            exponent = _require_bytes(cose_key.get(_COSE_RSA_E), field_name="RSA exponent")
            if not modulus or not exponent:
                raise PasskeyError("Eksik RSA public key verisi.")
            public_key = rsa.RSAPublicNumbers(
                int.from_bytes(exponent, "big"),
                int.from_bytes(modulus, "big"),
            ).public_key()
        elif kty == _COSE_KTY_OKP:
            if alg != -8:
                raise PasskeyError("Geçersiz OKP credential algoritması.")
            crv = _require_int(cose_key.get(_COSE_KEY_CRV), field_name="OKP eğrisi")
            if crv != _COSE_CRV_ED25519:
                raise PasskeyError("Desteklenmeyen OKP eğrisi.")
            x = _require_bytes(cose_key.get(_COSE_KEY_X), field_name="OKP public key")
            if len(x) != 32:
                raise PasskeyError("Geçersiz OKP public key uzunluğu.")
            public_key = ed25519.Ed25519PublicKey.from_public_bytes(x)
        else:
            raise PasskeyError("Desteklenmeyen credential key türü.")
    except PasskeyError:
        raise
    except Exception as exc:
        raise PasskeyError("Geçersiz credential public key verisi.") from exc

    return (
        public_key.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ),
        alg,
    )


def validate_registration_response(payload: dict[str, Any], *, expected_challenge: str, expected_rp_id: Optional[str] = None) -> dict[str, Any]:
    response = payload.get("response") or {}
    if str(payload.get("type") or "").strip() != "public-key":
        raise PasskeyError("Geçersiz public key yanıtı.")
    client_data_raw = parse_client_data(
        str(response.get("clientDataJSON") or ""),
        expected_type="webauthn.create",
        expected_challenge=expected_challenge,
    )
    attestation = parse_attestation_object(str(response.get("attestationObject") or ""))
    auth_data = parse_authenticator_data(attestation["auth_data"])
    verify_rp_id_hash(auth_data, rp_id=expected_rp_id)
    if not auth_data["user_present"] or not auth_data["user_verified"]:
        raise PasskeyError("Passkey doğrulaması tamamlanamadı.")
    credential_id = auth_data.get("credential_id")
    if not credential_id:
        raise PasskeyError("Eksik credential kimliği.")
    raw_id = b64url_decode(str(payload.get("rawId") or ""))
    if raw_id != credential_id:
        raise PasskeyError("Credential kimliği doğrulanamadı.")
    public_key_bytes, algorithm = cose_key_to_public_key(auth_data.get("credential_public_key"))
    transports = response.get("transports") or []
    if not isinstance(transports, list):
        transports = []
    return {
        "credential_id": b64url_encode(credential_id),
        "public_key": b64url_encode(public_key_bytes),
        "algorithm": algorithm,
        "sign_count": auth_data["sign_count"],
        "backup_eligible": auth_data["backup_eligible"],
        "backup_state": auth_data["backup_state"],
        "transports": [str(item).strip() for item in transports if str(item).strip()],
        "client_data_json": b64url_encode(client_data_raw),
    }


def verify_authentication_response(payload: dict[str, Any], *, credential_public_key: str, expected_challenge: str, stored_sign_count: int = 0, expected_rp_id: Optional[str] = None) -> dict[str, Any]:
    response = payload.get("response") or {}
    if str(payload.get("type") or "").strip() != "public-key":
        raise PasskeyError("Geçersiz public key yanıtı.")
    client_data_raw = parse_client_data(
        str(response.get("clientDataJSON") or ""),
        expected_type="webauthn.get",
        expected_challenge=expected_challenge,
    )
    auth_data = parse_authenticator_data(str(response.get("authenticatorData") or ""))
    verify_rp_id_hash(auth_data, rp_id=expected_rp_id)
    if not auth_data["user_present"] or not auth_data["user_verified"]:
        raise PasskeyError("Passkey doğrulaması tamamlanamadı.")
    signature = b64url_decode(str(response.get("signature") or ""))
    public_key_bytes = b64url_decode(credential_public_key)
    client_data_hash = hashlib.sha256(client_data_raw).digest()
    signed_data = auth_data["raw"] + client_data_hash
    _verify_signature(public_key_bytes, signature, signed_data)
    new_sign_count = int(auth_data["sign_count"] or 0)
    if stored_sign_count and new_sign_count and new_sign_count <= int(stored_sign_count):
        raise PasskeyError("Passkey sayaç doğrulaması başarısız oldu.")
    return {
        "sign_count": new_sign_count,
        "backup_eligible": auth_data["backup_eligible"],
        "backup_state": auth_data["backup_state"],
        "credential_id": b64url_encode(b64url_decode(str(payload.get("rawId") or ""))),
    }


def _verify_signature(public_key_bytes: bytes, signature: bytes, signed_data: bytes) -> None:
    try:
        public_key = serialization.load_der_public_key(public_key_bytes)
        if isinstance(public_key, ec.EllipticCurvePublicKey):
            public_key.verify(signature, signed_data, ec.ECDSA(hashes.SHA256()))
            return
        if isinstance(public_key, rsa.RSAPublicKey):
            public_key.verify(signature, signed_data, padding.PKCS1v15(), hashes.SHA256())
            return
        if isinstance(public_key, ed25519.Ed25519PublicKey):
            public_key.verify(signature, signed_data)
            return
    except InvalidSignature as exc:
        raise PasskeyError("Passkey imzası doğrulanamadı.") from exc
    except Exception as exc:
        raise PasskeyError("Passkey imzası doğrulanamadı.") from exc
    raise PasskeyError("Desteklenmeyen passkey algoritması.")
