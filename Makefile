# Atajos del proyecto. En Windows, el equivalente esta en scripts\rodalies.ps1.
.DEFAULT_GOAL := help
COMPOSE_LIVE := docker compose
COMPOSE_DEMO := docker compose -f docker-compose.demo.yml

.PHONY: help demo up down logs ps migrate gtfs poll refresh check stats export \
        install test lint format typecheck psql backup clean

help: ## Muestra esta ayuda
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

demo: ## Demostracion con datos sinteticos, sin red y sin credenciales
	$(COMPOSE_DEMO) up -d --build
	@echo "Grafana:  http://localhost:3001   (admin/admin)"
	@echo "API:      http://localhost:8001/docs"

up: ## Captura real de Renfe (requiere .env con las contrasenas)
	$(COMPOSE_LIVE) up -d --build
	@echo "Grafana:  http://localhost:3000"
	@echo "API:      http://localhost:8000/docs"

down: ## Para los contenedores (conserva los volumenes)
	$(COMPOSE_LIVE) down
	$(COMPOSE_DEMO) down

logs: ## Sigue el log del ingestor
	$(COMPOSE_LIVE) logs -f ingestor

ps: ## Estado de los servicios
	$(COMPOSE_LIVE) ps

migrate: ## Aplica las migraciones pendientes
	$(COMPOSE_LIVE) run --rm ingestor rodalies migrate

gtfs: ## Descarga y carga el horario programado
	$(COMPOSE_LIVE) run --rm ingestor rodalies load-gtfs

poll: ## Una consulta a los feeds
	$(COMPOSE_LIVE) run --rm ingestor rodalies poll

refresh: ## Refresca la capa analitica
	$(COMPOSE_LIVE) run --rm ingestor rodalies refresh

check: ## Comprobaciones de calidad de datos
	$(COMPOSE_LIVE) run --rm ingestor rodalies check

stats: ## Resumen del historico acumulado
	$(COMPOSE_LIVE) run --rm ingestor rodalies stats

export: ## Exporta el historico a data/export
	$(COMPOSE_LIVE) run --rm ingestor rodalies export

psql: ## Consola SQL
	$(COMPOSE_LIVE) exec db psql -U rodalies -d rodalies

backup: ## Copia de seguridad del historico (el activo del proyecto)
	@mkdir -p backups
	@sello=$$(date +%Y%m%d_%H%M%S); \
	docker compose exec -T db pg_dump -U rodalies -d rodalies -Fc -f /tmp/r.dump; \
	docker compose cp db:/tmp/r.dump backups/rodalies_$$sello.dump; \
	docker compose exec -T db rm -f /tmp/r.dump; \
	echo "Copia en backups/rodalies_$$sello.dump"; \
	echo "Comprueba que se restaura: pg_restore --list backups/rodalies_$$sello.dump"

install: ## Instala el proyecto en el entorno local
	pip install -e ".[dev,api,analysis]"

test: ## Tests (los de integracion necesitan RODALIES_TEST_DATABASE_URL)
	pytest -v

lint: ## Estilo
	ruff check .
	ruff format --check .

typecheck: ## Tipado estricto
	mypy

format: ## Formatea el codigo
	ruff format .
	ruff check --fix .

clean: ## Borra artefactos locales (NO toca los volumenes de datos)
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage build dist
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
