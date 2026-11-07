#!/usr/bin/env bash
# Start LendMate Django Development Web Server
set -e
cd "$(dirname "$0")/.."
source venv/bin/activate 2>/dev/null || true
python manage.py runserver
