"""Operaciones compartidas por la CLI y la TUI.

Aquí no hay entrada/salida: ni prompts, ni prints. Cada función recibe un
``Atlas`` (o ``None`` para trabajar directamente contra el servidor con PyMongo)
y devuelve datos normalizados. Las confirmaciones y la presentación las pone
quien llama.
"""

from datetime import datetime

from .atlas import CLUSTERS_API_VERSION, Atlas
from .errors import MangostaError
from .mongo import client, find_user, list_users, user_ip_sources
from .parsing import atlas_datetime, format_role, role_from_atlas, role_key, role_to_atlas

# Roles de Atlas con nombre amigable (lo que se escribe en la CLI) -> nombre de la API.
ORG_ROLES = {
    "owner": "ORG_OWNER",
    "project_creator": "ORG_GROUP_CREATOR",
    "billing_admin": "ORG_BILLING_ADMIN",
    "billing_read_only": "ORG_BILLING_READ_ONLY",
    "read_only": "ORG_READ_ONLY",
    "member": "ORG_MEMBER",
}
PROJECT_ROLES = {
    "owner": "GROUP_OWNER",
    "cluster_manager": "GROUP_CLUSTER_MANAGER",
    "data_access_admin": "GROUP_DATA_ACCESS_ADMIN",
    "data_access_read_write": "GROUP_DATA_ACCESS_READ_WRITE",
    "data_access_read_only": "GROUP_DATA_ACCESS_READ_ONLY",
    "read_only": "GROUP_READ_ONLY",
    "search_index_editor": "GROUP_SEARCH_INDEX_EDITOR",
}


def friendly_role(api_name: str) -> str:
    for table in (ORG_ROLES, PROJECT_ROLES):
        for friendly, api in table.items():
            if api == api_name:
                return friendly
    return api_name


# --- Organizaciones -----------------------------------------------------------------------


def list_orgs(atlas: Atlas) -> list[dict]:
    return [o for o in atlas.get_all("/orgs") if not o.get("isDeleted")]


def list_projects(atlas: Atlas, org_id: str | None = None) -> list[dict]:
    return atlas.get_all(f"/orgs/{org_id}/groups" if org_id else "/groups")


def create_project(atlas: Atlas, name: str, org_id: str) -> dict:
    return atlas.request("POST", "/groups", json={"name": name, "orgId": org_id})


def delete_project(atlas: Atlas, project_id: str) -> None:
    atlas.request("DELETE", f"/groups/{project_id}")


def _roles_for(user: dict, *, org_id: str | None = None, project_id: str | None = None) -> list[str]:
    roles = user.get("roles", [])
    if roles and isinstance(roles[0], str):
        return roles
    if org_id:
        return [r["roleName"] for r in roles if r.get("orgId") == org_id]
    return [r["roleName"] for r in roles if r.get("groupId") == project_id]


def _member(user: dict, roles: list[str]) -> dict:
    return {
        "id": user.get("id"),
        "email": user.get("username") or user.get("emailAddress"),
        "name": f"{user.get('firstName', '')} {user.get('lastName', '')}".strip(),
        "roles": roles,
        "status": "activo",
        "last_auth": user.get("lastAuth"),
        "raw": user,
    }


def _invite(invite: dict) -> dict:
    return {
        "id": invite.get("id"),
        "email": invite.get("username"),
        "name": "",
        "roles": invite.get("roles", []),
        "status": "invitado",
        "last_auth": None,
        "raw": invite,
    }


def _pending_invites(atlas: Atlas, path: str) -> list[dict]:
    try:
        invites = atlas.request("GET", path) or []
    except MangostaError:
        return []
    return invites.get("results", []) if isinstance(invites, dict) else invites


def org_members(atlas: Atlas, org_id: str) -> list[dict]:
    users = atlas.get_all(f"/orgs/{org_id}/users")
    members = [_member(u, _roles_for(u, org_id=org_id)) for u in users]
    return members + [_invite(i) for i in _pending_invites(atlas, f"/orgs/{org_id}/invites")]


def invite_org_member(atlas: Atlas, org_id: str, email: str, roles: list[str]) -> None:
    atlas.request("POST", f"/orgs/{org_id}/invites", json={"username": email, "roles": roles})


def remove_org_member(atlas: Atlas, org_id: str, member: dict) -> None:
    if member["status"] == "invitado":
        atlas.request("DELETE", f"/orgs/{org_id}/invites/{member['id']}")
    else:
        atlas.request("DELETE", f"/orgs/{org_id}/users/{member['id']}")


# --- Miembros del proyecto -----------------------------------------------------------------


def project_members(atlas: Atlas) -> list[dict]:
    users = atlas.get_all(atlas.group("/users"))
    members = [_member(u, _roles_for(u, project_id=atlas.project_id)) for u in users]
    return members + [_invite(i) for i in _pending_invites(atlas, atlas.group("/invites"))]


def find_member(members: list[dict], email: str) -> dict:
    for m in members:
        if (m["email"] or "").lower() == email.lower():
            return m
    raise MangostaError(f"{email} no es miembro (ni está invitado)")


