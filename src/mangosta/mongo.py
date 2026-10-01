"""Conexión directa a MongoDB con PyMongo."""

from pymongo import MongoClient

from .config import get_profile, resolve
from .errors import MangostaError
from .state import state

SYSTEM_DBS = {"admin", "local", "config"}

_client: MongoClient | None = None


def client() -> MongoClient:
    global _client
    if _client is None:
        profile = get_profile()
        uri = resolve(profile.get("uri"))
        if not state.uri:
            from . import connect  # import diferido: connect depende de atlas

            if connect.needs_renewal(profile):
                uri = connect.renew(profile)
        if not uri:
            raise MangostaError(
                f"El perfil '{profile['name']}' no tiene URI de conexión "
                f"(conéctate a un cluster con: mangosta cluster connect, o añádela con: mangosta profile set {profile['name']} --uri ...)"
            )
        _client = MongoClient(uri, serverSelectionTimeoutMS=10_000, appname="mangosta")
    return _client


def database_names() -> list[str]:
    return client().list_database_names()


def require_db(name: str) -> None:
    if name not in database_names():
        raise MangostaError(f"La base de datos '{name}' no existe")


def require_collection(db: str, coll: str) -> None:
    if coll not in client()[db].list_collection_names():
        raise MangostaError(f"La colección '{db}.{coll}' no existe")


def find_user(username: str, db: str) -> dict:
    res = client()[db].command({"usersInfo": {"user": username, "db": db}, "showAuthenticationRestrictions": True})
    if not res["users"]:
        raise MangostaError(f"El usuario '{username}' no existe en la BD '{db}' (usa --db si está en otra)")
    return res["users"][0]


def list_users(db: str | None = None) -> list[dict]:
    """Usuarios (de una BD o de todas) con sus restricciones de IP.

    MongoDB solo devuelve ``authenticationRestrictions`` en consultas exactas,
    así que primero se listan y luego se piden por nombre.
    """
    cmd = {"usersInfo": 1} if db else {"usersInfo": {"forAllDBs": True}}
    users = client()[db or "admin"].command(cmd)["users"]
    if not users:
        return []
    exact = [{"user": u["user"], "db": u["db"]} for u in users]
    return client().admin.command({"usersInfo": exact, "showAuthenticationRestrictions": True})["users"]


def user_ip_sources(user: dict) -> list[str]:
    """IPs/CIDRs de ``authenticationRestrictions.clientSource`` de un usuario."""
    sources: list[str] = []
    for r in user.get("authenticationRestrictions", []):
        restriction = r[0] if isinstance(r, list) else r
        sources += restriction.get("clientSource", [])
    return sources


def client_address() -> str | None:
    """IP con la que el servidor nos ve (útil para no bloquearnos al restringir IPs)."""
    try:
        you = client().admin.command("whatsmyuri")["you"]
    except Exception:
        return None
    host, _, _ = you.rpartition(":")
    return host.strip("[]") or None


def authenticated_users() -> list[dict]:
    try:
        return client().admin.command("connectionStatus")["authInfo"]["authenticatedUsers"]
    except Exception:
        return []
