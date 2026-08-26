"""Cliente HTTP con reintentos y descarga condicional.

Lo minimo para que la ingesta sobreviva sola: la fuente publica puede fallar, y
un fallo transitorio no debe tumbar el proceso ni provocar un hueco en la serie.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger(__name__)

USER_AGENT = "rodalies-observatory/0.1 (+https://github.com/; proyecto de portfolio)"

# Errores que merece la pena reintentar: cortes de red y caidas temporales.
RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class FetchError(RuntimeError):
    """La descarga fallo despues de agotar los reintentos."""


@dataclass(frozen=True)
class Response:
    url: str
    status: int
    content: bytes
    duration_ms: int
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False

    @property
    def size(self) -> int:
        return len(self.content)


def fetch(
    url: str,
    *,
    timeout: int = 30,
    retries: int = 3,
    etag: str | None = None,
    last_modified: str | None = None,
    session: requests.Session | None = None,
) -> Response:
    """Descarga una URL con reintentos y espera exponencial con jitter."""
    owned = session is None
    session = session or requests.Session()
    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    last_error: Exception | None = None
    try:
        for attempt in range(1, max(1, retries) + 1):
            started = time.perf_counter()
            try:
                response = session.get(url, timeout=timeout, headers=headers)
                elapsed = int((time.perf_counter() - started) * 1000)

                if response.status_code == 304:
                    return Response(url, 304, b"", elapsed, etag, last_modified, True)
                if response.status_code in RETRYABLE_STATUS:
                    raise FetchError(f"HTTP {response.status_code} en {url}")
                response.raise_for_status()

                return Response(
                    url=url,
                    status=response.status_code,
                    content=response.content,
                    duration_ms=elapsed,
                    etag=response.headers.get("ETag"),
                    last_modified=response.headers.get("Last-Modified"),
                )
            except (requests.RequestException, FetchError) as exc:
                last_error = exc
                if attempt >= retries:
                    break
                backoff = min(30.0, 2 ** (attempt - 1)) + random.uniform(0, 0.5)
                log.warning(
                    "fallo al descargar %s (intento %d/%d): %s; reintento en %.1fs",
                    url,
                    attempt,
                    retries,
                    exc,
                    backoff,
                )
                time.sleep(backoff)
    finally:
        if owned:
            session.close()

    raise FetchError(f"No se pudo descargar {url} tras {retries} intentos: {last_error}")


def download_to(url: str, destination: str | Path, **kwargs: Any) -> Response:
    """Como `fetch`, pero ademas deja el cuerpo en disco (para el zip del GTFS)."""
    response = fetch(url, **kwargs)
    if not response.not_modified:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
    return response
