@echo off
REM ==============================================================================
REM Safe MySQL Database Restore Script for LendMate (Windows)
REM
REM Restores a database backup from an SQL dump file.
REM NEVER restores automatically — requires explicit interactive confirmation.
REM Passwords are read from environment and passed via MYSQL_PWD (never echoed).
REM MYSQL_PWD is automatically cleared immediately after the command executes.
REM
REM Usage:
REM   scripts\restore_db.bat <path_to_backup_file.sql>
REM ==============================================================================

cd /d "%~dp0.."

REM 1. Validate argument
if "%~1"=="" (
    echo [ERROR] No backup file specified.
    echo Usage: scripts\restore_db.bat path\to\lendmate_backup_YYYYMMDD_HHMMSS.sql
    exit /b 1
)

set "BACKUP_FILE=%~1"

REM 2. Verify backup file exists and is not empty
if not exist "%BACKUP_FILE%" (
    echo [ERROR] Backup file not found: %BACKUP_FILE%
    exit /b 1
)

for %%F in ("%BACKUP_FILE%") do set "FILE_SIZE=%%~zF"
if "%FILE_SIZE%"=="" set "FILE_SIZE=0"
if %FILE_SIZE% LEQ 0 (
    echo [ERROR] Backup file is empty (0 bytes): %BACKUP_FILE%
    exit /b 1
)

REM 3. Verify mysql client is installed and accessible
where mysql >nul 2>&1
if errorlevel 1 (
    echo [ERROR] mysql client executable not found in PATH.
    echo Please install MySQL client tools and ensure mysql is in your PATH.
    exit /b 1
)

REM 4. Read configuration with fallback to DB_* aliases and defaults
if "%MYSQL_DATABASE%"=="" set "MYSQL_DATABASE=%DB_NAME%"
if "%MYSQL_USER%"==""     set "MYSQL_USER=%DB_USER%"
if "%MYSQL_HOST%"==""     set "MYSQL_HOST=%DB_HOST%"
if "%MYSQL_PORT%"==""     set "MYSQL_PORT=%DB_PORT%"
if "%MYSQL_PASSWORD%"=="" set "MYSQL_PASSWORD=%DB_PASSWORD%"

if "%MYSQL_DATABASE%"=="" set "MYSQL_DATABASE=lendmate"
if "%MYSQL_USER%"==""     set "MYSQL_USER=lendmate"
if "%MYSQL_HOST%"==""     set "MYSQL_HOST=127.0.0.1"
if "%MYSQL_PORT%"==""     set "MYSQL_PORT=3306"

REM 5a. Configure optional TLS/SSL parameters
set "SSL_ARGS="
if not "%MYSQL_SSL_CA%"=="" set "SSL_CA=%MYSQL_SSL_CA%"
if not "%DB_SSL_CA%"=="" if "%SSL_CA%"=="" set "SSL_CA=%DB_SSL_CA%"
if not "%SSL_CA%"=="" set "SSL_ARGS=%SSL_ARGS% --ssl-ca=%SSL_CA%"

set "SSL_MODE_VAL="
if not "%MYSQL_SSL_MODE%"=="" set "SSL_MODE_VAL=%MYSQL_SSL_MODE%"
if not "%DB_SSL_MODE%"=="" if "%SSL_MODE_VAL%"=="" set "SSL_MODE_VAL=%DB_SSL_MODE%"
if not "%SSL_MODE_VAL%"=="" set "SSL_ARGS=%SSL_ARGS% --ssl-mode=%SSL_MODE_VAL%"

REM 5. Display target and require explicit user confirmation
echo ==============================================================================
echo [WARNING] YOU ARE ABOUT TO RESTORE A DATABASE DUMP:
echo           Target Database : %MYSQL_DATABASE%
echo           Target Host     : %MYSQL_HOST%:%MYSQL_PORT%
echo           Target User     : %MYSQL_USER%
echo           Source Backup   : %BACKUP_FILE% (%FILE_SIZE% bytes)
echo.
echo           THIS ACTION WILL OVERWRITE DATA IN '%MYSQL_DATABASE%'.
echo ==============================================================================

set "CONFIRM="
set /p CONFIRM="Type 'YES' (all uppercase) to confirm restoration: "
if not "%CONFIRM%"=="YES" (
    echo [ABORTED] Database restoration cancelled by user. No changes were made.
    exit /b 0
)

echo [INFO] Restoring database from %BACKUP_FILE%...

REM 6. Set MYSQL_PWD temporarily for mysql client execution
set "MYSQL_PWD=%MYSQL_PASSWORD%"

mysql -h %MYSQL_HOST% -P %MYSQL_PORT% -u %MYSQL_USER% %SSL_ARGS% %MYSQL_DATABASE% < "%BACKUP_FILE%"
set "RESTORE_STATUS=%ERRORLEVEL%"

REM 7. Immediately clear MYSQL_PWD from environment
set "MYSQL_PWD="

REM 8. Validate execution status
if not "%RESTORE_STATUS%"=="0" (
    echo [ERROR] Database restore failed with exit code %RESTORE_STATUS%.
    exit /b 1
)

echo [SUCCESS] Database restored successfully from %BACKUP_FILE%.
exit /b 0
