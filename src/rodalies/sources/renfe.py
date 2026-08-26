"""Fuente real: feeds GTFS-Realtime publicados por Renfe.

Endpoints (verificados el 2026-08-25, ver `docs/FUENTE_DATOS.md`):

    https://gtfsrt.renfe.com/trip_updates.{json,pb}
    https://gtfsrt.renfe.com/alerts.{json,pb}
    https://gtfsrt.renfe.com/vehicle_positions.{json,pb}

Cubren los quince nucleos de Cercanias, Rodalies de Barcelona incluido.
"""

from __future__ import annotations

import logging

import requests

from ..config import Settings
from ..http import fetch
from .base import RawFeed, Source

log = logging.getLogger(__name__)


class RenfeSource(Source):
    name = "renfe"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.session = requests.Session()

    def fetch(self, feed: str) -> RawFeed:
        url = self.settings.feed_url(feed)
        response = fetch(
            url,
            timeout=self.settings.http_timeout,
            retries=self.settings.http_retries,
            session=self.session,
        )
        return RawFeed(
            feed=feed,
            payload=response.content,
            fmt=self.settings.feed_format,
            status=response.status,
            duration_ms=response.duration_ms,
            not_modified=response.not_modified,
        )

    def close(self) -> None:
        self.session.close()
