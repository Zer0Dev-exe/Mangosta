"""Usuarios de base de datos (equivalente a "Database Access" de Atlas).

Si el perfil tiene sesión/credenciales de Atlas se usan los endpoints de la
Admin API (en Atlas no se pueden crear usuarios con createUser). Si no, se
gestionan directamente en el servidor con createUser/updateUser/dropUser.
"""

import secrets
from typing import Annotated, Optional

import typer

from .. import services
from ..atlas import atlas_or_none
from ..mongo import authenticated_users, client
from ..output import confirm_typed, console, emit, emit_obj, success, warn
from ..parsing import format_role, parse_expiry, parse_role
from ..state import state

app = typer.Typer(help="Usuarios de BD (Database Access): crear, permisos, contraseñas, borrar.", no_args_is_help=True)

Username = Annotated[str, typer.Argument(help="Nombre de usuario")]
AuthDb = Annotated[str, typer.Option("--db", help="BD de autenticación del usuario (modo directo)")]
Roles = Annotated[list[str], typer.Argument(help="Roles: rol@bd, p.ej. readWrite@tienda read@logs.eventos")]

ROLE_HELP = "Rol rol@bd (repetible). Ej: readWrite@tienda, read@tienda.pedidos, readWriteAnyDatabase@admin, atlasAdmin@admin"


def _row(u: dict, atlas: bool) -> dict:
    row = {"user": u["user"], "auth_db": u["db"], "roles": [format_role(r) for r in u["roles"]]}
    if atlas:
        row |= {"scope": u["scopes"] or "todos los clusters", "expires": u["expires"]}
    else:
        row |= {"ips": u["ips"] or "cualquiera", "mechanisms": u["raw"].get("mechanisms")}
    return row


def _password(password: str | None, generate: bool) -> tuple[str, bool]:
    if generate:
        return secrets.token_urlsafe(18), True
    if password:
        return password, False
    return typer.prompt("Contraseña", hide_input=True, confirmation_prompt="Repite la contraseña"), False


@app.command("list")
def list_(db: Annotated[Optional[str], typer.Option("--db", help="Solo usuarios de esta BD (modo directo)")] = None):
    """Lista los usuarios de base de datos."""
    atlas = atlas_or_none()
    users = services.list_db_users(atlas, db)
    if atlas:
        columns = [("user", "Usuario"), ("auth_db", "Auth DB"), ("roles", "Roles"), ("scope", "Clusters"), ("expires", "Caduca")]
    else:
        columns = [("user", "Usuario"), ("auth_db", "Auth DB"), ("roles", "Roles"), ("ips", "IPs permitidas"), ("mechanisms", "Mecanismos")]
    emit([_row(u, bool(atlas)) for u in users], columns, raw=[u["raw"] for u in users])


@app.command()
def show(username: Username, db: AuthDb = "admin"):
    """Muestra un usuario."""
    atlas = atlas_or_none()
    u = services.get_db_user(atlas, username, db)
    emit_obj(u["raw"] if state.json else _row(u, bool(atlas)), title=f"Usuario {username}")


@app.command()
def create(
    username: Username,
    role: Annotated[list[str], typer.Option("--role", "-r", help=ROLE_HELP)],
    password: Annotated[Optional[str], typer.Option("--password", help="Contraseña (si no, se pide oculta)")] = None,
    generate: Annotated[bool, typer.Option("--generate-password", "-g", help="Generar una contraseña segura")] = False,
    db: AuthDb = "admin",
    allow_ip: Annotated[Optional[list[str]], typer.Option("--allow-ip", help="(Directo) solo permitir login desde esta IP/CIDR (repetible)")] = None,
    cluster: Annotated[Optional[list[str]], typer.Option("--cluster", help="(Atlas) limitar el usuario a este cluster (repetible)")] = None,
    expires: Annotated[Optional[str], typer.Option("--expires", help="(Atlas) usuario temporal: 6h, 7d o fecha ISO")] = None,
):
    """Crea un usuario de base de datos."""
    roles = [parse_role(r, db) for r in role]
    pwd, generated = _password(password, generate)
    services.create_db_user(atlas_or_none(), username, pwd, roles, db=db, allow_ip=allow_ip, clusters=cluster,
                            expires=parse_expiry(expires) if expires else None)
    success(f"Usuario '{username}' creado con roles: {services.roles_text(roles)}")
    if generated:
        console.print(f"[bold]Contraseña generada:[/] [yellow]{pwd}[/]  (guárdala, no se volverá a mostrar)")


@app.command()
def passwd(
    username: Username,
    password: Annotated[Optional[str], typer.Option("--password", help="Nueva contraseña (si no, se pide oculta)")] = None,
    generate: Annotated[bool, typer.Option("--generate-password", "-g", help="Generar una contraseña segura")] = False,
    db: AuthDb = "admin",
):
    """Cambia la contraseña de un usuario."""
    pwd, generated = _password(password, generate)
    services.set_db_user_password(atlas_or_none(), username, pwd, db)
    success(f"Contraseña de '{username}' cambiada")
    if generated:
        console.print(f"[bold]Contraseña generada:[/] [yellow]{pwd}[/]")


def _change_roles(username: str, specs: list[str], db: str, grant: bool) -> None:
    roles = [parse_role(r, db) for r in specs]
    services.change_db_user_roles(atlas_or_none(), username, roles, db, grant=grant)
    success(f"Roles {'concedidos' if grant else 'retirados'} a '{username}': {services.roles_text(roles)}")


@app.command()
def grant(username: Username, roles: Roles, db: AuthDb = "admin"):
    """Concede roles a un usuario."""
    _change_roles(username, roles, db, grant=True)


@app.command()
def revoke(username: Username, roles: Roles, db: AuthDb = "admin"):
    """Retira roles a un usuario."""
    _change_roles(username, roles, db, grant=False)


@app.command()
def delete(username: Username, db: AuthDb = "admin"):
    """Borra un usuario."""
    atlas = atlas_or_none()
    if not atlas and any(u["user"] == username and u["db"] == db for u in authenticated_users()):
        warn("¡Es el usuario con el que estás conectado! Perderás el acceso con este perfil.")
    confirm_typed(f"Vas a BORRAR el usuario '{username}'.", username)
    services.delete_db_user(atlas, username, db)
    success(f"Usuario '{username}' borrado")


@app.command()
def whoami():
    """Con qué usuario y roles estás conectado (conexión directa)."""
    info = client().admin.command({"connectionStatus": 1, "showPrivileges": False})["authInfo"]
    emit_obj({
        "usuarios": [f"{u['user']}@{u['db']}" for u in info.get("authenticatedUsers", [])] or "(sin autenticar)",
        "roles": [format_role(r) for r in info.get("authenticatedUserRoles", [])],
    })
