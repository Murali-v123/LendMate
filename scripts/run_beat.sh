#!/usr/bin/env bash
# Start LendMate Celery Beat Scheduler
set -e
cd "$(dirname "$0")/.."
source venv/bin/activate 2>/dev/null || true
celery -A config beat --loglevel=info
