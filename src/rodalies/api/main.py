"""API HTTP de solo lectura sobre el historico de puntualidad.

Es una de las extensiones opcionales del proyecto: da una URL que un
entrevistador puede abrir, y la documentacion interactiva sale gratis en
`/docs`. Solo lee: la escritura es exclusiva del ingestor.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from ..config import Settings, load_settings
from . import queries

log = logging.getLogger(__name__)

VENTANA_MAXIMA_DIAS = 400


def get_settings() -> Settings:
    return load_settings()


class Database:
    """Pool de conexiones minimo, creado al arrancar la aplicacion."""

    def __init__(self) -> None:
        self.pool: Any = None

    def open(self, settings: Settings) -> None:
        from psycopg_pool import ConnectionPool

        self.pool = ConnectionPool(settings.database_url, min_size=1, max_size=8, open=True)

    def close(self) -> None:
        if self.pool is not None:
            self.pool.close()
            self.pool = None

    def fetch(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Ejecuta una consulta y devuelve filas como diccionarios."""
        if self.pool is None:
            raise RuntimeError("el pool de conexiones no esta abierto")
        with self.pool.connection() as conn:
            cursor = conn.execute(sql, params or {})
            columnas = [c.name for c in cursor.description]
            filas: list[dict[str, Any]] = [
                dict(zip(columnas, fila, strict=False)) for fila in cursor.fetchall()
            ]
            return filas


db = Database()


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    db.open(load_settings())
    log.info("API lista")
    yield
    db.close()


app = FastAPI(
    title="Observatorio de puntualidad de Rodalies",
    description=(
        "Historico propio de retrasos de Rodalies/Cercanias, construido a partir "
        "de los feeds GTFS-Realtime publicos de Renfe. Solo lectura."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


def rango(
    desde: date | None = Query(None, description="fecha inicial (AAAA-MM-DD)"),
    hasta: date | None = Query(None, description="fecha final (AAAA-MM-DD)"),
) -> dict[str, date]:
    """Normaliza el rango de fechas: por defecto, los ultimos 30 dias."""
    hasta = hasta or date.today()
    desde = desde or hasta - timedelta(days=30)
    if desde > hasta:
        raise HTTPException(400, "'desde' es posterior a 'hasta'")
    if (hasta - desde).days > VENTANA_MAXIMA_DIAS:
        raise HTTPException(400, f"el rango no puede superar {VENTANA_MAXIMA_DIAS} dias")
    return {"desde": desde, "hasta": hasta}


@app.get("/", tags=["meta"], summary="Indice de la API")
def indice() -> dict[str, Any]:
    return {
        "proyecto": "Observatorio de puntualidad de Rodalies",
        "fuente": "GTFS-Realtime de Renfe (gtfsrt.renfe.com)",
        "documentacion": "/docs",
        "endpoints": [
            "/salud",
            "/calidad",
            "/kpi",
            "/lineas",
            "/estaciones",
            "/franjas",
            "/alertas",
            "/trenes/{trip_id}",
        ],
    }


@app.get("/salud", tags=["meta"], summary="Estado de la ingesta")
def salud() -> JSONResponse:
    """Estado por feed. Devuelve 503 si **cualquiera** de los feeds activos falla.

    Se comprueba feed a feed a proposito. Resumirlo con el minimo de antiguedades
    era un falso positivo: un feed recien actualizado tapaba a otro que llevaba
    horas sin responder, y el sistema se declaraba sano mientras perdia datos.
    """
    ajustes = get_settings()
    try:
        filas = db.fetch(queries.SALUD)
    except Exception as exc:
        return JSONResponse({"estado": "sin_base_de_datos", "detalle": str(exc)}, 503)

    por_feed = {str(f["feed"]): f for f in filas}
    limite = ajustes.stale_after_seconds
    detalle: list[dict[str, Any]] = []
    degradados: list[str] = []

    for feed in ajustes.active_feeds():
        fila = por_feed.get(feed)
        if fila is None:
            estado_feed = "sin_datos"
        elif (fila.get("antiguedad_s") or 10**9) > limite:
            estado_feed = "obsoleto"
        elif not fila.get("ultima_ok", True):
            estado_feed = "ultimo_intento_fallido"
        else:
            estado_feed = "ok"

        if estado_feed != "ok":
            degradados.append(feed)
        detalle.append({"feed": feed, "estado": estado_feed, **(fila or {})})

    estado = "ok" if not degradados else "degradado"
    return JSONResponse(
        {
            "estado": estado,
            "limite_antiguedad_s": limite,
            "feeds_degradados": degradados,
            "feeds": detalle,
        },
        200 if estado == "ok" else 503,
    )


@app.get("/calidad", tags=["meta"], summary="Comprobaciones de calidad de datos")
def calidad() -> list[dict[str, Any]]:
    return db.fetch(queries.CALIDAD)


@app.get("/kpi", tags=["puntualidad"], summary="Indicadores por dia")
def kpi(
    ventana: dict[str, date] = Depends(rango),
    nucleo: str | None = Query(None, description="codigo de nucleo, p. ej. 51"),
    source: str = Query("renfe", pattern="^(renfe|synthetic)$"),
) -> list[dict[str, Any]]:
    return db.fetch(queries.KPI_DIARIO, {**ventana, "nucleo": nucleo, "source": source})


@app.get("/lineas", tags=["puntualidad"], summary="Ranking de lineas")
def lineas(
    ventana: dict[str, date] = Depends(rango),
    nucleo: str | None = Query(None),
    source: str = Query("renfe", pattern="^(renfe|synthetic)$"),
) -> list[dict[str, Any]]:
    return db.fetch(queries.RANKING_LINEAS, {**ventana, "nucleo": nucleo, "source": source})


@app.get("/estaciones", tags=["puntualidad"], summary="Ranking de estaciones")
def estaciones(
    ventana: dict[str, date] = Depends(rango),
    nucleo: str | None = Query(None),
    source: str = Query("renfe", pattern="^(renfe|synthetic)$"),
    minimo: int = Query(20, ge=1, description="paradas observadas minimas"),
    limite: int = Query(50, ge=1, le=500),
) -> list[dict[str, Any]]:
    return db.fetch(
        queries.RANKING_ESTACIONES,
        {**ventana, "nucleo": nucleo, "source": source, "minimo": minimo, "limite": limite},
    )


@app.get("/franjas", tags=["puntualidad"], summary="Retraso por franja horaria")
def franjas(
    ventana: dict[str, date] = Depends(rango),
    nucleo: str | None = Query(None),
    linea: str | None = Query(None, description="p. ej. R2N"),
    source: str = Query("renfe", pattern="^(renfe|synthetic)$"),
) -> list[dict[str, Any]]:
    return db.fetch(
        queries.FRANJAS,
        {**ventana, "nucleo": nucleo, "linea": linea, "source": source},
    )


@app.get("/alertas", tags=["incidencias"], summary="Avisos activos")
def alertas(limite: int = Query(50, ge=1, le=200)) -> list[dict[str, Any]]:
    return db.fetch(queries.ALERTAS, {"limite": limite})


@app.get("/trenes/{trip_id}", tags=["puntualidad"], summary="Trayectoria de un tren")
def tren(trip_id: str, service_date: date | None = None) -> list[dict[str, Any]]:
    filas = db.fetch(queries.TRAYECTORIA, {"trip_id": trip_id, "service_date": service_date})
    if not filas:
        raise HTTPException(404, f"sin observaciones para el tren {trip_id}")
    return filas
