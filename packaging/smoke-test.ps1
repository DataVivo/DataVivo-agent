<#
.SYNOPSIS
  Prueba de humo del ejecutable empaquetado: --version y --check con datos SQLite + CSV reales.
.EXAMPLE
  .\packaging\smoke-test.ps1 -Exe .\build\agent\bin\datavivo-agent.exe -ExpectedVersion 0.2.1
#>
param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [string]$ExpectedVersion
)
$ErrorActionPreference = "Stop"
$work = Join-Path ([IO.Path]::GetTempPath()) ("dv-smoke-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory $work | Out-Null

$out = (& $Exe --version) -join " "
Write-Host "version: $out"
if ($LASTEXITCODE -ne 0) { throw "--version falló" }
if ($ExpectedVersion -and $out -notmatch [regex]::Escape($ExpectedVersion)) { throw "Versión inesperada: $out" }

# Datos de prueba: SQLite (con Python del runner) y CSV
$py = Join-Path $work "mkdb.py"
Set-Content $py @'
import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
con.execute("CREATE TABLE CLIENTES (CODIGO INTEGER, NOMBRE TEXT)")
con.execute("INSERT INTO CLIENTES VALUES (1, 'Prueba')")
con.commit()
'@ -Encoding ascii
python $py (Join-Path $work "erp.db")
if ($LASTEXITCODE -ne 0) { throw "No se pudo crear la base SQLite de prueba" }
Set-Content (Join-Path $work "tarifas.csv") "codigo;precio`nT1;10" -Encoding utf8
$cfg = @"
cloud:
  url: wss://datavivo.es/agent/ws
sources:
  erp:
    type: sql
    url: sqlite:///$(($work -replace '\\','/'))/erp.db
    tables:
      clientes: {table: CLIENTES, columns: [CODIGO, NOMBRE]}
  hojas:
    type: excel
    path: $($work -replace '\\','/')
    csv_sep: ";"
    tables:
      tarifas: {file: tarifas.csv, columns: "*"}
"@
Set-Content (Join-Path $work "config.yaml") $cfg -Encoding utf8

$check = (& $Exe --config (Join-Path $work "config.yaml") --check) -join "`n"
Write-Host $check
if ($LASTEXITCODE -ne 0) { throw "--check falló" }
foreach ($expected in "clientes: CODIGO:int, NOMBRE:str", "tarifas: codigo:str") {
    if ($check -notmatch [regex]::Escape($expected)) { throw "Falta en el catálogo: $expected" }
}
Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "SMOKE OK"
