@echo off
setlocal

echo [BUILD] Verificando e instalando PyInstaller...
python -m pip install --upgrade pyinstaller

echo [BUILD] Limpiando builds anteriores...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist *.spec del /f /q *.spec

echo [BUILD] Empaquetando PRUEBA...
pyinstaller --onefile --name migrar_prueba --log-level=WARN "migrar_adjuntos_spring_prueba.py"
if errorlevel 1 (
    echo [ERROR] Fallo el build de migrar_prueba.exe
    exit /b 1
)

echo [BUILD] Empaquetando PRODUCCION...
pyinstaller --onefile --name migrar_produccion --log-level=WARN "migrar_adjuntos_spring.py"
if errorlevel 1 (
    echo [ERROR] Fallo el build de migrar_produccion.exe
    exit /b 1
)

echo [BUILD] Empaquetamiento finalizado.
echo Ejecutables en: dist\
dir dist\*.exe

endlocal
