<#
.SYNOPSIS
  Desinstala DataVivo Agent. Con -Purge borra también config, token y logs.
#>
param(
    [switch]$Purge,
    [string]$InstallDir = "$env:ProgramFiles\DataVivo",
    [string]$DataDir = "$env:ProgramData\DataVivo"
)
$ErrorActionPreference = "Stop"
$TaskName = "DataVivo Agent"
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}
Get-Process datavivo-agent -ErrorAction SilentlyContinue | Stop-Process -Force
Remove-Item $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
if ($Purge) { Remove-Item $DataDir -Recurse -Force -ErrorAction SilentlyContinue }
Write-Host "DataVivo Agent desinstalado." $(if (-not $Purge) { "Configuración conservada en $DataDir" })
Write-Host "Recuerda revocar el token del agente en el panel si no vas a reinstalarlo."
