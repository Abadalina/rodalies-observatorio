<#
.SYNOPSIS
    Atajos del proyecto para Windows (equivalente al Makefile).

.DESCRIPTION
    Envuelve `docker compose` para no tener que recordar los comandos largos.
    Requiere Docker Desktop en marcha.

.EXAMPLE
    .\scripts\rodalies.ps1 up
    .\scripts\rodalies.ps1 demo
    .\scripts\rodalies.ps1 logs
    .\scripts\rodalies.ps1 backup
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('up', 'demo', 'down', 'logs', 'ps', 'migrate', 'gtfs', 'poll',
                 'refresh', 'check', 'stats', 'export', 'psql', 'backup', 'help')]
    [string]$Accion = 'help'
)

$ErrorActionPreference = 'Stop'
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz

function Invoke-Compose { docker compose @args }
function Invoke-ComposeDemo { docker compose -f docker-compose.demo.yml @args }

switch ($Accion) {
    'up' {
        Invoke-Compose up -d --build
        Write-Host ""
        Write-Host "Grafana:  http://localhost:3000" -ForegroundColor Green
        Write-Host "API:      http://localhost:8000/docs" -ForegroundColor Green
    }
    'demo' {
        # Perfil independiente: volumen, credenciales y puertos propios. No puede
        # tocar el historico real ni aunque se quiera.
        Invoke-ComposeDemo up -d --build
        Write-Host ""
        Write-Host "Demo con datos sinteticos en http://localhost:3001" -ForegroundColor Green
        Write-Host "Usuario admin / admin. El historico real no se toca." -ForegroundColor Yellow
    }
    'down'    { Invoke-Compose down }
    'logs'    { Invoke-Compose logs -f ingestor }
    'ps'      { Invoke-Compose ps }
    'migrate' { Invoke-Compose run --rm ingestor rodalies migrate }
    'gtfs'    { Invoke-Compose run --rm ingestor rodalies load-gtfs }
    'poll'    { Invoke-Compose run --rm ingestor rodalies poll }
    'refresh' { Invoke-Compose run --rm ingestor rodalies refresh }
    'check'   { Invoke-Compose run --rm ingestor rodalies check }
    'stats'   { Invoke-Compose run --rm ingestor rodalies stats }
    'export'  { Invoke-Compose run --rm ingestor rodalies export }
    'psql'    { Invoke-Compose exec db psql -U rodalies -d rodalies }
    'backup'  { & "$PSScriptRootackup.ps1" }
    default {
        Write-Host "Uso: .\scripts\rodalies.ps1 <accion>" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "  up       levanta el stack con datos reales de Renfe"
        Write-Host "  demo     levanta el stack con datos sinteticos"
        Write-Host "  down     para los contenedores (conserva los datos)"
        Write-Host "  logs     sigue el log del ingestor"
        Write-Host "  ps       estado de los servicios"
        Write-Host "  migrate  aplica las migraciones"
        Write-Host "  gtfs     carga el horario programado"
        Write-Host "  poll     una consulta a los feeds"
        Write-Host "  refresh  refresca la capa analitica"
        Write-Host "  check    comprobaciones de calidad"
        Write-Host "  stats    resumen del historico"
        Write-Host "  export   exporta el dataset a CSV"
        Write-Host "  psql     consola SQL"
        Write-Host "  backup   copia de seguridad del historico"
    }
}
