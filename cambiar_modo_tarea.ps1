param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("PRUEBA", "PRODUCCION")]
    [string]$Modo,
    [ValidateSet("LOCAL", "COMPARTIDA")]
    [string]$TipoPrueba = "LOCAL"
)

$taskName = "MigrarAdjuntosPortalProveedores"
$proyecto = "C:\Users\jonathan.marquina\Documents\Jonathan Marquina\proyectos\servicio_documentos"
$batchPath = Join-Path $proyecto "iniciar_servicio.bat"
$configPrueba = Join-Path $proyecto "config_modo.bat"
$configProduccion = Join-Path $proyecto "config.env"

if (-not (Test-Path $batchPath) -or -not (Test-Path $configPrueba) -or -not (Test-Path $configProduccion)) {
    Write-Host "[ERROR] Faltan archivos de inicio o configuracion" -ForegroundColor Red
    exit 1
}

if ($Modo -eq "PRUEBA") {
    $config = Get-Content $configPrueba
    $config = $config -replace '^set "TIPO_COPIA_PRUEBA=.*"$', "set `"TIPO_COPIA_PRUEBA=$TipoPrueba`""
    Set-Content -Path $configPrueba -Value $config -Encoding ASCII
    $descripcion = "Migrar adjuntos - PRUEBA $TipoPrueba (cada 2 horas)"
} else {
    $config = Get-Content $configProduccion
    $config = $config -replace '^HABILITAR_PRODUCCION=.*$', 'HABILITAR_PRODUCCION=NO'
    Set-Content -Path $configProduccion -Value $config -Encoding ASCII
    $descripcion = "Migrar adjuntos - PRODUCCION BLOQUEADA HASTA APROBACION (cada 2 horas)"
}

try {
    $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$batchPath`" $Modo"
    # Diario a las 00:00 repitiendo cada 2 horas durante el dia = cada 2 horas siempre.
    $repetition = (New-ScheduledTaskTrigger -Once -At "00:00" `
        -RepetitionInterval (New-TimeSpan -Hours 2) `
        -RepetitionDuration (New-TimeSpan -Days 1)).Repetition
    $trigger = New-ScheduledTaskTrigger -Daily -At "00:00"
    $trigger.Repetition = $repetition
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive
    $task = New-ScheduledTask -Action $action -Principal $principal -Trigger $trigger -Settings $settings -Description $descripcion

    # -Force crea la tarea si no existe o la reemplaza si ya existe.
    Register-ScheduledTask -TaskName $taskName -InputObject $task -Force | Out-Null

    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Tarea '$taskName' configurada en $Modo" -ForegroundColor Cyan
    Write-Host "Comando: cmd.exe /c `"$batchPath`" $Modo" -ForegroundColor Cyan
    if ($Modo -eq "PRUEBA") {
        Write-Host "Tipo de copia: $TipoPrueba" -ForegroundColor Cyan
    } else {
        Write-Host "Produccion permanece bloqueada en config.env" -ForegroundColor Yellow
    }
    Write-Host "============================================================" -ForegroundColor Cyan
} catch {
    Write-Host "[ERROR] No se pudo actualizar la tarea: $_" -ForegroundColor Red
    exit 1
}
