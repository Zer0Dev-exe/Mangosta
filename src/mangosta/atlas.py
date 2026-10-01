"""Cliente mínimo de la MongoDB Atlas Admin API v2.

Soporta tres tipos de credenciales:
  * Login con la cuenta de MongoDB (``mangosta login``) -> Bearer + refresh token.
  * API keys de programa (public/private key) -> HTTP Digest.
  * Service accounts (client id/secret) -> OAuth2 client credentials.
"""

import threading
import time
from urllib.parse import quote

import requests
from requests.auth import HTTPDigestAuth

from . import oauth
from .config import get_profile, has_atlas, load, resolve, update_atlas
from .errors import AtlasError, MangostaError

BASE_URL = "https://cloud.mongodb.com"
API_VERSION = "2023-01-01"
CLUSTERS_API_VERSION = "2023-02-01"
PAGE_SIZE = 500

# Las renovaciones del token de login se serializan: el refresh token puede rotar
# y dos renovaciones simultáneas con el mismo token invalidarían la segunda.
_refresh_lock = threading.Lock()


class Atlas:
    def __init__(self, profile: dict):
        creds = profile.get("atlas") or {}
        self.profile_name = profile["name"]
        self.project_id = creds.get("project_id")
        self.org_id = creds.get("org_id")
        self.default_cluster = creds.get("cluster")
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "mangosta-cli"
        self._client_id = resolve(creds.get("client_id"))
        self._client_secret = resolve(creds.get("client_secret"))
        self._token_expires = 0.0
        self._refresh_token = creds.get("refresh_token")
        self._oauth_client_id = creds.get("oauth_client_id") or oauth.CLIENT_ID
        if self._refresh_token:
            self._client_id = None
            self._token_expires = float(creds.get("expires_at") or 0)
            if creds.get("access_token"):
                self.session.headers["Authorization"] = f"Bearer {creds['access_token']}"
        elif not self._client_id:
            public_key = resolve(creds.get("public_key"))
            private_key = resolve(creds.get("private_key"))
            if not (public_key and private_key):
                raise MangostaError(f"El perfil '{self.profile_name}' no tiene sesión de Atlas. Entra con:  mangosta login")
            self.session.auth = HTTPDigestAuth(public_key, private_key)

    # --- HTTP ---------------------------------------------------------------

    def _adopt_stored_token(self, force: bool) -> bool:
        """Si otra instancia/proceso ya renovó la sesión, usa ese token guardado.

        Con ``force`` (tras un 401) no se readopta el mismo token que acaba de fallar.
        """
        stored = (load()["profiles"].get(self.profile_name) or {}).get("atlas") or {}
        token, expires = stored.get("access_token"), float(stored.get("expires_at") or 0)
        if not token or expires - 60 <= time.time():
            return False
        if force and self.session.headers.get("Authorization") == f"Bearer {token}":
            return False
        self.session.headers["Authorization"] = f"Bearer {token}"
        self._token_expires = expires
        self._refresh_token = stored.get("refresh_token", self._refresh_token)
        return True

    def _refresh_login(self, force: bool = False) -> None:
        with _refresh_lock:
            if self._adopt_stored_token(force):
                return
            token = oauth.refresh(self._refresh_token, self._oauth_client_id)
            fields = oauth.token_fields(token)
            self._refresh_token = fields.get("refresh_token", self._refresh_token)
            self._token_expires = fields["expires_at"]
            self.session.headers["Authorization"] = f"Bearer {fields['access_token']}"
            update_atlas(self.profile_name, **fields)

    def _ensure_token(self) -> None:
        if self._refresh_token:
            if time.time() >= self._token_expires - 60:
                self._refresh_login()
            return
        if not self._client_id or time.time() < self._token_expires - 60:
            return
        resp = requests.post(
            f"{BASE_URL}/api/oauth/token",
            auth=(self._client_id, self._client_secret),
            data={"grant_type": "client_credentials"},
            headers={"Accept": "application/json"},
            timeout=30,
        )
        if not resp.ok:
            raise AtlasError(f"No se pudo obtener token de la service account (HTTP {resp.status_code}): {resp.text[:300]}")
        body = resp.json()
        self.session.headers["Authorization"] = f"Bearer {body['access_token']}"
        self._token_expires = time.time() + body.get("expires_in", 3600)

    def request(self, method: str, path: str, *, json=None, params=None, version: str = API_VERSION, _retried: bool = False):
        self._ensure_token()
        media = f"application/vnd.atlas.{version}+json"
        headers = {"Accept": media}
        if json is not None:
            headers["Content-Type"] = media
        try:
            resp = self.session.request(
                method, f"{BASE_URL}/api/atlas/v2{path}", json=json, params=params, headers=headers, timeout=60
            )
        except requests.RequestException as e:
            raise AtlasError(f"No se pudo contactar con Atlas: {e}") from e
        if resp.status_code == 401 and self._refresh_token and not _retried:
            # El access token puede haberse revocado/caducado antes de tiempo.
            self._refresh_login(force=True)
            return self.request(method, path, json=json, params=params, version=version, _retried=True)
        if not resp.ok:
            try:
                body = resp.json()
                detail = body.get("detail") or body.get("reason") or resp.text
                code = body.get("errorCode", "")
                msg = f"{code}: {detail}" if code else detail
            except ValueError:
                msg = resp.text[:300]
            if resp.status_code == 401:
                msg += " (revisa las credenciales y que tu IP esté en la access list de la API key)"
            elif resp.status_code == 403 and self._refresh_token:
                msg += " (tu usuario de Atlas no tiene permisos suficientes en este proyecto/organización)"
            raise AtlasError(f"Atlas respondió HTTP {resp.status_code} — {msg}")
        return resp.json() if resp.content else None

    def get_all(self, path: str, version: str = API_VERSION) -> list[dict]:
        """GET paginado: devuelve todos los elementos de ``results``."""
        items: list[dict] = []
        page = 1
        while True:
            body = self.request("GET", path, params={"itemsPerPage": PAGE_SIZE, "pageNum": page}, version=version)
            results = body.get("results", [])
            items.extend(results)
            total = body.get("totalCount")
            if len(results) < PAGE_SIZE or (total is not None and len(items) >= total):
                return items
            page += 1

    # --- Helpers ------------------------------------------------------------

    def group(self, suffix: str = "") -> str:
        if not self.project_id:
            raise MangostaError("Falta el proyecto de Atlas: elige uno con  mangosta project use NOMBRE")
        return f"/groups/{self.project_id}{suffix}"

    def cluster_name(self, name: str | None) -> str:
        name = name or self.default_cluster
        if not name:
            raise MangostaError("Indica el nombre del cluster (o fija uno por defecto con: mangosta profile set PERFIL --atlas-cluster NOMBRE)")
        return name

    @staticmethod
    def seg(value: str) -> str:
        """Codifica un segmento de URL (p.ej. un CIDR con '/')."""
        return quote(value, safe="")


def atlas_or_none() -> Atlas | None:
    profile = get_profile()
    return Atlas(profile) if has_atlas(profile) else None


def require_atlas() -> Atlas:
    profile = get_profile()
    if not has_atlas(profile):
        raise MangostaError(
            f"Este comando necesita Atlas y el perfil '{profile['name']}' no tiene sesión de Atlas.\n"
            "Entra con tu cuenta de MongoDB:  mangosta login"
        )
    return Atlas(profile)
