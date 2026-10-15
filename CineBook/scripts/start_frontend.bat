@echo off
REM Starts the CineBook Streamlit frontend (Terminal 2). Double-click or run from the CineBook folder.
cd /d "%~dp0.."
if not exist venv\Scripts\activate.bat (
  echo Virtual environment not found. Follow the README setup steps first.
  pause
  exit /b 1
)
call venv\Scripts\activate.bat
echo Open http://localhost:8501 in your browser.
streamlit run frontend\app.py
pause
