"""Acceso por IP (equivalente a "Network Access" de Atlas).

* Atlas: la IP Access List del proyecto (vía Admin API).
* Self-hosted: MongoDB no tiene una lista global por IP fuera de ``bindIp``/firewall,
  pero sí restricciones por usuario (``authenticationRestrictions.clientSource``).
  En ese modo add/remove necesitan ``--user``.
"""

from typing import Annotated, Optional

import requests
import typer

from .. import services
from ..atlas import Atlas, atlas_or_none
from ..errors import MangostaError
from ..mongo import authenticated_users, client_address, find_user, list_users, user_ip_sources
from ..output import confirm, confirm_typed, emit, info, success, warn
from ..parsing import classify_access_entry, ip_allowed, is_open_to_world, parse_expiry

app = typer.Typer(help="Acceso por IP (Network Access): qué IPs pueden conectarse.", no_args_is_help=True)

Entry = Annotated[str, typer.Argument(help="IP (1.2.3.4), CIDR (10.0.0.0/24), sg-xxxx (AWS) o 'me' para tu IP pública")]
User = Annotated[Optional[str], typer.Option("--user", "-u", help="(Self-hosted) usuario al que aplicar la restricción")]
AuthDb = Annotated[str, typer.Option("--db", help="(Self-hosted) BD de autenticación del usuario")]


def public_ip() -> str:
    try:
        return requests.get("https://api.ipify.org", timeout=10).text.strip()
    except requests.RequestException as e:
        raise MangostaError(f"No se pudo averiguar tu IP pública: {e}") from e


def _resolve_entry(entry: str) -> str:
    if entry.lower() in ("me", "current", "mi-ip"):
        ip = public_ip()
        info(f"Tu IP pública es [bold]{ip}[/]")
        return ip
    return entry


def _check_mode(atlas: Atlas | None, user: str | None) -> None:
    if atlas and user:
        raise MangostaError("En Atlas la access list es del proyecto, no por usuario: quita --user")
    if not atlas and not user:
        raise MangostaError(
            "Este perfil no es de Atlas. En MongoDB self-hosted las IPs se restringen por usuario:\n"
            "  mangosta access add 10.0.0.0/24 --user app\n"
            "(La lista global de IPs se controla con bindIp en mongod.conf y el firewall.)"
        )


def _set_user_sources(username: str, db: str, sources: list[str]) -> None:
    """Como services.set_user_ip_sources, pero avisando si te vas a bloquear a ti mismo."""
    is_me = any(u["user"] == username and u["db"] == db for u in authenticated_users())
    my_ip = client_address() if is_me else None
    if is_me and sources and my_ip and not ip_allowed(my_ip, sources):
        warn(f"Eres '{username}' y el servidor te ve como {my_ip}, que NO estará en la lista: te quedarías sin acceso.")
        confirm_typed("Puedes bloquearte a ti mismo.", username)
    services.set_user_ip_sources(username, db, sources)


@app.command("list")
def list_(user: User = None, db: AuthDb = "admin"):
    """Lista las IPs permitidas."""
    atlas = atlas_or_none()
    if atlas:
        _check_mode(atlas, user)
        entries = services.list_access(atlas)
        rows = [e | {"expires": e["expires"] or "permanente"} for e in entries]
        emit(rows, [("entry", "IP / CIDR"), ("comment", "Comentario"), ("expires", "Caduca")], raw=[e["raw"] for e in entries])
        for e in entries:
            if is_open_to_world(e["entry"] or ""):
                warn(f"{e['entry']} permite conexiones desde CUALQUIER IP")
        return
    users = [find_user(user, db)] if user else list_users()
    rows = [{"user": f"{u['user']}@{u['db']}", "ips": user_ip_sources(u) or "cualquiera"} for u in users]
    emit(rows, [("user", "Usuario"), ("ips", "IPs permitidas")])


@app.command()
def add(
    entry: Entry,
    comment: Annotated[Optional[str], typer.Option("--comment", "-c", help="(Atlas) comentario")] = None,
    expires: Annotated[Optional[str], typer.Option("--expires", help="(Atlas) entrada temporal: 30m, 6h, 7d o fecha ISO (máx. 1 semana)")] = None,
    user: User = None,
    db: AuthDb = "admin",
):
    """Permite una IP / rango."""
    atlas = atlas_or_none()
    _check_mode(atlas, user)
    kind, value = classify_access_entry(_resolve_entry(entry))
    if is_open_to_world(value):
        warn("0.0.0.0/0 abre el acceso a TODO internet")
        confirm("¿Seguro que quieres permitir cualquier IP?")
    if atlas:
        services.add_access(atlas, kind, value, comment, parse_expiry(expires) if expires else None)
        success(f"{value} añadida a la access list" + (" (temporal)" if expires else ""))
        return
    if kind == "awsSecurityGroup":
        raise MangostaError("Los security groups solo existen en Atlas")
    if comment or expires:
        warn("--comment y --expires solo se aplican en Atlas; se ignoran")
    sources = user_ip_sources(find_user(user, db))
    if value in sources:
        info(f"{value} ya estaba permitida para {user}")
        return
    _set_user_sources(user, db, sources + [value])
    success(f"{user} ahora solo puede conectarse desde: {', '.join(sources + [value])}")


@app.command()
def remove(entry: Entry, user: User = None, db: AuthDb = "admin"):
    """Quita una IP / rango."""
    atlas = atlas_or_none()
    _check_mode(atlas, user)
    entry = _resolve_entry(entry)
    _, value = classify_access_entry(entry)
    if atlas:
        confirm(f"¿Quitar {value} de la access list del proyecto?")
        services.remove_access(atlas, value)
        success(f"{value} eliminada de la access list")
        return
    sources = user_ip_sources(find_user(user, db))
    remaining = [s for s in sources if s not in (value, entry)]
    if len(remaining) == len(sources):
        raise MangostaError(f"{value} no está en la lista de {user} ({', '.join(sources) or 'sin restricciones'})")
    if not remaining:
        warn(f"Era la última IP: {user} podrá conectarse desde CUALQUIER IP")
    confirm(f"¿Quitar {value} de las IPs permitidas de {user}?")
    _set_user_sources(user, db, remaining)
    success(f"{value} eliminada para {user}")


@app.command()
def clear(user: Annotated[str, typer.Option("--user", "-u", help="Usuario")], db: AuthDb = "admin"):
    """(Self-hosted) Quita todas las restricciones de IP de un usuario."""
    if atlas_or_none():
        raise MangostaError("En Atlas borra las entradas una a una con  mangosta access remove")
    confirm(f"{user} podrá conectarse desde cualquier IP. ¿Continuar?")
    services.set_user_ip_sources(user, db, [])
    success(f"Restricciones de IP de {user} eliminadas")


@app.command()
def myip():
    """Muestra tu IP pública (y la que ve el servidor, si hay conexión directa)."""
    info(f"IP pública: [bold]{public_ip()}[/]")
    try:
        seen = client_address()
    except MangostaError:
        seen = None
    if seen:
        info(f"El servidor te ve como: [bold]{seen}[/]")
