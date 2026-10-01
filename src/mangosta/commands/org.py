"""Organizaciones de Atlas."""

from enum import Enum
from typing import Annotated, Optional

import typer

from .. import config, services
from ..atlas import Atlas, require_atlas
from ..errors import MangostaError
from ..output import confirm_typed, emit, success
from .members import emit_members

app = typer.Typer(help="(Atlas) Organizaciones: listar, elegir, miembros.", no_args_is_help=True)
members_app = typer.Typer(help="Gente de la organización: listar, invitar, quitar.", no_args_is_help=True)
app.add_typer(members_app, name="members")

OrgRole = Enum("OrgRole", {k: k for k in services.ORG_ROLES}, type=str)
Org = Annotated[Optional[str], typer.Option("--org", help="Organización (ID o nombre; por defecto la activa)")]


def find_org(atlas: Atlas, org: str) -> dict:
    match = [o for o in services.list_orgs(atlas) if org in (o["id"], o["name"])]
    if not match:
        raise MangostaError(f"No encuentro la organización '{org}' (mira: mangosta org list)")
    if len(match) > 1:
        raise MangostaError(f"Hay varias organizaciones llamadas '{org}'; usa el ID")
    return match[0]


def _org_id(atlas: Atlas, org: str | None) -> str:
    if org:
        return find_org(atlas, org)["id"]
    if not atlas.org_id:
        raise MangostaError("No hay organización activa: elige una con  mangosta org use NOMBRE  (o usa --org)")
    return atlas.org_id


@app.command("list")
def list_():
    """Lista tus organizaciones."""
    atlas = require_atlas()
    orgs = services.list_orgs(atlas)
    rows = [{"active": "●" if o["id"] == atlas.org_id else "", "name": o["name"], "id": o["id"]} for o in orgs]
    emit(rows, [("active", ""), ("name", "Organización"), ("id", "ID")], raw=orgs)


@app.command()
def use(org: Annotated[str, typer.Argument(help="ID o nombre de la organización")]):
    """Fija la organización activa (y su primer proyecto si el actual no es de ella)."""
    atlas = require_atlas()
    found = find_org(atlas, org)
    projects = services.list_projects(atlas, found["id"])
    fields: dict = {"org_id": found["id"]}
    if atlas.project_id not in {p["id"] for p in projects}:
        fields |= {"project_id": projects[0]["id"] if len(projects) == 1 else None, "cluster": None}
    config.update_atlas(atlas.profile_name, **fields)
    success(f"Organización activa: {found['name']}")
    if fields.get("project_id"):
        success(f"Proyecto activo: {projects[0]['name']}")
    elif "project_id" in fields:
        success(f"Elige proyecto con: mangosta project use NOMBRE  ({len(projects)} disponibles)")


@members_app.command("list")
def members_list(org: Org = None):
    """Lista los miembros de la organización y las invitaciones pendientes."""
    atlas = require_atlas()
    emit_members(services.org_members(atlas, _org_id(atlas, org)))


@members_app.command()
def invite(
    email: Annotated[str, typer.Argument(help="Email de la persona")],
    role: Annotated[Optional[list[OrgRole]], typer.Option("--role", "-r", help="Rol en la organización (repetible)", case_sensitive=False)] = None,
    org: Org = None,
):
    """Invita a una persona a la organización (por defecto como member)."""
    atlas = require_atlas()
    roles = [services.ORG_ROLES[r.value] for r in role] if role else ["ORG_MEMBER"]
    services.invite_org_member(atlas, _org_id(atlas, org), email, roles)
    success(f"Invitación enviada a {email} ({', '.join(services.friendly_role(r) for r in roles)})")


@members_app.command()
def remove(email: Annotated[str, typer.Argument(help="Email de la persona")], org: Org = None):
    """Quita a una persona de la organización (y de todos sus proyectos)."""
    atlas = require_atlas()
    org_id = _org_id(atlas, org)
    member = services.find_member(services.org_members(atlas, org_id), email)
    confirm_typed(f"{email} perderá el acceso a la organización y a todos sus proyectos.", email)
    services.remove_org_member(atlas, org_id, member)
    success(f"{email} eliminado de la organización")
