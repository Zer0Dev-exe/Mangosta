from typing import Annotated, Optional

import typer

from .. import config
from ..atlas import Atlas
from ..errors import MangostaError
from ..output import confirm, emit, emit_obj, success, warn
from ..state import state

app = typer.Typer(help="Perfiles de conexión (servidores / proyectos de Atlas).", no_args_is_help=True)

Uri = Annotated[Optional[str], typer.Option("--uri", help="Cadena de conexión mongodb:// o mongodb+srv:// (o env:VARIABLE)")]
PublicKey = Annotated[Optional[str], typer.Option("--atlas-public-key", help="Public key de la Atlas Admin API")]
PrivateKey = Annotated[Optional[str], typer.Option("--atlas-private-key", help="Private key (si no la pasas se pide oculta; admite env:VARIABLE)")]
ClientId = Annotated[Optional[str], typer.Option("--atlas-client-id", help="Client ID de una service account de Atlas")]
ClientSecret = Annotated[Optional[str], typer.Option("--atlas-client-secret", help="Client secret de la service account (se pide oculto si falta)")]
Project = Annotated[Optional[str], typer.Option("--atlas-project", help="ID del proyecto de Atlas (group id)")]
Cluster = Annotated[Optional[str], typer.Option("--atlas-cluster", help="Cluster de Atlas por defecto")]


def _mask(value):
    if not value:
        return value
    if str(value).startswith("env:"):
        return value
    return "•" * 8


def _mask_uri(uri: str | None) -> str | None:
    if not uri or uri.startswith("env:") or "@" not in uri:
        return uri
    scheme, _, rest = uri.partition("://")
    creds, _, host = rest.rpartition("@")
    user = creds.split(":", 1)[0]
    return f"{scheme}://{user}:••••@{host}"


def _apply(profile: dict, uri, public_key, private_key, client_id, client_secret, project, cluster) -> None:
    if uri is not None:
        profile["uri"] = uri
    atlas = profile.setdefault("atlas", {})
    if public_key is not None:
        atlas["public_key"] = public_key
        if private_key is None and not atlas.get("private_key"):
            private_key = typer.prompt("Atlas private key", hide_input=True)
    if private_key is not None:
        atlas["private_key"] = private_key
    if client_id is not None:
        atlas["client_id"] = client_id
        if client_secret is None and not atlas.get("client_secret"):
            client_secret = typer.prompt("Atlas client secret", hide_input=True)
    if client_secret is not None:
        atlas["client_secret"] = client_secret
    if project is not None:
        atlas["project_id"] = project
    if cluster is not None:
        atlas["cluster"] = cluster
    if not atlas:
        del profile["atlas"]


@app.command()
def add(
    name: Annotated[str, typer.Argument(help="Nombre del perfil, p.ej. prod")],
    uri: Uri = None,
    atlas_public_key: PublicKey = None,
    atlas_private_key: PrivateKey = None,
    atlas_client_id: ClientId = None,
    atlas_client_secret: ClientSecret = None,
    atlas_project: Project = None,
    atlas_cluster: Cluster = None,
    use: Annotated[bool, typer.Option("--use/--no-use", help="Activarlo al crearlo")] = True,
):
    """Crea un perfil con URI y/o API keys de Atlas. (Para entrar con tu cuenta usa: mangosta login)"""
    cfg = config.load()
    if name in cfg["profiles"]:
        raise MangostaError(f"El perfil '{name}' ya existe (modifícalo con: mangosta profile set {name} ...)")
    if not any([uri, atlas_public_key, atlas_client_id]):
        raise MangostaError("Indica al menos --uri o credenciales de Atlas (--atlas-public-key / --atlas-client-id). Para entrar con tu cuenta de MongoDB usa: mangosta login")
    profile: dict = {}
    _apply(profile, uri, atlas_public_key, atlas_private_key, atlas_client_id, atlas_client_secret, atlas_project, atlas_cluster)
    cfg["profiles"][name] = profile
    if use or cfg["current"] is None:
        cfg["current"] = name
    config.save(cfg)
    success(f"Perfil '{name}' creado" + (" y activado" if cfg["current"] == name else ""))
    if any(v and not str(v).startswith("env:") for v in (uri, atlas_private_key, atlas_client_secret)):
        warn(f"Los secretos se guardan en {config.config_path()}. Para no guardarlos en claro usa env:VARIABLE.")


