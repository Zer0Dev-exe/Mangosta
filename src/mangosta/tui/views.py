"""Qué muestra cada pestaña de la TUI: columnas, filas y detalle.

Son funciones puras (datos -> filas), sin widgets, para poder probarlas sin
arrancar la interfaz.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from bson import ObjectId, json_util
from rich.text import Text

from .. import services
from ..parsing import format_role

# Paleta de MongoDB (Leafygreen).
GREEN = "#00ED64"
FOREST = "#00684A"
BLUE = "#016BF8"
SKY = "#5EB6FF"
AMBER = "#FFC010"
RED = "#FF6F44"
VIOLET = "#B45AF2"
MUTED = "#889397"
INK = "#001E2B"
TABLE_BG = "#001E2B"


def _blend(color: str, base: str = TABLE_BG, amount: float = 0.24) -> str:
    a = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(base[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * amount + y * (1 - amount)):02x}" for x, y in zip(a, b))


def pill(text: str, color: str) -> Text:
    return Text(f" {text} ", style=f"bold {color} on {_blend(color)}")


def pills(items: list[tuple[str, str]]) -> Text:
    out = Text()
    for i, (label, color) in enumerate(items):
        if i:
            out.append(" ")
        out.append_text(pill(label, color))
    return out


def dim(text: str | None) -> Text:
    return Text(text or "—", style=MUTED)


def short_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


# --- Contexto y estructura -------------------------------------------------------------------


@dataclass(frozen=True)
class Ctx:
    """Qué está seleccionado en el árbol lateral."""

    kind: str  # empty | atlas-profile | direct-profile | org | project
    profile: str | None = None
    org_id: str | None = None
    org_name: str | None = None
    project_id: str | None = None
    project_name: str | None = None

    @property
    def is_atlas(self) -> bool:
        return self.kind in ("atlas-profile", "org", "project")

    def label(self) -> str:
        if self.kind == "project":
            return f"{self.org_name} › {self.project_name}"
        if self.kind == "org":
            return self.org_name or ""
        return self.profile or ""


@dataclass
class Row:
    key: str
    cells: tuple
    detail: Any = None  # lista de (etiqueta, valor) o un renderable de Rich
    obj: Any = None
    search: str = ""


TABS: dict[str, str] = {
    "clusters": "Clusters",
    "data": "Datos",
    "dbusers": "Usuarios BD",
    "access": "Acceso IP",
    "members": "Miembros",
    "projects": "Proyectos",
    "orgmembers": "Miembros",
    "orgs": "Organizaciones",
    "conns": "Conexiones",
    "welcome": "Bienvenida",
}

TABS_FOR: dict[str, list[str]] = {
    "project": ["clusters", "data", "dbusers", "access", "members"],
    "org": ["projects", "orgmembers"],
    "atlas-profile": ["orgs"],
    "direct-profile": ["data", "dbusers", "access", "conns"],
    "empty": ["welcome"],
}


def columns(view: str, ctx: Ctx) -> tuple[str, ...]:
    if view == "clusters":
        return ("CLUSTER", "ESTADO", "TIER", "PROVEEDOR", "REGIÓN", "MONGODB", "DATOS")
    if view == "dbusers":
        if ctx.is_atlas:
            return ("USUARIO", "ROLES", "CLUSTERS", "CADUCA")
        return ("USUARIO", "AUTH DB", "ROLES", "IPS PERMITIDAS")
    if view == "access":
        return ("IP / CIDR", "COMENTARIO", "CADUCA") if ctx.is_atlas else ("USUARIO", "IPS PERMITIDAS")
    if view in ("members", "orgmembers"):
        return ("EMAIL", "NOMBRE", "ROLES", "ESTADO")
    if view == "projects":
        return ("PROYECTO", "CLUSTERS", "CREADO", "ID")
    if view == "orgs":
        return ("ORGANIZACIÓN", "ID")
    if view == "conns":
        return ("IP", "USUARIO", "APLICACIÓN", "CONEXIONES", "ACTIVAS")
    return ()


# --- Colores ------------------------------------------------------------------------------------

STATE_COLORS = {
    "IDLE": GREEN, "CREATING": AMBER, "UPDATING": AMBER, "REPAIRING": AMBER,
    "DELETING": RED, "DELETED": MUTED, "PAUSED": SKY,
}
STATE_LABELS = {"IDLE": "activo", "CREATING": "creando", "UPDATING": "actualizando", "REPAIRING": "reparando",
                "DELETING": "borrando", "DELETED": "borrado", "PAUSED": "pausado"}


def db_role_color(role: str) -> str:
    if role in ("atlasAdmin", "root", "dbOwner", "userAdminAnyDatabase", "clusterAdmin"):
        return RED
    if role.startswith("readWrite"):
        return GREEN
    if role.startswith("read"):
        return SKY
    return VIOLET


def atlas_role_color(role: str) -> str:
    if role.endswith("OWNER"):
        return AMBER
    if "READ_ONLY" in role:
        return SKY
    if role.endswith("MEMBER"):
        return MUTED
    return VIOLET


# --- Filas por pestaña ------------------------------------------------------------------------------


def cluster_rows(clusters: list[dict], data_cluster: str | None) -> list[Row]:
    rows = []
    for c in clusters:
        state = c["state"] or "?"
        connected = c["name"] == data_cluster
        rows.append(Row(
            key=c["name"],
            cells=(
                Text(c["name"], style="bold"),
                pill(STATE_LABELS.get(state, state.lower()), STATE_COLORS.get(state, MUTED)),
                c["tier"] or "",
                c["provider"] or "",
                c["region"] or "",
                c["version"] or "",
                Text("● conectado", style=f"bold {GREEN}") if connected else dim("c conectar"),
            ),
            detail=[
                ("Conexión", Text(c["srv"] or "(aún sin cadena de conexión)", style=SKY)),
                ("Tipo", f"{c['type']} · {c['tier']} · {c['provider']} {c['region'] or ''}"),
                ("Backups", "sí" if c["backup"] else "no"),
                ("Protección", "termination protection activada" if c["protected"] else "no"),
            ],
            obj=c,
            search=c["name"],
        ))
    return rows


def db_user_rows(users: list[dict], atlas: bool) -> list[Row]:
    rows = []
    for u in users:
        role_cell = pills([(format_role(r), db_role_color(r["role"])) for r in u["roles"]])
        if atlas:
            cells = (Text(u["user"], style="bold"), role_cell,
                     ", ".join(u["scopes"]) or dim("todos"), short_date(u["expires"]) or dim("nunca"))
        else:
            cells = (Text(u["user"], style="bold"), u["db"], role_cell,
                     ", ".join(u["ips"]) if u["ips"] else dim("cualquiera"))
        detail = [("Roles", services.roles_text(u["roles"]) or "—")]
        if atlas:
            detail.append(("Clusters", ", ".join(u["scopes"]) or "todos los del proyecto"))
            if u["expires"]:
                detail.append(("Caduca", short_date(u["expires"])))
            if u["user"].startswith("mangosta-"):
                detail.append(("Nota", Text("usuario temporal de mangosta para acceder a los datos", style=MUTED)))
        else:
            detail.append(("IPs", ", ".join(u["ips"]) or "cualquiera"))
            detail.append(("Auth DB", u["db"]))
        rows.append(Row(key=f"{u['db']}.{u['user']}", cells=cells, detail=detail, obj=u, search=u["user"]))
    return rows


def access_rows(entries: list[dict]) -> list[Row]:
    rows = []
    for e in entries:
        entry = e["entry"] or "?"
        open_world = entry in ("0.0.0.0/0", "::/0")
        rows.append(Row(
            key=entry,
            cells=(Text(entry, style=f"bold {RED}" if open_world else "bold"), e["comment"] or "",
                   short_date(e["expires"]) or dim("permanente")),
            detail=[("Entrada", entry), ("Comentario", e["comment"] or "—"),
                    ("Aviso", Text("permite conexiones desde CUALQUIER IP", style=f"bold {RED}")) if open_world
                    else ("Caduca", short_date(e["expires"]) or "permanente")],
            obj=e,
            search=f"{entry} {e['comment'] or ''}",
        ))
    return rows


def user_ip_rows(users: list[dict]) -> list[Row]:
    return [Row(
        key=f"{u['db']}.{u['user']}",
        cells=(Text(f"{u['user']}@{u['db']}", style="bold"), ", ".join(u["ips"]) if u["ips"] else dim("cualquiera")),
        detail=[("Usuario", f"{u['user']}@{u['db']}"), ("IPs", ", ".join(u["ips"]) or "cualquiera (sin restricción)")],
        obj=u,
        search=u["user"],
    ) for u in users]


def member_rows(members: list[dict]) -> list[Row]:
    rows = []
    for m in members:
        invited = m["status"] == "invitado"
        rows.append(Row(
            key=m["email"] or m["id"],
            cells=(Text(m["email"] or "?", style="bold"), m["name"],
                   pills([(services.friendly_role(r), atlas_role_color(r)) for r in m["roles"]]),
                   pill("invitado", AMBER) if invited else pill("activo", GREEN)),
            detail=[("Email", m["email"] or "?"), ("Roles", ", ".join(services.friendly_role(r) for r in m["roles"]) or "—"),
                    ("Último acceso", short_date(m["last_auth"]) or ("pendiente de aceptar" if invited else "—"))],
            obj=m,
            search=f"{m['email']} {m['name']}",
        ))
    return rows


def project_rows(projects: list[dict]) -> list[Row]:
    return [Row(
        key=p["id"],
        cells=(Text(p["name"], style="bold"), str(p.get("clusterCount", 0)), short_date(p.get("created")), dim(p["id"])),
        detail=[("Proyecto", p["name"]), ("ID", p["id"]), ("Creado", short_date(p.get("created")))],
        obj=p,
        search=p["name"],
    ) for p in projects]


def org_rows(orgs: list[dict]) -> list[Row]:
    return [Row(key=o["id"], cells=(Text(o["name"], style="bold"), dim(o["id"])),
                detail=[("Organización", o["name"]), ("ID", o["id"])], obj=o, search=o["name"]) for o in orgs]


def connection_rows(ops: list[dict]) -> list[Row]:
    groups: dict[tuple, dict] = {}
    for op in ops:
        if not op.get("client"):
            continue
        ip = op["client"].rsplit(":", 1)[0]
        users = ", ".join(f"{u['user']}@{u['db']}" for u in op.get("effectiveUsers", [])) or "(sin autenticar)"
        g = groups.setdefault((ip, users, op.get("appName", "")), {"n": 0, "active": 0})
        g["n"] += 1
        g["active"] += 1 if op.get("active") else 0
    ordered = sorted(groups.items(), key=lambda kv: -kv[1]["n"])
    return [Row(key=f"{ip}|{users}|{app}", cells=(Text(ip, style="bold"), users, app or dim("—"), str(g["n"]), str(g["active"])),
                detail=[("IP", ip), ("Usuario", users), ("Aplicación", app or "—")], search=f"{ip} {users} {app}")
            for (ip, users, app), g in ordered]


# --- Documentos --------------------------------------------------------------------------------------

MAX_DOC_COLUMNS = 7
CELL_WIDTH = 32


def _cell_value(value) -> Text:
    if isinstance(value, ObjectId):
        return Text(str(value), style=MUTED)
    if isinstance(value, bool):
        return Text("true" if value else "false", style=VIOLET)
    if isinstance(value, (int, float)):
        return Text(str(value), style=SKY)
    if isinstance(value, datetime):
        return Text(value.strftime("%Y-%m-%d %H:%M"), style=AMBER)
    if value is None:
        return Text("null", style=MUTED)
    if isinstance(value, (dict, list)):
        text = json_util.dumps(value, json_options=json_util.RELAXED_JSON_OPTIONS, ensure_ascii=False)
        style = MUTED
    else:
        text, style = str(value), ""
    text = text.replace("\n", "⏎")
    return Text(text if len(text) <= CELL_WIDTH else text[: CELL_WIDTH - 1] + "…", style=style)


def doc_columns(docs: list[dict]) -> list[str]:
    counts: dict[str, int] = {}
    for d in docs:
        for k in d:
            counts[k] = counts.get(k, 0) + 1
    keys = sorted(counts, key=lambda k: (k != "_id", -counts[k]))
    return keys[:MAX_DOC_COLUMNS]


def doc_to_json(doc: dict) -> str:
    return json_util.dumps(doc, json_options=json_util.RELAXED_JSON_OPTIONS, indent=2, ensure_ascii=False)


def doc_rows(docs: list[dict], keys: list[str]) -> list[Row]:
    from rich.json import JSON

    rows = []
    for i, d in enumerate(docs):
        text = doc_to_json(d)
        rows.append(Row(
            key=str(i),
            cells=tuple(_cell_value(d[k]) if k in d else Text("") for k in keys),
            detail=JSON(text),
            obj=d,
            search=text,
        ))
    return rows
