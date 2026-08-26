"""Interfaz de linea de comandos.

Un solo punto de entrada para todo lo que hace el proyecto:

    rodalies migrate      aplica las migraciones pendientes
    rodalies load-gtfs    descarga y carga el horario programado
    rodalies poll         una consulta a los feeds (util para depurar)
    rodalies run          bucle de ingesta continuo (lo que corre en Docker)
    rodalies refresh      refresca la capa analitica
    rodalies check        comprobaciones de calidad de datos
    rodalies stats        resumen del historico acumulado
    rodalies export       vuelca el historico a CSV
    rodalies capture      guarda los feeds crudos en disco
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import signal
import sys
from argparse import Namespace
from datetime import date, timedelta

from .config import Settings, load_settings
from .logging_setup import setup_logging

log = logging.getLogger("rodalies")

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_QUALITY = 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rodalies",
        description="Observatorio de puntualidad de Rodalies / Cercanias Renfe",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate", help="aplica las migraciones de base de datos")

    gtfs = sub.add_parser("load-gtfs", help="descarga y carga el horario programado")
    gtfs.add_argument("--force", action="store_true", help="recarga aunque no haya cambiado")
    gtfs.add_argument("--file", help="usa un zip GTFS local en vez de descargarlo")

    sub.add_parser("poll", help="una consulta a los feeds y salida")

    run = sub.add_parser("run", help="bucle de ingesta continuo")
    run.add_argument("--migrate", action="store_true", help="migra antes de arrancar")

    refresh = sub.add_parser("refresh", help="refresca las vistas materializadas")
    refresh.add_argument("--blocking", action="store_true", help="sin CONCURRENTLY")

    sub.add_parser("check", help="comprobaciones de calidad de datos")
    sub.add_parser("stats", help="resumen del historico")

    export = sub.add_parser("export", help="vuelca el historico a CSV")
    export.add_argument("--desde", help="fecha inicial AAAA-MM-DD")
    export.add_argument("--hasta", help="fecha final AAAA-MM-DD")
    export.add_argument("--salida", default=None, help="ruta del CSV")
    export.add_argument("--source", default="renfe", help="renfe o synthetic")

    capture = sub.add_parser("capture", help="guarda los feeds crudos en disco")
    capture.add_argument("--salida", default="data/captures")

    return parser


def _cmd_migrate(settings: Settings) -> int:
    from .db import apply_migrations, wait_for_db

    wait_for_db(settings.database_url)
    applied = apply_migrations(settings.database_url)
    if applied:
        print("Migraciones aplicadas: " + ", ".join(applied))
    else:
        print("La base de datos ya estaba al dia.")
    return EXIT_OK


def _cmd_load_gtfs(settings: Settings, args: Namespace) -> int:
    from .ingest import Ingestor

    with Ingestor(settings) as ingestor:
        summary = ingestor.load_gtfs(force=args.force, path=args.file)
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    return EXIT_OK


def _cmd_poll(settings: Settings) -> int:
    from .ingest import Ingestor

    with Ingestor(settings) as ingestor:
        ingestor.prepare()
        results = ingestor.poll_once()
    for result in results:
        print(result.describe())
    return EXIT_OK if all(r.ok for r in results) else EXIT_ERROR


def _cmd_run(settings: Settings, args: Namespace) -> int:
    from .db import apply_migrations, wait_for_db
    from .ingest import Ingestor

    wait_for_db(settings.database_url)
    if args.migrate:
        apply_migrations(settings.database_url)

    stopping = {"flag": False}

    def _handle(signum: int, _frame: object) -> None:
        log.info("recibida senal %s, terminando el ciclo en curso...", signum)
        stopping["flag"] = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        # En Windows y fuera del hilo principal no siempre se puede capturar.
        with contextlib.suppress(ValueError, AttributeError):
            signal.signal(sig, _handle)

    with Ingestor(settings) as ingestor:
        ingestor.run_forever(stop_flag=lambda: stopping["flag"])
    return EXIT_OK


def _cmd_refresh(settings: Settings, args: Namespace) -> int:
    from .ingest import Ingestor

    with Ingestor(settings) as ingestor:
        for vista, ms in ingestor.refresh_analytics(concurrently=not args.blocking):
            print(f"{vista}: {ms} ms")
    return EXIT_OK


def _cmd_check(settings: Settings) -> int:
    from .db import session
    from .repository import Repository

    with session(settings.database_url) as conn:
        checks = Repository(conn).quality_checks()

    ancho = max((len(c[0]) for c in checks), default=20)
    peor = EXIT_OK
    for nombre, estado, detalle in checks:
        print(f"{estado:<6} {nombre:<{ancho}}  {detalle}")
        if estado == "ERROR":
            peor = EXIT_QUALITY
    return peor


def _cmd_stats(settings: Settings) -> int:
    from .db import session
    from .repository import Repository

    with session(settings.database_url) as conn:
        resumen = Repository(conn).summary()
    for clave, valor in resumen.items():
        print(f"{clave:<20} {valor}")
    return EXIT_OK


def _cmd_export(settings: Settings, args: Namespace) -> int:
    from .export import export_csv

    hasta = date.fromisoformat(args.hasta) if args.hasta else date.today()
    desde = date.fromisoformat(args.desde) if args.desde else hasta - timedelta(days=30)
    salida = args.salida or f"{settings.export_dir}/rodalies_{desde}_{hasta}.csv"
    ruta, filas = export_csv(
        settings.database_url, salida, desde=desde, hasta=hasta, source=args.source
    )
    print(f"{filas} filas exportadas a {ruta}")
    return EXIT_OK


def _cmd_capture(settings: Settings, args: Namespace) -> int:
    """Guarda los feeds crudos: sirven de material para la fuente `replay`."""
    import json as _json
    from datetime import UTC, datetime
    from pathlib import Path

    from .sources import build_source

    destino = Path(args.salida)
    destino.mkdir(parents=True, exist_ok=True)
    sello = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")

    with build_source(settings) as source:
        for feed in ("trip_updates", "alerts", "vehicle_positions"):
            raw = source.fetch(feed)
            extension = "json" if raw.fmt == "json" else "pb"
            ruta = destino / f"{feed}_{sello}.{extension}"
            if isinstance(raw.payload, bytes):
                ruta.write_bytes(raw.payload)
            else:
                ruta.write_text(_json.dumps(raw.payload, ensure_ascii=False), encoding="utf-8")
            print(f"{ruta} ({ruta.stat().st_size} bytes)")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = load_settings()
    setup_logging(settings.log_level, settings.log_json)

    try:
        if args.command == "migrate":
            return _cmd_migrate(settings)
        if args.command == "load-gtfs":
            return _cmd_load_gtfs(settings, args)
        if args.command == "poll":
            return _cmd_poll(settings)
        if args.command == "run":
            return _cmd_run(settings, args)
        if args.command == "refresh":
            return _cmd_refresh(settings, args)
        if args.command == "check":
            return _cmd_check(settings)
        if args.command == "stats":
            return _cmd_stats(settings)
        if args.command == "export":
            return _cmd_export(settings, args)
        if args.command == "capture":
            return _cmd_capture(settings, args)
    except KeyboardInterrupt:
        log.info("interrumpido por el usuario")
        return EXIT_OK
    except Exception as exc:
        log.error("%s: %s", type(exc).__name__, exc)
        if settings.log_level == "DEBUG":
            raise
        return EXIT_ERROR

    return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
