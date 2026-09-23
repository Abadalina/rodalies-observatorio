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
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from .. import __version__
from ..config import Settings, load_settings
from . import queries

log = logging.getLogger(__name__)

VENTANA_MAXIMA_DIAS = 400
SOURCE_PATTERN = "^(renfe|synthetic|replay)$"


def get_settings() -> Settings:
    return load_settings()


def origen(
    source: str | None = Query(None, pattern=SOURCE_PATTERN, description="Origen de los datos"),
) -> str:
    """Usa el origen del servicio cuando el cliente no especifica otro.

    En producción es ``renfe`` y en la demo es ``synthetic``. Mantener un valor
    fijo aquí dejaba vacía la API de demostración aunque el ingestor estuviera
    escribiendo correctamente.
    """
    return source or get_settings().source


class Database:
    """Pool de conexiones minimo, creado al arrancar la aplicacion."""

    def __init__(self) -> None:
        self.pool: Any = None

    def open(self, settings: Settings) -> None:
        from psycopg_pool import ConnectionPool

        # `check` valida la conexion ANTES de entregarla. Sin esto, una conexion
        # que la base haya cerrado por su cuenta —un reinicio, un tiempo de
        # espera, un corte de red— se entrega rota y la primera consulta que la
        # use falla. Ocurre de tarde en tarde y basta para que /salud conteste
        # 503 con todo perfectamente sano, que es la clase de falso positivo que
        # ensena a ignorar la monitorizacion.
        self.pool = ConnectionPool(
            settings.database_url,
            min_size=1,
            max_size=8,
            open=True,
            check=ConnectionPool.check_connection,
        )

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
    version=__version__,
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
            "/colores",
            "/buscar/trenes",
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
        # Se registra. Antes se devolvia el 503 en silencio y, cuando pasaba, no
        # habia forma de saber por que: ni una linea en el log del servicio cuyo
        # unico trabajo es avisar de que algo va mal.
        log.exception("/salud no ha podido consultar la base de datos")
        return JSONResponse({"estado": "sin_base_de_datos", "detalle": str(exc)}, 503)

    por_feed = {str(f["feed"]): f for f in filas}
    limite = ajustes.stale_after_seconds
    detalle: list[dict[str, Any]] = []
    degradados: list[str] = []

    for feed in ajustes.active_feeds():
        fila = por_feed.get(feed)
        if fila is None:
            estado_feed = "sin_datos"
        elif fila.get("antiguedad_s") is None or fila["antiguedad_s"] > limite:
            estado_feed = "obsoleto"
        elif not fila.get("ultima_ok", True):
            estado_feed = "ultimo_intento_fallido"
        else:
            estado_feed = "ok"

        if estado_feed != "ok":
            degradados.append(feed)
        detalle.append({"feed": feed, "estado": estado_feed, **(fila or {})})

    estado = "ok" if not degradados else "degradado"
    # jsonable_encoder porque JSONResponse usa json.dumps a pelo y las filas
    # traen marcas de tiempo. El resto de endpoints no falla porque FastAPI las
    # codifica por su cuenta al devolver dict o list.
    return JSONResponse(
        jsonable_encoder(
            {
                "estado": estado,
                "limite_antiguedad_s": limite,
                "feeds_degradados": degradados,
                "feeds": detalle,
            }
        ),
        200 if estado == "ok" else 503,
    )


@app.get("/calidad", tags=["meta"], summary="Comprobaciones de calidad de datos")
def calidad() -> list[dict[str, Any]]:
    return db.fetch(queries.CALIDAD)


@app.get("/kpi", tags=["puntualidad"], summary="Indicadores por dia")
def kpi(
    ventana: dict[str, date] = Depends(rango),
    nucleo: str | None = Query(None, description="codigo de nucleo, p. ej. 51"),
    source: str = Depends(origen),
) -> list[dict[str, Any]]:
    return db.fetch(queries.KPI_DIARIO, {**ventana, "nucleo": nucleo, "source": source})


@app.get("/lineas", tags=["puntualidad"], summary="Ranking de lineas")
def lineas(
    ventana: dict[str, date] = Depends(rango),
    nucleo: str | None = Query(None),
    source: str = Depends(origen),
) -> list[dict[str, Any]]:
    return db.fetch(queries.RANKING_LINEAS, {**ventana, "nucleo": nucleo, "source": source})


@app.get("/estaciones", tags=["puntualidad"], summary="Ranking de estaciones")
def estaciones(
    ventana: dict[str, date] = Depends(rango),
    nucleo: str | None = Query(None),
    source: str = Depends(origen),
    minimo: int = Query(20, ge=1, description="paradas observadas minimas"),
    limite: int = Query(50, ge=1, le=2000),
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
    source: str = Depends(origen),
) -> list[dict[str, Any]]:
    return db.fetch(
        queries.FRANJAS,
        {**ventana, "nucleo": nucleo, "linea": linea, "source": source},
    )


