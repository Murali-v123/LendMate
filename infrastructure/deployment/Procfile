# Procfile for Railway / Heroku-style deployments.
# Each line defines a separate service.
# On Railway, create separate services and point each to the relevant command.

web: gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 3 --timeout 120
worker: celery -A config worker --loglevel=info --concurrency=2
beat: celery -A config beat --loglevel=info
release: python manage.py migrate --noinput