@app.command("set")
def set_(
    name: Annotated[str, typer.Argument(help="Perfil a modificar")],
    uri: Uri = None,
    atlas_public_key: PublicKey = None,
    atlas_private_key: PrivateKey = None,
    atlas_client_id: ClientId = None,
    atlas_client_secret: ClientSecret = None,
    atlas_project: Project = None,
    atlas_cluster: Cluster = None,
):
    """Modifica campos de un perfil existente."""
    cfg = config.load()
    if name not in cfg["profiles"]:
        raise MangostaError(f"El perfil '{name}' no existe")
    _apply(cfg["profiles"][name], uri, atlas_public_key, atlas_private_key, atlas_client_id, atlas_client_secret, atlas_project, atlas_cluster)
    config.save(cfg)
    success(f"Perfil '{name}' actualizado")


@app.command("list")
def list_():
    """Lista los perfiles (el activo marcado con ●)."""
    cfg = config.load()
    active = config.active_profile_name()
    rows = []
    for name, p in cfg["profiles"].items():
        atlas = p.get("atlas") or {}
        rows.append({
            "active": "●" if name == active else "",
            "name": name,
            "uri": _mask_uri(p.get("uri")),
            "atlas": config.atlas_auth_kind(p | {"name": name}),
            "project": atlas.get("project_id"),
            "cluster": atlas.get("cluster"),
        })
    emit(rows, [("active", ""), ("name", "Perfil"), ("uri", "URI"), ("atlas", "Atlas"), ("project", "Proyecto"), ("cluster", "Cluster")],
         raw=[{k: v for k, v in r.items() if k != "active"} | {"active": r["active"] == "●"} for r in rows])


@app.command()
def use(name: Annotated[str, typer.Argument(help="Perfil a activar")]):
    """Cambia el perfil activo."""
    cfg = config.load()
    if name not in cfg["profiles"]:
        raise MangostaError(f"El perfil '{name}' no existe")
    cfg["current"] = name
    config.save(cfg)
    success(f"Perfil activo: {name}")


@app.command()
def show(name: Annotated[Optional[str], typer.Argument(help="Perfil (por defecto el activo)")] = None):
    """Muestra un perfil (secretos ocultos)."""
    if name:
        state.profile = name
    p = config.get_profile()
    atlas = p.get("atlas") or {}
    emit_obj({
        "perfil": p["name"],
        "uri": _mask_uri(p.get("uri")),
        "atlas public key": atlas.get("public_key"),
        "atlas private key": _mask(atlas.get("private_key")),
        "atlas client id": atlas.get("client_id"),
        "atlas client secret": _mask(atlas.get("client_secret")),
        "atlas sesión": "login con cuenta" if atlas.get("refresh_token") else None,
        "atlas proyecto": atlas.get("project_id"),
        "atlas cluster": atlas.get("cluster"),
        "usuario BD temporal": (atlas.get("managed_user") or {}).get("username"),
        "fichero": str(config.config_path()),
    })


@app.command()
def remove(name: Annotated[str, typer.Argument(help="Perfil a borrar")]):
    """Borra un perfil (no toca nada en el servidor)."""
    cfg = config.load()
    if name not in cfg["profiles"]:
        raise MangostaError(f"El perfil '{name}' no existe")
    confirm(f"¿Borrar el perfil '{name}'?")
    del cfg["profiles"][name]
    if cfg["current"] == name:
        cfg["current"] = next(iter(cfg["profiles"]), None)
    config.save(cfg)
    success(f"Perfil '{name}' borrado")


@app.command()
def test(name: Annotated[Optional[str], typer.Argument(help="Perfil (por defecto el activo)")] = None):
    """Comprueba la conexión a MongoDB y a la Atlas API."""
    from ..mongo import client

    if name:
        state.profile = name
    p = config.get_profile()
    ok = True
    if p.get("uri"):
        try:
            info = client().admin.command("buildInfo")
            success(f"MongoDB OK — versión {info.get('version')}")
        except Exception as e:  # noqa: BLE001 - queremos informar de cualquier fallo
            ok = False
            warn(f"MongoDB: {e}")
    if config.has_atlas(p):
        try:
            atlas = Atlas(p)
            if atlas.project_id:
                project = atlas.request("GET", atlas.group())
                success(f"Atlas OK — proyecto '{project['name']}'")
            else:
                atlas.request("GET", "/groups", params={"itemsPerPage": 1})
                success("Atlas OK (sin proyecto seleccionado: mangosta project list)")
        except Exception as e:  # noqa: BLE001
            ok = False
            warn(f"Atlas: {e}")
    if not ok:
        raise typer.Exit(1)
