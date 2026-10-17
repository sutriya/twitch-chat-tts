@echo off
rem Запуск озвучки без активации venv (обходит запрет .ps1-скриптов в PowerShell)
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Не найдено окружение .venv. Сначала выполните установку из README.md
    pause
    exit /b 1
)

".venv\Scripts\python.exe" main.py %*
if errorlevel 1 pause
