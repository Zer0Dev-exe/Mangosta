"""Acceso a los datos de un cluster de Atlas a partir del login de la cuenta.

El token de la cuenta solo sirve para la Admin API; para leer/escribir datos
hace falta un usuario de base de datos. mangosta crea uno propio y temporal
(``mangosta-<usuario>-<equipo>``), con caducidad en Atlas, y lo renueva solo
cuando está a punto de caducar. Así no hay contraseñas que gestionar a mano.
"""

import getpass
import re
import secrets
import socket
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from . import config
from .atlas import CLUSTERS_API_VERSION, Atlas
from .errors import AtlasError, MangostaError
from .output import info, status
from .parsing import atlas_datetime, role_to_atlas

# Atlas rechaza caducidades de 7 días justos (EXPIRATION_DATE_EXCEEDS_MAX): 6 días y renovación el último.
MANAGED_TTL = timedelta(days=6)
RENEW_BEFORE = timedelta(days=1)
DEFAULT_ROLES = [{"role": "atlasAdmin", "db": "admin"}]


def managed_username() -> str:
    raw = f"mangosta-{getpass.getuser()}-{socket.gethostname()}".lower()
    return re.sub(r"[^a-z0-9-]+", "-", raw).strip("-")[:60]


def build_uri(srv: str, username: str, password: str) -> str:
    scheme, sep, rest = srv.partition("://")
    if not sep:
        raise MangostaError(f"Cadena de conexión inesperada: {srv}")
    return f"{scheme}://{quote(username, safe='')}:{quote(password, safe='')}@{rest}"


def _user_path(atlas: Atlas, username: str) -> str:
    return atlas.group(f"/databaseUsers/admin/{atlas.seg(username)}")


def upsert_managed_user(atlas: Atlas, cluster: str, roles: list[dict]) -> tuple[str, str, datetime]:
    username = managed_username()
    password = secrets.token_urlsafe(24)
    expires = datetime.now(timezone.utc) + MANAGED_TTL
    body = {
        "databaseName": "admin",
        "username": username,
        "password": password,
        "roles": [role_to_atlas(r) for r in roles],
        "scopes": [{"name": cluster, "type": "CLUSTER"}],
        "deleteAfterDate": atlas_datetime(expires),
    }
    try:
        atlas.request("GET", _user_path(atlas, username))
        exists = True
    except AtlasError as e:
        if "404" not in str(e):
            raise
        exists = False
    if exists:
        atlas.request("PATCH", _user_path(atlas, username), json={k: v for k, v in body.items() if k not in ("databaseName", "username")})
    else:
        atlas.request("POST", atlas.group("/databaseUsers"), json=body | {"groupId": atlas.project_id})
    return username, password, expires


def wait_until_applied(atlas: Atlas, cluster: str, timeout: int = 120) -> None:
    """Atlas tarda unos segundos en propagar usuarios/IPs al cluster."""
    path = atlas.group(f"/clusters/{atlas.seg(cluster)}/status")
    deadline = time.monotonic() + timeout
    with status("Aplicando cambios en el cluster…"):
        while time.monotonic() < deadline:
            try:
                result = atlas.request("GET", path)
            except AtlasError:
                time.sleep(5)  # endpoint no disponible: margen prudente y seguimos
                return
            if (result or {}).get("changeStatus") == "APPLIED":
                return
            time.sleep(3)
    info("[yellow]Atlas aún está aplicando los cambios; si la conexión falla, espera un minuto.[/]")


def connect(atlas: Atlas, cluster: str, roles: list[dict] | None = None) -> str:
    """Crea/renueva el usuario gestionado y guarda la URI en el perfil. Devuelve el usuario."""
    c = atlas.request("GET", atlas.group(f"/clusters/{atlas.seg(cluster)}"), version=CLUSTERS_API_VERSION)
    if c.get("paused"):
        raise MangostaError(f"El cluster '{cluster}' está pausado (reanúdalo con: mangosta cluster resume {cluster})")
    srv = (c.get("connectionStrings") or {}).get("standardSrv")
    if not srv:
        raise MangostaError(f"'{cluster}' aún no tiene cadena de conexión (¿se está creando?)")
    roles = roles or DEFAULT_ROLES
    username, password, expires = upsert_managed_user(atlas, cluster, roles)
    wait_until_applied(atlas, cluster)
    _save(atlas.profile_name, build_uri(srv, username, password), cluster, username, expires, roles, atlas.project_id)
    return username


def renew(profile: dict) -> str:
    """Renueva la contraseña y caducidad del usuario gestionado. Devuelve la URI nueva."""
    creds = profile.get("atlas") or {}
    managed = creds["managed_user"]
    atlas = Atlas(profile)
    atlas.project_id = managed.get("project_id") or atlas.project_id
    cluster = managed["cluster"]
    info("[dim]Renovando las credenciales temporales de base de datos…[/]")
    c = atlas.request("GET", atlas.group(f"/clusters/{atlas.seg(cluster)}"), version=CLUSTERS_API_VERSION)
    srv = (c.get("connectionStrings") or {}).get("standardSrv")
    roles = managed.get("roles") or DEFAULT_ROLES
    username, password, expires = upsert_managed_user(atlas, cluster, roles)
    wait_until_applied(atlas, cluster)
    uri = build_uri(srv, username, password)
    _save(profile["name"], uri, cluster, username, expires, roles, atlas.project_id)
    return uri


def needs_renewal(profile: dict) -> bool:
    managed = (profile.get("atlas") or {}).get("managed_user")
    if not managed:
        return False
    expires = datetime.fromisoformat(managed["expires_at"])
    return datetime.now(timezone.utc) >= expires - RENEW_BEFORE


def _save(profile_name: str, uri: str, cluster: str, username: str, expires: datetime, roles: list[dict],
          project_id: str | None) -> None:
    cfg = config.load()
    profile = cfg["profiles"][profile_name]
    profile["uri"] = uri
    atlas = profile.setdefault("atlas", {})
    atlas["cluster"] = cluster
    atlas["managed_user"] = {
        "username": username,
        "cluster": cluster,
        "project_id": project_id,
        "expires_at": expires.isoformat(),
        "roles": roles,
    }
    config.save(cfg)
