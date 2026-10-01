"""Opciones globales de la invocación actual (perfil, --json, --yes...)."""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class State:
    profile: str | None = None
    uri: str | None = None
    json: bool = False
    yes: bool = False
    # Dentro de la TUI los mensajes se muestran como notificaciones: (mensaje, severidad).
    notifier: Callable[[str, str], None] | None = None


state = State()