def invite_project_member(atlas: Atlas, email: str, roles: list[str]) -> None:
    atlas.request("POST", atlas.group("/invites"), json={"username": email, "roles": roles})


def set_project_member_roles(atlas: Atlas, member: dict, roles: list[str]) -> None:
    atlas.request("PUT", atlas.group(f"/users/{member['id']}/roles"), json={"groupRoles": roles})


def remove_project_member(atlas: Atlas, member: dict) -> None:
    if member["status"] == "invitado":
        atlas.request("DELETE", atlas.group(f"/invites/{member['id']}"))
    else:
        atlas.request("DELETE", atlas.group(f"/users/{member['id']}"))


# --- Clusters ---------------------------------------------------------------------------------


def _cluster_path(atlas: Atlas, name: str = "") -> str:
    return atlas.group(f"/clusters/{atlas.seg(name)}" if name else "/clusters")


def cluster_summary(c: dict) -> dict:
    regions = [rc for spec in c.get("replicationSpecs", []) for rc in spec.get("regionConfigs", [])]
    first = regions[0] if regions else {}
    provider = first.get("backingProviderName") or first.get("providerName")
    conn = c.get("connectionStrings") or {}
    return {
        "name": c["name"],
        "state": "PAUSED" if c.get("paused") else c.get("stateName"),
        "tier": (first.get("electableSpecs") or {}).get("instanceSize"),
        "provider": provider,
        "region": first.get("regionName"),
        "version": c.get("mongoDBVersion"),
        "type": c.get("clusterType"),
        "backup": c.get("backupEnabled"),
        "protected": c.get("terminationProtectionEnabled"),
        "srv": conn.get("standardSrv"),
        "raw": c,
    }


def list_clusters(atlas: Atlas) -> list[dict]:
    return [cluster_summary(c) for c in atlas.get_all(_cluster_path(atlas), version=CLUSTERS_API_VERSION)]


def get_cluster(atlas: Atlas, name: str) -> dict:
    return atlas.request("GET", _cluster_path(atlas, name), version=CLUSTERS_API_VERSION)


def set_cluster_paused(atlas: Atlas, name: str, paused: bool) -> None:
    atlas.request("PATCH", _cluster_path(atlas, name), json={"paused": paused}, version=CLUSTERS_API_VERSION)


def delete_cluster(atlas: Atlas, name: str) -> None:
    if get_cluster(atlas, name).get("terminationProtectionEnabled"):
        raise MangostaError(f"'{name}' tiene termination protection activada; desactívala antes en Atlas")
    atlas.request("DELETE", _cluster_path(atlas, name), version=CLUSTERS_API_VERSION)


def create_cluster(atlas: Atlas, name: str, tier: str = "M0", provider: str = "AWS", region: str = "EU_WEST_1",
                   version: str | None = None, backup: bool = False) -> None:
    tier, provider = tier.upper(), provider.upper()
    if tier == "M0":
        region_config = {"providerName": "TENANT", "backingProviderName": provider, "regionName": region,
                         "priority": 7, "electableSpecs": {"instanceSize": "M0"}}
    else:
        region_config = {"providerName": provider, "regionName": region, "priority": 7,
                         "electableSpecs": {"instanceSize": tier, "nodeCount": 3}}
    body: dict = {"name": name, "clusterType": "REPLICASET", "replicationSpecs": [{"regionConfigs": [region_config]}]}
    if version:
        body["mongoDBMajorVersion"] = version
    if backup and tier != "M0":
        body["backupEnabled"] = True
    atlas.request("POST", _cluster_path(atlas), json=body, version=CLUSTERS_API_VERSION)


def scale_cluster(atlas: Atlas, name: str, tier: str) -> None:
    specs = get_cluster(atlas, name).get("replicationSpecs", [])
    for spec in specs:
        for rc in spec.get("regionConfigs", []):
            if rc.get("providerName") == "TENANT":
                raise MangostaError("Los clusters M0 no se escalan así; crea uno dedicado (M10+)")
            for key in ("electableSpecs", "readOnlySpecs", "analyticsSpecs"):
                if rc.get(key) and rc[key].get("nodeCount", 1):
                    rc[key]["instanceSize"] = tier.upper()
    atlas.request("PATCH", _cluster_path(atlas, name), json={"replicationSpecs": specs}, version=CLUSTERS_API_VERSION)


# --- Usuarios de base de datos (Atlas o directo) -------------------------------------------------


def _user_path(atlas: Atlas, username: str) -> str:
    return atlas.group(f"/databaseUsers/admin/{atlas.seg(username)}")


def _normalize_atlas_user(u: dict) -> dict:
    return {
        "user": u["username"],
        "db": u.get("databaseName", "admin"),
        "roles": [role_from_atlas(r) for r in u.get("roles", [])],
        "scopes": [s["name"] for s in u.get("scopes", [])],
        "expires": u.get("deleteAfterDate"),
        "ips": [],
        "raw": u,
    }


