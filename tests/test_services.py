"""Operaciones de organizaciones, proyectos y miembros contra una Atlas API simulada."""

from datetime import datetime

from mangosta import services
from mangosta.tui import views


class FakeAtlas:
    project_id = "p1"
    org_id = "o1"
    profile_name = "atlas"

    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or {}

    def request(self, method, path, *, json=None, params=None, version=None):
        self.calls.append((method, path, json))
        return self.responses.get((method, path))

    def get_all(self, path, version=None):
        self.calls.append(("GET*", path, None))
        return self.responses.get(("GET*", path), [])

    def group(self, suffix=""):
        return f"/groups/{self.project_id}{suffix}"

    @staticmethod
    def seg(value):
        from urllib.parse import quote
        return quote(value, safe="")


USER = {"id": "u1", "username": "ana@x.com", "firstName": "Ana", "lastName": "Pi",
        "roles": [{"orgId": "o1", "roleName": "ORG_OWNER"}, {"groupId": "p1", "roleName": "GROUP_READ_ONLY"},
                  {"groupId": "otro", "roleName": "GROUP_OWNER"}]}


def test_org_members_includes_pending_invites_and_org_roles_only():
    atlas = FakeAtlas({("GET*", "/orgs/o1/users"): [USER],
                       ("GET", "/orgs/o1/invites"): [{"id": "i1", "username": "luis@x.com", "roles": ["ORG_MEMBER"]}]})
    members = services.org_members(atlas, "o1")
    assert [(m["email"], m["roles"], m["status"]) for m in members] == [
        ("ana@x.com", ["ORG_OWNER"], "activo"), ("luis@x.com", ["ORG_MEMBER"], "invitado")]


def test_project_members_filters_roles_by_project():
    atlas = FakeAtlas({("GET*", "/groups/p1/users"): [USER], ("GET", "/groups/p1/invites"): []})
    assert services.project_members(atlas)[0]["roles"] == ["GROUP_READ_ONLY"]


def test_remove_member_uses_invite_endpoint_for_pending_invites():
    atlas = FakeAtlas()
    services.remove_org_member(atlas, "o1", {"id": "i1", "status": "invitado"})
    services.remove_org_member(atlas, "o1", {"id": "u1", "status": "activo"})
    services.remove_project_member(atlas, {"id": "i2", "status": "invitado"})
    assert [c[:2] for c in atlas.calls] == [
        ("DELETE", "/orgs/o1/invites/i1"), ("DELETE", "/orgs/o1/users/u1"), ("DELETE", "/groups/p1/invites/i2")]


def test_create_project_and_org_invite_bodies():
    atlas = FakeAtlas({("POST", "/groups"): {"id": "p9"}})
    assert services.create_project(atlas, "Nuevo", "o1") == {"id": "p9"}
    services.invite_org_member(atlas, "o1", "eva@x.com", ["ORG_READ_ONLY"])
    assert atlas.calls == [("POST", "/groups", {"name": "Nuevo", "orgId": "o1"}),
                           ("POST", "/orgs/o1/invites", {"username": "eva@x.com", "roles": ["ORG_READ_ONLY"]})]


def test_friendly_roles_roundtrip():
    for table in (services.ORG_ROLES, services.PROJECT_ROLES):
        for friendly, api in table.items():
            assert services.friendly_role(api) == friendly


def test_cluster_summary_and_rows():
    raw = {"name": "C0", "stateName": "IDLE", "mongoDBVersion": "8.0.1", "clusterType": "REPLICASET",
           "connectionStrings": {"standardSrv": "mongodb+srv://c0.x.mongodb.net"},
           "replicationSpecs": [{"regionConfigs": [{"providerName": "TENANT", "backingProviderName": "AWS",
                                                   "regionName": "EU_WEST_1", "electableSpecs": {"instanceSize": "M0"}}]}]}
    c = services.cluster_summary(raw)
    assert (c["tier"], c["provider"], c["region"], c["srv"]) == ("M0", "AWS", "EU_WEST_1", "mongodb+srv://c0.x.mongodb.net")
    rows = views.cluster_rows([c, services.cluster_summary(raw | {"name": "C1", "paused": True})], data_cluster="C0")
    assert rows[0].cells[6].plain == "● conectado"
    assert rows[1].cells[1].plain.strip() == "pausado"


def test_doc_columns_and_cells():
    docs = [{"_id": 1, "a": 1, "b": {"x": 1}}, {"_id": 2, "a": 2, "c": datetime(2026, 1, 2, 3, 4)}]
    keys = views.doc_columns(docs)
    assert keys[0] == "_id" and keys[1] == "a"
    rows = views.doc_rows(docs, keys)
    cells = dict(zip(keys, rows[1].cells))
    assert cells["c"].plain == "2026-01-02 03:04"
    assert cells["b"].plain == ""


def test_connection_rows_groups_by_ip_user_and_app():
    ops = [{"client": "1.2.3.4:5000", "effectiveUsers": [{"user": "app", "db": "admin"}], "appName": "bot", "active": True},
           {"client": "1.2.3.4:5001", "effectiveUsers": [{"user": "app", "db": "admin"}], "appName": "bot"},
           {"desc": "interno"}]
    rows = views.connection_rows(ops)
    assert len(rows) == 1
    assert [c if isinstance(c, str) else c.plain for c in rows[0].cells] == ["1.2.3.4", "app@admin", "bot", "2", "1"]
