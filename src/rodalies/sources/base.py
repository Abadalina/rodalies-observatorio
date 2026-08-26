"""Contrato comun de las fuentes de datos.

Una fuente solo sabe entregar el cuerpo crudo de un feed. Decodificar y
normalizar es responsabilidad de `rodalies.parsing`, de modo que el codigo de
negocio es identico tanto si los bytes vienen de Renfe, de una captura guardada
o del generador sintetico.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

FEEDS = ("trip_updates", "alerts", "vehicle_positions")


@dataclass(frozen=True)
class RawFeed:
    """Cuerpo sin interpretar de un feed, mas metricas de la descarga."""

    feed: str
    payload: bytes | dict[str, Any]
    fmt: str
    status: int = 200
    duration_ms: int = 0
    not_modified: bool = False

    @property
    def size(self) -> int:
        return len(self.payload) if isinstance(self.payload, bytes) else 0


class Source:
    """Interfaz que implementan todas las fuentes."""

    name = "base"

    def fetch(self, feed: str) -> RawFeed:  # pragma: no cover - interfaz
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - opcional
        pass

    def __enter__(self) -> Source:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
