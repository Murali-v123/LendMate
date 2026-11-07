@echo off
REM Start LendMate Celery Asynchronous Background Worker
cd /d "%~dp0.."
if not exist "venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found at venv\Scripts\activate.bat
    echo Run: python -m venv venv
    exit /b 1
)
call venv\Scripts\activate.bat
celery -A config worker --loglevel=info --pool=solo
