"""Logo y logotipo dibujados en la terminal con medios bloques (▀ ▄) en color.

Cada celda de texto muestra dos píxeles en vertical: el de arriba como color de
letra y el de abajo como fondo. Las celdas de terminal miden más o menos 1:2, así
que los píxeles salen cuadrados.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import resources

from PIL import Image
from rich.style import Style
from rich.text import Text

Color = tuple[int, int, int]

ALPHA_MIN = 48  # por debajo, el píxel se considera transparente


@lru_cache(maxsize=None)
def _asset(name: str) -> Image.Image:
    with resources.as_file(resources.files("mangosta") / "assets" / name) as path:
        return Image.open(path).convert("RGBA").copy()


def _hex(color: str) -> Color:
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _pixel(rgba: tuple[int, int, int, int], bg: Color | None) -> Color | None:
    r, g, b, a = rgba
    if a < ALPHA_MIN:
        return None
    if bg is None or a >= 250:
        return r, g, b
    k = a / 255  # bordes suaves: mezcla con el fondo del panel
    return tuple(round(c * k + f * (1 - k)) for c, f in zip((r, g, b), bg))


def half_blocks(image: Image.Image, width: int, background: str | None = None) -> Text:
    """Convierte una imagen RGBA en texto de ``width`` columnas."""
    height = max(2, round(image.height * width / image.width / 2) * 2)
    # Premultiplicado para que el reescalado no oscurezca los bordes transparentes.
    small = image.convert("RGBa").resize((width, height), Image.LANCZOS).convert("RGBA")
    bg = _hex(background) if background else None
    px = small.load()
    out = Text()
    for y in range(0, height, 2):
        if y:
            out.append("\n")
        for x in range(width):
            top, bottom = _pixel(px[x, y], bg), _pixel(px[x, y + 1], bg)
            if top and bottom:
                out.append("▀", Style(color=f"rgb{top}", bgcolor=f"rgb{bottom}"))
            elif top:
                out.append("▀", Style(color=f"rgb{top}"))
            elif bottom:
                out.append("▄", Style(color=f"rgb{bottom}"))
            else:
                out.append(" ")
    return out


@lru_cache(maxsize=32)
def logo(width: int, background: str | None = None) -> Text:
    return half_blocks(_asset("logo.png"), width, background)


@lru_cache(maxsize=32)
def wordmark(width: int, background: str | None = None) -> Text:
    return half_blocks(_asset("wordmark.png"), width, background)


def banner(width: int, background: str | None = None) -> Text:
    """Logo encima del nombre, centrados, para pantallas de bienvenida."""
    art = Text(justify="center")
    art.append_text(logo(round(width * 0.55), background))
    art.append("\n\n")
    art.append_text(wordmark(width, background))
    return art
