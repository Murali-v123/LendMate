@echo off
REM Run LendMate Django Test Suite
cd /d "%~dp0.."
if not exist "venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found at venv\Scripts\activate.bat
    echo Run: python -m venv venv
    exit /b 1
)
call venv\Scripts\activate.bat
python manage.py test notifications accounts core lending
