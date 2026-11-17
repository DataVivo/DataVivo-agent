<#
.SYNOPSIS
  Instala DataVivo Agent como tarea de arranque (cuenta SYSTEM, reinicio automático).
.EXAMPLE
  # PowerShell como administrador, en la carpeta descomprimida:
  .\install-agent.ps1 -Token "dva_..." -Config .\config.yaml
  .\install-agent.ps1 -Token "dva_..." -Config .\config.yaml -DbUrl "mssql+pyodbc://lector:clave@MI_DSN"
#>
param(
    [Parameter(Mandatory = $true)][string]$Token,
    [string]$Config = (Join-Path $PSScriptRoot "config.yaml"),
    [string]$DbUrl,
    [string]$InstallDir = "$env:ProgramFiles\DataVivo",
    [string]$DataDir = "$env:ProgramData\DataVivo"
)
$ErrorActionPreference = "Stop"
$TaskName = "DataVivo Agent"

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Ejecuta este script en una consola de PowerShell abierta como administrador."
}
if ($Token -notmatch '^dva_[0-9a-f]{16}_[A-Za-z0-9_-]{20,}$') { throw "El token no tiene el formato esperado (dva_...)." }
if (-not (Test-Path $Config)) { throw "No se encuentra $Config. Descárgalo desde el panel (paso 2)." }

Write-Host "1/5 Copiando ficheros..."
New-Item -ItemType Directory -Force $InstallDir, $DataDir | Out-Null
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) { Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue; Start-Sleep -Seconds 2 }
Copy-Item (Join-Path $PSScriptRoot "datavivo-agent.exe") $InstallDir -Force
if ((Resolve-Path $Config).Path -ne (Join-Path $DataDir "config.yaml")) {
    Copy-Item $Config (Join-Path $DataDir "config.yaml") -Force
}

Write-Host "2/5 Guardando secretos protegidos..."
Set-Content -Path (Join-Path $DataDir "agent.token") -Value $Token -Encoding ascii -NoNewline
if ($DbUrl) {
    Set-Content -Path (Join-Path $DataDir "db.url") -Value $DbUrl -Encoding utf8 -NoNewline
    Write-Host "   Cadena de BD guardada en $DataDir\db.url -> usa 'url_file: $($DataDir -replace '\\','/')/db.url' en config.yaml"
}
# Solo SYSTEM y Administradores pueden leer la carpeta de datos (token y credenciales)
icacls $DataDir /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" | Out-Null

Write-Host "3/5 Validando configuración..."
$exe = Join-Path $InstallDir "datavivo-agent.exe"
& $exe --config (Join-Path $DataDir "config.yaml") --check
if ($LASTEXITCODE -ne 0) { throw "La configuración no es válida. Corrige config.yaml y vuelve a ejecutar el instalador." }

Write-Host "4/5 Registrando tarea de arranque..."
$taskArgs = "--config `"$DataDir\config.yaml`" --log-file `"$DataDir\agent.log`""
$action = New-ScheduledTaskAction -Execute $exe -Argument $taskArgs -WorkingDirectory $DataDir
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$taskPrincipal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Principal $taskPrincipal -Description "Conector DataVivo (solo lectura)" -Force | Out-Null

Write-Host "5/5 Iniciando agente..."
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 5
Get-Content (Join-Path $DataDir "agent.log") -Tail 5 -ErrorAction SilentlyContinue
Write-Host ""
Write-Host "Listo. Comprueba en el panel que el agente aparece como 'Conectado'."
Write-Host "Logs: $DataDir\agent.log"
Write-Host "Nota: la cuenta SYSTEM no ve unidades de red mapeadas (Z:). Usa rutas UNC (\\servidor\carpeta) en config.yaml."
