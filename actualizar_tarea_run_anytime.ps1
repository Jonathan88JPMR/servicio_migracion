$taskName = "MigrarAdjuntosPortalProveedores"

Write-Host "Configurando la tarea '$taskName' para ejecutarse aunque no estes logueado." -ForegroundColor Cyan
Write-Host "Ingresa tu usuario y contrasena de Windows cuando se solicite." -ForegroundColor Cyan
Write-Host ""

$cred = Get-Credential -Message "Credenciales de Windows para la tarea programada"

if (-not $cred) {
    Write-Host "No se proporcionaron credenciales. Operacion cancelada." -ForegroundColor Red
    exit 1
}

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Set-ScheduledTask `
    -TaskName $taskName `
    -User $cred.UserName `
    -Password $cred.GetNetworkCredential().Password `
    -Settings $settings | Out-Null

Write-Host ""
Write-Host "Tarea actualizada correctamente." -ForegroundColor Green
