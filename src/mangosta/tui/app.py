"""Interfaz interactiva (Textual): todo Atlas / MongoDB en una pantalla."""

from __future__ import annotations

import copy
import secrets
import socket
import threading
from collections.abc import Callable
from typing import Any

from rich.markup import escape
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.theme import Theme
from textual.widgets import DataTable, Footer, Input, Static, TabbedContent, TabPane, TextArea, Tree

from .. import __version__, art, config, connect, mongo, oauth, services
from ..atlas import Atlas
from ..commands.access import public_ip
from ..errors import MangostaError, describe_error
from ..mongo import SYSTEM_DBS
from ..parsing import classify_access_entry, ip_allowed, is_open_to_world, parse_expiry, parse_json_object, parse_role
from ..state import state
from . import views
from .screens import AboutScreen, ConfirmScreen, Field, FormScreen, LoginScreen, SecretScreen, TypedConfirmScreen
from .views import AMBER, GREEN, INK, MUTED, SKY, Ctx, Row

DOC_LIMIT = 100

SURFACE = "#04242F"  # fondo de la barra lateral y los diálogos
BACKGROUND = "#001E2B"

THEME = Theme(
    name="mangosta",
    primary=views.GREEN,
    secondary=views.FOREST,
    accent=views.SKY,
    success=views.GREEN,
    warning=views.AMBER,
    error=views.RED,
    foreground="#E8EDEB",
    background=BACKGROUND,
    surface=SURFACE,
    panel="#0B3240",
    dark=True,
)

CSS = """
Screen { background: $background; }

/* ------------------------------------------------------------ cabecera */
#top { height: 3; padding: 1 2; background: $panel; }
#brand { width: 1fr; }
#conn { width: auto; }

/* ------------------------------------------------------ barra lateral */
#main { height: 1fr; }
#sidebar { width: 36; background: $surface; padding: 1 1 0 1; }
.section-title { height: 1; padding: 0 1; color: $text-muted; text-style: bold; }
Tree { background: transparent; padding: 0; scrollbar-size-vertical: 1; }
#nav { margin-top: 1; overflow-x: hidden; height: 1fr; }
#side-logo { height: auto; padding: 1 0; content-align: center middle; }
Tree > .tree--guides { color: $panel-lighten-2; }
Tree > .tree--guides-selected, Tree > .tree--guides-hover { color: $primary; }
Tree > .tree--cursor { background: $primary 20%; color: $text; text-style: none; }
Tree:focus > .tree--cursor { background: $primary 35%; text-style: bold; }
Tree > .tree--highlight-line { background: $boost; }

/* ------------------------------------------------------ zona principal */
#right { width: 1fr; padding: 1 2 0 2; }
#search { border: round $panel-lighten-2; background: transparent; padding: 0 1; }
#search:focus { border: round $primary; background: transparent; }
#search > .input--placeholder { color: $text-muted; }

#tabs { height: 1fr; margin-top: 1; }
#tabs Tabs { background: transparent; }
#tabs Tab { color: $text-muted; }
#tabs Tab.-active { color: $primary; text-style: bold; }
#tabs Underline > .underline--bar { color: $primary; background: $panel; }
TabPane { padding: 0; }

.card { border: round $panel-lighten-2; background: transparent; padding: 0 1;
        border-title-color: $foreground; border-title-style: bold;
        border-subtitle-color: $text-muted; }
.card:focus-within { border: round $primary 70%; border-title-color: $primary; }
.table-card { height: 1fr; margin-top: 1; }
DataTable { height: 1fr; background: transparent; scrollbar-size-vertical: 1; }
DataTable > .datatable--header { background: $panel; color: $text-muted; text-style: bold; }
DataTable > .datatable--even-row { background: $boost; }
DataTable > .datatable--hover { background: $primary 10%; }
DataTable > .datatable--cursor { background: $primary 20%; color: $text; text-style: none; }
DataTable:focus > .datatable--cursor { background: $primary 35%; text-style: bold; }

#data-split { height: 1fr; }
#data-nav-card { width: 34; height: 1fr; margin-top: 1; margin-right: 1; }

#detail-card { height: auto; min-height: 5; max-height: 16; margin: 1 0; }
#detail-scroll { height: auto; max-height: 14; }
#detail { height: auto; padding: 0 1; }
.welcome { padding: 1 4; }
.about { width: 84; }

/* --------------------------------------------------------------- pie */
Footer { background: $panel; }
Footer FooterKey .footer-key--key { color: $primary; background: transparent; text-style: bold; }
Footer FooterKey .footer-key--description { color: $text-muted; }

/* ----------------------------------------------------------- diálogos */
ModalScreen { align: center middle; background: $background 70%; }
.dialog { width: 76; height: auto; max-height: 90%; padding: 1 2; background: $surface; border: round $primary;
          border-title-color: $primary; border-title-style: bold; border-subtitle-color: $text-muted; }
.dialog.wide { width: 110; }
.dialog.danger { width: 64; border: round $error; border-title-color: $error; }
.dialog Label { color: $text-muted; margin-top: 1; }
.dialog Input { border: round $panel-lighten-2; background: transparent; }
.dialog Input:focus { border: round $primary; background: transparent; }
.dialog Select { margin: 0; }
.dialog Checkbox { background: transparent; border: none; padding: 0; margin-top: 1; }
.dialog TextArea.json { height: 18; border: round $panel-lighten-2; }
.dialog TextArea.json:focus { border: round $primary; }
.dialog LoadingIndicator { height: 3; color: $primary; }
.dialog-buttons { height: auto; margin-top: 1; align-horizontal: right; }
.dialog-buttons Button { margin-left: 2; min-width: 12; }
.help-text { color: $text-muted; height: auto; }
.error-text { color: $error; height: auto; }
.login-code { text-align: center; padding: 1 0; }
"""

WELCOME = f"""Gestiona MongoDB Atlas y tus servidores como desde el panel web:
organizaciones, proyectos, clusters, datos, usuarios, IPs y miembros.

  [b {GREEN}]l[/]   Iniciar sesión con tu cuenta de MongoDB
  [b {GREEN}]q[/]   Salir

[{MUTED}]¿Servidor propio? Añádelo desde la terminal:
  mangosta profile add local --uri "mongodb://usuario:pass@host:27017"[/]
"""

# Qué acciones tienen sentido en cada pestaña (el resto se ocultan del pie).
AVAILABLE = {
    "new": {"clusters", "dbusers", "access", "members", "orgmembers", "projects", "data"},
    "edit": {"dbusers", "members", "data"},
    "password": {"dbusers"},
    "my_ip": {"access"},
    "connect": {"clusters"},
    "pause": {"clusters"},
    "filter": {"data"},
    "copy": {"clusters", "dbusers", "access", "members", "orgmembers", "projects", "orgs", "data"},
    "delete": {"clusters", "dbusers", "access", "members", "orgmembers", "projects", "data"},
}
LETTER_ACTIONS = set(AVAILABLE) | {"refresh", "login", "quit", "focus_search", "tab", "about"}


