"""Login con la cuenta de MongoDB (OAuth 2.0 Device Authorization Flow).

Es el mismo flujo que usa ``atlas auth login`` del CLI oficial: se pide un
código, el usuario lo confirma en el navegador y se obtiene un access token
(Bearer para la Admin API) más un refresh token para renovarlo.

Endpoints, scopes y client ID tomados de github.com/mongodb/atlas-cli-core
(transport/oauth.go) y github.com/mongodb/go-client-mongodb-atlas (auth/).
MongoDB no permite registrar apps OAuth de terceros, así que por defecto se
usa el client ID público del Atlas CLI; se puede cambiar con --client-id.
"""

import base64
import json
import time

import requests

from .errors import AtlasError, MangostaError

ACCOUNT_URL = "https://cloud.mongodb.com"
DEVICE_PATH = "/api/private/unauth/account/device"
CLIENT_ID = "0oabtxactgS3gHIR0297"
SCOPES = "openid profile offline_access"
ISSUER = "https://auth.mongodb.com/oauth2/default"  # emisor de los tokens (claim "iss")

_HEADERS = {"Accept": "application/json", "User-Agent": "mangosta-cli"}


class SessionExpired(MangostaError):
    def __init__(self):
        super().__init__("La sesión de MongoDB ha caducado. Vuelve a entrar con:  mangosta login")


def _post(endpoint: str, data: dict) -> requests.Response:
    try:
        return requests.post(f"{ACCOUNT_URL}{DEVICE_PATH}/{endpoint}", data=data, headers=_HEADERS, timeout=30)
    except requests.RequestException as e:
        raise AtlasError(f"No se pudo contactar con MongoDB Cloud: {e}") from e


def _error_code(resp: requests.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return ""
    return body.get("errorCode") or body.get("error") or ""


def _error_message(resp: requests.Response) -> str:
    try:
        body = resp.json()
        return body.get("detail") or body.get("error_description") or body.get("errorCode") or resp.text[:300]
    except ValueError:
        return resp.text[:300]


def request_code(client_id: str = CLIENT_ID) -> dict:
    """Devuelve {user_code, verification_uri, device_code, expires_in, interval}."""
    resp = _post("authorize", {"client_id": client_id, "scope": SCOPES})
    if not resp.ok:
        raise AtlasError(f"No se pudo iniciar el login (HTTP {resp.status_code}): {_error_message(resp)}")
    return resp.json()


def poll_token(code: dict, client_id: str = CLIENT_ID, sleep=time.sleep) -> dict:
    """Espera a que el usuario confirme el código en el navegador."""
    interval = max(int(code.get("interval") or 5), 1)
    deadline = time.monotonic() + int(code.get("expires_in") or 900)
    while time.monotonic() < deadline:
        sleep(interval)
        resp = _post("token", {
            "client_id": client_id,
            "device_code": code["device_code"],
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        })
        if resp.ok:
            return resp.json()
        error = _error_code(resp)
        if error in ("DEVICE_AUTHORIZATION_PENDING", "authorization_pending"):
            continue
        if error in ("slow_down", "SLOW_DOWN") or resp.status_code == 429:
            interval += 5
            continue
        if error in ("DEVICE_AUTHORIZATION_EXPIRED", "expired_token"):
            break
        raise AtlasError(f"Login rechazado (HTTP {resp.status_code}): {_error_message(resp)}")
    raise MangostaError("El código ha caducado sin confirmarse. Vuelve a ejecutar  mangosta login")


def refresh(refresh_token: str, client_id: str = CLIENT_ID) -> dict:
    resp = _post("token", {
        "client_id": client_id,
        "refresh_token": refresh_token,
        "scope": SCOPES,
        "grant_type": "refresh_token",
    })
    if resp.status_code in (400, 401, 403):
        raise SessionExpired()
    if not resp.ok:
        raise AtlasError(f"No se pudo renovar la sesión (HTTP {resp.status_code}): {_error_message(resp)}")
    return resp.json()


def revoke(token: str, hint: str = "refresh_token", client_id: str = CLIENT_ID) -> None:
    _post("revoke", {"client_id": client_id, "token": token, "token_type_hint": hint})


def token_fields(token: dict) -> dict:
    """Campos a guardar en el perfil a partir de una respuesta de /token."""
    fields = {
        "auth": "oauth",
        "access_token": token["access_token"],
        "expires_at": int(time.time()) + int(token.get("expires_in") or 3600),
    }
    if token.get("refresh_token"):
        fields["refresh_token"] = token["refresh_token"]
    return fields


def userinfo(access_token: str) -> dict:
    """Perfil OpenID de la cuenta (email, nombre). Vacío si no se puede obtener."""
    try:
        resp = requests.get(f"{ISSUER}/v1/userinfo", headers=_HEADERS | {"Authorization": f"Bearer {access_token}"}, timeout=15)
    except requests.RequestException:
        return {}
    return resp.json() if resp.ok else {}


def account_label(info: dict) -> str | None:
    return info.get("primaryEmail") or info.get("email") or info.get("preferred_username") or info.get("name")


def jwt_claims(token: str | None) -> dict:
    """Lee (sin verificar) las claims de un JWT, solo para mostrar el email/usuario."""
    if not token or token.count(".") != 2:
        return {}
    payload = token.split(".")[1]
    try:
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (ValueError, json.JSONDecodeError):
        return {}


def account_name(token: str | None) -> str | None:
    claims = jwt_claims(token)
    # "sub" es un ID interno del proveedor de identidad: no sirve para mostrar.
    return claims.get("email") or claims.get("preferred_username")
