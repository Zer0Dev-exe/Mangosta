"""Proyectos de Atlas."""

from typing import Annotated, Optional

import typer

from .. import config, services
from ..atlas import require_atlas
from ..errors import MangostaError
from ..output import confirm_typed, emit, success

app = typer.Typer(help="(Atlas) Proyectos: listar, elegir, crear, borrar.", no_args_is_help=True)

AllOrgs = Annotated[bool, typer.Option("--all", "-a", help="De todas las organizaciones (no solo la activa)")]


def find_project(atlas, project: str, org_id: str | None = None) -> dict:
    match = [p for p in services.list_projects(atlas, org_id) if project in (p["id"], p["name"])]
    if not match:
        raise MangostaError(f"No encuentro el proyecto '{project}' (mira: mangosta project list --all)")
    if len(match) > 1:
        raise MangostaError(f"Hay varios proyectos llamados '{project}'; usa el ID")
    return match[0]


def use_project(profile_name: str, project: dict) -> None:
    config.update_atlas(profile_name, project_id=project["id"], org_id=project.get("orgId"), cluster=None)


@app.command("list")
def list_(all_: AllOrgs = False):
    """Lista los proyectos de la organización activa (o de todas con --all)."""
    atlas = require_atlas()
    projects = services.list_projects(atlas, None if all_ else atlas.org_id)
    org_names = {o["id"]: o["name"] for o in services.list_orgs(atlas)} if all_ or not atlas.org_id else {}
    rows = [{
        "active": "●" if p["id"] == atlas.project_id else "",
        "name": p["name"],
        "id": p["id"],
        "clusters": p.get("clusterCount"),
        "org": org_names.get(p.get("orgId"), p.get("orgId")) if org_names else None,
    } for p in projects]
    columns = [("active", ""), ("name", "Proyecto"), ("id", "ID"), ("clusters", "Clusters")]
    if org_names:
        columns.append(("org", "Organización"))
    emit(rows, columns, raw=projects)


@app.command()
def use(project: Annotated[str, typer.Argument(help="ID o nombre del proyecto")]):
    """Fija el proyecto con el que trabajan el resto de comandos."""
    atlas = require_atlas()
    found = find_project(atlas, project)
    use_project(atlas.profile_name, found)
    success(f"Proyecto activo: {found['name']} ({found['id']})")


@app.command()
def create(
    name: Annotated[str, typer.Argument(help="Nombre del proyecto nuevo")],
    org: Annotated[Optional[str], typer.Option("--org", help="Organización (ID o nombre; por defecto la activa)")] = None,
    use: Annotated[bool, typer.Option("--use/--no-use", help="Activarlo al crearlo")] = True,
):
    """Crea un proyecto en una organización."""
    from .org import find_org

    atlas = require_atlas()
    org_id = find_org(atlas, org)["id"] if org else atlas.org_id
    if not org_id:
        raise MangostaError("Indica la organización con --org (o elige una con: mangosta org use NOMBRE)")
    project = services.create_project(atlas, name, org_id)
    success(f"Proyecto '{name}' creado ({project['id']})")
    if use:
        use_project(atlas.profile_name, project)
        success("Proyecto activo")


@app.command()
def delete(project: Annotated[str, typer.Argument(help="ID o nombre del proyecto")]):
    """Borra un proyecto (Atlas exige que no tenga clusters). ¡Irreversible!"""
    atlas = require_atlas()
    found = find_project(atlas, project)
    if found.get("clusterCount"):
        raise MangostaError(f"'{found['name']}' tiene {found['clusterCount']} cluster(s); bórralos antes")
    confirm_typed(f"Vas a BORRAR el proyecto '{found['name']}' con sus usuarios, IPs y configuración.", found["name"])
    services.delete_project(atlas, found["id"])
    if atlas.project_id == found["id"]:
        config.update_atlas(atlas.profile_name, project_id=None, cluster=None)
    success(f"Proyecto '{found['name']}' borrado")
