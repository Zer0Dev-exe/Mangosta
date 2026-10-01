"""Personas con acceso al proyecto de Atlas (Project Access Manager)."""

from enum import Enum
from typing import Annotated

import typer

from .. import services
from ..atlas import require_atlas
from ..output import confirm_typed, emit, success

app = typer.Typer(help="(Atlas) Gente con acceso al proyecto: listar, invitar, cambiar rol, quitar.", no_args_is_help=True)

ProjectRole = Enum("ProjectRole", {k: k for k in services.PROJECT_ROLES}, type=str)

Email = Annotated[str, typer.Argument(help="Email de la persona")]
Roles = Annotated[list[ProjectRole], typer.Option("--role", "-r", help="Rol en el proyecto (repetible)", case_sensitive=False)]

COLUMNS = [("email", "Email"), ("name", "Nombre"), ("roles", "Roles"), ("status", "Estado")]


def _api_roles(roles: list) -> list[str]:
    return [services.PROJECT_ROLES[r.value] for r in roles]


def emit_members(members: list[dict]) -> None:
    rows = [m | {"roles": [services.friendly_role(r) for r in m["roles"]]} for m in members]
    emit(rows, COLUMNS, raw=[m["raw"] for m in members])


@app.command("list")
def list_():
    """Lista las personas con acceso al proyecto y las invitaciones pendientes."""
    emit_members(services.project_members(require_atlas()))


@app.command()
def invite(email: Email, role: Roles):
    """Invita a una persona al proyecto."""
    services.invite_project_member(require_atlas(), email, _api_roles(role))
    success(f"Invitación enviada a {email} ({', '.join(r.value for r in role)})")


@app.command("set-roles")
def set_roles(email: Email, role: Roles):
    """Sustituye los roles de un miembro del proyecto."""
    atlas = require_atlas()
    member = services.find_member(services.project_members(atlas), email)
    services.set_project_member_roles(atlas, member, _api_roles(role))
    success(f"Roles de {email}: {', '.join(r.value for r in role)}")


@app.command()
def remove(email: Email):
    """Quita a una persona del proyecto (o cancela su invitación)."""
    atlas = require_atlas()
    member = services.find_member(services.project_members(atlas), email)
    confirm_typed(f"{email} perderá el acceso al proyecto.", email)
    services.remove_project_member(atlas, member)
    success(f"{email} eliminado del proyecto")
