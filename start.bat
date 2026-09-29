@echo off
setlocal
cd /d "%~dp0"
echo.
echo  ==========================================
echo    Lifeline - one-command launcher
echo  ==========================================
echo.

set "PYEXE="
python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul && set "PYEXE=python"
if not defined PYEXE py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul && set "PYEXE=py -3"
if not defined PYEXE (
  echo Python 3.10 or newer is required. Install it from https://www.python.org/downloads/
  echo During install tick "Add python.exe to PATH", then run start.bat again.
  pause
  exit /b 1
)

if not exist "backend\.venv\Scripts\python.exe" (
  echo [1/3] Creating a private Python environment...
  %PYEXE% -m venv backend\.venv || goto :fail
)
set "VPY=%~dp0backend\.venv\Scripts\python.exe"

if not exist "backend\.venv\.lifeline-installed" (
  echo [2/3] Installing dependencies - first run only, takes 1-3 minutes...
  "%VPY%" -m pip install --disable-pip-version-check -q --upgrade pip
  "%VPY%" -m pip install --disable-pip-version-check -q -r backend\requirements.txt || goto :fail
  echo ok> "backend\.venv\.lifeline-installed"
)

"%VPY%" -c "import sqlalchemy.util" >nul 2>nul
if errorlevel 1 (
  echo Windows blocked a compiled SQLAlchemy file - installing the pure-Python build instead...
  set "DISABLE_SQLALCHEMY_CEXT=1"
  "%VPY%" -m pip install --disable-pip-version-check -q --force-reinstall --no-deps --no-binary sqlalchemy sqlalchemy || goto :fail
)

if not exist "frontend\dist\index.html" (
  echo Web app build missing - building it with npm...
  pushd frontend && call npm install && call npm run build && popd || goto :fail
)

echo [3/3] Starting Lifeline at http://localhost:8000  - keep this window open, press Ctrl+C to stop.
start "" cmd /c "timeout /t 5 >nul & start http://localhost:8000"
cd backend
"%VPY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
goto :eof

:fail
echo.
echo Something went wrong above. Copy the error text and see README.md - Troubleshooting.
pause
exit /b 1
