@echo off
setlocal
cd /d "%~dp0"
title Taktspur

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Erstelle virtuelle Umgebung ...
  python -m venv .venv
  if errorlevel 1 py -3 -m venv .venv
  if not exist "%PY%" (
    echo FEHLER: Python wurde nicht gefunden. Bitte Python 3.10 oder neuer installieren ^(python.org^), "Add to PATH" anhaken.
    goto :fail
  )
)

rem Pakete installieren, wenn requirements.txt neu ist oder sich geaendert hat (z. B. nach einem Update)
fc /b requirements.txt ".venv\installed-requirements.txt" >nul 2>&1
if errorlevel 1 (
  echo Installiere benoetigte Pakete ^(einmalig, braucht Internet^) ...
  "%PY%" -m pip install --disable-pip-version-check -r requirements.txt
  if errorlevel 1 goto :fail
  copy /y requirements.txt ".venv\installed-requirements.txt" >nul
)

rem Browser erst oeffnen, wenn der Server wirklich antwortet
start "" /min powershell -NoProfile -Command "for($i=0;$i -lt 60;$i++){try{Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8775/api/health -TimeoutSec 1 | Out-Null;Start-Process 'http://127.0.0.1:8775';break}catch{Start-Sleep -Milliseconds 500}}"

"%PY%" scripts\run_local.py
if errorlevel 1 goto :fail
goto :eof

:fail
echo.
echo Taktspur wurde nicht gestartet. Bitte die Meldung oben lesen.
pause
exit /b 1
