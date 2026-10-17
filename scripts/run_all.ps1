# Full lab run (Windows PowerShell). Run from the repository root:
#   powershell -ExecutionPolicy Bypass -File .\scripts\run_all.ps1
# (ASCII only on purpose: Windows PowerShell 5.1 misreads UTF-8 without BOM)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
docker compose up -d
Write-Host "Waiting for Trino to become healthy..."
while ((docker inspect -f "{{.State.Health.Status}}" trino 2>$null) -ne "healthy") { Start-Sleep -Seconds 3 }
docker ps
docker exec trino trino --execute "SHOW CATALOGS"
docker compose run --rm runner python runner/lakehouse.py all
docker compose --profile bi up -d superset
Write-Host "Done: REPORT.md is updated, Superset is starting at http://localhost:8088 (admin/admin)"
