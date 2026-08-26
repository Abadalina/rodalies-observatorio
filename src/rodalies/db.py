"""Conexion a PostgreSQL y aplicacion de migraciones.

Las migraciones son ficheros `.sql` numerados que se aplican en orden y se
anotan en `public.schema_migration`. Se hace asi, y no con los scripts de
arranque de la imagen de Postgres, porque esos solo se ejecutan cuando el
volumen esta vacio: el volumen de datos es justo lo que nunca hay que borrar.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg

log = logging.getLogger(__name__)


def _default_migrations_dir() -> Path:
    """Directorio de migraciones: `RODALIES_MIGRATIONS_DIR` o el del repositorio."""
    import os

    override = os.environ.get("RODALIES_MIGRATIONS_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "db" / "migrations"


MIGRATIONS_DIR = _default_migrations_dir()

BOOTSTRAP_SQL = """
CREATE TABLE IF NOT EXISTS public.schema_migration (
    filename    text PRIMARY KEY,
    checksum    text NOT NULL,
    applied_at  timestamptz NOT NULL DEFAULT now(),
    duration_ms integer
);
"""


def connect(database_url: str, *, autocommit: bool = False) -> psycopg.Connection:
    return psycopg.connect(database_url, autocommit=autocommit)


def wait_for_db(database_url: str, *, attempts: int = 30, delay: float = 2.0) -> None:
    """Espera a que la base de datos acepte conexiones.

    En `docker compose` el ingestor arranca a la vez que Postgres; sin esta
    espera el primer arranque falla siempre.
    """
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with connect(database_url) as conn:
                conn.execute("SELECT 1")
            if attempt > 1:
                log.info("base de datos disponible tras %d intentos", attempt)
            return
        except psycopg.Error as exc:
            last = exc
            log.info("esperando a la base de datos (%d/%d)...", attempt, attempts)
            time.sleep(delay)
    raise RuntimeError(f"la base de datos no respondio tras {attempts} intentos: {last}")


@contextmanager
def session(database_url: str, *, autocommit: bool = False) -> Iterator[psycopg.Connection]:
    conn = connect(database_url, autocommit=autocommit)
    try:
        yield conn
        if not autocommit:
            conn.commit()
    except Exception:
        if not autocommit:
            conn.rollback()
        raise
    finally:
        conn.close()


def migration_files(directory: Path | str = MIGRATIONS_DIR) -> list[Path]:
    return sorted(Path(directory).glob("*.sql"))


def apply_migrations(
    database_url: str, directory: Path | str = MIGRATIONS_DIR, *, verbose: bool = True
) -> list[str]:
    """Aplica las migraciones pendientes. Devuelve las que se han ejecutado.

    Cada fichero se guarda con su checksum: si alguien edita una migracion ya
    aplicada, se avisa en lugar de dejar dos entornos silenciosamente distintos.
    """
    applied: list[str] = []
    files = migration_files(directory)
    if not files:
        raise FileNotFoundError(f"no hay migraciones en {directory}")

    with session(database_url, autocommit=True) as conn:
        conn.execute(BOOTSTRAP_SQL)
        known = {
            row[0]: row[1]
            for row in conn.execute("SELECT filename, checksum FROM public.schema_migration")
        }

        for path in files:
            sql = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()

            if path.name in known:
                if known[path.name] != checksum:
                    log.warning(
                        "la migracion %s ha cambiado desde que se aplico; "
                        "crea una migracion nueva en lugar de editarla",
                        path.name,
                    )
                continue

            started = time.perf_counter()
            with conn.transaction():
                conn.execute(sql)
                conn.execute(
                    "INSERT INTO public.schema_migration (filename, checksum, duration_ms) "
                    "VALUES (%s, %s, %s)",
                    (path.name, checksum, int((time.perf_counter() - started) * 1000)),
                )
            applied.append(path.name)
            if verbose:
                log.info(
                    "migracion aplicada: %s (%.0f ms)",
                    path.name,
                    (time.perf_counter() - started) * 1000,
                )

    return applied
