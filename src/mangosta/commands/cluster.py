"""Clusters de Atlas."""

import socket
import sys
from typing import Annotated, Optional

import typer

from .. import connect as data_access
from .. import mongo, services
from ..atlas import Atlas, require_atlas
from ..errors import MangostaError
from ..output import choose, confirm, confirm_typed, emit, emit_obj, info, success, warn
from ..parsing import ip_allowed, parse_role
from ..state import state
from .access import public_ip

app = typer.Typer(help="(Atlas) Clusters: conectar, listar, crear, pausar, reanudar, escalar, borrar.", no_args_is_help=True)

ClusterName = Annotated[Optional[str], typer.Argument(help="Nombre del cluster (por defecto el del perfil)")]


def _row(c: dict) -> dict:
    provider = f"{c['provider']} {c['region'] or ''}".strip() if c["provider"] else None
    return {"name": c["name"], "state": "PAUSADO" if c["state"] == "PAUSED" else c["state"], "tier": c["tier"],
            "provider": provider, "version": c["version"], "type": c["type"]}


@app.command("list")
def list_():
    """Lista los clusters del proyecto."""
    clusters = services.list_clusters(require_atlas())
    emit([_row(c) for c in clusters],
         [("name", "Cluster"), ("state", "Estado"), ("tier", "Tier"), ("provider", "Proveedor/Región"),
          ("version", "MongoDB"), ("type", "Tipo")], raw=[c["raw"] for c in clusters])


@app.command()
def show(name: ClusterName = None):
    """Detalle de un cluster, incluidas las cadenas de conexión."""
    atlas = require_atlas()
    c = services.cluster_summary(services.get_cluster(atlas, atlas.cluster_name(name)))
    row = _row(c)
    emit_obj({
        "nombre": row["name"], "estado": row["state"], "tier": row["tier"], "proveedor": row["provider"],
        "mongodb": row["version"], "tipo": row["type"], "backups": c["backup"],
        "termination protection": c["protected"], "conexión (srv)": c["srv"],
        "conexión": (c["raw"].get("connectionStrings") or {}).get("standard"),
    }, title=f"Cluster {row['name']}")


@app.command("connection-string")
def connection_string(name: ClusterName = None):
    """Imprime la cadena de conexión mongodb+srv:// (sin usuario)."""
    atlas = require_atlas()
    conn = services.get_cluster(atlas, atlas.cluster_name(name)).get("connectionStrings") or {}
    uri = conn.get("standardSrv") or conn.get("standard")
    if not uri:
        raise MangostaError("El cluster aún no tiene cadena de conexión (¿se está creando?)")
    print(uri)


def pick_cluster(atlas: Atlas, name: str | None) -> str:
    if name:
        return name
    clusters = services.list_clusters(atlas)
    if not clusters:
        raise MangostaError("El proyecto no tiene clusters (crea uno con: mangosta cluster create NOMBRE)")
    return choose("¿Qué cluster?", [(f"{c['name']} ({c['tier']}, {c['state']})", c["name"]) for c in clusters],
                  "indica el nombre del cluster")


def ensure_ip_allowed(atlas: Atlas) -> None:
    """Como el botón 'Add current IP address' de Atlas."""
    ip = public_ip()
    if ip_allowed(ip, [e["entry"] for e in services.list_access(atlas) if e["entry"]]):
        return
    if not state.yes and not (sys.stdin.isatty() and typer.confirm(f"Tu IP {ip} no está en la access list del proyecto. ¿Añadirla?", default=True)):
        warn(f"Sin añadir tu IP ({ip}) no podrás conectarte a los datos")
        return
    services.add_access(atlas, "ipAddress", ip, f"mangosta {socket.gethostname()}")
    success(f"IP {ip} añadida a la access list")


