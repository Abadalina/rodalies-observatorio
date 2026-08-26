"""Fuente de reproduccion: sirve capturas guardadas en disco, en bucle.

Util para demostrar el proyecto con datos reales sin depender de la red (por
ejemplo en una entrevista, o para reproducir un incidente concreto).
"""

from __future__ import annotations

import itertools
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .base import RawFeed, Source

log = logging.getLogger(__name__)


class SinCapturas(FileNotFoundError):
    """El directorio de reproduccion no tiene capturas del feed pedido."""


class ReplaySource(Source):
    name = "replay"

    def __init__(self, settings: Any = None, directory: str | Path = "data/captures") -> None:
        self.settings = settings
        self.directory = Path(directory)
        self._cycles: dict[str, Iterator[Path] | None] = {}

    def _files(self, feed: str) -> list[Path]:
        patterns = (f"{feed}*.json", f"{feed}*.pb")
        found: list[Path] = []
        for pattern in patterns:
            found.extend(sorted(self.directory.glob(pattern)))
        return found

    def fetch(self, feed: str) -> RawFeed:
        if feed not in self._cycles:
            files = self._files(feed)
            if not files:
                log.warning("sin capturas de %s en %s", feed, self.directory)
                self._cycles[feed] = None
            else:
                self._cycles[feed] = itertools.cycle(files)

        cycle = self._cycles[feed]
        if cycle is None:
            # Antes se devolvia un feed vacio con marca de tiempo cero. Eso
            # convertia un error de configuracion en un dato de aspecto valido;
            # ahora falla de forma visible y el ciclo lo registra como fallo.
            raise SinCapturas(
                f"no hay capturas de {feed} en {self.directory}; "
                "genera alguna con `rodalies capture`"
            )

        path = next(cycle)
        return RawFeed(
            feed=feed,
            payload=path.read_bytes(),
            fmt="pb" if path.suffix == ".pb" else "json",
            status=200,
        )
