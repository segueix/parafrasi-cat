@echo off
REM Obre parafrasi-cat en un navegador. No cal escriure cap ordre:
REM feu doble clic sobre aquest fitxer.
cd /d "%~dp0"

where py >nul 2>&1
if %errorlevel%==0 (set PYTHON=py -3) else (set PYTHON=python)

%PYTHON% -c "import parafrasi_cat" >nul 2>&1
if errorlevel 1 (
  echo Instal.lant parafrasi-cat per primera vegada...
  %PYTHON% -m pip install -e .
  if errorlevel 1 (
    echo La instal.lacio ha fallat.
    pause
    exit /b 1
  )
)

echo Obrint parafrasi-cat al navegador...
echo Per aturar-lo, tanqueu aquesta finestra.
%PYTHON% -m parafrasi_cat web
pause
