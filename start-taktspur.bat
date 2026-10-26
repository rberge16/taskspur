@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Erstelle virtuelle Umgebung ...
  python -m venv .venv || goto :fail
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail
)
echo Taktspur laeuft auf http://127.0.0.1:8775  (Beenden mit Strg+C)
start "" "http://127.0.0.1:8775"
".venv\Scripts\python.exe" scripts\run_local.py
goto :eof
:fail
echo Einrichtung fehlgeschlagen.
pause
