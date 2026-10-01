"""La TUI de punta a punta con una Atlas simulada (sin red)."""

import asyncio
import time

import pytest
from textual.widgets import Tree

from mangosta import config, mongo, services
from mangosta.state import state
from mangosta.tui import app as tui_app
from mangosta.tui.app import MangostaApp
from mangosta.tui.screens import FormScreen
from mangosta.tui.views import Ctx

ORGS = [{"id": "o1", "name": "Mi Org"}, {"id": "o2", "name": "Vacía"}]
PROJECTS = {"o1": [{"id": "p1", "name": "Backend", "clusterCount": 1, "orgId": "o1"}], "o2": []}
CLUSTER = {"name": "C0", "state": "IDLE", "tier": "M0", "provider": "AWS", "region": "EU_WEST_1", "version": "8.0",
           "type": "REPLICASET", "backup": False, "protected": False, "srv": "mongodb+srv://c0.x.net", "raw": {}}


@pytest.fixture
def fake_atlas(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGOSTA_HOME", str(tmp_path))
    monkeypatch.setattr(mongo, "_client", None)
    monkeypatch.setattr(state, "profile", None)
    config.save({"current": "atlas", "profiles": {"atlas": {"atlas": {
        "auth": "oauth", "access_token": "t", "refresh_token": "r", "expires_at": time.time() + 3600,
        "account": "yo@x.com", "org_id": "o1", "project_id": "p1"}}}})
    added = []
    monkeypatch.setattr(services, "list_orgs", lambda atlas: ORGS)
    monkeypatch.setattr(services, "list_projects", lambda atlas, org_id=None: PROJECTS[org_id])
    monkeypatch.setattr(services, "list_clusters", lambda atlas: [CLUSTER])
    monkeypatch.setattr(services, "list_access", lambda atlas: [{"entry": "1.2.3.4", "comment": "casa", "expires": None, "raw": {}}])
    monkeypatch.setattr(services, "add_access", lambda atlas, kind, value, comment=None, expires=None: added.append((atlas.project_id, kind, value, comment)))
    return added


async def settle(app, pilot, rounds=6):
    for _ in range(rounds):
        await app.workers.wait_for_complete()
        await pilot.pause(0.05)


def test_navigation_and_add_ip(fake_atlas):
    async def scenario():
        app = MangostaApp()
        async with app.run_test(size=(160, 44)) as pilot:
            await settle(app, pilot)
            # Abre directamente el proyecto guardado en el perfil, en la pestaña Clusters.
            assert app.ctx == Ctx("project", "atlas", "o1", "Mi Org", "p1", "Backend")
            assert app.view == "clusters"
            assert [r.key for r in app.rows["clusters"]] == ["C0"]

            nav = app.query_one("#nav", Tree)
            labels = [str(n.label) for n in nav.root.children[0].children]
            assert labels == ["▣ Mi Org", "▣ Vacía"]
            assert str(nav.root.children[0].children[1].children[0].label) == "(sin proyectos)"

            await pilot.press("4")  # Acceso IP
            await settle(app, pilot)
            assert app.view == "access"
            await pilot.press("n")
            await settle(app, pilot)
            assert isinstance(app.screen, FormScreen)
            app.screen.query_one("#f-entry").value = "10.0.0.0/24"
            app.screen.query_one("#f-comment").value = "oficina"
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            assert fake_atlas == [("p1", "cidrBlock", "10.0.0.0/24", "oficina")]

            # Las acciones que no tocan en esta pestaña no se ofrecen.
            assert app.check_action("pause", ()) is False
            assert app.check_action("my_ip", ()) is True

    asyncio.run(scenario())


def test_selecting_org_shows_org_tabs_and_persists_context(fake_atlas, monkeypatch):
    monkeypatch.setattr(services, "org_members", lambda atlas, org_id: [])

    async def scenario():
        app = MangostaApp()
        async with app.run_test(size=(160, 44)) as pilot:
            await settle(app, pilot)
            nav = app.query_one("#nav", Tree)
            org_node = nav.root.children[0].children[0]
            nav.focus()
            nav.move_cursor(org_node)
            await settle(app, pilot)
            assert app.ctx.kind == "org"
            assert app.view == "projects"
            assert [r.key for r in app.rows["projects"]] == ["p1"]
            assert config.load()["profiles"]["atlas"]["atlas"]["org_id"] == "o1"

    asyncio.run(scenario())


def test_welcome_without_profiles(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGOSTA_HOME", str(tmp_path))

    async def scenario():
        app = MangostaApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await settle(app, pilot)
            assert app.ctx.kind == "empty"
            assert app.view == "welcome"
            assert app.check_action("login", ()) is True
            assert app.check_action("new", ()) is False

    asyncio.run(scenario())


def test_split_helper():
    assert tui_app._split(" a, b ,,c ") == ["a", "b", "c"]
