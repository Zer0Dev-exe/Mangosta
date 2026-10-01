"""Login con la cuenta de MongoDB (como ``atlas auth login``)."""

import sys
import webbrowser
from datetime import datetime, timezone
from typing import Annotated, Optional

import typer
from rich.panel import Panel

from .. import config, oauth, services
from ..atlas import Atlas
from ..errors import MangostaError
from ..output import choose, console, emit_obj, info, success, warn
from ..state import state
from .cluster import connect_cluster, pick_cluster

app = typer.Typer(help="Sesión con tu cuenta de MongoDB: login, logout, estado.", no_args_is_help=True)

ProfileName = Annotated[Optional[str], typer.Option("--name", help="Perfil donde guardar la sesión (por defecto 'atlas' o el activo si ya es de Atlas)")]
API_KEY_FIELDS = ("public_key", "private_key", "client_id", "client_secret")


def _target_profile(name: str | None) -> str:
    if name or state.profile:
        return name or state.profile
    cfg = config.load()
    current = cfg["current"]
    if current and config.has_atlas(cfg["profiles"].get(current, {}) | {"name": current}):
        return current
    return "atlas"


def store_session(profile_name: str, token: dict, client_id: str = oauth.CLIENT_ID) -> tuple[str | None, bool]:
    """Guarda la sesión en el perfil y lo activa. Devuelve (email de la cuenta, si sustituyó API keys)."""
    cfg = config.load()
    profile = cfg["profiles"].setdefault(profile_name, {})
    atlas_cfg = profile.setdefault("atlas", {})
    replaced = bool([k for k in API_KEY_FIELDS if atlas_cfg.pop(k, None)])
    atlas_cfg.update(oauth.token_fields(token))
    account = oauth.account_label(oauth.userinfo(token["access_token"]))
    if account:
        atlas_cfg["account"] = account
    if client_id != oauth.CLIENT_ID:
        atlas_cfg["oauth_client_id"] = client_id
    cfg["current"] = profile_name
    config.save(cfg)
    state.profile = profile_name
    return account, replaced


def default_profile_name(name: str | None = None) -> str:
    return _target_profile(name)


def _select_org_and_project(atlas: Atlas, org: str | None, project: str | None) -> None:
    orgs = services.list_orgs(atlas)
    if org:
        orgs = [o for o in orgs if org in (o["id"], o["name"])]
        if not orgs:
            raise MangostaError(f"No encuentro la organización '{org}'")
    if not orgs:
        warn("Tu cuenta no pertenece a ninguna organización; créala en cloud.mongodb.com")
        return
    if project and not org:
        # Con --project basta: se busca en todas las organizaciones.
        matches = [p for p in services.list_projects(atlas) if project in (p["id"], p["name"])]
        if not matches:
            raise MangostaError(f"No encuentro el proyecto '{project}'")
        chosen_project = matches[0]
        chosen_org = next((o for o in orgs if o["id"] == chosen_project.get("orgId")), {"id": chosen_project.get("orgId"), "name": "?"})
    else:
        chosen_org = choose("¿Qué organización?", [(o["name"], o) for o in orgs], "indícala con --org NOMBRE")
        projects = services.list_projects(atlas, chosen_org["id"])
        if project:
            projects = [p for p in projects if project in (p["id"], p["name"])]
        if not projects:
            config.update_atlas(atlas.profile_name, org_id=chosen_org["id"], project_id=None, cluster=None)
            atlas.org_id, atlas.project_id = chosen_org["id"], None
            success(f"Organización: {chosen_org['name']}")
            warn("No tiene proyectos (o no encuentro ese); crea uno con: mangosta project create NOMBRE")
            return
        chosen_project = choose(f"¿Qué proyecto de {chosen_org['name']}?",
                                [(f"{p['name']}  [dim]({p.get('clusterCount', 0)} clusters)[/]", p) for p in projects],
                                "indícalo con --project NOMBRE")
    atlas.org_id, atlas.project_id = chosen_org["id"], chosen_project["id"]
    config.update_atlas(atlas.profile_name, org_id=chosen_org["id"], project_id=chosen_project["id"], cluster=None)
    success(f"Organización: {chosen_org['name']}  ·  Proyecto: {chosen_project['name']}")


