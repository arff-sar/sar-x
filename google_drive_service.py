import json
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import current_app
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials

from extensions import db


class GoogleDriveError(RuntimeError):
    pass


class GoogleDriveDrillService:
    DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
    DRIVE_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3/files"
    DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
    FOLDER_MIME = "application/vnd.google-apps.folder"

    def __init__(self, app=None):
        self.app = app or current_app

    def _config(self, key, default=None):
        return self.app.config.get(key, default)

    def build_redirect_uri(self):
        configured = str(self._config("GOOGLE_DRIVE_REDIRECT_URI") or "").strip()
        if configured:
            return configured

        public_base_url = str(self._config("PUBLIC_BASE_URL") or "").strip().rstrip("/")
        if not public_base_url:
            raise GoogleDriveError("Google Drive redirect URI yapılandırması eksik.")
        return f"{public_base_url}/google-drive/oauth/callback"

    def _credentials(self):
        client_id = self._config("GOOGLE_DRIVE_CLIENT_ID")
        client_secret = self._config("GOOGLE_DRIVE_CLIENT_SECRET")
        refresh_token = self._config("GOOGLE_DRIVE_REFRESH_TOKEN")
        token_uri = self._config("GOOGLE_DRIVE_TOKEN_URI")
        if not all([client_id, client_secret, refresh_token, token_uri]):
            raise GoogleDriveError("Google Drive yapılandırması eksik.")

        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=token_uri,
            client_id=client_id,
            client_secret=client_secret,
            scopes=[self.DRIVE_SCOPE],
        )
        credentials.refresh(GoogleAuthRequest())
        return credentials

    def _request(self, method, url, *, params=None, data=None, headers=None):
        request_url = url
        if params:
            request_url = f"{url}?{urlencode(params)}"

        auth_headers = {
            "Authorization": f"Bearer {self._credentials().token}",
        }
        if headers:
            auth_headers.update(headers)

        request = Request(request_url, data=data, headers=auth_headers, method=method)
        try:
            with urlopen(request) as response:
                body = response.read()
                return response, body
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="ignore")
            raise GoogleDriveError(f"Google Drive isteği başarısız oldu: {exc.code} {error_body}") from exc
        except URLError as exc:
            raise GoogleDriveError("Google Drive ağına bağlanılamadı.") from exc

    def _request_json(self, method, url, *, params=None, json_body=None, headers=None):
        payload = None
        combined_headers = {"Accept": "application/json"}
        if json_body is not None:
            payload = json.dumps(json_body).encode("utf-8")
            combined_headers["Content-Type"] = "application/json; charset=UTF-8"
        if headers:
            combined_headers.update(headers)
        _, body = self._request(method, url, params=params, data=payload, headers=combined_headers)
        if not body:
            return {}
        return json.loads(body.decode("utf-8"))

    def exchange_authorization_code(self, code):
        client_id = self._config("GOOGLE_DRIVE_CLIENT_ID")
        client_secret = self._config("GOOGLE_DRIVE_CLIENT_SECRET")
        token_uri = self._config("GOOGLE_DRIVE_TOKEN_URI")
        if not all([client_id, client_secret, token_uri]):
            raise GoogleDriveError("Google Drive OAuth yapılandırması eksik.")

        payload = urlencode(
            {
                "code": str(code or "").strip(),
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": self.build_redirect_uri(),
                "grant_type": "authorization_code",
            }
        ).encode("utf-8")
        request = Request(
            token_uri,
            data=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with urlopen(request) as response:
                body = response.read()
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="ignore")
            raise GoogleDriveError(f"Google OAuth token isteği başarısız oldu: {exc.code} {error_body}") from exc
        except URLError as exc:
            raise GoogleDriveError("Google OAuth ağına bağlanılamadı.") from exc

        if not body:
            raise GoogleDriveError("Google OAuth yanıtı boş döndü.")
        return json.loads(body.decode("utf-8"))

    @staticmethod
    def _escape_query(value):
        return str(value or "").replace("\\", "\\\\").replace("'", "\\'")

    def _find_folder(self, name, parent_folder_id):
        query = (
            f"mimeType = '{self.FOLDER_MIME}' and trashed = false and "
            f"name = '{self._escape_query(name)}' and '{parent_folder_id}' in parents"
        )
        data = self._request_json(
            "GET",
            f"{self.DRIVE_API_BASE}/files",
            params={
                "q": query,
                "fields": "files(id,name)",
                "pageSize": 1,
                "supportsAllDrives": "false",
            },
        )
        files = data.get("files") or []
        return files[0]["id"] if files else None

    def _create_folder(self, name, parent_folder_id):
        payload = {
            "name": name,
            "mimeType": self.FOLDER_MIME,
            "parents": [parent_folder_id],
        }
        data = self._request_json(
            "POST",
            f"{self.DRIVE_API_BASE}/files",
            params={"fields": "id,name"},
            json_body=payload,
        )
        folder_id = data.get("id")
        if not folder_id:
            raise GoogleDriveError("Google Drive klasörü oluşturulamadı.")
        return folder_id

    def ensure_root_folder(self):
        cache = self.app.extensions.setdefault("tatbikat_drive_cache", {})
        cached = cache.get("root_folder_id")
        if cached:
            return cached

        parent_folder_id = self._config("GOOGLE_DRIVE_PARENT_FOLDER_ID", "root")
        root_name = self._config("GOOGLE_DRIVE_DRILLS_ROOT_FOLDER_NAME", "SAR-X Tatbikat Belgeleri")
        folder_id = self._find_folder(root_name, parent_folder_id)
        if not folder_id:
            folder_id = self._create_folder(root_name, parent_folder_id)
        cache["root_folder_id"] = folder_id
        return folder_id

    def ensure_airport_folder(self, airport, refresh=False):
        if airport.drive_folder_id and not refresh:
            return airport.drive_folder_id

        root_folder_id = self.ensure_root_folder()
        folder_name = f"{airport.kodu} - {airport.ad}"
        folder_id = self._find_folder(folder_name, root_folder_id)
        if not folder_id:
            folder_id = self._create_folder(folder_name, root_folder_id)
        airport.drive_folder_id = folder_id
        db.session.flush()
        return folder_id

    def upload_file(self, airport, upload, filename, mime_type):
        file_content = upload.read()
        if file_content is None:
            raise GoogleDriveError("Dosya içeriği okunamadı.")

        def _build_multipart(folder_id):
            metadata = {
                "name": filename,
                "parents": [folder_id],
            }
            boundary = f"sarx-{uuid.uuid4().hex}"
            metadata_part = json.dumps(metadata).encode("utf-8")
            body = b"".join(
                [
                    f"--{boundary}\r\n".encode("utf-8"),
                    b"Content-Type: application/json; charset=UTF-8\r\n\r\n",
                    metadata_part,
                    b"\r\n",
                    f"--{boundary}\r\n".encode("utf-8"),
                    f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"),
                    file_content,
                    b"\r\n",
                    f"--{boundary}--\r\n".encode("utf-8"),
                ]
            )
            return boundary, body

        folder_id = self.ensure_airport_folder(airport)
        try:
            boundary, body = _build_multipart(folder_id)
            _, response_body = self._request(
                "POST",
                self.DRIVE_UPLOAD_BASE,
                params={"uploadType": "multipart", "fields": "id,name,mimeType,size,parents"},
                data=body,
                headers={"Content-Type": f'multipart/related; boundary="{boundary}"'},
            )
            data = json.loads(response_body.decode("utf-8"))
        except GoogleDriveError:
            if not airport.drive_folder_id:
                raise
            airport.drive_folder_id = None
            db.session.flush()
            folder_id = self.ensure_airport_folder(airport, refresh=True)
            boundary, body = _build_multipart(folder_id)
            _, response_body = self._request(
                "POST",
                self.DRIVE_UPLOAD_BASE,
                params={"uploadType": "multipart", "fields": "id,name,mimeType,size,parents"},
                data=body,
                headers={"Content-Type": f'multipart/related; boundary="{boundary}"'},
            )
            data = json.loads(response_body.decode("utf-8"))

        file_id = data.get("id")
        if not file_id:
            raise GoogleDriveError("Google Drive dosya kimliği alınamadı.")
        return {
            "drive_file_id": file_id,
            "drive_folder_id": folder_id,
            "mime_type": data.get("mimeType") or mime_type,
            "file_size": int(data.get("size") or len(file_content)),
            "filename": data.get("name") or filename,
        }

    def get_file_metadata(self, drive_file_id):
        return self._request_json(
            "GET",
            f"{self.DRIVE_API_BASE}/files/{drive_file_id}",
            params={"fields": "id,name,mimeType,size,trashed"},
        )

    def download_file(self, drive_file_id):
        metadata = self.get_file_metadata(drive_file_id)
        _, content = self._request(
            "GET",
            f"{self.DRIVE_API_BASE}/files/{drive_file_id}",
            params={"alt": "media"},
        )
        return {
            "content": content,
            "mime_type": metadata.get("mimeType") or "application/octet-stream",
            "filename": metadata.get("name") or drive_file_id,
            "size": int(metadata.get("size") or len(content)),
        }

    def delete_file(self, drive_file_id):
        self._request("DELETE", f"{self.DRIVE_API_BASE}/files/{drive_file_id}")
        return True


def get_drill_drive_service():
    return GoogleDriveDrillService()
