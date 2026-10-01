"""Login con cuenta de MongoDB: device flow, renovación de tokens y usuario de BD temporal."""

import time
from datetime import datetime, timedelta, timezone

import pytest
from typer.testing import CliRunner

from mangosta import config, connect, mongo, oauth
from mangosta.atlas import Atlas
from mangosta.cli import app
from mangosta.errors import MangostaError

runner = CliRunner()


class FakeResponse:
    def __init__(self, status: int, body: dict | None = None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._body = body or {}
        self.content = b"x" if body else b""
        self.text = str(body)

    def json(self):
        return self._body


PENDING = FakeResponse(400, {"errorCode": "DEVICE_AUTHORIZATION_PENDING"})
TOKEN = {"access_token": "acc1", "refresh_token": "ref1", "expires_in": 3600}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGOSTA_HOME", str(tmp_path))
    monkeypatch.setattr(mongo, "_client", None)
    return tmp_path


def test_poll_token_waits_while_pending(monkeypatch):
    responses = iter([PENDING, PENDING, FakeResponse(200, TOKEN)])
    monkeypatch.setattr(oauth, "_post", lambda endpoint, data: next(responses))
    token = oauth.poll_token({"device_code": "d", "interval": 1, "expires_in": 60}, sleep=lambda s: None)
    assert token["access_token"] == "acc1"


def test_poll_token_expired(monkeypatch):
    monkeypatch.setattr(oauth, "_post", lambda e, d: FakeResponse(400, {"errorCode": "DEVICE_AUTHORIZATION_EXPIRED"}))
    with pytest.raises(MangostaError, match="caducado"):
        oauth.poll_token({"device_code": "d", "interval": 1, "expires_in": 60}, sleep=lambda s: None)


def test_refresh_with_invalid_token_asks_to_login_again(monkeypatch):
    monkeypatch.setattr(oauth, "_post", lambda e, d: FakeResponse(400, {"errorCode": "INVALID_REFRESH_TOKEN"}))
    with pytest.raises(oauth.SessionExpired):
        oauth.refresh("viejo")


def _login_profile(expires_at: float, **extra) -> dict:
    atlas = {"auth": "oauth", "access_token": "old", "refresh_token": "ref0", "expires_at": expires_at, "project_id": "p1"} | extra
    config.save({"current": "atlas", "profiles": {"atlas": {"atlas": atlas}}})
    return config.get_profile()


def test_expired_access_token_is_refreshed_and_saved(home, monkeypatch):
    profile = _login_profile(time.time() - 10)
    monkeypatch.setattr(oauth, "_post", lambda e, d: FakeResponse(200, {"access_token": "new", "refresh_token": "ref2", "expires_in": 3600}))
    seen = {}

    def fake_session_request(method, url, **kw):
        seen["auth"] = atlas.session.headers["Authorization"]
        return FakeResponse(200, {"name": "Proyecto"})

    atlas = Atlas(profile)
    monkeypatch.setattr(atlas.session, "request", fake_session_request)
    assert atlas.request("GET", atlas.group())["name"] == "Proyecto"
    assert seen["auth"] == "Bearer new"
    saved = config.load()["profiles"]["atlas"]["atlas"]
    assert saved["access_token"] == "new" and saved["refresh_token"] == "ref2"


def test_401_triggers_one_refresh_and_retry(home, monkeypatch):
    profile = _login_profile(time.time() + 3000)
    monkeypatch.setattr(oauth, "_post", lambda e, d: FakeResponse(200, {"access_token": "new", "expires_in": 3600}))
    responses = iter([FakeResponse(401, {"detail": "expired"}), FakeResponse(200, {"ok": 1})])
    atlas = Atlas(profile)
    monkeypatch.setattr(atlas.session, "request", lambda *a, **k: next(responses))
    assert atlas.request("GET", "/groups") == {"ok": 1}


def test_build_uri_escapes_credentials():
    uri = connect.build_uri("mongodb+srv://cluster0.abc.mongodb.net", "mangosta-yo-pc", "a/b+c")
    assert uri == "mongodb+srv://mangosta-yo-pc:a%2Fb%2Bc@cluster0.abc.mongodb.net"


def test_managed_username_is_valid():
    name = connect.managed_username()
    assert name.startswith("mangosta-") and len(name) <= 60
    assert all(ch.isalnum() or ch == "-" for ch in name)


def test_needs_renewal():
    soon = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    later = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    assert connect.needs_renewal({"atlas": {"managed_user": {"expires_at": soon}}})
    assert not connect.needs_renewal({"atlas": {"managed_user": {"expires_at": later}}})
    assert not connect.needs_renewal({"atlas": {}})


def test_connect_creates_temporary_user_and_saves_uri(home, monkeypatch):
    profile = _login_profile(time.time() + 3000)
    calls = []

    def fake_request(self, method, path, *, json=None, params=None, version=None, _retried=False):
        calls.append((method, path, json))
        if path.endswith("/clusters/Cluster0"):
            return {"connectionStrings": {"standardSrv": "mongodb+srv://cluster0.abc.mongodb.net"}}
        if method == "GET" and "/databaseUsers/admin/" in path:
            raise oauth.AtlasError("Atlas respondió HTTP 404 — USER_NOT_FOUND")
        if path.endswith("/status"):
            return {"changeStatus": "APPLIED"}
        return {}

    monkeypatch.setattr(Atlas, "request", fake_request)
    username = connect.connect(Atlas(profile), "Cluster0")
    post = next(c for c in calls if c[0] == "POST")
    assert post[2]["username"] == username
    assert post[2]["scopes"] == [{"name": "Cluster0", "type": "CLUSTER"}]
    assert post[2]["roles"] == [{"roleName": "atlasAdmin", "databaseName": "admin"}]
    assert post[2]["deleteAfterDate"].endswith("Z")
    saved = config.load()["profiles"]["atlas"]
    assert saved["uri"].startswith(f"mongodb+srv://{username}:")
    assert saved["atlas"]["managed_user"]["cluster"] == "Cluster0"


def test_login_command(home, monkeypatch):
    config.save({"current": "atlas", "profiles": {"atlas": {"atlas": {"public_key": "pub", "private_key": "priv"}}}})
    monkeypatch.setattr(oauth, "request_code", lambda cid: {
        "device_code": "d", "user_code": "ABCD1234", "verification_uri": "https://account.mongodb.com/account/connect",
        "interval": 1, "expires_in": 60})
    monkeypatch.setattr(oauth, "poll_token", lambda code, cid: TOKEN)
    monkeypatch.setattr(Atlas, "request", lambda self, m, p, **k: {"results": [
        {"id": "p1", "name": "Uno"}, {"id": "p2", "name": "Dos"}]})
    result = runner.invoke(app, ["login", "--no-browser", "--project", "Dos", "--no-connect"])
    assert result.exit_code == 0, (result.output, result.exception)
    assert "ABCD1234" in result.output
    saved = config.load()["profiles"]["atlas"]["atlas"]
    assert saved["refresh_token"] == "ref1"
    assert saved["project_id"] == "p2"
    assert "public_key" not in saved and "private_key" not in saved
