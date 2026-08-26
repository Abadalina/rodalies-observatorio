# Imagen unica para el ingestor y para la API: mismo codigo, distinto comando.
# Compartirla evita que las dos partes se desincronicen y ahorra una
# construccion entera en CI.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Europe/Madrid

WORKDIR /app

# Dependencias primero: esta capa se cachea mientras no cambie pyproject.toml.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip && pip install ".[api]"

# Las migraciones viajan con la imagen para que `rodalies migrate` funcione
# tambien en un contenedor efimero.
COPY db ./db

# Usuario sin privilegios: el contenedor no necesita ser root para nada.
RUN useradd --create-home --uid 10001 rodalies \
    && mkdir -p /app/data && chown -R rodalies:rodalies /app
USER rodalies

ENV RODALIES_MIGRATIONS_DIR=/app/db/migrations

# Comprueba que hubo una captura correcta reciente, no que el paquete importa:
# un ingestor parado seis horas superaba la comprobacion anterior sin problema.
HEALTHCHECK --interval=60s --timeout=15s --start-period=120s --retries=3 \
    CMD python -m rodalies.healthcheck || exit 1

CMD ["rodalies", "run", "--migrate"]
