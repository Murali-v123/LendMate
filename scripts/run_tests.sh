#!/usr/bin/env bash
# Run LendMate Django Test Suite
set -e
cd "$(dirname "$0")/.."
source venv/bin/activate 2>/dev/null || true
python manage.py test notifications accounts core lending
