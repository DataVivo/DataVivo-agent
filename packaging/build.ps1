<#
.SYNOPSIS
  Empaqueta el agente (ejecutable único + instalador) en dist\:
    datavivo-agent-windows.zip            nombre fijo  -> .../releases/latest/download/datavivo-agent-windows.zip
    datavivo-agent-<versión>-windows.zip  copia versionada
  Funciona dentro del monorepo (local-agent/) y en el repositorio público datavivo-agent.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#>
param(
    [string]$Python
)
$ErrorActionPreference = "Stop"
$agentDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
# Repositorio independiente (tiene .git propio) -> salida dentro; monorepo -> salida en la raíz del monorepo
$outRoot = if (Test-Path (Join-Path $agentDir ".git")) { $agentDir } else { (Resolve-Path (Join-Path $agentDir "..")).Path }
if (-not $Python) {
    $candidates = @((Join-Path $agentDir ".venv\Scripts\python.exe"), (Join-Path $agentDir "..\.venv\Scripts\python.exe"))
    $Python = ($candidates | Where-Object { Test-Path $_ } | Select-Object -First 1)
    if (-not $Python) { $Python = (Get-Command python).Source }
}
$build = Join-Path $outRoot "build\agent"
$dist = Join-Path $outRoot "dist"

& $Python -m pip install --quiet "pyinstaller>=6.16"
if ($LASTEXITCODE -ne 0) { throw "No se pudo instalar PyInstaller" }

$version = ((& $Python (Join-Path $agentDir "agent.py") --version) -split " ")[-1].Trim()
if (-not $version) { throw "No se pudo leer la versión del agente" }
Write-Host "Empaquetando DataVivo Agent $version"

Push-Location $agentDir
try {
    & $Python -m PyInstaller agent.py `
        --onefile --console --noconfirm --clean `
        --name datavivo-agent `
        --distpath (Join-Path $build "bin") --workpath (Join-Path $build "work") --specpath $build `
        --collect-submodules sqlalchemy.dialects `
        --hidden-import pyodbc --hidden-import openpyxl --hidden-import dbfread `
        --hidden-import connectors.sql_connector --hidden-import connectors.dbf_connector --hidden-import connectors.excel_connector `
        --exclude-module pytest --exclude-module tkinter
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller falló" }
} finally { Pop-Location }

$stage = Join-Path $build "package"
Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $stage | Out-Null
Copy-Item (Join-Path $build "bin\datavivo-agent.exe") $stage
Copy-Item (Join-Path $PSScriptRoot "install-agent.ps1"), (Join-Path $PSScriptRoot "uninstall-agent.ps1"), (Join-Path $PSScriptRoot "LEEME.txt") $stage
Copy-Item (Join-Path $agentDir "config.example.yaml") $stage

New-Item -ItemType Directory -Force $dist | Out-Null
foreach ($name in "datavivo-agent-windows.zip", "datavivo-agent-$version-windows.zip") {
    $zip = Join-Path $dist $name
    Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -Force
    $hash = (Get-FileHash $zip -Algorithm SHA256).Hash
    Set-Content -Path "$zip.sha256" -Value "$hash  $name" -Encoding ascii
    Write-Host "OK -> $zip"
    Write-Host "SHA256 $hash"
}
