"""Perfiles de conexión guardados en ~/.mangosta/config.json.

Cualquier valor puede ser una referencia a variable de entorno con el
formato ``env:NOMBRE_VARIABLE`` para no guardar secretos en claro.
"""

import json
import os
from pathlib import Path

from .errors import MangostaError
from .state import state

SECRET_KEYS = {"private_key", "client_secret", "access_token", "refresh_token"}


def config_dir() -> Path:
    return Path(os.environ.get("MANGOSTA_HOME") or Path.home() / ".mangosta")


def config_path() -> Path:
    return config_dir() / "config.json"


def load() -> dict:
    path = config_path()
    if not path.exists():
        return {"current": None, "profiles": {}}
    with path.open(encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("current", None)
    cfg.setdefault("profiles", {})
    return cfg


def save(cfg: dict) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(path)


def resolve(value):
    """Sustituye ``env:VAR`` por el valor de la variable de entorno."""
    if isinstance(value, str) and value.startswith("env:"):
        var = value[4:]
        if var not in os.environ:
            raise MangostaError(f"La variable de entorno {var} no está definida")
        return os.environ[var]
    return value


def active_profile_name() -> str | None:
    return state.profile or load()["current"]


def get_profile() -> dict:
    name = active_profile_name()
    if name is None:
        if state.uri:
            return {"name": "(uri)", "uri": state.uri}
        raise MangostaError(
            "No hay perfil activo. Crea uno con:  mangosta profile add NOMBRE --uri \"mongodb://...\""
        )
    profile = load()["profiles"].get(name)
    if profile is None:
        raise MangostaError(f"El perfil '{name}' no existe (mira: mangosta profile list)")
    profile = dict(profile, name=name)
    if state.uri:
        profile["uri"] = state.uri
    return profile


def has_atlas(profile: dict) -> bool:
    atlas = profile.get("atlas") or {}
    return bool(
        atlas.get("refresh_token")
        or (atlas.get("public_key") and atlas.get("private_key"))
        or (atlas.get("client_id") and atlas.get("client_secret"))
    )


def atlas_auth_kind(profile: dict) -> str | None:
    atlas = profile.get("atlas") or {}
    if atlas.get("refresh_token"):
        return "login"
    if atlas.get("client_id") and atlas.get("client_secret"):
        return "service account"
    if atlas.get("public_key") and atlas.get("private_key"):
        return "API key"
    return None


def update_atlas(profile_name: str, **fields) -> None:
    """Actualiza campos de ``atlas`` de un perfil guardado (``None`` borra el campo)."""
    cfg = load()
    profile = cfg["profiles"].get(profile_name)
    if profile is None:
        return
    atlas = profile.setdefault("atlas", {})
    for key, value in fields.items():
        if value is None:
            atlas.pop(key, None)
        else:
            atlas[key] = value
    save(cfg)
