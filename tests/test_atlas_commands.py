"""Comprueba que los comandos en modo Atlas envían las peticiones correctas a la Admin API."""

import json

import pytest
from typer.testing import CliRunner

from mangosta import config, mongo
from mangosta.atlas import Atlas
from mangosta.cli import app
from mangosta.state import state

runner = CliRunner()
PROJECT = "64aaaaaaaaaaaaaaaaaaaaaa"


@pytest.fixture
def atlas_calls(tmp_path, monkeypatch):
    """Perfil de Atlas en un HOME temporal y una API falsa que registra las llamadas."""
    monkeypatch.setenv("MANGOSTA_HOME", str(tmp_path))
    config.save({"current": "prod", "profiles": {"prod": {"atlas": {
        "public_key": "pub", "private_key": "priv", "project_id": PROJECT, "cluster": "Cluster0"}}}})
    monkeypatch.setattr(mongo, "_client", None)
    monkeypatch.setattr(state, "yes", False)

    calls: list[tuple] = []
    responses: dict[tuple, object] = {}

    def fake_request(self, method, path, *, json=None, params=None, version="2023-01-01"):
        calls.append((method, path, json))
        return responses.get((method, path), {"results": []})

    monkeypatch.setattr(Atlas, "request", fake_request)
    return calls, responses


def run(*args):
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, (result.output, result.exception)
    return result


def test_user_create(atlas_calls):
    calls, _ = atlas_calls
    run("user", "create", "app", "-r", "readWrite@tienda", "-r", "read@logs.eventos",
        "--password", "x", "--cluster", "Cluster0")
    method, path, body = calls[-1]
    assert (method, path) == ("POST", f"/groups/{PROJECT}/databaseUsers")
    assert body["databaseName"] == "admin"
    assert body["roles"] == [
        {"roleName": "readWrite", "databaseName": "tienda"},
        {"roleName": "read", "databaseName": "logs", "collectionName": "eventos"},
    ]
    assert body["scopes"] == [{"name": "Cluster0", "type": "CLUSTER"}]


def test_user_grant_merges_roles(atlas_calls):
    calls, responses = atlas_calls
    path = f"/groups/{PROJECT}/databaseUsers/admin/app"
    responses[("GET", path)] = {"username": "app", "databaseName": "admin", "roles": [{"roleName": "read", "databaseName": "tienda"}]}
    run("user", "grant", "app", "readWrite@informes", "read@tienda")
    method, patch_path, body = calls[-1]
    assert (method, patch_path) == ("PATCH", path)
    assert body["roles"] == [
        {"roleName": "read", "databaseName": "tienda"},
        {"roleName": "readWrite", "databaseName": "informes"},
    ]


def test_user_revoke_last_role_is_rejected(atlas_calls):
    _, responses = atlas_calls
    responses[("GET", f"/groups/{PROJECT}/databaseUsers/admin/app")] = {"username": "app", "databaseName": "admin", "roles": [{"roleName": "read", "databaseName": "tienda"}]}
    result = runner.invoke(app, ["user", "revoke", "app", "read@tienda"])
    assert result.exit_code != 0
    assert "al menos un rol" in str(result.exception)


def test_access_add_and_remove(atlas_calls):
    calls, _ = atlas_calls
    run("access", "add", "10.0.0.7/24", "--comment", "oficina", "--expires", "6h")
    method, path, body = calls[-1]
    assert (method, path) == ("POST", f"/groups/{PROJECT}/accessList")
    assert body[0]["cidrBlock"] == "10.0.0.0/24"
    assert body[0]["comment"] == "oficina"
    assert body[0]["deleteAfterDate"].endswith("Z")

    run("--yes", "access", "remove", "10.0.0.0/24")
    assert calls[-1][:2] == ("DELETE", f"/groups/{PROJECT}/accessList/10.0.0.0%2F24")


def test_access_rejects_user_flag_in_atlas(atlas_calls):
    result = runner.invoke(app, ["access", "add", "1.2.3.4", "--user", "app"])
    assert result.exit_code != 0


def test_cluster_pause_uses_default_cluster(atlas_calls):
    calls, _ = atlas_calls
    run("cluster", "pause")
    assert calls[-1] == ("PATCH", f"/groups/{PROJECT}/clusters/Cluster0", {"paused": True})


def test_custom_role_create(atlas_calls):
    calls, _ = atlas_calls
    run("role", "create", "lector", "-P", "tienda.pedidos:find,listCollections", "-i", "read@logs")
    method, path, body = calls[-1]
    assert (method, path) == ("POST", f"/groups/{PROJECT}/customDBRoles/roles")
    assert body["actions"] == [
        {"action": "FIND", "resources": [{"db": "tienda", "collection": "pedidos"}]},
        {"action": "LIST_COLLECTIONS", "resources": [{"db": "tienda", "collection": "pedidos"}]},
    ]
    assert body["inheritedRoles"] == [{"role": "read", "db": "logs"}]


def test_members_invite(atlas_calls):
    calls, _ = atlas_calls
    run("members", "invite", "ana@empresa.com", "--role", "read_only")
    assert calls[-1] == ("POST", f"/groups/{PROJECT}/invites", {"username": "ana@empresa.com", "roles": ["GROUP_READ_ONLY"]})


def test_user_list_json(atlas_calls):
    _, responses = atlas_calls
    responses[("GET", f"/groups/{PROJECT}/databaseUsers")] = {
        "results": [{"username": "app", "databaseName": "admin", "roles": []}], "totalCount": 1}
    # get_all llama a request con params; la respuesta falsa ignora la paginación.
    result = run("--json", "user", "list")
    assert json.loads(result.output)[0]["username"] == "app"
