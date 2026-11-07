#!/usr/bin/env bash
# ==============================================================================
# Safe MySQL Database Backup Script for LendMate (Linux / macOS / POSIX)
#
# Reads connection settings from environment variables (or .env if sourced).
# Supports both local and remote MySQL databases.
# Passwords are read from environment and passed via MYSQL_PWD (never echoed).
# MYSQL_PWD is automatically unset immediately after the command executes.
# Validates backup creation and verifies that the file is non-empty.
#
# Environment variables (all optional — defaults shown):
#   MYSQL_DATABASE or DB_NAME      — database name  (default: lendmate)
#   MYSQL_USER     or DB_USER      — database user  (default: lendmate)
#   MYSQL_HOST     or DB_HOST      — database host  (default: 127.0.0.1)
#   MYSQL_PORT     or DB_PORT      — database port  (default: 3306)
#   MYSQL_PASSWORD or DB_PASSWORD  — database password (never printed)
#
# Production Option File Recommendation:
#   For production environments without environment variables, configure
#   a protected MySQL option file (~/.my.cnf) with permissions restricted:
#     chmod 600 ~/.my.cnf
#     [client]
#     user=lendmate
#     password="your_password"
# ==============================================================================

set -euo pipefail

# Change to project root (parent of scripts/)
cd "$(dirname "$0")/.."

# 1. Verify mysqldump is installed and accessible
if ! command -v mysqldump &>/dev/null; then
    echo "[ERROR] mysqldump command not found in system PATH." >&2
    echo "Please install MySQL client tools and ensure mysqldump is accessible." >&2
    exit 1
fi

# 2. Read configuration with fallback to DB_* aliases and defaults
MYSQL_DATABASE="${MYSQL_DATABASE:-${DB_NAME:-lendmate}}"
MYSQL_USER="${MYSQL_USER:-${DB_USER:-lendmate}}"
MYSQL_HOST="${MYSQL_HOST:-${DB_HOST:-127.0.0.1}}"
MYSQL_PORT="${MYSQL_PORT:-${DB_PORT:-3306}}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:-${DB_PASSWORD:-}}"

# 3. Configure optional TLS/SSL parameters
SSL_ARGS=""
if [ -n "${MYSQL_SSL_CA:-}" ] || [ -n "${DB_SSL_CA:-}" ]; then
    SSL_CA="${MYSQL_SSL_CA:-${DB_SSL_CA:-}}"
    SSL_ARGS="--ssl-ca=\"${SSL_CA}\""
fi
if [ -n "${MYSQL_SSL_MODE:-}" ] || [ -n "${DB_SSL_MODE:-}" ]; then
    SSL_MODE="${MYSQL_SSL_MODE:-${DB_SSL_MODE:-}}"
    SSL_ARGS="${SSL_ARGS} --ssl-mode=${SSL_MODE}"
fi

# 4. Ensure consistent backup directory exists
BACKUP_DIR="backups"
mkdir -p "${BACKUP_DIR}"

# 5. Generate ISO locale-independent timestamp (yyyyMMdd_HHmmss)
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/lendmate_backup_${TIMESTAMP}.sql"

# 6. Ensure file does not already exist (do not automatically overwrite)
if [ -e "${BACKUP_FILE}" ]; then
    echo "[ERROR] Backup target already exists: ${BACKUP_FILE}" >&2
    exit 1
fi

echo "[INFO] Starting MySQL database backup:"
echo "       Database  : ${MYSQL_DATABASE}"
echo "       Host      : ${MYSQL_HOST}:${MYSQL_PORT}"
echo "       User      : ${MYSQL_USER}"
echo "       Directory : ${BACKUP_DIR}"
echo "       Target    : ${BACKUP_FILE}"

# 7. Set MYSQL_PWD temporarily for mysqldump execution
export MYSQL_PWD="${MYSQL_PASSWORD}"

# 8. Execute mysqldump with single-transaction consistency
set +e
# shellcheck disable=SC2086
mysqldump \
    -h "${MYSQL_HOST}" \
    -P "${MYSQL_PORT}" \
    -u "${MYSQL_USER}" \
    --single-transaction \
    --quick \
    --lock-tables=false \
    --no-tablespaces \
    ${SSL_ARGS} \
    "${MYSQL_DATABASE}" > "${BACKUP_FILE}"
DUMP_STATUS=$?
set -e

# 9. Immediately clear MYSQL_PWD from the environment
unset MYSQL_PWD || true

# 10. Validate execution status
if [ ${DUMP_STATUS} -ne 0 ]; then
    echo "[ERROR] mysqldump command failed with exit code ${DUMP_STATUS}." >&2
    rm -f "${BACKUP_FILE}"
    exit 1
fi

# 11. Validate backup file existence and non-empty content (> 0 bytes)
if [ ! -s "${BACKUP_FILE}" ]; then
    echo "[ERROR] Backup file was not created or is empty (0 bytes): ${BACKUP_FILE}" >&2
    rm -f "${BACKUP_FILE}"
    exit 1
fi

FILE_SIZE=$(wc -c < "${BACKUP_FILE}" | tr -d ' ')
echo "[SUCCESS] Backup completed successfully."
echo "          File : ${BACKUP_FILE}"
echo "          Size : ${FILE_SIZE} bytes"
exit 0
