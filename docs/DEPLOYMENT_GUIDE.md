# LendMate · Production Deployment Guide

This guide explains how to deploy LendMate on Railway, Docker, or any Linux VPS using a platform-independent architecture.

---

## 5-Service Architecture

LendMate consists of five discrete, independently scalable components:

1. **Django Web Service**: Runs Gunicorn WSGI server. Serves HTML/CSS/JS and processes web requests.
2. **MySQL Database**: Persistent relational database for all ledger and notification records.
3. **Redis Service**: In-memory message broker for Celery task queuing.
4. **Celery Background Worker**: Processes pending WhatsApp notification jobs asynchronously.
5. **Celery Beat Scheduler**: Evaluates periodic crontab schedules (monthly reminders at 09:00, overdue reminders at 10:00, stuck job recovery every 15 mins).

---

## Option 1: Railway Cloud Deployment

Railway runs all 5 services within one project:

### 1. Create Railway Project
- Log in to Railway and create a new Project named `LendMate`.

### 2. Add MySQL Database
- Click **New** → **Database** → **Add MySQL**.
- Under Service Settings, verify Persistent Storage volume is attached.

### 3. Add Redis Service
- Click **New** → **Database** → **Add Redis**.

### 4. Deploy Django Web Service
- Click **New** → **GitHub Repo** → select your LendMate repository.
- **Custom Start Command** (application server only — no automatic migrations on startup):
  ```bash
  gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 3 --timeout 120
  ```
- **Health Check Path**: `/health/`
- Set Environment Variables:
  - `MYSQL_HOST` = `${{MySQL.MYSQLHOST}}`
  - `MYSQL_PORT` = `${{MySQL.MYSQLPORT}}`
  - `MYSQL_USER` = `${{MySQL.MYSQLUSER}}`
  - `MYSQL_PASSWORD` = `${{MySQL.MYSQLPASSWORD}}`
  - `MYSQL_DATABASE` = `${{MySQL.MYSQLDATABASE}}`
  - `REDIS_URL` = `${{Redis.REDIS_URL}}`
  - `CELERY_BROKER_URL` = `${{Redis.REDIS_URL}}`
  - `CELERY_RESULT_BACKEND` = `${{Redis.REDIS_URL}}`
  - `DJANGO_SECRET_KEY` = `(generate secure 50+ character random string)`
  - `DJANGO_DEBUG` = `false`
  - `DJANGO_ALLOWED_HOSTS` = `${{RAILWAY_PUBLIC_DOMAIN}}`
  - `DJANGO_CSRF_TRUSTED_ORIGINS` = `https://${{RAILWAY_PUBLIC_DOMAIN}}`
  - `WHATSAPP_BACKEND` = `notifications.whatsapp.MockWhatsAppBackend` (or `notifications.whatsapp.MetaWhatsAppCloudBackend` for live Meta WhatsApp Cloud API)
  - `WHATSAPP_ACCESS_TOKEN` = `(Meta System User access token)`
  - `WHATSAPP_PHONE_NUMBER_ID` = `(Meta Phone Number ID)`
  - `WHATSAPP_VERIFY_TOKEN` = `(Webhook verification challenge token)`
  - `WHATSAPP_APP_SECRET` = `(Meta App Secret for webhook signature validation)`

### 5. Controlled Railway Database Migration Procedure
Running migrations automatically on web server startup is an anti-pattern that creates race conditions and table locking issues during horizontal scaling or container restarts.

Execute migrations strictly **once per release** using one of the two controlled options below:

#### Option A: Railway Procfile Release Phase (Recommended if supported by your buildpack)
If using a Heroku/Procfile-compatible buildpack, Railway executes the `release:` process in `Procfile` before new containers receive traffic:
```
release: python manage.py migrate --noinput
```
*Note: Depending on your Railway deployment method (e.g. Nixpacks or Dockerfile builds), Procfile release hooks may not execute automatically without explicit configuration. In that case, use Option B below to run migrations with complete operational control.*