@app.command()
def login(
    name: ProfileName = None,
    org: Annotated[Optional[str], typer.Option("--org", help="Organización a usar (ID o nombre)")] = None,
    project: Annotated[Optional[str], typer.Option("--project", help="Proyecto a usar (ID o nombre)")] = None,
    cluster: Annotated[Optional[str], typer.Option("--cluster", help="Cluster al que conectarse para gestionar datos")] = None,
    no_connect: Annotated[bool, typer.Option("--no-connect", help="No configurar acceso a los datos de un cluster")] = False,
    no_browser: Annotated[bool, typer.Option("--no-browser", help="No abrir el navegador automáticamente")] = False,
    client_id: Annotated[str, typer.Option("--client-id", help="Client ID OAuth (por defecto el público del Atlas CLI)")] = oauth.CLIENT_ID,
):
    """Inicia sesión con tu cuenta de MongoDB en el navegador y elige proyecto/cluster."""
    profile_name = _target_profile(name)
    code = oauth.request_code(client_id)
    url = code["verification_uri"]
    console.print(Panel.fit(
        f"1. Abre [link={url}][bold cyan]{url}[/][/link]\n"
        f"2. Inicia sesión con tu cuenta de MongoDB\n"
        f"3. Introduce este código:  [bold yellow]{code['user_code']}[/]",
        title="Login en MongoDB", border_style="cyan"))
    if not no_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 - sin navegador seguimos con el enlace
            pass
    with console.status("Esperando a que confirmes el código en el navegador…"):
        token = oauth.poll_token(code, client_id)

    account, replaced = store_session(profile_name, token, client_id)
    success(f"Sesión iniciada{f' como {account}' if account else ''} (perfil '{profile_name}')")
    if replaced:
        info("[dim]Las API keys que tenía este perfil se han sustituido por tu sesión.[/]")

    atlas = Atlas(config.get_profile())
    _select_org_and_project(atlas, org, project)
    if no_connect or not atlas.project_id:
        return
    if not cluster and not sys.stdin.isatty():
        return
    if not cluster:
        if not typer.confirm("¿Configurar acceso a los datos de un cluster ahora?", default=True):
            info("Puedes hacerlo luego con:  mangosta cluster connect")
            return
    connect_cluster(atlas, pick_cluster(atlas, cluster))


@app.command()
def logout(
    name: Annotated[Optional[str], typer.Option("--name", help="Perfil (por defecto el activo)")] = None,
    keep_db_user: Annotated[bool, typer.Option("--keep-db-user", help="No borrar el usuario de BD temporal de mangosta")] = False,
):
    """Cierra la sesión: revoca el token y borra el usuario de BD temporal."""
    if name:
        state.profile = name
    profile = config.get_profile()
    creds = profile.get("atlas") or {}
    if not creds.get("refresh_token"):
        raise MangostaError(f"El perfil '{profile['name']}' no tiene una sesión iniciada")
    managed = creds.get("managed_user")
    if managed and not keep_db_user:
        try:
            atlas = Atlas(profile)
            atlas.request("DELETE", atlas.group(f"/databaseUsers/admin/{atlas.seg(managed['username'])}"))
            success(f"Usuario de BD temporal '{managed['username']}' eliminado")
        except MangostaError as e:
            warn(f"No se pudo borrar el usuario temporal '{managed['username']}': {e}")
    try:
        oauth.revoke(creds["refresh_token"], client_id=creds.get("oauth_client_id") or oauth.CLIENT_ID)
    except MangostaError:
        pass
    cfg = config.load()
    stored = cfg["profiles"][profile["name"]]
    for key in ("auth", "access_token", "refresh_token", "expires_at", "oauth_client_id", "managed_user", "account"):
        stored.get("atlas", {}).pop(key, None)
    if managed and not keep_db_user:
        stored.pop("uri", None)
    config.save(cfg)
    success(f"Sesión cerrada (perfil '{profile['name']}')")


def _when(ts) -> str:
    if not ts:
        return ""
    dt = datetime.fromisoformat(ts) if isinstance(ts, str) else datetime.fromtimestamp(ts, timezone.utc)
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


@app.command()
def status():
    """Con qué cuenta, proyecto y cluster estás trabajando."""
    profile = config.get_profile()
    creds = profile.get("atlas") or {}
    kind = config.atlas_auth_kind(profile)
    data: dict = {"perfil": profile["name"], "autenticación Atlas": kind or "(ninguna)"}
    if kind == "login":
        data["cuenta"] = creds.get("account") or oauth.account_name(creds.get("access_token"))
        data["token renovado hasta"] = _when(creds.get("expires_at"))
    if kind:
        try:
            atlas = Atlas(profile)
            if atlas.org_id:
                data["organización"] = atlas.request("GET", f"/orgs/{atlas.org_id}")["name"]
            if atlas.project_id:
                data["proyecto"] = atlas.request("GET", atlas.group())["name"]
            else:
                atlas.request("GET", "/groups", params={"itemsPerPage": 1})
                data["proyecto"] = "(sin elegir: mangosta project use NOMBRE)"
            data["sesión"] = "válida"
            if kind == "login" and not data.get("cuenta"):
                account = oauth.account_label(oauth.userinfo(atlas.session.headers.get("Authorization", "")[7:]))
                if account:
                    data["cuenta"] = account
                    config.update_atlas(profile["name"], account=account)
        except MangostaError as e:
            data["sesión"] = f"ERROR: {e}"
    data["cluster"] = creds.get("cluster")
    managed = creds.get("managed_user")
    if managed:
        data["usuario de BD temporal"] = f"{managed['username']} (caduca {_when(managed['expires_at'])}, se renueva solo)"
    elif profile.get("uri"):
        data["acceso a datos"] = "URI configurada manualmente"
    emit_obj(data, title="Estado de la sesión")
