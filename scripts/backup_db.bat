@echo off
REM ==============================================================================
REM Safe MySQL Database Backup Script for LendMate (Windows)
REM
REM Reads connection settings from environment variables (or .env if loaded).
REM Supports both local and remote MySQL databases.
REM Passwords are read from environment and passed via MYSQL_PWD (never echoed).
REM MYSQL_PWD is automatically cleared immediately after the command executes.
REM Validates backup creation and verifies that the file is non-empty.
REM
REM Environment variables (all optional — defaults shown):
REM   MYSQL_DATABASE or DB_NAME      — database name  (default: lendmate)
REM   MYSQL_USER     or DB_USER      — database user  (default: lendmate)
REM   MYSQL_HOST     or DB_HOST      — database host  (default: 127.0.0.1)
REM   MYSQL_PORT     or DB_PORT      — database port  (default: 3306)
REM   MYSQL_PASSWORD or DB_PASSWORD  — database password (never printed)
REM
REM Production Option File Recommendation:
REM   For production environments without environment variables, configure
REM   a protected MySQL option file (e.g. %APPDATA%\MySQL\my.ini or mysql_config_editor)
REM   with permissions restricted to the running service account:
REM     [client]
REM     user=lendmate
REM     password="your_password"
REM ==============================================================================

cd /d "%~dp0.."

REM 1. Verify mysqldump is installed and accessible
where mysqldump >nul 2>&1
if errorlevel 1 (
    echo [ERROR] mysqldump not found in system PATH.
    echo Please install MySQL client tools and ensure mysqldump is in your PATH.
    exit /b 1
)

REM 2. Read configuration with fallback to DB_* aliases and defaults
if "%MYSQL_DATABASE%"=="" set "MYSQL_DATABASE=%DB_NAME%"
if "%MYSQL_USER%"==""     set "MYSQL_USER=%DB_USER%"
if "%MYSQL_HOST%"==""     set "MYSQL_HOST=%DB_HOST%"
if "%MYSQL_PORT%"==""     set "MYSQL_PORT=%DB_PORT%"
if "%MYSQL_PASSWORD%"=="" set "MYSQL_PASSWORD=%DB_PASSWORD%"

if "%MYSQL_DATABASE%"=="" set "MYSQL_DATABASE=lendmate"
if "%MYSQL_USER%"==""     set "MYSQL_USER=lendmate"
if "%MYSQL_HOST%"==""     set "MYSQL_HOST=127.0.0.1"
if "%MYSQL_PORT%"==""     set "MYSQL_PORT=3306"

REM 3. Configure optional TLS/SSL parameters
set "SSL_ARGS="
if not "%MYSQL_SSL_CA%"=="" set "SSL_ARGS=--ssl-ca=""%MYSQL_SSL_CA%"""
if not "%DB_SSL_CA%"==""    set "SSL_ARGS=--ssl-ca=""%DB_SSL_CA%"""
if not "%MYSQL_SSL_MODE%"=="" set "SSL_ARGS=%SSL_ARGS% --ssl-mode=%MYSQL_SSL_MODE%"
if not "%DB_SSL_MODE%"==""    set "SSL_ARGS=%SSL_ARGS% --ssl-mode=%DB_SSL_MODE%"

REM 4. Ensure consistent backup directory exists
set "BACKUP_DIR=backups"
if not exist "%BACKUP_DIR%" (
    mkdir "%BACKUP_DIR%" >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Failed to create backup directory: %BACKUP_DIR%
        exit /b 1
    )
)

REM 4. Generate ISO locale-independent timestamp (yyyyMMdd_HHmmss)
for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "Get-Date -Format 'yyyyMMdd_HHmmss'"`) do set TIMESTAMP=%%i
if "%TIMESTAMP%"=="" (
    echo [ERROR] Failed to generate timestamp for backup.
    exit /b 1
)

set "BACKUP_FILE=%BACKUP_DIR%\lendmate_backup_%TIMESTAMP%.sql"

REM 5. Ensure file does not already exist (do not automatically overwrite)
if exist "%BACKUP_FILE%" (
    echo [ERROR] Backup target already exists: %BACKUP_FILE%
    exit /b 1
)

echo [INFO] Starting MySQL database backup:
echo        Database  : %MYSQL_DATABASE%
echo        Host      : %MYSQL_HOST%:%MYSQL_PORT%
echo        User      : %MYSQL_USER%
echo        Directory : %BACKUP_DIR%
echo        Target    : %BACKUP_FILE%

REM 6. Set MYSQL_PWD temporarily for mysqldump execution
set "MYSQL_PWD=%MYSQL_PASSWORD%"

REM 7. Execute mysqldump with single-transaction consistency
mysqldump -h %MYSQL_HOST% -P %MYSQL_PORT% -u %MYSQL_USER% %SSL_ARGS% --single-transaction --quick --lock-tables=false --no-tablespaces %MYSQL_DATABASE% > "%BACKUP_FILE%"
set "DUMP_STATUS=%ERRORLEVEL%"

REM 8. Immediately clear MYSQL_PWD from the environment
set "MYSQL_PWD="

REM 9. Validate execution status
if not "%DUMP_STATUS%"=="0" (
    echo [ERROR] mysqldump command failed with exit code %DUMP_STATUS%.
    if exist "%BACKUP_FILE%" del "%BACKUP_FILE%" >nul 2>&1
    exit /b 1
)

REM 10. Validate backup file existence
if not exist "%BACKUP_FILE%" (
    echo [ERROR] Backup file was not created: %BACKUP_FILE%
    exit /b 1
)

REM 11. Validate backup file is not empty (> 0 bytes)
set "FILE_SIZE=0"
for %%F in ("%BACKUP_FILE%") do set "FILE_SIZE=%%~zF"
if "%FILE_SIZE%"=="" set "FILE_SIZE=0"
if "%FILE_SIZE%"=="0" (
    echo [ERROR] Backup file was created but is empty: 0 bytes.
    if exist "%BACKUP_FILE%" del "%BACKUP_FILE%" >nul 2>&1
    exit /b 1
)

echo [SUCCESS] Backup completed successfully.
echo           File : %BACKUP_FILE%
echo           Size : %FILE_SIZE% bytes
exit /b 0
