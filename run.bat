@echo off
rem Запуск озвучки без активации venv (обходит запрет .ps1-скриптов в PowerShell)
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    >>crash.log echo ===== %date% %time% run.bat: не найдено окружение .venv =====
    echo Не найдено окружение .venv. Сначала выполните установку из README.md
    pause
    exit /b 1
)

".venv\Scripts\python.exe" main.py %*
set "code=%errorlevel%"

if "%code%"=="0" (
    if exist crash_native.tmp del crash_native.tmp
    exit /b 0
)

rem Расшифровка частых кодов аварийного завершения Windows
set "hint="
if "%code%"=="-1073741819" set "hint=Аварийное падение внутри библиотеки: access violation, 0xC0000005. Чаще всего PyTorch или звуковой драйвер."
if "%code%"=="-1073741795" set "hint=Процессор не поддерживает нужные инструкции: illegal instruction, 0xC000001D. PyTorch не работает на этом CPU."
if "%code%"=="-1073741515" set "hint=Не найдена системная DLL: 0xC0000135. Установите Microsoft Visual C++ Redistributable x64."
if "%code%"=="-1073740791" set "hint=Аварийное завершение процесса: 0xC0000409."
if "%code%"=="-1073741571" set "hint=Переполнение стека: 0xC00000FD."
if "%code%"=="101" set "hint=Python из .venv не запускается. Окружение скопировано с другого ПК или удалён Python - создайте .venv заново."
if "%code%"=="103" set "hint=Python из .venv не запускается. Окружение скопировано с другого ПК или удалён Python - создайте .venv заново."

>>crash.log echo ===== %date% %time% run.bat: скрипт завершился с кодом %code% =====
if defined hint >>crash.log echo %hint%
if exist crash_native.tmp (
    type crash_native.tmp >>crash.log
    del crash_native.tmp
)

echo.
echo Скрипт завершился с кодом %code%. %hint%
echo Подробности в crash.log
pause
exit /b %code%
