param(
    [ValidateSet("PRUEBA", "PRODUCCION")]
    [string]$Modo = "PRUEBA",
    [string]$Ruta = "C:\Servicios\servicio_documentos",
    [int]$IntervaloHoras = 2
)

$taskName = "MigrarAdjuntosPortalProveedores"
$batchPath = Join-Path $Ruta "iniciar_servicio_sin_python.bat"

if (-not (Test-Path $batchPath)) {
    Write-Host "[ERROR] No existe $batchPath" -ForegroundColor Red
    exit 1
}

try {
    $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$batchPath`" $Modo"

    # Diario a las 00:00 repitiendo cada N horas durante el dia = cada N horas siempre.
    $repetition = (New-ScheduledTaskTrigger -Once -At "00:00" `
        -RepetitionInterval (New-TimeSpan -Hours $IntervaloHoras) `
        -RepetitionDuration (New-TimeSpan -Days 1)).Repetition
    $trigger = New-ScheduledTaskTrigger -Daily -At "00:00"
    $trigger.Repetition = $repetition

    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive
    $descripcion = "Migrar adjuntos del portal de proveedores a Spring Gestion Documental - $Modo cada $IntervaloHoras horas"

    $task = New-ScheduledTask -Action $action -Principal $principal -Trigger $trigger -Settings $settings -Description $descripcion

    # -Force crea la tarea si no existe o la reemplaza si ya existe.
    Register-ScheduledTask -TaskName $taskName -InputObject $task -Force | Out-Null

    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Tarea '$taskName' registrada." -ForegroundColor Cyan
    Write-Host "Comando: cmd.exe /c `"$batchPath`" $Modo" -ForegroundColor Cyan
    Write-Host "Frecuencia: cada $IntervaloHoras horas" -ForegroundColor Cyan
    Write-Host "Para que corra sin sesion iniciada, ejecuta actualizar_tarea_run_anytime.ps1" -ForegroundColor Yellow
    Write-Host "============================================================" -ForegroundColor Cyan
} catch {
    Write-Host "[ERROR] No se pudo registrar la tarea: $_" -ForegroundColor Red
    exit 1
}
