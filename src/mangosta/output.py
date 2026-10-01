"""Salida por terminal: tablas, JSON y confirmaciones."""

import contextlib
import sys

import typer
from bson import json_util
from rich.console import Console
from rich.table import Table

from .errors import MangostaError
from .state import state

console = Console()
err_console = Console(stderr=True)


def to_json(data, canonical: bool = False) -> str:
    options = json_util.CANONICAL_JSON_OPTIONS if canonical else json_util.RELAXED_JSON_OPTIONS
    return json_util.dumps(data, json_options=options, indent=2, ensure_ascii=False)


def print_json(data) -> None:
    text = to_json(data)
    if sys.stdout.isatty():
        console.print_json(text)
    else:
        print(text)


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "sí" if value else "no"
    if isinstance(value, (list, tuple)):
        return ", ".join(_cell(v) for v in value)
    if isinstance(value, dict):
        return to_json(value).replace("\n", " ")
    return str(value)


def emit(rows: list[dict], columns: list[tuple[str, str]], title: str | None = None, raw=None) -> None:
    """Muestra ``rows`` como tabla o, con --json, ``raw`` (o ``rows``) como JSON."""
    if state.json:
        print_json(rows if raw is None else raw)
        return
    if not rows:
        console.print("[dim](sin resultados)[/]")
        return
    table = Table(title=title, header_style="bold cyan", title_justify="left")
    for _, header in columns:
        table.add_column(header, overflow="fold")
    for row in rows:
        table.add_row(*(_cell(row.get(key)) for key, _ in columns))
    console.print(table)


def emit_obj(data: dict, title: str | None = None) -> None:
    """Muestra un objeto clave/valor."""
    if state.json:
        print_json(data)
        return
    table = Table(title=title, show_header=False, title_justify="left", box=None, padding=(0, 2))
    table.add_column(style="bold cyan")
    table.add_column(overflow="fold")
    for key, value in data.items():
        table.add_row(str(key), _cell(value))
    console.print(table)


def success(msg: str) -> None:
    if state.notifier:
        state.notifier(msg, "information")
    elif not state.json:
        console.print(f"[green]✓[/] {msg}")


def info(msg: str) -> None:
    if state.notifier:
        state.notifier(msg, "information")
    elif not state.json:
        console.print(msg)


def warn(msg: str) -> None:
    if state.notifier:
        state.notifier(msg, "warning")
    else:
        err_console.print(f"[yellow]⚠ {msg}[/]")


def status(msg: str):
    """Spinner en la terminal; dentro de la TUI, una notificación."""
    if state.notifier:
        state.notifier(msg, "information")
        return contextlib.nullcontext()
    return console.status(msg)


def confirm(msg: str) -> None:
    """Confirmación sí/no. Se salta con --yes."""
    if state.yes:
        return
    if not sys.stdin.isatty():
        raise MangostaError("Se necesita confirmación: añade --yes para ejecutarlo sin preguntar")
    if not typer.confirm(msg, default=False):
        raise MangostaError("Cancelado")


def confirm_typed(msg: str, expected: str) -> None:
    """Confirmación fuerte estilo Atlas: hay que escribir el nombre. Se salta con --yes."""
    if state.yes:
        return
    if not sys.stdin.isatty():
        raise MangostaError("Operación destructiva: añade --yes para ejecutarla sin preguntar")
    console.print(f"[bold red]⚠ {msg}[/]")
    typed = typer.prompt(f"Escribe '{expected}' para confirmar", default="", show_default=False)
    if typed.strip() != expected:
        raise MangostaError("Cancelado: el texto no coincide")


def choose(title: str, options: list[tuple[str, object]], hint: str) -> object:
    """Menú numerado. ``hint`` explica qué opción usar en modo no interactivo."""
    if len(options) == 1:
        return options[0][1]
    if not sys.stdin.isatty():
        raise MangostaError(f"{title}: hay varias opciones; {hint}")
    console.print(f"[bold]{title}[/]")
    for i, (label, _) in enumerate(options, 1):
        console.print(f"  [cyan]{i}[/]) {label}")
    while True:
        pick = typer.prompt("Elige un número", type=int)
        if 1 <= pick <= len(options):
            return options[pick - 1][1]
        console.print("[red]Número fuera de rango[/]")


def human_bytes(n) -> str:
    if n is None:
        return ""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)
