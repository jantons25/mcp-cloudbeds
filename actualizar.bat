@echo off
rem Doble clic para actualizar el MCP de Cloudbeds (git pull). Luego reinicia Claude desde la bandeja.
cd /d "%~dp0"
".venv\Scripts\python.exe" scripts\actualizar.py %*
echo.
pause
