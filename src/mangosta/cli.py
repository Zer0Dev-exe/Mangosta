"""Punto de entrada de la CLI."""

import shutil
import subprocess
import sys
from typing import Annotated, Optional

import typer
from pymongo.errors import PyMongoError, ServerSelectionTimeoutError

from . import __version__
from .commands import access, auth, cluster, coll, db, doc, index, members, org, profile, project, role, server, user
from .config import get_profile, resolve
from .errors import MangostaError
from .output import err_console
from .state import state

app = typer.Typer(
    name="mangosta",
    help="[bold]mangosta[/] — gestiona MongoDB (self-hosted y Atlas) desde la terminal.",
    no_args_is_help=False,
    invoke_without_command=True,
    pretty_exceptions_enable=False,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)

app.command("login", rich_help_panel="General")(auth.login)
app.command("logout", rich_help_panel="General")(auth.logout)
app.add_typer(auth.app, name="auth", rich_help_panel="General")
app.add_typer(profile.app, name="profile", rich_help_panel="General")
app.add_typer(db.app, name="db", rich_help_panel="Datos")
app.add_typer(coll.app, name="coll", rich_help_panel="Datos")
app.add_typer(doc.app, name="doc", rich_help_panel="Datos")
app.add_typer(index.app, name="index", rich_help_panel="Datos")
app.add_typer(user.app, name="user", rich_help_panel="Seguridad")
app.add_typer(role.app, name="role", rich_help_panel="Seguridad")
app.add_typer(access.app, name="access", rich_help_panel="Seguridad")
app.add_typer(server.app, name="server", rich_help_panel="Monitorización")
app.add_typer(org.app, name="org", rich_help_panel="Atlas")
app.add_typer(project.app, name="project", rich_help_panel="Atlas")
app.add_typer(cluster.app, name="cluster", rich_help_panel="Atlas")
app.add_typer(members.app, name="members", rich_help_panel="Atlas")


def _version(value: bool) -> None:
    if value:
        print(f"mangosta {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    profile_name: Annotated[Optional[str], typer.Option("--profile", "-p", envvar="MANGOSTA_PROFILE", help="Perfil a usar (por defecto el activo)")] = None,
    uri: Annotated[Optional[str], typer.Option("--uri", envvar="MANGOSTA_URI", help="URI de conexión puntual (ignora la del perfil)")] = None,
    json_: Annotated[bool, typer.Option("--json", help="Salida en JSON (para scripts)")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="No pedir confirmaciones")] = False,
    version: Annotated[bool, typer.Option("--version", callback=_version, is_eager=True, help="Muestra la versión")] = False,
):
    """Sin comando abre la interfaz interactiva."""
    state.profile = profile_name
    state.uri = uri
    state.json = json_
    state.yes = yes
    if ctx.invoked_subcommand is None:
        if sys.stdout.isatty() and sys.stdin.isatty():
            ui()
        else:
            print(ctx.get_help())


@app.command(rich_help_panel="General")
def ui():
    """Abre la interfaz interactiva (lo mismo que ejecutar  mangosta  sin nada)."""
    from .tui.app import run

    run()


@app.command(rich_help_panel="General")
def shell():
    """Abre mongosh conectado con el perfil activo."""
    exe = shutil.which("mongosh")
    if not exe:
        raise MangostaError("No encuentro mongosh en el PATH (https://www.mongodb.com/try/download/shell)")
    uri = resolve(get_profile().get("uri"))
    if not uri:
        raise MangostaError("El perfil no tiene URI de conexión")
    raise typer.Exit(subprocess.call([exe, uri]))


GLOBAL_FLAGS = {"--yes", "-y", "--json"}


def _hoist_global_flags(argv: list[str]) -> list[str]:
    """Permite poner --yes / --json en cualquier posición (``mangosta db drop x -y``)."""
    head, sep, tail = argv, [], []
    if "--" in argv:
        i = argv.index("--")
        head, sep, tail = argv[:i], ["--"], argv[i + 1:]
    flags = [a for a in head if a in GLOBAL_FLAGS]
    rest = [a for a in head if a not in GLOBAL_FLAGS]
    return flags + rest + sep + tail


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    try:
        app(args=_hoist_global_flags(sys.argv[1:]), prog_name="mangosta")
    except MangostaError as e:
        err_console.print(f"[red]✗[/] {e}")
        sys.exit(1)
    except ServerSelectionTimeoutError as e:
        reason = str(e).split(" (configured timeouts")[0].split(", Timeout:")[0]
        err_console.print(f"[red]✗ No se pudo conectar a MongoDB:[/] {reason}")
        err_console.print("[dim]  Revisa la URI, que el servidor esté arrancado y (en Atlas) que tu IP esté permitida: mangosta access add me[/]")
        sys.exit(1)
    except PyMongoError as e:
        err_console.print(f"[red]✗ MongoDB:[/] {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        err_console.print("\n[dim]Interrumpido[/]")
        sys.exit(130)
