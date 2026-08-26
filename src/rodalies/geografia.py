"""Provincia y comunidad autonoma de cada estacion.

El GTFS de Renfe no dice donde esta cada estacion mas alla de sus coordenadas.
Pero Renfe publica aparte un listado de estaciones con provincia y poblacion:

    https://ssl.renfe.com/ftransit/Fichero_estaciones/estaciones.csv

De sus 1.027 estaciones con provincia utilizable, 669 coinciden con un stop_id
del GTFS: un 57,6 % de las 1.162. Para el resto se infiere la provincia por
cercania a la estacion etiquetada mas proxima, y **se marca** como inferida:
una validacion dejando fuera cada estacion y prediciendola con su vecina
acerto el 90,9 % de las veces, asi que el dato es util pero no es oficial y
quien analice debe poder distinguirlo.

La comunidad autonoma sale de la provincia con una tabla estatica: es una
correspondencia administrativa fija, no un dato que haya que descargar.
"""

from __future__ import annotations

import csv
import io
import logging
import math
from dataclasses import dataclass

from .http import fetch

log = logging.getLogger(__name__)

LISTADO_ESTACIONES = "https://ssl.renfe.com/ftransit/Fichero_estaciones/estaciones.csv"

# Provincia -> comunidad autonoma. Los nombres de provincia son los que usa el
# fichero de Renfe, tal cual, incluidas sus formas bilingues.
COMUNIDADES: dict[str, str] = {
    "ALBACETE": "Castilla-La Mancha",
    "ALICANTE/ALACANT": "Comunitat Valenciana",
    "ALMERIA": "Andalucia",
    "ARABA/ALAVA": "Pais Vasco",
    "ASTURIAS": "Principado de Asturias",
    "AVILA": "Castilla y Leon",
    "BADAJOZ": "Extremadura",
    "BARCELONA": "Catalunya",
    "BIZKAIA": "Pais Vasco",
    "BURGOS": "Castilla y Leon",
    "CACERES": "Extremadura",
    "CADIZ": "Andalucia",
    "CANTABRIA": "Cantabria",
    "CASTELLON/CASTELLO": "Comunitat Valenciana",
    "CIUDAD REAL": "Castilla-La Mancha",
    "CORDOBA": "Andalucia",
    "CORUNA, A": "Galicia",
    "CUENCA": "Castilla-La Mancha",
    "GIPUZKOA": "Pais Vasco",
    "GIRONA": "Catalunya",
    "GRANADA": "Andalucia",
    "GUADALAJARA": "Castilla-La Mancha",
    "HUELVA": "Andalucia",
    "HUESCA": "Aragon",
    "JAEN": "Andalucia",
    "LEON": "Castilla y Leon",
    "LLEIDA": "Catalunya",
    "LUGO": "Galicia",
    "MADRID": "Comunidad de Madrid",
    "MALAGA": "Andalucia",
    "MURCIA": "Region de Murcia",
    "NAVARRA": "Comunidad Foral de Navarra",
    "OURENSE": "Galicia",
    "PALENCIA": "Castilla y Leon",
    "PONTEVEDRA": "Galicia",
    "RIOJA, LA": "La Rioja",
    "SALAMANCA": "Castilla y Leon",
    "SEGOVIA": "Castilla y Leon",
    "SEVILLA": "Andalucia",
    "SORIA": "Castilla y Leon",
    "TARRAGONA": "Catalunya",
    "TERUEL": "Aragon",
    "TOLEDO": "Castilla-La Mancha",
    "VALENCIA/VALENCIA": "Comunitat Valenciana",
    "VALLADOLID": "Castilla y Leon",
    "ZAMORA": "Castilla y Leon",
    "ZARAGOZA": "Aragon",
}

# Acentos fuera para que el nombre del fichero (latin-1, con enes y tildes)
# case con las claves de arriba sin depender de la codificacion.
_TILDES = str.maketrans("ÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ", "AAAAEEEEIIIIOOOOUUUUNC")