class MangostaApp(App[None]):
    TITLE = "mangosta"
    CSS = CSS

    BINDINGS = [
        Binding("slash", "focus_search", "Buscar"),
        Binding("n", "new", "Nuevo"),
        Binding("e", "edit", "Editar"),
        Binding("k", "password", "Contraseña"),
        Binding("m", "my_ip", "Mi IP"),
        Binding("c", "connect", "Conectar datos"),
        Binding("p", "pause", "Pausar/Reanudar"),
        Binding("f", "filter", "Filtrar"),
        Binding("y", "copy", "Copiar"),
        Binding("x,delete", "delete", "Borrar"),
        Binding("r", "refresh", "Refrescar"),
        Binding("l", "login", "Login"),
        Binding("question_mark", "about", "Acerca de", show=False),
        Binding("escape", "clear_search", "Limpiar", show=False),
        *[Binding(str(i), f"tab({i})", f"Pestaña {i}", show=False) for i in range(1, 6)],
        Binding("q", "quit", "Salir"),
    ]

    def __init__(self):
        super().__init__()
        self.register_theme(THEME)
        self.theme = THEME.name
        self.ctx = Ctx("empty")
        self.ctx_version = 0
        self.view = "welcome"
        self.rows: dict[str, list[Row]] = {}
        self.shown: dict[str, list[Row]] = {}
        self.search_text = ""
        self.atlas_cache: dict[str, Atlas] = {}
        self.doc_keys: list[str] = []
        self.doc_filter: dict = {}
        self.doc_total: int | None = None
        self.data_coll: tuple[str, str] | None = None
        self.data_tree_key: tuple | None = None
        self.tabs_ready = False
        self.errors: dict[str, str] = {}

    # ----------------------------------------------------------------- layout
    def compose(self) -> ComposeResult:
        with Horizontal(id="top"):
            yield Static("", id="brand")
            yield Static("", id="conn")
        with Horizontal(id="main"):
            with Vertical(id="sidebar"):
                yield Static("CONEXIONES", classes="section-title")
                yield Tree("mangosta", id="nav")
                yield Static(self.side_logo(), id="side-logo")
            with Vertical(id="right"):
                yield Input(placeholder="⌕  Buscar en la tabla   /", id="search")
                with TabbedContent(id="tabs"):
                    for view, title in views.TABS.items():
                        with TabPane(title, id=view):
                            if view == "welcome":
                                welcome = art.banner(60, BACKGROUND)
                                welcome.append("\n\n")
                                welcome.append_text(Text.from_markup(WELCOME, justify="left"))
                                yield Static(welcome, classes="welcome")
                            elif view == "data":
                                with Horizontal(id="data-split"):
                                    with Vertical(id="data-nav-card", classes="card"):
                                        yield Tree("datos", id="data-tree")
                                    with Vertical(id="t-data-card", classes="card table-card"):
                                        yield DataTable(id="t-data", cursor_type="row", zebra_stripes=True)
                            else:
                                with Vertical(id=f"t-{view}-card", classes="card table-card"):
                                    yield DataTable(id=f"t-{view}", cursor_type="row", zebra_stripes=True)
                with Vertical(id="detail-card", classes="card"):
                    with VerticalScroll(id="detail-scroll"):
                        yield Static("", id="detail")
        yield Footer()

    def on_mount(self) -> None:
        state.notifier = self.notify_any
        for tree_id in ("#nav", "#data-tree"):
            tree = self.query_one(tree_id, Tree)
            tree.show_root = False
            tree.guide_depth = 3
        self.query_one("#data-nav-card").border_title = " Bases de datos "
        self.apply_tabs()
        self.update_header()
        self.build_nav()
        self.query_one("#nav", Tree).focus()

    def on_unmount(self) -> None:
        state.notifier = None

    @staticmethod
    def side_logo() -> Text:
        logo = art.logo(30, SURFACE).copy()  # copia: el original está en caché
        logo.append("\n")
        logo.append("mangosta", style=f"bold italic {GREEN}")
        logo.append(f"  v{__version__}", style=MUTED)
        logo.justify = "center"
        return logo

    def on_resize(self, event) -> None:
        # En ventanas bajas el árbol necesita el sitio más que el logo.
        self.query_one("#side-logo").display = self.size.height >= 38

    def action_about(self) -> None:
        self.push_screen(AboutScreen(art.banner(64, SURFACE), __version__))

    # ----------------------------------------------------------- utilidades
    def notify_any(self, message: str, severity: str = "information") -> None:
        """notify() que se puede llamar desde hilos de trabajo."""
        if threading.get_ident() == getattr(self, "_thread_id", None):
            self.notify(message, severity=severity)
        else:
            self.call_from_thread(self.notify, message, severity=severity)

    def background(self, fn: Callable[[], Any], done: Callable[[Any], None] | None = None, *,
                   group: str = "task", on_error: Callable[[Exception], None] | None = None) -> None:
        """Ejecuta ``fn`` en un hilo y ``done(resultado)`` de vuelta en la interfaz."""

        def runner() -> None:
            try:
                result = fn()
            except Exception as e:  # noqa: BLE001 - todo error se notifica
                self.call_from_thread(self._background_failed, e, on_error)
                return
            if done:
                self.call_from_thread(done, result)

        self.run_worker(runner, thread=True, group=group, exit_on_error=False)

    def _background_failed(self, error: Exception, on_error: Callable[[Exception], None] | None) -> None:
        self.notify(describe_error(error), severity="error", timeout=10)
        if on_error:
            on_error(error)

    def profile_dict(self, name: str | None) -> dict:
        if not name:
            return {}
        return (config.load()["profiles"].get(name) or {}) | {"name": name}

    def atlas_for(self, profile: str) -> Atlas:
        if profile not in self.atlas_cache:
            self.atlas_cache[profile] = Atlas(self.profile_dict(profile))
        return self.atlas_cache[profile]

    def scoped_atlas(self, ctx: Ctx) -> Atlas:
        """Atlas apuntando al proyecto/organización del contexto (comparte la sesión HTTP)."""
        atlas = copy.copy(self.atlas_for(ctx.profile))
        atlas.project_id = ctx.project_id
        atlas.org_id = ctx.org_id
        return atlas

    def data_cluster(self, ctx: Ctx) -> str | None:
        """Cluster cuyos datos se pueden ver en este contexto (None si no hay conexión)."""
        profile = self.profile_dict(ctx.profile)
        if ctx.kind == "direct-profile":
            return "servidor" if profile.get("uri") else None
        if ctx.kind != "project":
            return None
        creds = profile.get("atlas") or {}
        managed = creds.get("managed_user")
        if managed:
            return managed["cluster"] if (managed.get("project_id") or creds.get("project_id")) == ctx.project_id else None
        return "URI del perfil" if profile.get("uri") else None

    # ------------------------------------------------------------- cabecera
    def update_header(self) -> None:
        brand = Text()
        brand.append(" 🦞 mangosta ", style=f"bold italic {INK} on {GREEN}")
        brand.append("   ")
        ctx = self.ctx
        if ctx.kind == "empty":
            brand.append("pulsa ", style=MUTED)
            brand.append("l", style=f"bold {GREEN}")
            brand.append(" para entrar con tu cuenta de MongoDB", style=MUTED)
        else:
            account = (self.profile_dict(ctx.profile).get("atlas") or {}).get("account")
            brand.append(account or ctx.profile or "", style="bold")
            if ctx.org_name:
                brand.append("  ·  ", style=MUTED)
                brand.append(ctx.org_name, style=AMBER)
            if ctx.project_name:
                brand.append("  ›  ", style=MUTED)
                brand.append(ctx.project_name, style=f"bold {GREEN}")
        self.query_one("#brand", Static).update(brand)
        cluster = self.data_cluster(ctx)
        conn = Text()
        if cluster:
            conn.append("◉ ", style=GREEN)
            conn.append("datos: ", style=MUTED)
            conn.append(cluster, style="bold")
        elif ctx.kind == "project":
            conn.append("○ sin conexión a datos", style=MUTED)
        self.query_one("#conn", Static).update(conn)

    # --------------------------------------------------------- árbol lateral
    def build_nav(self) -> None:
        tree = self.query_one("#nav", Tree)
        tree.clear()
        cfg = config.load()
        current = cfg["current"]
        target = None
        for name, profile in cfg["profiles"].items():
            p = profile | {"name": name}
            if config.has_atlas(p):
                account = (profile.get("atlas") or {}).get("account") or "Atlas"
                label = Text.assemble(("◆ ", GREEN), (name, "bold"), (f"  {account}", MUTED))
                node = tree.root.add(label, data=Ctx("atlas-profile", name), allow_expand=True)
                node.add_leaf(Text("cargando…", style=MUTED))
                self.load_orgs(node, select_saved=name == current)
            else:
                label = Text.assemble(("● ", SKY), (name, "bold"), ("  servidor", MUTED))
                node = tree.root.add_leaf(label, data=Ctx("direct-profile", name))
            if name == current:
                target = node
        if not cfg["profiles"]:
            self.set_ctx(Ctx("empty"))
        elif target is not None:
            self.select_nav(target)

    def load_orgs(self, node, select_saved: bool) -> None:
        ctx: Ctx = node.data

        def work():
            atlas = self.atlas_for(ctx.profile)
            return [(o, services.list_projects(atlas, o["id"])) for o in services.list_orgs(atlas)]

        def done(result) -> None:
            node.remove_children()
            saved = (self.profile_dict(ctx.profile).get("atlas") or {}).get("project_id")
            target = None
            for org, projects in result:
                org_node = node.add(Text.assemble(("▣ ", AMBER), (org["name"], "bold")),
                                    data=Ctx("org", ctx.profile, org["id"], org["name"]), expand=True)
                for p in projects:
                    leaf = org_node.add_leaf(
                        Text.assemble(("◇ ", GREEN), p["name"], (f"  {p.get('clusterCount', 0)}", MUTED)),
                        data=Ctx("project", ctx.profile, org["id"], org["name"], p["id"], p["name"]))
                    if p["id"] == saved:
                        target = leaf
                if not projects:
                    org_node.add_leaf(Text("(sin proyectos)", style=MUTED))
            node.expand()
            if select_saved and target is not None:
                self.select_nav(target)

        def failed(_error: Exception) -> None:
            node.remove_children()
            node.add_leaf(Text("error al cargar (r para reintentar)", style=views.RED))

        self.background(work, done, group=f"nav-{ctx.profile}", on_error=failed)

    def select_nav(self, node) -> None:
        """Mueve el cursor a ``node`` y aplica su contexto.

        Si el cursor ya estaba en esa línea Textual no emite NodeHighlighted,
        así que el contexto se aplica también a mano.
        """
        tree = self.query_one("#nav", Tree)
        self.call_after_refresh(tree.move_cursor, node)
        if isinstance(node.data, Ctx):
            self.set_ctx(node.data)

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        if event.control.id == "nav":
            if isinstance(event.node.data, Ctx):
                self.set_ctx(event.node.data)
        elif event.control.id == "data-tree":
            self.on_data_node(event.node.data)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        if event.control.id == "nav" and isinstance(event.node.data, Ctx) and event.node.data.kind != "atlas-profile":
            self.current_table().focus()

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        if event.control.id == "data-tree" and isinstance(event.node.data, tuple) and event.node.data[0] == "db":
            self.load_collections(event.node)

    # -------------------------------------------------------------- contexto
    def set_ctx(self, ctx: Ctx) -> None:
        if ctx == self.ctx:
            return
        self.ctx = ctx
        self.ctx_version += 1
        if ctx.profile != state.profile:
            state.profile = ctx.profile
            mongo._client = None
        self.persist_ctx(ctx)
        self.rows.clear()
        self.shown.clear()
        self.errors.clear()
        self.data_tree_key = None
        self.data_coll = None
        self.apply_tabs()
        self.update_detail()
        self.update_header()
        self.load_view(self.view)
        self.refresh_bindings()

    def persist_ctx(self, ctx: Ctx) -> None:
        """Lo elegido aquí es también el contexto de los comandos de la CLI."""
        if not ctx.profile:
            return
        cfg = config.load()
        cfg["current"] = ctx.profile
        config.save(cfg)
        if ctx.kind == "project":
            config.update_atlas(ctx.profile, org_id=ctx.org_id, project_id=ctx.project_id)
        elif ctx.kind == "org":
            config.update_atlas(ctx.profile, org_id=ctx.org_id)

    def apply_tabs(self) -> None:
        """Muestra solo las pestañas del tipo de nodo elegido.

        Ocultar la pestaña activa hace que Textual active otra (con eventos que
        llegan después), así que esos eventos se ignoran hasta fijar la nuestra.
        """
        tabs = self.query_one("#tabs", TabbedContent)
        visible = views.TABS_FOR[self.ctx.kind]
        self.tabs_ready = False
        for view in views.TABS:
            if view in visible:
                tabs.show_tab(view)
            else:
                tabs.hide_tab(view)
        if self.view not in visible:
            self.view = visible[0]

        def settle() -> None:
            tabs.active = self.view
            self.tabs_ready = True

        self.call_after_refresh(settle)

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        view = event.pane.id
        # Los eventos que Textual emite al ocultar pestañas llegan tarde: solo vale el
        # de la pestaña que está activa de verdad ahora.
        if not self.tabs_ready or view != event.tabbed_content.active or view not in views.TABS_FOR[self.ctx.kind]:
            return
        if view == self.view and (view in self.rows or view == "welcome"):
            return
        self.view = view
        if view not in self.rows:
            self.load_view(view)
        else:
            self.render_table(view)
        self.refresh_bindings()

    def action_tab(self, number: int) -> None:
        visible = views.TABS_FOR[self.ctx.kind]
        if 1 <= number <= len(visible):
            self.query_one("#tabs", TabbedContent).active = visible[number - 1]

    # ----------------------------------------------------------------- tablas
    def table(self, view: str) -> DataTable:
        return self.query_one(f"#t-{view}", DataTable)

    def current_table(self):
        if self.view == "welcome":
            return self.query_one("#nav", Tree)
        if self.view == "data" and not self.data_coll:
            return self.query_one("#data-tree", Tree)
        return self.table(self.view)

    def load_view(self, view: str) -> None:
        if view == "welcome":
            self.update_detail()
            return
        if view == "data":
            self.load_data_tree()
            return
        ctx, version = self.ctx, self.ctx_version
        table = self.table(view)
        table.clear(columns=True)  # que no queden filas de otro proyecto mientras carga
        self.errors.pop(view, None)
        table.loading = True

        def done(rows: list[Row]) -> None:
            table.loading = False
            if version != self.ctx_version:
                return
            self.rows[view] = rows
            self.render_table(view)

        def failed(error: Exception) -> None:
            table.loading = False
            if version != self.ctx_version:
                return
            self.errors[view] = describe_error(error)
            self.rows[view] = []
            self.render_table(view)

        self.background(lambda: self.fetch_rows(view, ctx), done, group=f"view-{view}", on_error=failed)

    def fetch_rows(self, view: str, ctx: Ctx) -> list[Row]:
        """Se ejecuta en un hilo."""
        atlas = self.scoped_atlas(ctx) if ctx.is_atlas else None
        if view == "clusters":
            return views.cluster_rows(services.list_clusters(atlas), self.data_cluster(ctx))
        if view == "dbusers":
            return views.db_user_rows(services.list_db_users(atlas), ctx.is_atlas)
        if view == "access":
            if atlas:
                return views.access_rows(services.list_access(atlas))
            return views.user_ip_rows(services.list_db_users(None))
        if view == "members":
            return views.member_rows(services.project_members(atlas))
        if view == "orgmembers":
            return views.member_rows(services.org_members(atlas, ctx.org_id))
        if view == "projects":
            return views.project_rows(services.list_projects(atlas, ctx.org_id))
        if view == "orgs":
            return views.org_rows(services.list_orgs(atlas))
        if view == "conns":
            ops = mongo.client().admin.aggregate([{"$currentOp": {"allUsers": True, "idleConnections": True}}])
            return views.connection_rows(list(ops))
        return []

    def render_table(self, view: str) -> None:
        table = self.table(view)
        cursor = table.cursor_row
        rows = self.rows.get(view, [])
        query = self.search_text.lower()
        shown = [r for r in rows if not query or query in r.search.lower()]
        self.shown[view] = shown
        table.clear(columns=True)
        cols = self.doc_keys if view == "data" else views.columns(view, self.ctx)
        table.add_columns(*cols)
        for row in shown:
            table.add_row(*row.cells, key=row.key)
        if shown:
            table.move_cursor(row=min(max(cursor, 0), len(shown) - 1))
        card = self.query_one(f"#t-{view}-card")
        if view == "data" and self.data_coll:
            db, coll = self.data_coll
            card.border_title = f" {db}.{coll} "
            total = f" de {self.doc_total}" if self.doc_total is not None else ""
            filt = " · filtrado" if self.doc_filter else ""
            card.border_subtitle = f" {len(shown)}{total} documentos{filt} "
        else:
            card.border_title = f" {views.TABS[view]} · {self.ctx.label()} "
            card.border_subtitle = f" {len(shown)} de {len(rows)} " if query else f" {len(rows)} "
        self.update_detail()

    def selected_row(self) -> Row | None:
        if self.view in ("welcome",) or (self.view == "data" and not self.data_coll):
            return None
        shown = self.shown.get(self.view) or []
        table = self.table(self.view)
        if not shown or table.cursor_row < 0:
            return None
        return shown[min(table.cursor_row, len(shown) - 1)]

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self.update_detail()

    def update_detail(self) -> None:
        detail = self.query_one("#detail", Static)
        card = self.query_one("#detail-card")
        card.border_subtitle = ""
        row = self.selected_row()
        if row is None:
            card.border_title = " Detalle "
            detail.update(self.empty_hint())
            return
        card.border_title = f" {row.key if self.view != 'data' else 'Documento'} "
        if isinstance(row.detail, list):
            lines = Text()
            for i, (label, value) in enumerate(row.detail):
                if i:
                    lines.append("\n")
                lines.append(f"{label:<15}", style=MUTED)
                lines.append_text(value if isinstance(value, Text) else Text(str(value)))
            detail.update(lines)
        else:
            detail.update(row.detail or "")
        hints = {"clusters": " c conectar datos · p pausar · y copiar conexión · x borrar ",
                 "dbusers": " e roles · k contraseña · x borrar ", "access": " m añadir mi IP · x quitar ",
                 "members": " e rol · x quitar ", "orgmembers": " x quitar ", "projects": " x borrar ",
                 "data": " e editar · y copiar · x borrar "}
        card.border_subtitle = hints.get(self.view, "")

    def empty_hint(self) -> Text:
        if self.view == "data" and "data" not in self.errors:
            if not self.data_cluster(self.ctx):
                return Text.from_markup(f"[{MUTED}]Sin conexión a los datos de este proyecto. Ve a [b]Clusters[/b] "
                                        f"(tecla [b {GREEN}]1[/]) y pulsa [b {GREEN}]c[/] sobre un cluster.[/]")
            return Text.from_markup(f"[{MUTED}]Elige una colección a la izquierda. [b {GREEN}]n[/] crea una colección, "
                                    f"[b {GREEN}]x[/] borra la colección o BD seleccionada.[/]")
        if self.view == "welcome":
            return Text("")
        if self.view in self.errors:
            return Text.from_markup(f"[b {views.RED}]No se pudo cargar:[/] {escape(self.errors[self.view])}\n"
                                    f"[{MUTED}]Pulsa [b {GREEN}]r[/] para reintentar.[/]")
        if self.view in self.rows and not self.rows[self.view]:
            return Text.from_markup(f"[{MUTED}]No hay nada aquí todavía. Pulsa [b {GREEN}]n[/] para crear.[/]")
        return Text("")

    # ----------------------------------------------------------------- datos
    def load_data_tree(self, force: bool = False) -> None:
        ctx, version = self.ctx, self.ctx_version
        cluster = self.data_cluster(ctx)
        tree = self.query_one("#data-tree", Tree)
        key = (ctx.profile, ctx.project_id, cluster)
        if not force and self.data_tree_key == key:
            return
        self.errors.pop("data", None)
        tree.clear()
        self.data_coll = None
        self.rows["data"] = []
        self.doc_keys = []
        self.render_table("data")
        if not cluster:
            tree.root.add_leaf(Text("sin conexión", style=MUTED))
            self.update_detail()
            return
        self.query_one("#data-nav-card").border_title = f" {cluster} "
        tree.loading = True

        def work():
            cli = mongo.client()
            return [(db, sorted(cli[db].list_collection_names())) for db in cli.list_database_names()]

        def done(dbs) -> None:
            tree.loading = False
            if version != self.ctx_version:
                return
            self.data_tree_key = key
            user_dbs = [d for d in dbs if d[0] not in SYSTEM_DBS]
            for db, colls in user_dbs + [d for d in dbs if d[0] in SYSTEM_DBS]:
                icon = ("▤ ", MUTED if db in SYSTEM_DBS else GREEN)
                node = tree.root.add(Text.assemble(icon, (db, "bold"), (f"  {len(colls)}", MUTED)), data=("db", db),
                                     expand=len(user_dbs) == 1 and db not in SYSTEM_DBS)
                for coll in colls:
                    node.add_leaf(Text.assemble(("· ", MUTED), coll), data=("coll", db, coll))
            if not dbs:
                tree.root.add_leaf(Text("(sin bases de datos)", style=MUTED))
            self.update_detail()

        def failed(error: Exception) -> None:
            tree.loading = False
            tree.root.add_leaf(Text("error al conectar (r reintentar)", style=views.RED))
            self.errors["data"] = describe_error(error)
            self.update_detail()

        self.background(work, done, group="data-tree", on_error=failed)

    def load_collections(self, node) -> None:
        _, db = node.data

        def done(colls: list[str]) -> None:
            node.remove_children()
            for coll in colls:
                node.add_leaf(Text.assemble(("· ", MUTED), coll), data=("coll", db, coll))

        self.background(lambda: sorted(mongo.client()[db].list_collection_names()), done, group="data-colls")

    def on_data_node(self, data) -> None:
        if not isinstance(data, tuple):
            return
        if data[0] == "coll":
            if self.data_coll != (data[1], data[2]):
                self.data_coll = (data[1], data[2])
                self.doc_filter = {}
                self.load_docs()
        else:
            self.data_coll = None
            self.rows["data"] = []
            self.render_table("data")
            self.show_db_stats(data[1])

    def show_db_stats(self, db: str) -> None:
        def done(s: dict) -> None:
            if self.data_coll is not None:
                return
            card = self.query_one("#detail-card")
            card.border_title = f" {db} "
            card.border_subtitle = " n nueva colección · x borrar BD "
            self.query_one("#detail", Static).update(Text.assemble(
                ("Colecciones  ", MUTED), str(s.get("collections")), "\n",
                ("Documentos   ", MUTED), str(s.get("objects")), "\n",
                ("Datos        ", MUTED), views_bytes(s.get("dataSize")), "\n",
                ("Índices      ", MUTED), f"{s.get('indexes')} ({views_bytes(s.get('indexSize'))})"))

        self.background(lambda: mongo.client()[db].command("dbStats"), done, group="db-stats")

    def load_docs(self) -> None:
        if not self.data_coll:
            return
        db, coll = self.data_coll
        flt = self.doc_filter
        table = self.table("data")
        table.loading = True

        def work():
            collection = mongo.client()[db][coll]
            docs = list(collection.find(flt).limit(DOC_LIMIT))
            total = collection.count_documents(flt) if flt else collection.estimated_document_count()
            return docs, total

        def done(result) -> None:
            table.loading = False
            if self.data_coll != (db, coll):
                return
            docs, self.doc_total = result
            self.doc_keys = views.doc_columns(docs)
            self.rows["data"] = views.doc_rows(docs, self.doc_keys)
            self.render_table("data")

        self.background(work, done, group="docs", on_error=lambda _e: setattr(table, "loading", False))

    def data_tree_selection(self):
        node = self.query_one("#data-tree", Tree).cursor_node
        return node.data if node is not None and isinstance(node.data, tuple) else None

    # ---------------------------------------------------------------- buscar
    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self.search_text = event.value.strip()
            if self.view in self.rows:
                self.render_table(self.view)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search":
            self.current_table().focus()

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_clear_search(self) -> None:
        self.query_one("#search", Input).value = ""
        self.current_table().focus()

    # -------------------------------------------------------------- acciones
    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in LETTER_ACTIONS and isinstance(self.focused, (Input, TextArea)):
            return False
        if action in AVAILABLE and self.view not in AVAILABLE[action]:
            return False
        if action == "my_ip" and not self.ctx.is_atlas:
            return False
        if action == "edit" and self.view == "members" and not self.ctx.is_atlas:
            return False
        return True

    def reload(self) -> None:
        self.rows.pop(self.view, None)
        self.load_view(self.view)

    def action_refresh(self) -> None:
        if self.focused is self.query_one("#nav", Tree):
            self.atlas_cache.clear()
            self.build_nav()
        elif self.view == "data":
            if self.data_coll:
                self.load_docs()
            else:
                self.load_data_tree(force=True)
        else:
            self.reload()
        self.notify("Actualizando…", timeout=2)

    def perform(self, fn: Callable[[], Any], message: str | Callable[[Any], str], *, reload: bool = True,
                   after: Callable[[Any], None] | None = None) -> None:
        """Ejecuta una operación en segundo plano, notifica y refresca la vista."""

        def done(result) -> None:
            self.notify(message(result) if callable(message) else message)
            if after:
                after(result)
            if reload:
                self.reload()

        self.background(fn, done, group="action")

    def action_copy(self) -> None:
        row = self.selected_row()
        if row is None:
            return
        obj = row.obj
        value = {
            "clusters": lambda: obj["srv"] or "",
            "dbusers": lambda: obj["user"],
            "access": lambda: obj["entry"] if self.ctx.is_atlas else ", ".join(obj["ips"]),
            "members": lambda: obj["email"],
            "orgmembers": lambda: obj["email"],
            "projects": lambda: obj["id"],
            "orgs": lambda: obj["id"],
            "data": lambda: views.doc_to_json(obj),
        }[self.view]()
        if not value:
            self.notify("Nada que copiar", severity="warning")
            return
        self.copy_to_clipboard(value)
        self.notify("Copiado al portapapeles")

    # --- nuevo ---------------------------------------------------------------
    def action_new(self) -> None:
        getattr(self, f"new_{self.view}")()

    def new_clusters(self) -> None:
        atlas = self.scoped_atlas(self.ctx)
        fields = [
            Field("name", "Nombre", placeholder="Cluster0"),
            Field("tier", "Tier", "select", "M0", [(t + (" (gratis)" if t == "M0" else ""), t)
                                                   for t in ("M0", "M10", "M20", "M30", "M40", "M50")]),
            Field("provider", "Proveedor", "select", "AWS", [("AWS", "AWS"), ("Google Cloud", "GCP"), ("Azure", "AZURE")]),
            Field("region", "Región", value="EU_WEST_1", help="AWS: EU_WEST_1, EU_CENTRAL_1, US_EAST_1 · GCP: EUROPE_WEST1 · Azure: EUROPE_WEST"),
        ]

        def done(v: dict | None) -> None:
            if v:
                self.perform(lambda: services.create_cluster(atlas, v["name"], v["tier"], v["provider"], v["region"]),
                                f"Cluster {v['name']} en creación (tarda unos minutos)")

        self.push_screen(FormScreen("Nuevo cluster · puede tener coste", fields, "Crear",
                                    validate=lambda v: None if v["name"] else "Ponle un nombre"), done)

    def new_dbusers(self) -> None:
        ctx = self.ctx
        atlas = self.scoped_atlas(ctx) if ctx.is_atlas else None
        fields = [
            Field("user", "Usuario", placeholder="app"),
            Field("roles", "Roles (separados por comas)", value="readWrite@",
                  help="rol@bd · ej: readWrite@tienda, read@logs" + (", atlasAdmin@admin, read@tienda.pedidos" if atlas else ", root@admin")),
            Field("password", "Contraseña", "password", help="Déjala vacía para generar una segura"),
        ]
        if atlas:
            fields += [Field("clusters", "Limitar a clusters (opcional)", placeholder="Cluster0, Cluster1"),
                       Field("expires", "Caduca (opcional)", placeholder="6h, 3d o 2026-12-31 (máx. 7 días)")]
        else:
            fields += [Field("db", "BD de autenticación", value="admin"),
                       Field("allow_ip", "Solo desde IPs (opcional)", placeholder="10.0.0.0/24, 1.2.3.4")]

        def parse(v: dict):
            db = v.get("db") or "admin"
            return [parse_role(r, db) for r in _split(v["roles"])]

        def validate(v: dict) -> str | None:
            if not v["user"]:
                return "Falta el nombre de usuario"
            try:
                if not parse(v):
                    return "Indica al menos un rol"
                if v.get("expires"):
                    parse_expiry(v["expires"])
            except MangostaError as e:
                return str(e)
            return None

        def done(v: dict | None) -> None:
            if not v:
                return
            password = v["password"] or secrets.token_urlsafe(18)
            roles = parse(v)

            def work():
                services.create_db_user(atlas, v["user"], password, roles, db=v.get("db") or "admin",
                                        allow_ip=_split(v.get("allow_ip", "")) or None,
                                        clusters=_split(v.get("clusters", "")) or None,
                                        expires=parse_expiry(v["expires"]) if v.get("expires") else None)

            after = None
            if not v["password"]:
                def after(_):
                    self.push_screen(SecretScreen("Usuario creado", f"Contraseña de [b]{escape(v['user'])}[/]:", password))
            self.perform(work, f"Usuario {v['user']} creado", after=after)

        self.push_screen(FormScreen("Nuevo usuario de base de datos", fields, "Crear", validate=validate), done)

    def new_access(self) -> None:
        ctx = self.ctx
        if not ctx.is_atlas:
            users = self.rows.get("access") or []
            if not users:
                self.notify("No hay usuarios a los que restringir", severity="warning")
                return
            fields = [Field("user", "Usuario", "select", users[0].key, [(r.key, r.key) for r in users]),
                      Field("entry", "IP o CIDR permitido", placeholder="10.0.0.0/24")]

            def done_direct(v: dict | None) -> None:
                if not v:
                    return
                user = next(r.obj for r in users if r.key == v["user"])
                try:
                    _, value = classify_access_entry(v["entry"])
                except MangostaError as e:
                    self.notify(str(e), severity="error")
                    return
                self.set_user_ips(user, user["ips"] + [value], f"{value} permitida para {user['user']}")

            self.push_screen(FormScreen("Restringir usuario por IP", fields, "Añadir"), done_direct)
            return
        atlas = self.scoped_atlas(ctx)
        fields = [Field("entry", "IP, CIDR o 'me'", placeholder="1.2.3.4 · 10.0.0.0/24 · me (tu IP actual)"),
                  Field("comment", "Comentario (opcional)", placeholder="oficina"),
                  Field("expires", "Caduca (opcional)", placeholder="6h, 3d (máx. 7 días)")]

        def validate(v: dict) -> str | None:
            try:
                if v["entry"].lower() != "me":
                    classify_access_entry(v["entry"])
                if v["expires"]:
                    parse_expiry(v["expires"])
            except MangostaError as e:
                return str(e)
            return None

        def done(v: dict | None) -> None:
            if not v:
                return

            def add():
                entry = public_ip() if v["entry"].lower() == "me" else v["entry"]
                kind, value = classify_access_entry(entry)
                services.add_access(atlas, kind, value, v["comment"] or None,
                                    parse_expiry(v["expires"]) if v["expires"] else None)
                return value

            if is_open_to_world(v["entry"]):
                self.push_screen(ConfirmScreen("[b]0.0.0.0/0[/] permite conexiones desde [b]CUALQUIER IP[/] de internet. ¿Seguro?",
                                               "Permitir"), lambda ok: ok and self.perform(add, lambda val: f"{val} permitida"))
            else:
                self.perform(add, lambda val: f"{val} permitida")

        self.push_screen(FormScreen("Permitir IP", fields, "Añadir", validate=validate), done)

    def new_members(self) -> None:
        atlas = self.scoped_atlas(self.ctx)
        fields = [Field("email", "Email", placeholder="persona@empresa.com"),
                  Field("role", "Rol en el proyecto", "select", "read_only", [(k, k) for k in services.PROJECT_ROLES])]

        def done(v: dict | None) -> None:
            if v:
                self.perform(lambda: services.invite_project_member(atlas, v["email"], [services.PROJECT_ROLES[v["role"]]]),
                                f"Invitación enviada a {v['email']}")

        self.push_screen(FormScreen("Invitar al proyecto", fields, "Invitar",
                                    validate=lambda v: None if "@" in v["email"] else "Email no válido"), done)

    def new_orgmembers(self) -> None:
        atlas = self.scoped_atlas(self.ctx)
        org_id = self.ctx.org_id
        fields = [Field("email", "Email", placeholder="persona@empresa.com"),
                  Field("role", "Rol en la organización", "select", "member", [(k, k) for k in services.ORG_ROLES])]

        def done(v: dict | None) -> None:
            if v:
                self.perform(lambda: services.invite_org_member(atlas, org_id, v["email"], [services.ORG_ROLES[v["role"]]]),
                                f"Invitación enviada a {v['email']}")

        self.push_screen(FormScreen(f"Invitar a {self.ctx.org_name}", fields, "Invitar",
                                    validate=lambda v: None if "@" in v["email"] else "Email no válido"), done)

    def new_projects(self) -> None:
        atlas = self.scoped_atlas(self.ctx)
        org_id = self.ctx.org_id

        def done(v: dict | None) -> None:
            if v:
                self.perform(lambda: services.create_project(atlas, v["name"], org_id), f"Proyecto {v['name']} creado",
                                after=lambda _: self.refresh_nav())

        self.push_screen(FormScreen(f"Nuevo proyecto en {self.ctx.org_name}", [Field("name", "Nombre")], "Crear",
                                    validate=lambda v: None if v["name"] else "Ponle un nombre"), done)

    def new_data(self) -> None:
        if self.data_coll and self.focused is self.table("data"):
            self.insert_document()
            return
        selected = self.data_tree_selection()
        db = selected[1] if selected else ""
        fields = [Field("db", "Base de datos", value=db, help="Si no existe, se crea"),
                  Field("coll", "Colección nueva")]

        def done(v: dict | None) -> None:
            if v:
                self.perform(lambda: mongo.client()[v["db"]].create_collection(v["coll"]),
                                f"Colección {v['db']}.{v['coll']} creada", reload=False,
                                after=lambda _: self.load_data_tree(force=True))

        self.push_screen(FormScreen("Nueva colección", fields, "Crear",
                                    validate=lambda v: None if v["db"] and v["coll"] else "Indica BD y colección"), done)

    def insert_document(self) -> None:
        db, coll = self.data_coll

        def validate(v: dict) -> str | None:
            try:
                parse_json_object(v["doc"], "El documento")
            except MangostaError as e:
                return str(e)
            return None

        def done(v: dict | None) -> None:
            if v:
                doc = parse_json_object(v["doc"], "El documento")
                self.perform(lambda: mongo.client()[db][coll].insert_one(doc).inserted_id,
                                lambda _id: f"Insertado _id={_id}", reload=False, after=lambda _: self.load_docs())

        self.push_screen(FormScreen(f"Insertar en {db}.{coll}", [Field("doc", "Documento (JSON)", "json", '{\n  \n}')],
                                    "Insertar", validate=validate, wide=True), done)

    # --- editar --------------------------------------------------------------
    def action_edit(self) -> None:
        row = self.selected_row()
        if row is None:
            return
        getattr(self, f"edit_{self.view}")(row)

    def edit_dbusers(self, row: Row) -> None:
        user = row.obj
        atlas = self.scoped_atlas(self.ctx) if self.ctx.is_atlas else None
        fields = [Field("roles", "Roles (separados por comas)", value=services.roles_text(user["roles"]),
                        help="rol@bd · sustituye todos los roles del usuario")]

        def validate(v: dict) -> str | None:
            try:
                [parse_role(r, user["db"]) for r in _split(v["roles"])]
            except MangostaError as e:
                return str(e)
            return None

        def done(v: dict | None) -> None:
            if v:
                roles = [parse_role(r, user["db"]) for r in _split(v["roles"])]
                self.perform(lambda: services.set_db_user_roles(atlas, user["user"], roles, user["db"]),
                                f"Roles de {user['user']} actualizados")

        self.push_screen(FormScreen(f"Roles de {user['user']}", fields, validate=validate), done)

    def edit_members(self, row: Row) -> None:
        member = row.obj
        if member["status"] == "invitado":
            self.notify("Es una invitación pendiente: bórrala y vuelve a invitar", severity="warning")
            return
        atlas = self.scoped_atlas(self.ctx)
        current = next((services.friendly_role(r) for r in member["roles"]), "read_only")
        fields = [Field("role", "Rol en el proyecto", "select", current if current in services.PROJECT_ROLES else "read_only",
                        [(k, k) for k in services.PROJECT_ROLES])]

        def done(v: dict | None) -> None:
            if v:
                self.perform(lambda: services.set_project_member_roles(atlas, member, [services.PROJECT_ROLES[v["role"]]]),
                                f"Rol de {member['email']}: {v['role']}")

        self.push_screen(FormScreen(f"Rol de {member['email']}", fields), done)

    def edit_data(self, row: Row) -> None:
        db, coll = self.data_coll
        original = row.obj

        def validate(v: dict) -> str | None:
            try:
                doc = parse_json_object(v["doc"], "El documento")
            except MangostaError as e:
                return str(e)
            if doc.get("_id") != original.get("_id"):
                return "No se puede cambiar el _id"
            return None

        def done(v: dict | None) -> None:
            if v:
                doc = parse_json_object(v["doc"], "El documento")
                self.perform(lambda: mongo.client()[db][coll].replace_one({"_id": original["_id"]}, doc).modified_count,
                                lambda n: "Documento guardado" if n else "Sin cambios", reload=False,
                                after=lambda _: self.load_docs())

        self.push_screen(FormScreen(f"Editar documento de {db}.{coll}", [Field("doc", "Documento (JSON)", "json", views.doc_to_json(original))],
                                    validate=validate, wide=True), done)

    def action_password(self) -> None:
        row = self.selected_row()
        if row is None:
            return
        user = row.obj
        if user["user"].startswith("mangosta-"):
            self.notify("Es el usuario temporal de mangosta: su contraseña se gestiona sola", severity="warning")
            return
        atlas = self.scoped_atlas(self.ctx) if self.ctx.is_atlas else None

        def done(v: dict | None) -> None:
            if v is None:
                return
            password = v["password"] or secrets.token_urlsafe(18)
            after = None
            if not v["password"]:
                def after(_):
                    self.push_screen(SecretScreen("Contraseña cambiada", f"Nueva contraseña de [b]{escape(user['user'])}[/]:", password))
            self.perform(lambda: services.set_db_user_password(atlas, user["user"], password, user["db"]),
                            f"Contraseña de {user['user']} cambiada", after=after, reload=False)

        self.push_screen(FormScreen(f"Contraseña de {user['user']}",
                                    [Field("password", "Nueva contraseña", "password", help="Vacía = generar una segura")],
                                    "Cambiar"), done)

    # --- otras acciones --------------------------------------------------------
    def action_my_ip(self) -> None:
        atlas = self.scoped_atlas(self.ctx)

        def work():
            ip = public_ip()
            if ip_allowed(ip, [e["entry"] for e in services.list_access(atlas) if e["entry"]]):
                return f"Tu IP {ip} ya está permitida"
            services.add_access(atlas, "ipAddress", ip, f"mangosta {socket.gethostname()}")
            return f"Tu IP {ip} añadida"

        self.perform(work, lambda msg: msg)

    def action_pause(self) -> None:
        row = self.selected_row()
        if row is None:
            return
        cluster = row.obj
        atlas = self.scoped_atlas(self.ctx)
        if cluster["tier"] == "M0":
            self.notify("Los clusters gratuitos (M0) no se pueden pausar", severity="warning")
            return
        if cluster["state"] == "PAUSED":
            self.perform(lambda: services.set_cluster_paused(atlas, cluster["name"], False), f"Reanudando {cluster['name']}…")
            return
        self.push_screen(ConfirmScreen(f"¿Pausar [b]{escape(cluster['name'])}[/]? Dejará de aceptar conexiones.", "Pausar"),
                         lambda ok: ok and self.perform(lambda: services.set_cluster_paused(atlas, cluster["name"], True),
                                                           f"Pausando {cluster['name']}…"))

    def action_connect(self) -> None:
        """Como 'Connect' de Atlas: IP permitida + usuario temporal + datos listos."""
        row = self.selected_row()
        if row is None:
            return
        cluster = row.obj["name"]
        ctx = self.ctx
        atlas = self.scoped_atlas(ctx)

        def check_ip():
            ip = public_ip()
            return ip, ip_allowed(ip, [e["entry"] for e in services.list_access(atlas) if e["entry"]])

        def after_check(result) -> None:
            ip, allowed = result
            if allowed:
                do_connect()
                return
            self.push_screen(ConfirmScreen(f"Tu IP [b]{ip}[/] no está en la access list del proyecto.\n"
                                           f"¿Añadirla para poder conectarte?", "Añadir y conectar", danger=False),
                             lambda ok: ok and self.background(
                                 lambda: services.add_access(atlas, "ipAddress", ip, f"mangosta {socket.gethostname()}"),
                                 lambda _: do_connect()))

        def do_connect() -> None:
            self.notify(f"Preparando acceso a los datos de {cluster}…", timeout=6)

            def work():
                username = connect.connect(atlas, cluster)
                mongo._client = None
                mongo.client().admin.command("ping")
                return username

            def done(username: str) -> None:
                self.notify(f"Datos de {cluster} conectados (usuario temporal {username})")
                self.update_header()
                self.data_tree_key = None
                self.rows.pop("clusters", None)
                self.query_one("#tabs", TabbedContent).active = "data"

            self.background(work, done, group="connect")

        self.background(check_ip, after_check, group="connect")

    def action_filter(self) -> None:
        if not self.data_coll:
            self.notify("Elige antes una colección", severity="warning")
            return
        current = views.doc_to_json(self.doc_filter) if self.doc_filter else "{}"

        def validate(v: dict) -> str | None:
            try:
                parse_json_object(v["filter"] or "{}", "El filtro")
            except MangostaError as e:
                return str(e)
            return None

        def done(v: dict | None) -> None:
            if v is not None:
                self.doc_filter = parse_json_object(v["filter"] or "{}", "El filtro")
                self.load_docs()

        self.push_screen(FormScreen("Filtrar documentos", [Field("filter", "Filtro (JSON de MongoDB)", value=" ".join(current.split()),
                                                                 help='Ej: {"pais": "ES", "edad": {"$gt": 30}} · vacío = todos')],
                                    "Aplicar", validate=validate), done)

    # --- borrar --------------------------------------------------------------
    def action_delete(self) -> None:
        if self.view == "data" and (not self.data_coll or self.focused is self.query_one("#data-tree", Tree)):
            self.delete_data_node()
            return
        row = self.selected_row()
        if row is None:
            return
        getattr(self, f"delete_{self.view}")(row)

    def delete_clusters(self, row: Row) -> None:
        atlas = self.scoped_atlas(self.ctx)
        name = row.obj["name"]
        self.push_screen(TypedConfirmScreen(f"Vas a BORRAR el cluster [b]{escape(name)}[/] y TODOS sus datos.", name),
                         lambda ok: ok and self.perform(lambda: services.delete_cluster(atlas, name), f"Cluster {name} borrándose"))

    def delete_dbusers(self, row: Row) -> None:
        user = row.obj
        atlas = self.scoped_atlas(self.ctx) if self.ctx.is_atlas else None
        extra = "\n[b $warning]Es el usuario temporal de mangosta: perderás el acceso a los datos.[/]" if user["user"].startswith("mangosta-") else ""
        self.push_screen(TypedConfirmScreen(f"Vas a borrar el usuario [b]{escape(user['user'])}[/].{extra}", user["user"]),
                         lambda ok: ok and self.perform(lambda: services.delete_db_user(atlas, user["user"], user["db"]),
                                                           f"Usuario {user['user']} borrado"))

    def delete_access(self, row: Row) -> None:
        if not self.ctx.is_atlas:
            user = row.obj
            if not user["ips"]:
                self.notify(f"{user['user']} no tiene restricciones de IP", severity="warning")
                return
            fields = [Field("ip", "IP a quitar", "select", user["ips"][0], [(ip, ip) for ip in user["ips"]])]
            self.push_screen(FormScreen(f"IPs de {user['user']}", fields, "Quitar"),
                             lambda v: v and self.set_user_ips(user, [ip for ip in user["ips"] if ip != v["ip"]],
                                                               f"{v['ip']} quitada de {user['user']}"))
            return
        atlas = self.scoped_atlas(self.ctx)
        entry = row.obj["entry"]
        self.push_screen(ConfirmScreen(f"¿Quitar [b]{escape(entry)}[/] de la access list? Quien conecte desde ahí perderá el acceso.", "Quitar"),
                         lambda ok: ok and self.perform(lambda: services.remove_access(atlas, entry), f"{entry} quitada"))

    def delete_members(self, row: Row) -> None:
        atlas = self.scoped_atlas(self.ctx)
        member = row.obj
        self.push_screen(TypedConfirmScreen(f"[b]{escape(member['email'])}[/] perderá el acceso al proyecto.", member["email"], "Quitar"),
                         lambda ok: ok and self.perform(lambda: services.remove_project_member(atlas, member),
                                                           f"{member['email']} quitado del proyecto"))

    def delete_orgmembers(self, row: Row) -> None:
        atlas = self.scoped_atlas(self.ctx)
        org_id = self.ctx.org_id
        member = row.obj
        self.push_screen(TypedConfirmScreen(f"[b]{escape(member['email'])}[/] perderá el acceso a la organización y a todos sus proyectos.",
                                            member["email"], "Quitar"),
                         lambda ok: ok and self.perform(lambda: services.remove_org_member(atlas, org_id, member),
                                                           f"{member['email']} quitado de la organización"))

    def delete_projects(self, row: Row) -> None:
        project = row.obj
        if project.get("clusterCount"):
            self.notify(f"{project['name']} tiene clusters: bórralos antes", severity="error")
            return
        atlas = self.scoped_atlas(self.ctx)
        self.push_screen(TypedConfirmScreen(f"Vas a BORRAR el proyecto [b]{escape(project['name'])}[/].", project["name"]),
                         lambda ok: ok and self.perform(lambda: services.delete_project(atlas, project["id"]),
                                                           f"Proyecto {project['name']} borrado", after=lambda _: self.refresh_nav()))

    def delete_data(self, row: Row) -> None:
        db, coll = self.data_coll
        doc = row.obj
        self.push_screen(ConfirmScreen(f"¿Borrar el documento [b]{escape(str(doc.get('_id')))}[/] de {db}.{coll}?", "Borrar"),
                         lambda ok: ok and self.perform(lambda: mongo.client()[db][coll].delete_one({"_id": doc["_id"]}),
                                                           "Documento borrado", reload=False, after=lambda _: self.load_docs()))

    def delete_data_node(self) -> None:
        selected = self.data_tree_selection()
        if not selected:
            return
        if selected[0] == "coll":
            _, db, coll = selected
            self.push_screen(TypedConfirmScreen(f"Vas a BORRAR la colección [b]{escape(db)}.{escape(coll)}[/] con todos sus documentos.", coll),
                             lambda ok: ok and self.perform(lambda: mongo.client()[db].drop_collection(coll),
                                                               f"Colección {db}.{coll} borrada", reload=False,
                                                               after=lambda _: self.load_data_tree(force=True)))
            return
        db = selected[1]
        if db in SYSTEM_DBS:
            self.notify(f"'{db}' es una base de datos del sistema", severity="error")
            return
        self.push_screen(TypedConfirmScreen(f"Vas a BORRAR la base de datos [b]{escape(db)}[/] entera.", db),
                         lambda ok: ok and self.perform(lambda: mongo.client().drop_database(db), f"Base de datos {db} borrada",
                                                           reload=False, after=lambda _: self.load_data_tree(force=True)))

    def set_user_ips(self, user: dict, sources: list[str], message: str) -> None:
        """(Self-hosted) cambia las IPs de un usuario avisando si te bloquearías."""

        def risk():
            me = mongo.authenticated_users()
            if not any(u["user"] == user["user"] and u["db"] == user["db"] for u in me):
                return None
            ip = mongo.client_address()
            return ip if ip and sources and not ip_allowed(ip, sources) else None

        def apply() -> None:
            self.perform(lambda: services.set_user_ip_sources(user["user"], user["db"], sources), message)

        def checked(ip: str | None) -> None:
            if ip is None:
                apply()
                return
            self.push_screen(TypedConfirmScreen(f"Estás conectado como [b]{escape(user['user'])}[/] desde {ip}, que no estará "
                                                f"permitida: [b]te quedarías sin acceso[/].", user["user"], "Aplicar igualmente"),
                             lambda ok: ok and apply())

        self.background(risk, checked)

    # ----------------------------------------------------------------- login
    def action_login(self) -> None:
        from ..commands.auth import default_profile_name, store_session

        profile_name = self.ctx.profile if self.ctx.is_atlas else default_profile_name()

        def show(code: dict) -> None:
            self.push_screen(LoginScreen(code, oauth.poll_token), got_token)

        def got_token(token: dict | None) -> None:
            if not token:
                return

            def stored(result) -> None:
                account, _ = result
                self.notify(f"Sesión iniciada{f' como {account}' if account else ''}")
                self.atlas_cache.pop(profile_name, None)
                self.build_nav()

            self.background(lambda: store_session(profile_name, token), stored)

        self.background(oauth.request_code, show)

    def refresh_nav(self) -> None:
        tree = self.query_one("#nav", Tree)
        for node in tree.root.children:
            if isinstance(node.data, Ctx) and node.data.profile == self.ctx.profile and node.data.kind == "atlas-profile":
                self.load_orgs(node, select_saved=False)


def views_bytes(n) -> str:
    from ..output import human_bytes

    return human_bytes(n)


def _split(text: str) -> list[str]:
    return [p.strip() for p in (text or "").split(",") if p.strip()]


def run() -> None:
    MangostaApp().run()