def _normalize_direct_user(u: dict) -> dict:
    return {
        "user": u["user"],
        "db": u["db"],
        "roles": [{"role": r["role"], "db": r["db"]} for r in u.get("roles", [])],
        "scopes": [],
        "expires": None,
        "ips": user_ip_sources(u),
        "raw": u,
    }


def list_db_users(atlas: Atlas | None, db: str | None = None) -> list[dict]:
    if atlas:
        return [_normalize_atlas_user(u) for u in atlas.get_all(atlas.group("/databaseUsers"))]
    return [_normalize_direct_user(u) for u in list_users(db)]


def get_db_user(atlas: Atlas | None, username: str, db: str = "admin") -> dict:
    if atlas:
        return _normalize_atlas_user(atlas.request("GET", _user_path(atlas, username)))
    return _normalize_direct_user(find_user(username, db))


def create_db_user(atlas: Atlas | None, username: str, password: str, roles: list[dict], *, db: str = "admin",
                   allow_ip: list[str] | None = None, clusters: list[str] | None = None,
                   expires: datetime | None = None) -> None:
    if atlas:
        if allow_ip:
            raise MangostaError("En Atlas el acceso por IP es por proyecto: usa  mangosta access add IP")
        body: dict = {"databaseName": "admin", "username": username, "password": password,
                      "groupId": atlas.project_id, "roles": [role_to_atlas(r) for r in roles]}
        if clusters:
            body["scopes"] = [{"name": c, "type": "CLUSTER"} for c in clusters]
        if expires:
            body["deleteAfterDate"] = atlas_datetime(expires)
        atlas.request("POST", atlas.group("/databaseUsers"), json=body)
        return
    if clusters or expires:
        raise MangostaError("Limitar por cluster y la caducidad solo existen en Atlas")
    if any(r.get("collection") for r in roles):
        raise MangostaError("Los roles a nivel de colección (rol@bd.coleccion) solo existen en Atlas; crea un rol personalizado con  mangosta role create")
    cmd: dict = {"createUser": username, "pwd": password, "roles": roles}
    if allow_ip:
        cmd["authenticationRestrictions"] = [{"clientSource": allow_ip}]
    client()[db].command(cmd)


def delete_db_user(atlas: Atlas | None, username: str, db: str = "admin") -> None:
    if atlas:
        atlas.request("DELETE", _user_path(atlas, username))
    else:
        client()[db].command({"dropUser": username})


def set_db_user_password(atlas: Atlas | None, username: str, password: str, db: str = "admin") -> None:
    if atlas:
        atlas.request("PATCH", _user_path(atlas, username), json={"password": password})
    else:
        client()[db].command({"updateUser": username, "pwd": password})


def set_db_user_roles(atlas: Atlas | None, username: str, roles: list[dict], db: str = "admin") -> None:
    """Sustituye todos los roles del usuario."""
    if not roles and atlas:
        raise MangostaError("En Atlas un usuario debe tener al menos un rol (bórralo si ya no lo necesitas)")
    if atlas:
        atlas.request("PATCH", _user_path(atlas, username), json={"roles": [role_to_atlas(r) for r in roles]})
    else:
        client()[db].command({"updateUser": username, "roles": roles})


def change_db_user_roles(atlas: Atlas | None, username: str, roles: list[dict], db: str = "admin", *, grant: bool) -> None:
    if not atlas:
        command = "grantRolesToUser" if grant else "revokeRolesFromUser"
        client()[db].command({command: username, "roles": roles})
        return
    current = get_db_user(atlas, username)["roles"]
    keys = {role_key(r) for r in roles}
    if grant:
        new = current + [r for r in roles if role_key(r) not in {role_key(c) for c in current}]
    else:
        new = [r for r in current if role_key(r) not in keys]
    set_db_user_roles(atlas, username, new, db)


def roles_text(roles: list[dict]) -> str:
    return ", ".join(format_role(r) for r in roles)


# --- Acceso por IP -----------------------------------------------------------------------------


def list_access(atlas: Atlas) -> list[dict]:
    return [{
        "entry": e.get("cidrBlock") or e.get("ipAddress") or e.get("awsSecurityGroup"),
        "comment": e.get("comment"),
        "expires": e.get("deleteAfterDate"),
        "raw": e,
    } for e in atlas.get_all(atlas.group("/accessList"))]


def add_access(atlas: Atlas, kind: str, value: str, comment: str | None = None, expires: datetime | None = None) -> None:
    body: dict = {kind: value}
    if comment:
        body["comment"] = comment
    if expires:
        body["deleteAfterDate"] = atlas_datetime(expires)
    atlas.request("POST", atlas.group("/accessList"), json=[body])


def remove_access(atlas: Atlas, value: str) -> None:
    atlas.request("DELETE", atlas.group(f"/accessList/{atlas.seg(value)}"))


def set_user_ip_sources(username: str, db: str, sources: list[str]) -> None:
    """(Self-hosted) fija las IPs desde las que puede autenticarse un usuario ([] = cualquiera)."""
    restrictions = [{"clientSource": sources}] if sources else []
    client()[db].command({"updateUser": username, "authenticationRestrictions": restrictions})