def normalizar(nombre: str) -> str:
    """Mayusculas sin acentos, para comparar nombres de provincia."""
    return nombre.strip().upper().translate(_TILDES)


def comunidad_de(provincia: str | None) -> str | None:
    if not provincia:
        return None
    return COMUNIDADES.get(normalizar(provincia))


@dataclass(frozen=True, slots=True)
class Ubicacion:
    """Donde esta una estacion, y como de fiable es ese dato."""

    stop_id: str
    provincia: str | None
    comunidad: str | None
    poblacion: str | None
    codigo_postal: str | None
    origen: str  # "oficial" | "inferida"


def leer_listado(contenido: bytes) -> dict[str, Ubicacion]:
    """Parsea el CSV oficial de estaciones. Viene en latin-1 y con punto y coma."""
    texto = contenido.decode("latin-1", errors="replace")
    ubicaciones: dict[str, Ubicacion] = {}
    for fila in csv.DictReader(io.StringIO(texto), delimiter=";"):
        codigo = (fila.get("CODIGO") or "").strip()
        provincia = (fila.get("PROVINCIA") or "").strip()
        if not codigo or not provincia or normalizar(provincia) == "DESCONOCIDO":
            continue
        ubicaciones[codigo] = Ubicacion(
            stop_id=codigo,
            provincia=provincia,
            comunidad=comunidad_de(provincia),
            poblacion=(fila.get("POBLACION") or "").strip() or None,
            codigo_postal=(fila.get("CP") or "").strip() or None,
            origen="oficial",
        )
    return ubicaciones


def _distancia2(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia al cuadrado, con la longitud corregida por la latitud.

    No hace falta la formula del gran circulo: solo se compara cual es la mas
    cercana, y a esta escala el error de una aproximacion plana es irrelevante.
    """
    dlat = lat1 - lat2
    dlon = (lon1 - lon2) * math.cos(math.radians(lat1))
    return dlat * dlat + dlon * dlon


def completar_por_cercania(
    conocidas: dict[str, Ubicacion],
    coordenadas: dict[str, tuple[float, float]],
) -> dict[str, Ubicacion]:
    """Rellena las estaciones sin provincia con la de su vecina mas cercana.

    `coordenadas` es {stop_id: (lat, lon)} de TODAS las estaciones del GTFS.
    Devuelve el mapa completo, con las inferidas marcadas como tales.
    """
    referencia = [
        (u.stop_id, *coordenadas[u.stop_id], u)
        for u in conocidas.values()
        if u.stop_id in coordenadas
    ]
    if not referencia:
        log.warning("ninguna estacion oficial tiene coordenadas; no se infiere nada")
        return dict(conocidas)

    completo = dict(conocidas)
    inferidas = 0
    for stop_id, (lat, lon) in coordenadas.items():
        if stop_id in completo or lat is None or lon is None:
            continue
        mejor: Ubicacion | None = None
        mejor_d = float("inf")
        for _, rlat, rlon, ubic in referencia:
            d = _distancia2(lat, lon, rlat, rlon)
            if d < mejor_d:
                mejor, mejor_d = ubic, d
        if mejor is not None:
            completo[stop_id] = Ubicacion(
                stop_id=stop_id,
                provincia=mejor.provincia,
                comunidad=mejor.comunidad,
                poblacion=None,  # la poblacion NO se infiere: seria inventarla
                codigo_postal=None,
                origen="inferida",
            )
            inferidas += 1

    log.info(
        "geografia de estaciones: %d oficiales, %d inferidas por cercania",
        len(conocidas),
        inferidas,
    )
    return completo


def descargar(url: str = LISTADO_ESTACIONES, timeout: int = 60) -> dict[str, Ubicacion]:
    respuesta = fetch(url, timeout=timeout)
    ubicaciones = leer_listado(respuesta.content)
    log.info("listado oficial de estaciones: %d con provincia", len(ubicaciones))
    return ubicaciones
