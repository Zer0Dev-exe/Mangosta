"""Conversión de los argumentos de texto de la CLI a estructuras de MongoDB/Atlas."""

import ipaddress
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pymongo
from bson import json_util

from .errors import MangostaError

# --- JSON ---------------------------------------------------------------------


def parse_json(text: str | None, what: str = "JSON", default=None):
    """Parsea Extended JSON. ``@fichero.json`` lee el contenido de un fichero."""
    if text is None:
        return default
    if text.startswith("@"):
        path = Path(text[1:])
        if not path.exists():
            raise MangostaError(f"No existe el fichero {path}")
        text = path.read_text(encoding="utf-8")
    try:
        return json_util.loads(text)
    except ValueError as e:
        raise MangostaError(f"{what} no es JSON válido: {e}") from e


def parse_json_object(text: str | None, what: str, default=None) -> dict | None:
    value = parse_json(text, what, default)
    if value is not None and not isinstance(value, dict):
        raise MangostaError(f"{what} debe ser un objeto JSON {{...}}")
    return value


# --- Roles ----------------------------------------------------------------------


def parse_role(spec: str, default_db: str = "admin") -> dict:
    """``readWrite@tienda`` -> {"role": "readWrite", "db": "tienda"}.

    ``read@tienda.pedidos`` añade ``collection`` (solo Atlas lo soporta).
    Sin ``@`` se usa ``default_db`` (p.ej. ``root`` -> root@admin).
    """
    role, _, scope = spec.strip().partition("@")
    if not role:
        raise MangostaError(f"Rol inválido: '{spec}' (formato: rol@bd, p.ej. readWrite@tienda)")
    db, _, coll = scope.partition(".")
    result = {"role": role, "db": db or default_db}
    if coll:
        result["collection"] = coll
    return result


def format_role(role: dict) -> str:
    text = f"{role['role']}@{role['db']}"
    if role.get("collection"):
        text += f".{role['collection']}"
    return text


def role_to_atlas(role: dict) -> dict:
    out = {"roleName": role["role"], "databaseName": role["db"]}
    if role.get("collection"):
        out["collectionName"] = role["collection"]
    return out


def role_from_atlas(role: dict) -> dict:
    out = {"role": role["roleName"], "db": role["databaseName"]}
    if role.get("collectionName"):
        out["collection"] = role["collectionName"]
    return out


def role_key(role: dict) -> tuple:
    return role["role"], role["db"], role.get("collection") or ""


# --- Privilegios de roles personalizados ------------------------------------------


def parse_privilege(spec: str) -> dict:
    """``tienda.pedidos:find,insert`` -> {"resource": {"db", "collection"}, "actions": [...]}.

    ``tienda:find`` aplica a todas las colecciones de la BD.
    """
    resource, sep, actions = spec.partition(":")
    if not sep or not resource or not actions:
        raise MangostaError(f"Privilegio inválido: '{spec}' (formato: bd[.coleccion]:accion1,accion2)")
    db, _, coll = resource.partition(".")
    return {
        "resource": {"db": db, "collection": coll},
        "actions": [a.strip() for a in actions.split(",") if a.strip()],
    }


def action_to_atlas(action: str) -> str:
    """``listCollections`` -> ``LIST_COLLECTIONS`` (formato de la Atlas API)."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", action).upper()


def action_from_atlas(action: str) -> str:
    first, *rest = action.lower().split("_")
    return first + "".join(word.capitalize() for word in rest)


# --- Red ------------------------------------------------------------------------------


def classify_access_entry(entry: str) -> tuple[str, str]:
    """Devuelve (tipo, valor normalizado) para una entrada de access list de Atlas."""
    entry = entry.strip()
    if entry.startswith("sg-"):
        return "awsSecurityGroup", entry
    try:
        if "/" in entry:
            return "cidrBlock", str(ipaddress.ip_network(entry, strict=False))
        return "ipAddress", str(ipaddress.ip_address(entry))
    except ValueError as e:
        raise MangostaError(f"'{entry}' no es una IP, un CIDR ni un security group de AWS") from e


def ip_allowed(ip: str, sources: list[str]) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for source in sources:
        try:
            if addr in ipaddress.ip_network(source, strict=False):
                return True
        except ValueError:
            continue
    return False


def is_open_to_world(entry: str) -> bool:
    return entry in ("0.0.0.0/0", "::/0")


# --- Tiempo -----------------------------------------------------------------------------

_DURATION = re.compile(r"(\d+)\s*([mhdw])")
_UNITS = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}


def parse_expiry(text: str) -> datetime:
    """``6h``, ``30m``, ``7d``, ``1w`` o una fecha ISO (``2026-12-31`` / ``2026-12-31T18:00``)."""
    match = _DURATION.fullmatch(text.strip().lower())
    if match:
        amount, unit = match.groups()
        return datetime.now(timezone.utc) + timedelta(**{_UNITS[unit]: int(amount)})
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as e:
        raise MangostaError(f"Expiración inválida '{text}' (usa 6h, 7d, 1w o una fecha ISO)") from e
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc)


def atlas_datetime(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# --- Índices -------------------------------------------------------------------------------

_INDEX_TYPES = {
    "1": pymongo.ASCENDING,
    "-1": pymongo.DESCENDING,
    "text": pymongo.TEXT,
    "2dsphere": pymongo.GEOSPHERE,
    "2d": pymongo.GEO2D,
    "hashed": pymongo.HASHED,
}


def parse_index_keys(spec: str) -> list[tuple[str, object]]:
    """``email:1,edad:-1`` o JSON ``{"email": 1}``. Sin tipo se asume ascendente."""
    spec = spec.strip()
    if spec.startswith("{"):
        keys = parse_json_object(spec, "Las claves del índice")
        return list(keys.items())
    keys = []
    for part in spec.split(","):
        field, _, kind = part.strip().partition(":")
        kind = kind.strip() or "1"
        if not field or kind not in _INDEX_TYPES:
            raise MangostaError(f"Clave de índice inválida: '{part}' (tipos: {', '.join(_INDEX_TYPES)})")
        keys.append((field.strip(), _INDEX_TYPES[kind]))
    return keys
