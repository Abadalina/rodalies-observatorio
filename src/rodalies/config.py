"""Configuracion del proyecto, validada al arrancar.

Todo llega por variables de entorno: `.env.example` las documenta y
`docker-compose.yml` las inyecta. Ningun secreto vive en el codigo.

La validacion la hace Pydantic con cotas explicitas. No es adorno: un
`RODALIES_POLL_SECONDS=0` mal copiado convertiria el ingestor en un bucle que
machaca la fuente publica, y un valor no numerico se tragaria en silencio si el
parseo fuera manual. Mejor reventar al iniciar que descubrirlo en produccion.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Zona horaria de referencia del servicio ferroviario espanol.
MADRID = ZoneInfo("Europe/Madrid")

# Nucleos de Cercanias tal y como aparecen en los dos primeros caracteres del
# `trip_id` / `route_id` del GTFS de Renfe. Verificado contra routes.txt.
NUCLEOS: dict[str, str] = {
    "10": "Madrid",
    "20": "Asturias",
    "30": "Sevilla",
    "31": "Cadiz",
    "32": "Malaga",
    "40": "Valencia",
    "41": "Murcia/Alacant",
    "45": "Cartagena-Los Nietos",
    "46": "Ferrol-Ortigueira",
    "47": "Leon",
    "51": "Barcelona (Rodalies)",
    "60": "Bilbao",
    "61": "San Sebastian",
    "62": "Santander",
    "70": "Zaragoza",
    "90": "Cercedilla-Cotos",
}

SourceName = Literal["renfe", "synthetic", "replay"]
FeedFormat = Literal["json", "pb"]

FEEDS: tuple[str, ...] = ("trip_updates", "alerts", "vehicle_positions")


class Settings(BaseSettings):
    """Ajustes efectivos del proceso. Inmutables una vez construidos."""

    model_config = SettingsConfigDict(
        env_prefix="RODALIES_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    database_url: str = "postgresql://rodalies:rodalies@localhost:5433/rodalies"

    source: SourceName = "renfe"
    feed_format: FeedFormat = "json"
    rt_base_url: str = "https://gtfsrt.renfe.com"
    gtfs_static_url: str = "https://ssl.renfe.com/ftransit/Fichero_CER_FOMENTO/fomento_transit.zip"

    # Nucleos a capturar. Vacio o "all" = toda Espana (unas diez veces mas datos).
    nucleos: str = "51"

    # El feed se refresca cada ~20 s. Bajar de 20 no aporta y castiga un servicio
    # publico gratuito; el maximo evita configurar por error una cadencia inutil.
    poll_seconds: int = Field(default=60, ge=20, le=3600)
    refresh_seconds: int = Field(default=900, ge=60, le=86_400)
    gtfs_reload_seconds: int = Field(default=86_400, ge=3600, le=604_800)
    http_timeout: int = Field(default=30, ge=5, le=300)
    http_retries: int = Field(default=3, ge=1, le=10)

    on_time_threshold_s: int = Field(default=180, ge=0, le=3600)
    late_threshold_s: int = Field(default=300, ge=0, le=7200)
    severe_threshold_s: int = Field(default=900, ge=0, le=86_400)

    # Tolerancia de la comprobacion de salud: cuantos ciclos puede fallar un feed
    # antes de considerarlo caido.
    health_max_missed_cycles: int = Field(default=3, ge=1, le=100)

    log_level: str = "INFO"
    log_json: bool = False
    ingest_alerts: bool = True
    ingest_vehicle_positions: bool = False
    # Contrasena del rol de solo lectura que usan Grafana y los consumidores
    # externos. Vacia = el rol se queda sin acceso, que es el valor seguro.
    readonly_password: str = ""
    export_dir: str = "data/export"
    replay_dir: str = "data/captures"

    @field_validator("log_level")
    @classmethod
    def _upper(cls, value: str) -> str:
        nivel = value.strip().upper()
        if nivel not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"RODALIES_LOG_LEVEL invalido: {value!r}")
        return nivel

    @field_validator("nucleos")
    @classmethod
    def _normalize_nucleos(cls, value: str) -> str:
        return value.strip().lower()

    @property
    def nucleo_codes(self) -> tuple[str, ...]:
        """Codigos de nucleo configurados. Tupla vacia = todos."""
        if self.nucleos in {"", "all", "todos", "*"}:
            return ()
        return tuple(sorted({p.strip() for p in self.nucleos.split(",") if p.strip()}))

    @property
    def all_nucleos(self) -> bool:
        return not self.nucleo_codes

    def keeps(self, identifier: str) -> bool:
        """True si el identificador pertenece a un nucleo configurado."""
        if self.all_nucleos:
            return True
        return identifier[:2] in self.nucleo_codes

    def feed_url(self, feed: str) -> str:
        extension = "json" if self.feed_format == "json" else "pb"
        return f"{self.rt_base_url.rstrip('/')}/{feed}.{extension}"

    def active_feeds(self) -> tuple[str, ...]:
        feeds = ["trip_updates"]
        if self.ingest_alerts:
            feeds.append("alerts")
        if self.ingest_vehicle_positions:
            feeds.append("vehicle_positions")
        return tuple(feeds)

    def nucleo_names(self) -> list[str]:
        if self.all_nucleos:
            return ["todos"]
        return [NUCLEOS.get(code, code) for code in self.nucleo_codes]

    @property
    def stale_after_seconds(self) -> int:
        """Antiguedad a partir de la cual un feed se considera caido."""
        return self.poll_seconds * self.health_max_missed_cycles + 60


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_settings() -> Settings:
    """Alias explicito para el codigo que no quiere la version cacheada."""
    return Settings()
