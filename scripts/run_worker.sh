#!/usr/bin/env bash
# Start LendMate Celery Worker
set -e
cd "$(dirname "$0")/.."
source venv/bin/activate 2>/dev/null || true
celery -A config worker --loglevel=info --concurrency=2
