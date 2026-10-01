"""Diálogos modales de la TUI."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, LoadingIndicator, Select, Static, TextArea


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [Binding("escape", "cancel", "Cancelar")]

    def __init__(self, message: str, confirm_label: str = "Confirmar", danger: bool = True):
        super().__init__()
        self.message = message
        self.confirm_label = confirm_label
        self.danger = danger

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog danger" if self.danger else "dialog") as dialog:
            dialog.border_title = "Confirmar"
            yield Static(self.message)
            with Horizontal(classes="dialog-buttons"):
                yield Button(self.confirm_label, id="confirm", variant="error" if self.danger else "success")
                yield Button("Cancelar", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#cancel" if self.danger else "#confirm", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class TypedConfirmScreen(ModalScreen[bool]):
    """Como en Atlas: para borrar hay que escribir el nombre del recurso."""

    BINDINGS = [Binding("escape", "cancel", "Cancelar")]

    def __init__(self, message: str, expected: str, confirm_label: str = "Borrar"):
        super().__init__()
        self.message = message
        self.expected = expected
        self.confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog danger") as dialog:
            dialog.border_title = "Operación irreversible"
            yield Static(self.message)
            yield Label(f"Escribe [b]{escape(self.expected)}[/] para confirmar")
            yield Input(id="typed")
            with Horizontal(classes="dialog-buttons"):
                yield Button(self.confirm_label, id="confirm", variant="error", disabled=True)
                yield Button("Cancelar", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#typed", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        self.query_one("#confirm", Button).disabled = event.value.strip() != self.expected

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.value.strip() == self.expected:
            self.dismiss(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


@dataclass
class Field:
    id: str
    label: str
    kind: str = "text"  # text | password | select | checkbox | json
    value: object = ""
    options: list[tuple[str, object]] = field(default_factory=list)
    placeholder: str = ""
    help: str = ""


Validator = Callable[[dict], "str | None"]


class FormScreen(ModalScreen["dict | None"]):
    """Formulario genérico: devuelve {id: valor} o None si se cancela."""

    BINDINGS = [Binding("escape", "cancel", "Cancelar"), Binding("ctrl+s", "save", "Guardar")]

    def __init__(self, title: str, fields: list[Field], submit_label: str = "Guardar",
                 validate: Validator | None = None, wide: bool = False):
        super().__init__()
        self.title_text = title
        self.fields = fields
        self.submit_label = submit_label
        self.validate = validate
        self.wide = wide

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog wide" if self.wide else "dialog") as dialog:
            dialog.border_title = self.title_text
            dialog.border_subtitle = "ctrl+s guardar · esc cancelar"
            for f in self.fields:
                if f.kind == "checkbox":
                    yield Checkbox(f.label, value=bool(f.value), id=f"f-{f.id}")
                    continue
                yield Label(f.label)
                if f.kind == "select":
                    yield Select(f.options, value=f.value if f.value != "" else f.options[0][1],
                                 allow_blank=False, id=f"f-{f.id}")
                elif f.kind == "json":
                    area = TextArea(str(f.value), id=f"f-{f.id}", show_line_numbers=True, classes="json")
                    yield area
                else:
                    yield Input(value=str(f.value), placeholder=f.placeholder, password=f.kind == "password", id=f"f-{f.id}")
                if f.help:
                    yield Static(f.help, classes="help-text")
            yield Static("", id="error", classes="error-text")
            with Horizontal(classes="dialog-buttons"):
                yield Button(self.submit_label, id="save", variant="success")
                yield Button("Cancelar", id="cancel")

    def on_mount(self) -> None:
        first = self.fields[0] if self.fields else None
        if first:
            self.query_one(f"#f-{first.id}").focus()

    def values(self) -> dict:
        out: dict = {}
        for f in self.fields:
            widget = self.query_one(f"#f-{f.id}")
            if isinstance(widget, TextArea):
                out[f.id] = widget.text
            elif isinstance(widget, (Input, Checkbox, Select)):
                out[f.id] = widget.value.strip() if isinstance(widget, Input) and f.kind != "password" else widget.value
        return out

    def show_error(self, message: str) -> None:
        self.query_one("#error", Static).update(escape(message))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.action_save()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self.action_save()
        else:
            self.dismiss(None)

    def action_save(self) -> None:
        values = self.values()
        if self.validate:
            error = self.validate(values)
            if error:
                self.show_error(error)
                return
        self.dismiss(values)

    def action_cancel(self) -> None:
        self.dismiss(None)


class AboutScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape,question_mark,enter", "close", "Cerrar")]

    def __init__(self, banner, version: str):
        super().__init__()
        self.banner = banner
        self.version = version

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog about") as dialog:
            dialog.border_title = "Acerca de"
            dialog.border_subtitle = "esc cerrar"
            yield Static(self.banner)
            yield Static(f"\n[b]v{escape(self.version)}[/]  ·  MongoDB Atlas y servidores propios desde la terminal\n"
                         "[dim]Organizaciones, proyectos, clusters, datos, usuarios, IPs y miembros.\n"
                         "Pulsa [b]?[/b] en cualquier momento para volver aquí.[/]", classes="about-text")

    def action_close(self) -> None:
        self.dismiss(None)


class SecretScreen(ModalScreen[None]):
    """Muestra un secreto una sola vez (p.ej. una contraseña generada)."""

    BINDINGS = [Binding("escape", "close", "Cerrar"), Binding("c", "copy", "Copiar")]

    def __init__(self, title: str, message: str, secret: str):
        super().__init__()
        self.title_text = title
        self.message = message
        self.secret = secret

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog") as dialog:
            dialog.border_title = self.title_text
            dialog.border_subtitle = "c copiar · esc cerrar"
            yield Static(self.message)
            yield Static(f"\n[b $warning]{escape(self.secret)}[/]\n", classes="secret")
            yield Static("[dim]Guárdala ahora: no se volverá a mostrar.[/]")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Copiar", id="copy", variant="primary")
                yield Button("Cerrar", id="close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "copy":
            self.action_copy()
        else:
            self.dismiss(None)

    def action_copy(self) -> None:
        self.app.copy_to_clipboard(self.secret)
        self.app.notify("Copiada al portapapeles")

    def action_close(self) -> None:
        self.dismiss(None)


class LoginScreen(ModalScreen["dict | None"]):
    """Device flow: enseña el código y espera a que se confirme en el navegador."""

    BINDINGS = [Binding("escape", "cancel", "Cancelar"), Binding("o", "open", "Abrir navegador")]

    def __init__(self, code: dict, poll: Callable[[dict], dict]):
        super().__init__()
        self.code = code
        self.poll = poll
        self.cancelled = False

    def compose(self) -> ComposeResult:
        url = self.code["verification_uri"]
        with Vertical(classes="dialog") as dialog:
            dialog.border_title = "Iniciar sesión en MongoDB"
            dialog.border_subtitle = "o abrir navegador · esc cancelar"
            yield Static(f"1. Abre [b $accent]{escape(url)}[/]\n"
                         f"2. Inicia sesión con tu cuenta de MongoDB\n"
                         f"3. Introduce este código:")
            yield Static(f"[b $warning]{escape(self.code['user_code'])}[/]", classes="login-code")
            yield LoadingIndicator()
            yield Static("[dim]Esperando a que confirmes en el navegador…[/]", id="login-status")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Abrir navegador", id="open", variant="primary")
                yield Button("Cancelar", id="cancel")

    def on_mount(self) -> None:
        self.action_open()
        self.run_worker(self._wait, thread=True, exit_on_error=False, group="login")

    def _wait(self) -> None:
        try:
            token = self.poll(self.code)
        except Exception as e:  # noqa: BLE001 - se muestra al usuario
            if not self.cancelled:
                self.app.call_from_thread(self._failed, str(e))
            return
        if not self.cancelled:
            self.app.call_from_thread(self.dismiss, token)

    def _failed(self, message: str) -> None:
        self.query_one(LoadingIndicator).display = False
        self.query_one("#login-status", Static).update(f"[b $error]{escape(message)}[/]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "open":
            self.action_open()
        else:
            self.action_cancel()

    def action_open(self) -> None:
        self.app.open_url(self.code["verification_uri"])

    def action_cancel(self) -> None:
        # El hilo de sondeo no se puede interrumpir; simplemente se ignora su resultado.
        self.cancelled = True
        self.dismiss(None)
