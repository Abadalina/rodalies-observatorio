<#
.SYNOPSIS
    Copia de seguridad del historico, a prueba de PowerShell.

.DESCRIPTION
    El volcado se genera DENTRO del contenedor y se copia despues con
    `docker compose cp`. Canalizar la salida binaria de pg_dump por el pipeline
    de PowerShell puede corromper el fichero segun la version y la codificacion,
    y una copia corrupta es peor que no tener copia: da falsa tranquilidad.
#>
[CmdletBinding()]
param([string]$Destino = "backups")

$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Test-Path $Destino)) { New-Item -ItemType Directory $Destino | Out-Null }

$sello   = Get-Date -Format 'yyyyMMdd_HHmmss'
$interno = "/tmp/rodalies_$sello.dump"
$externo = Join-Path $Destino "rodalies_$sello.dump"
$usuario = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { 'rodalies' }
$base    = if ($env:POSTGRES_DB)   { $env:POSTGRES_DB }   else { 'rodalies' }

Write-Host "Generando el volcado dentro del contenedor..." -ForegroundColor Cyan
docker compose exec -T db pg_dump -U $usuario -d $base -Fc -f $interno
if ($LASTEXITCODE -ne 0) { throw "pg_dump devolvio $LASTEXITCODE" }

docker compose cp "db:$interno" $externo
docker compose exec -T db rm -f $interno

$tam = (Get-Item $externo).Length
if ($tam -lt 1024) { throw "La copia parece vacia ($tam bytes). Revisala antes de fiarte." }
Write-Host ("Copia guardada en {0} ({1:N1} MB)" -f $externo, ($tam / 1MB)) -ForegroundColor Green
Write-Host "Comprueba que se puede restaurar: pg_restore --list `"$externo`"" -ForegroundColor Yellow
