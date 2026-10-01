class MangostaError(Exception):
    """Error esperado: se muestra al usuario sin traceback."""


class AtlasError(MangostaError):
    """Error devuelto por la Atlas Admin API."""


def describe_error(e: BaseException) -> str:
    """Mensaje corto y legible para cualquier error (para notificaciones)."""
    from pymongo.errors import PyMongoError, ServerSelectionTimeoutError

    if isinstance(e, ServerSelectionTimeoutError):
        reason = str(e).split(" (configured timeouts")[0].split(", Timeout:")[0]
        return f"No se pudo conectar a MongoDB: {reason}"
    if isinstance(e, PyMongoError):
        return f"MongoDB: {e}"
    if isinstance(e, MangostaError):
        return str(e)
    return f"{type(e).__name__}: {e}"
