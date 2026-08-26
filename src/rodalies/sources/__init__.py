"""Registro de fuentes de datos.

Cambiar de fuente es cambiar una variable de entorno (`RODALIES_SOURCE`), no
tocar codigo: `renfe` en produccion, `synthetic` para la demo y los tests,
`replay` para reproducir capturas guardadas.
"""

from __future__ import annotations

from ..config import Settings
from .base import FEEDS, RawFeed, Source
from .renfe import RenfeSource
from .replay import ReplaySource
from .synthetic import SyntheticSource

SOURCES = {
    "renfe": RenfeSource,
    "synthetic": SyntheticSource,
    "replay": ReplaySource,
}

__all__ = [
    "FEEDS",
    "SOURCES",
    "RawFeed",
    "RenfeSource",
    "ReplaySource",
    "Source",
    "SyntheticSource",
    "build_source",
]


def build_source(settings: Settings) -> Source:
    """Instancia la fuente indicada en la configuracion."""
    try:
        factory = SOURCES[settings.source]
    except KeyError:
        opciones = ", ".join(sorted(SOURCES))
        raise ValueError(
            f"RODALIES_SOURCE={settings.source!r} no existe. Opciones: {opciones}"
        ) from None
    fuente: Source = factory(settings)
    return fuente