@app.get("/resumen", tags=["puntualidad"], summary="Cifras de cabecera")
def resumen(
    ventana: dict[str, date] = Depends(rango),
    nucleo: str | None = Query(None, description="Nucleo de Cercanias; 51 es Catalunya"),
    source: str = Depends(origen),
) -> dict[str, Any]:
    filas = db.fetch(queries.RESUMEN, {**ventana, "nucleo": nucleo, "source": source})
    return filas[0] if filas else {}


@app.get("/semana", tags=["puntualidad"], summary="Puntualidad por dia de la semana")
def semana(
    ventana: dict[str, date] = Depends(rango),
    nucleo: str | None = Query(None, description="Nucleo de Cercanias; 51 es Catalunya"),
    source: str = Depends(origen),
) -> list[dict[str, Any]]:
    return db.fetch(queries.SEMANA, {**ventana, "nucleo": nucleo, "source": source})


@app.get("/colores", tags=["meta"], summary="Color oficial de cada linea")
def colores(
    nucleo: str | None = Query(None, description="Nucleo de Cercanias; 51 es Catalunya"),
) -> list[dict[str, Any]]:
    """El color con el que Renfe identifica cada linea, por nucleo."""
    return db.fetch(queries.COLORES, {"nucleo": nucleo})


@app.get("/buscar/trenes", tags=["puntualidad"], summary="Buscar un tren por su numero")
def buscar_trenes(
    numero: str = Query(..., pattern=r"^[0-9]{1,6}$", description="Numero comercial o su inicio"),
    nucleo: str | None = Query(None, description="Nucleo de Cercanias; 51 es Catalunya"),
    limite: int = Query(8, ge=1, le=30),
    source: str = Depends(origen),
) -> list[dict[str, Any]]:
    """Trenes vistos en los ultimos catorce dias cuyo numero empieza por `numero`.

    Solo digitos: el patron se pasa a un LIKE y un `%` o un `_` tecleados
    cambiarian lo que se busca.
    """
    return db.fetch(
        queries.BUSCAR_TRENES,
        {"patron": f"{numero}%", "nucleo": nucleo, "limite": limite, "source": source},
    )


@app.get("/alertas", tags=["incidencias"], summary="Avisos activos")
def alertas(limite: int = Query(50, ge=1, le=200)) -> list[dict[str, Any]]:
    return db.fetch(queries.ALERTAS, {"limite": limite})


@app.get("/posiciones", tags=["en vivo"], summary="Donde esta cada tren ahora")
def posiciones(
    nucleo: str | None = Query(None, description="Nucleo de Cercanias; 51 es Catalunya"),
    source: str = Depends(origen),
) -> list[dict[str, Any]]:
    """Ultima posicion conocida de cada tren en circulacion, con su retraso.

    Solo trenes vistos en los ultimos diez minutos: si Renfe deja de publicar
    uno, desaparece del mapa en vez de quedarse clavado donde se le vio por
    ultima vez, que es lo que haria creer que sigue ahi.
    """
    return db.fetch(queries.POSICIONES, {"nucleo": nucleo, "source": source})


@app.get("/trazados", tags=["en vivo"], summary="Geometria de las vias")
def trazados(
    nucleo: str | None = Query(None, description="Nucleo de Cercanias; 51 es Catalunya"),
) -> list[dict[str, Any]]:
    """El trazado real de cada recorrido, para dibujar la red de fondo."""
    return db.fetch(queries.TRAZADOS, {"nucleo": nucleo})


@app.get(
    "/trenes/{trip_id}/historial",
    tags=["puntualidad"],
    summary="Como se ha portado un tren estos dias",
)
def historial_tren(
    trip_id: str,
    dias: int = Query(14, ge=1, le=90),
    source: str = Depends(origen),
) -> dict[str, Any]:
    """Ficha del tren y su retraso dia a dia.

    Devuelve la ficha aunque no haya historico: que un tren no haya circulado
    estos dias es una respuesta, no un error.
    """
    ficha = db.fetch(queries.FICHA_TREN, {"trip_id": trip_id})
    dias_sueltos = db.fetch(
        queries.HISTORIAL_TREN, {"trip_id": trip_id, "dias": dias, "source": source}
    )
    if not ficha and not dias_sueltos:
        raise HTTPException(404, f"el tren {trip_id} no aparece ni en el horario ni en la serie")
    return {"tren": ficha[0] if ficha else {"trip_id": trip_id}, "dias": dias_sueltos}


@app.get("/trenes/{trip_id}", tags=["puntualidad"], summary="Trayectoria de un tren")
def tren(trip_id: str, service_date: date | None = None) -> list[dict[str, Any]]:
    filas = db.fetch(queries.TRAYECTORIA, {"trip_id": trip_id, "service_date": service_date})
    if not filas:
        raise HTTPException(404, f"sin observaciones para el tren {trip_id}")
    return filas
