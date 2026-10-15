@echo off
REM Starts the CineBook FastAPI backend (Terminal 1). Double-click or run from the CineBook folder.
cd /d "%~dp0.."
if not exist venv\Scripts\activate.bat (
  echo Virtual environment not found. Follow the README setup steps first.
  pause
  exit /b 1
)
call venv\Scripts\activate.bat
uvicorn backend.main:app --reload --reload-dir backend --port 8000
pause