def connect_cluster(atlas: Atlas, name: str, roles: list[dict] | None = None, check_ip: bool = True) -> None:
    if check_ip:
        ensure_ip_allowed(atlas)
    username = data_access.connect(atlas, name, roles)
    mongo._client = None
    success(f"Acceso a datos de '{name}' configurado con el usuario temporal '{username}' (se renueva solo)")
    try:
        mongo.client().admin.command("ping")
        success("Conexión al cluster OK — ya puedes usar  mangosta db list")
    except Exception as e:  # noqa: BLE001 - informativo
        warn(f"Aún no se puede conectar ({e.__class__.__name__}); Atlas puede tardar un minuto en propagar los cambios")


@app.command()
def connect(
    name: ClusterName = None,
    role: Annotated[Optional[list[str]], typer.Option("--role", "-r", help="Roles del usuario temporal (por defecto atlasAdmin@admin)")] = None,
    skip_ip: Annotated[bool, typer.Option("--skip-ip", help="No comprobar/añadir tu IP a la access list")] = False,
):
    """Configura el acceso a los DATOS del cluster con tu sesión (usuario de BD temporal automático)."""
    atlas = require_atlas()
    cluster = pick_cluster(atlas, name)
    connect_cluster(atlas, cluster, [parse_role(r) for r in role] if role else None, check_ip=not skip_ip)


@app.command()
def create(
    name: Annotated[str, typer.Argument(help="Nombre del cluster nuevo")],
    tier: Annotated[str, typer.Option("--tier", help="M0 (gratis), M10, M20, M30...")] = "M0",
    provider: Annotated[str, typer.Option("--provider", help="AWS | GCP | AZURE")] = "AWS",
    region: Annotated[str, typer.Option("--region", help="Región Atlas, p.ej. EU_WEST_1 (AWS), EUROPE_WEST1 (GCP)")] = "EU_WEST_1",
    version: Annotated[Optional[str], typer.Option("--mongodb-version", help="Versión mayor, p.ej. 8.0")] = None,
    backup: Annotated[bool, typer.Option("--backup/--no-backup", help="Backups en la nube (no M0)")] = False,
):
    """Crea un cluster (replica set de una región)."""
    atlas = require_atlas()
    confirm(f"Crear cluster '{name}' {tier.upper()} en {provider.upper()}/{region}? (puede tener coste)")
    services.create_cluster(atlas, name, tier, provider, region, version, backup)
    success(f"Cluster '{name}' en creación. Sigue el estado con: mangosta cluster show {name}")


@app.command()
def scale(
    name: Annotated[str, typer.Argument(help="Cluster")],
    tier: Annotated[str, typer.Option("--tier", help="Nuevo tier, p.ej. M20")],
):
    """Cambia el tier (tamaño) de un cluster dedicado."""
    atlas = require_atlas()
    confirm(f"Escalar '{name}' a {tier.upper()}? (puede cambiar el coste)")
    services.scale_cluster(atlas, name, tier)
    success(f"Escalado de '{name}' a {tier.upper()} solicitado")


def _set_paused(name: str | None, paused: bool) -> None:
    atlas = require_atlas()
    name = atlas.cluster_name(name)
    services.set_cluster_paused(atlas, name, paused)
    success(f"Cluster '{name}' {'pausándose' if paused else 'reanudándose'}")


@app.command()
def pause(name: ClusterName = None):
    """Pausa un cluster dedicado (deja de cobrar cómputo)."""
    _set_paused(name, True)


@app.command()
def resume(name: ClusterName = None):
    """Reanuda un cluster pausado."""
    _set_paused(name, False)


@app.command()
def delete(name: Annotated[str, typer.Argument(help="Cluster a borrar")]):
    """Borra un cluster y TODOS sus datos. ¡Irreversible!"""
    atlas = require_atlas()
    confirm_typed(f"Vas a BORRAR el cluster '{name}' y todos sus datos.", name)
    services.delete_cluster(atlas, name)
    success(f"Cluster '{name}' en proceso de borrado")
    info("[dim]Los backups pueden conservarse según la política del proyecto.[/]")
