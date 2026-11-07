#!/usr/bin/env bash
# ==============================================================================
# Safe MySQL Database Restore Script for LendMate (Linux / macOS / POSIX)
#
# Restores a database backup from an SQL dump file.
# NEVER restores automatically — requires explicit interactive confirmation.
# Passwords are read from environment and passed via MYSQL_PWD (never echoed).
# MYSQL_PWD is automatically unset immediately after the command executes.
#
# Usage:
#   bash scripts/restore_db.sh path/to/lendmate_backup_YYYYMMDD_HHMMSS.sql
# ==============================================================================

set -euo pipefail

cd "$(dirname "$0")/.."

# 1. Validate argument
if [ $# -lt 1 ]; then
    echo "[ERROR] No backup file specified." >&2
    echo "Usage: bash scripts/restore_db.sh path/to/lendmate_backup_YYYYMMDD_HHMMSS.sql" >&2
    exit 1
fi

BACKUP_FILE="$1"

# 2. Verify backup file exists and is not empty
if [ ! -s "${BACKUP_FILE}" ]; then
    echo "[ERROR] Backup file not found or is empty (0 bytes): ${BACKUP_FILE}" >&2
    exit 1
fi

# 3. Verify mysql client is installed and accessible
if ! command -v mysql &>/dev/null; then
    echo "[ERROR] mysql command not found in system PATH." >&2
    echo "Please install MySQL client tools and ensure mysql is accessible." >&2
    exit 1
fi

# 4. Read configuration with fallback to DB_* aliases and defaults
MYSQL_DATABASE="${MYSQL_DATABASE:-${DB_NAME:-lendmate}}"
MYSQL_USER="${MYSQL_USER:-${DB_USER:-lendmate}}"
MYSQL_HOST="${MYSQL_HOST:-${DB_HOST:-127.0.0.1}}"
MYSQL_PORT="${MYSQL_PORT:-${DB_PORT:-3306}}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:-${DB_PASSWORD:-}}"

# 5. Configure optional TLS/SSL parameters
SSL_ARGS=""
if [ -n "${MYSQL_SSL_CA:-}" ] || [ -n "${DB_SSL_CA:-}" ]; then
    SSL_CA="${MYSQL_SSL_CA:-${DB_SSL_CA:-}}"
    SSL_ARGS="--ssl-ca=\"${SSL_CA}\""
fi
if [ -n "${MYSQL_SSL_MODE:-}" ] || [ -n "${DB_SSL_MODE:-}" ]; then
    SSL_MODE="${MYSQL_SSL_MODE:-${DB_SSL_MODE:-}}"
    SSL_ARGS="${SSL_ARGS} --ssl-mode=${SSL_MODE}"
fi

FILE_SIZE=$(wc -c < "${BACKUP_FILE}" | tr -d ' ')

# 5. Display target and require explicit user confirmation
echo "=============================================================================="
echo "[WARNING] YOU ARE ABOUT TO RESTORE A DATABASE DUMP:"
echo "          Target Database : ${MYSQL_DATABASE}"
echo "          Target Host     : ${MYSQL_HOST}:${MYSQL_PORT}"
echo "          Target User     : ${MYSQL_USER}"
echo "          Source Backup   : ${BACKUP_FILE} (${FILE_SIZE} bytes)"
echo ""
echo "          THIS ACTION WILL OVERWRITE DATA IN '${MYSQL_DATABASE}'."
echo "=============================================================================="

read -r -p "Type 'YES' (all uppercase) to confirm restoration: " CONFIRM
if [ "${CONFIRM}" != "YES" ]; then
    echo "[ABORTED] Database restoration cancelled by user. No changes were made."
    exit 0
fi

echo "[INFO] Restoring database from ${BACKUP_FILE}..."

# 6. Set MYSQL_PWD temporarily for mysql client execution
export MYSQL_PWD="${MYSQL_PASSWORD}"

set +e
# shellcheck disable=SC2086
mysql \
    -h "${MYSQL_HOST}" \
    -P "${MYSQL_PORT}" \
    -u "${MYSQL_USER}" \
    ${SSL_ARGS} \
    "${MYSQL_DATABASE}" < "${BACKUP_FILE}"
RESTORE_STATUS=$?
set -e

# 7. Immediately clear MYSQL_PWD from environment
unset MYSQL_PWD || true

# 8. Validate execution status
if [ ${RESTORE_STATUS} -ne 0 ]; then
    echo "[ERROR] Database restore failed with exit code ${RESTORE_STATUS}." >&2
    exit 1
fi

echo "[SUCCESS] Database restored successfully from ${BACKUP_FILE}."
exit 0
