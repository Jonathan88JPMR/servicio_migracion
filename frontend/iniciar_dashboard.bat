@echo off
setlocal

set "PROYECTO=C:\Users\jonathan.marquina\Documents\Jonathan Marquina\proyectos\servicio_documentos"
cd /d "%PROYECTO%\frontend"

if "%SQL_PASSWORD%"=="" (
    echo [ERROR] No esta definida la variable de entorno SQL_PASSWORD.
    echo Inicia desde una consola que tenga la variable configurada.
    exit /b 1
)

set "PYTHON=C:\Users\jonathan.marquina\AppData\Local\Programs\Python\Python314\python.exe"
"%PYTHON%" "app.py"