#### Option B: Railway CLI One-Off Command (Direct & Deterministic)
Run and verify migrations directly from your local terminal using the Railway CLI:
```bash
# 1. Verify current migration status:
railway run python manage.py showmigrations

# 2. Execute pending migrations safely:
railway run python manage.py migrate --noinput

# 3. Confirm all migrations are applied:
railway run python manage.py showmigrations
```

### 6. Deploy Celery Worker
- Click **New** → select the same LendMate repository.
- Rename service to `Celery Worker`.
- **Start Command**:
  ```bash
  celery -A config worker --loglevel=info --concurrency=2
  ```
- Copy the exact same environment variables from the Web service.

### 7. Deploy Celery Beat Scheduler
- Click **New** → select the same LendMate repository.
- Rename service to `Celery Beat`.
- **Start Command**:
  ```bash
  celery -A config beat --loglevel=info
  ```
- Copy the exact same environment variables.
- *Ensure only 1 instance of Celery Beat is running.*

---

## Option 2: Docker Compose Deployment (Local or VPS)

### Production Configuration (Default)

The authoritative root `docker-compose.yml` provides a hardened, production-ready environment:
- **Zero Exposed Ports for Internal Services**: MySQL (3306) and Redis (6379) are kept strictly internal to the isolated `lendmate-network` Docker bridge network. Only the Django web application (port 8000) is published.
- **Environment Variable Isolation**: `MYSQL_ROOT_PASSWORD` is strictly confined to the `mysql` container. Application containers (`web`, `celery-worker`, `celery-beat`, `migrate`) use ONLY the dedicated application database credentials (`MYSQL_USER` and `MYSQL_PASSWORD`). The complete `.env` file is NOT indiscriminately injected into application containers.
- **Non-Root Execution**: Containers run as the dedicated `lendmate` user (`UID 999`), preventing container breakout or unauthorized host access.
- **Health Checks & Startup Dependencies**: MySQL runs an authenticated health check (`mysqladmin ping`) and Redis runs `redis-cli ping`. Django and Celery services wait for both dependencies to report healthy before starting.
- **Controlled Database Migration**: Migrations are separated from standard application container startup, preventing concurrent migration race conditions across application replicas.

```bash
# 1. Copy environment template
cp .env.example .env

# 2. Fill in your MySQL passwords, root password, and secret key in .env
# Example required fields in .env:
#   MYSQL_ROOT_PASSWORD=your_secure_root_password
#   MYSQL_PASSWORD=your_secure_app_password
#   DJANGO_SECRET_KEY=your_secret_key_string

# 3. Step A: Perform Controlled Database Migration
docker compose run --rm migrate

# 4. Step B: Launch Application and Background Services
docker compose up -d

# 5. View logs
docker compose logs -f web celery-worker celery-beat
```

### Controlled Migration Strategy for Zero-Downtime Deployment

In production environments, running migrations inside web server entrypoints causes race conditions when multiple replicas start simultaneously. LendMate strictly separates migrations:
1. Verify pending migrations:
   ```bash
   docker compose run --rm web python manage.py showmigrations
   ```
2. Apply migrations in a dedicated release container:
   ```bash
   docker compose run --rm migrate
   ```
3. Start or reload web and background worker containers:
   ```bash
   docker compose up -d
   ```
4. Confirm migration state:
   ```bash
   docker compose run --rm web python manage.py showmigrations
   ```

### Local Development Override (`docker-compose.dev.yml`)

When you need direct access to MySQL (port 3306) and Redis (port 6379) from your host machine (e.g. GUI tools like MySQL Workbench, DBeaver, or Redis Insight):

