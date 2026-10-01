"""Roles personalizados (Custom Roles en Atlas, createRole en self-hosted)."""

from typing import Annotated, Optional

import typer

from ..atlas import atlas_or_none
from ..errors import MangostaError
from ..mongo import client
from ..output import confirm_typed, emit, success
from ..parsing import action_from_atlas, action_to_atlas, format_role, parse_privilege, parse_role

app = typer.Typer(help="Roles personalizados: listar, crear, borrar.", no_args_is_help=True)

Name = Annotated[str, typer.Argument(help="Nombre del rol")]
RoleDb = Annotated[str, typer.Option("--db", help="(Self-hosted) BD donde vive el rol")]


def _fmt_privilege(resource: dict, actions: list[str]) -> str:
    if resource.get("cluster"):
        target = "cluster"
    else:
        target = (resource.get("db") or "*") + (f".{resource['collection']}" if resource.get("collection") else "")
    return f"{target}:{','.join(actions)}"


@app.command("list")
def list_(
    db: RoleDb = "admin",
    builtin: Annotated[bool, typer.Option("--builtin", help="(Self-hosted) incluir roles predefinidos")] = False,
):
    """Lista los roles personalizados."""
    atlas = atlas_or_none()
    if atlas:
        roles = atlas.request("GET", atlas.group("/customDBRoles/roles")) or []
        rows = [{
            "name": r["roleName"],
            "privileges": [
                _fmt_privilege(res, [action_from_atlas(a["action"])])
                for a in r.get("actions", []) for res in a.get("resources", [])
            ],
            "inherits": [f"{i['role']}@{i['db']}" for i in r.get("inheritedRoles", [])],
        } for r in roles]
        emit(rows, [("name", "Rol"), ("privileges", "Privilegios"), ("inherits", "Hereda de")], raw=roles)
        return
    res = client()[db].command({"rolesInfo": 1, "showPrivileges": True, "showBuiltinRoles": builtin})
    rows = [{
        "name": f"{r['role']}@{r['db']}",
        "builtin": r.get("isBuiltin"),
        "privileges": [_fmt_privilege(p["resource"], p["actions"]) for p in r.get("privileges", [])],
        "inherits": [format_role(i) for i in r.get("roles", [])],
    } for r in res["roles"]]
    emit(rows, [("name", "Rol"), ("builtin", "Predefinido"), ("privileges", "Privilegios"), ("inherits", "Hereda de")], raw=res["roles"])


@app.command()
def create(
    name: Name,
    privilege: Annotated[Optional[list[str]], typer.Option("--privilege", "-P", help="bd[.coleccion]:accion1,accion2 (repetible). Ej: tienda.pedidos:find,insert")] = None,
    inherit: Annotated[Optional[list[str]], typer.Option("--inherit", "-i", help="Heredar de otro rol: rol@bd (repetible)")] = None,
    db: RoleDb = "admin",
):
    """Crea un rol personalizado."""
    privileges = [parse_privilege(p) for p in privilege or []]
    inherits = [parse_role(r, db) for r in inherit or []]
    if not privileges and not inherits:
        raise MangostaError("Indica al menos un --privilege o un --inherit")
    atlas = atlas_or_none()
    if atlas:
        actions: dict[str, list] = {}
        for p in privileges:
            for a in p["actions"]:
                actions.setdefault(action_to_atlas(a), []).append(p["resource"])
        body = {
            "roleName": name,
            "actions": [{"action": a, "resources": res} for a, res in actions.items()],
            "inheritedRoles": inherits,
        }
        atlas.request("POST", atlas.group("/customDBRoles/roles"), json=body)
    else:
        client()[db].command({"createRole": name, "privileges": privileges, "roles": inherits})
    success(f"Rol '{name}' creado")


@app.command()
def drop(name: Name, db: RoleDb = "admin"):
    """Borra un rol personalizado."""
    confirm_typed(f"Vas a borrar el rol '{name}'. Los usuarios que lo tengan perderán esos permisos.", name)
    atlas = atlas_or_none()
    if atlas:
        atlas.request("DELETE", atlas.group(f"/customDBRoles/roles/{atlas.seg(name)}"))
    else:
        client()[db].command({"dropRole": name})
    success(f"Rol '{name}' borrado")