```bash
# Launch with development port exposure (bound to 127.0.0.1 only):
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

---

## Remote MySQL TLS / SSL Configuration

When connecting LendMate to managed cloud databases (such as AWS RDS, Google Cloud SQL, Azure Database for MySQL, or DigitalOcean Managed Databases), enforce TLS encryption by configuring:

- `MYSQL_SSL_CA` (or `DB_SSL_CA`): Path to the Certificate Authority bundle (e.g. `/etc/ssl/certs/rds-ca-bundle.pem`).
- `MYSQL_SSL_MODE` (or `DB_SSL_MODE`): SSL verification mode. Supported values:
  - `VERIFY_IDENTITY`: Validates the certificate chain and verifies the server hostname.
  - `VERIFY_CA`: Validates the certificate chain.
  - `REQUIRED`: Enforces encrypted transport.

---

## Safe Database Backups and Restores

Scripts are provided in `scripts/`:
- **Windows**: `scripts\backup_db.bat` and `scripts\restore_db.bat`
- **Linux/macOS**: `bash scripts/backup_db.sh` and `bash scripts/restore_db.sh`

### Backup Procedure:
Both scripts:
- Dynamically detect configuration from `MYSQL_*` / `DB_*` environment variables.
- Pass passwords securely via `MYSQL_PWD` without printing passwords to logs or process argument lists.
- Immediately clear `MYSQL_PWD` from the environment upon command completion.
- Validate that the backup file exists and is strictly non-empty (> 0 bytes).
- Generate ISO-standard timestamped backups inside the `backups/` directory: `backups/lendmate_backup_YYYYMMDD_HHMMSS.sql`.
- Support optional TLS/SSL encryption parameters (`MYSQL_SSL_CA`, `MYSQL_SSL_MODE`, `DB_SSL_CA`, `DB_SSL_MODE`) when connecting to managed cloud databases.

### Safe Restore Procedure:
- Restore scripts require passing the backup file path as an explicit argument.
- Restore scripts **NEVER** run automatically: they display the target database, host, user, and backup file size, and require the operator to type uppercase `YES` before proceeding.
- Usage:
  ```bash
  # Windows
  scripts\restore_db.bat backups\lendmate_backup_20261107_160209.sql

  # Linux / macOS
  bash scripts/restore_db.sh backups/lendmate_backup_20261107_160209.sql
  ```

### Production Option File (`.my.cnf` / Option Files)
For automated unattended production backups without shell environment variables:
Create a protected client option file owned strictly by the service account with permissions `600`:
```ini
# ~/.my.cnf (or %APPDATA%\MySQL\my.ini on Windows)
[client]
user=lendmate
password="your_secure_password"
host=127.0.0.1
port=3306
```

---

## WhatsApp Delivery Reliability & Known Limitations

1. **Webhook Correlation & Worker Crash Resilience**:
   - Meta Cloud API provides a client-generated reference field (`biz_opaque_callback_data`) which LendMate populates with `notif_<id>`.
   - If a delivery webhook arrives before the Celery worker has saved `provider_message_id`, or if the worker crashes immediately after Meta accepts the request, LendMate correlates the incoming event via `biz_opaque_callback_data`.
   - If a webhook event arrives for an unrecognized notification ID and cannot be correlated immediately, LendMate **never discards** it silently; it stores the payload in `UnmatchedWebhookEvent` and automatically replays it when the worker or recovery task finishes saving the record.
   - Status updates are governed by an explicit non-downgrading state machine: `DELIVERED` and `FAILED` are terminal states that cannot be corrupted by late or out-of-order `sent` receipts. Duplicate delivery webhooks are safely idempotent.

2. **Uncertain Transmission Handling**:
   - Meta WhatsApp Cloud API requests may experience ambiguous network outcomes (e.g. `ReadTimeout`, mid-flight connection drops, or HTTP 5xx server errors).
   - In these cases, the payload may already have been received and queued by Meta. To prevent sending duplicate financial reminders to borrowers, LendMate **NEVER** automatically retries ambiguous outcomes.
   - Ambiguous outcomes are marked as `SUBMITTED` with a diagnostic marker (`[UNCERTAIN]`).
   - Meta webhooks asynchronously confirm delivery (`DELIVERED` status) or failure once the carrier resolves the message.
3. **Delivery Limitations**:
   - External WhatsApp delivery depends on Meta Cloud API availability, borrower WhatsApp registration, handset network connectivity, and Meta 24-hour customer care messaging windows.
   - Webhook delivery receipts provide at-least-once delivery confirmation; applications should never claim synchronous or exactly-once delivery across external carrier networks.

