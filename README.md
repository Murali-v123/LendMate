# LendMate · Personal Lending & Repayment Management System

LendMate is a private money-lending ledger web application designed for personal lenders who manage loans to friends, family, or private borrowers. Borrowers do not require user accounts—only the lender logs in to record loans, track repayments, generate automated monthly payment schedules, and manage outbound WhatsApp notifications.

---

## 1. Technologies Used

- **Backend**: Python 3.11+, Django 5.2, Gunicorn
- **Database**: MySQL 8.0+ (utf8mb4)
- **Task Queue & Broker**: Celery 5.4+, Redis 6.1+
- **Frontend**: Django Templates, Bootstrap 5.3, Custom LendMate CSS (Warm luxury editorial design)
- **Notification Infrastructure**: Official Meta WhatsApp Business Platform (Cloud API) with Mock adapter for local testing and secure webhook delivery receipts
- **Deployment**: Docker, Docker Compose, Railway, Linux VPS

---

## 2. Project Folder Structure

```
LendMate/
│
├── frontend/                     # FRONTEND TIER (UI & Presentation)
│   ├── templates/                # HTML templates grouped by app
│   │   ├── accounts/             # Login, register, password change
│   │   ├── core/                 # Dashboard and settings UI
│   │   ├── layouts/              # Base shell, topbars, sidebar frames
│   │   ├── lending/              # Borrowers, loans, payments, trackers
│   │   ├── notifications/        # WhatsApp notification history & retry dashboard
│   │   ├── partials/             # Navigation links, messages, form helpers
│   │   └── registration/         # Password reset flow
│   │
│   └── static/                   # Static files (CSS, JS, Images, Favicon)
│       ├── css/                  # Custom stylesheet (lendmate.css)
│       ├── js/                   # Client-side JavaScript helpers
│       ├── img/                  # Logos and marks (SVG)
│       └── favicon/              # Browser tab icon
│
├── accounts/                     # BACKEND: Authentication, accounts, passwords
├── core/                         # BACKEND: Dashboard KPIs, user preferences
├── lending/                      # BACKEND: Borrowers, loans, payments, monthly trackers
├── notifications/                # BACKEND: WhatsApp queue, templates, Meta Cloud API, Webhook
├── config/                       # BACKEND: Django settings, urls, wsgi, asgi, celery
│
├── infrastructure/               # DEPLOYMENT: Docker, Compose, Procfile, Railway
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── deployment/
│       ├── Procfile
│       └── railway.toml
│
├── docs/                         # DOCUMENTATION GUIDES
│   ├── WHATSAPP_SETUP_GUIDE.md   # Meta WhatsApp Cloud API & Webhook setup
│   ├── PROJECT_STRUCTURE.md      # Detailed map of every file
│   ├── FRONTEND_GUIDE.md         # Where to modify UI, CSS, and templates
│   ├── BACKEND_GUIDE.md          # Where to modify views, calculations, logic
│   ├── DATABASE_GUIDE.md         # Models, migrations, MySQL backup/restore
│   └── DEPLOYMENT_GUIDE.md       # Railway, Docker, and VPS instructions
│
├── scripts/                      # HELPER AUTOMATION SCRIPTS
│   ├── run_server.bat / .sh      # Launch web server
│   ├── run_worker.bat / .sh      # Launch Celery worker
│   ├── run_beat.bat / .sh        # Launch Celery Beat scheduler
│   ├── run_tests.bat / .sh       # Run full test suite
│   └── backup_db.bat / .sh       # MySQL database dump
│
├── manage.py                     # Django management entry point
├── requirements.txt              # Pinned Python dependencies
├── .env.example                  # Environment variable reference
├── .gitignore                    # Git exclusions
└── README.md                     # Project overview (this file)
```

---

## 3. Quick Reference: Where is Everything?

| Component | Directory Location |
| :--- | :--- |
| **Frontend Templates** | `frontend/templates/` |
| **Frontend Styles & Images** | `frontend/static/` |
| **Backend Business Logic** | `accounts/`, `core/`, `lending/`, `notifications/` |
| **Database Models** | `core/models.py`, `lending/models.py`, `notifications/models.py` |
| **Database Migrations** | `<app_name>/migrations/` (e.g. `lending/migrations/`, `notifications/migrations/`) |
| **WhatsApp Backend & Adapter** | `notifications/whatsapp.py`, `notifications/service.py` |
| **WhatsApp Message Templates** | `notifications/templates_whatsapp.py` |
| **WhatsApp Delivery Webhook** | `notifications/views.py` (`/notifications/webhook/whatsapp/`) |
| **Background Tasks & Scheduler** | `notifications/tasks.py` and `config/celery.py` |
| **Meta WhatsApp Guide** | `docs/WHATSAPP_SETUP_GUIDE.md` |

---

## 4. Local Installation & Setup

### Step 1: Install Python Dependencies
```bash
# Windows:
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# Linux / macOS:
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Step 2: Configure Environment Variables
Copy `.env.example` to `.env` and configure your credentials:
```bash
cp .env.example .env
```
Key settings in `.env`:
```ini
DJANGO_SECRET_KEY=your-random-secret-key
DJANGO_DEBUG=true
MYSQL_DATABASE=lendmate
MYSQL_USER=lendmate
MYSQL_PASSWORD=your_mysql_password
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
REDIS_URL=redis://127.0.0.1:6379/0

# WhatsApp Provider:
# In development, defaults to mock backend (no real messages sent, marked MOCKED):
WHATSAPP_BACKEND=notifications.whatsapp.MockWhatsAppBackend

# For production with Meta Cloud API:
# WHATSAPP_BACKEND=notifications.whatsapp.MetaWhatsAppCloudBackend
# WHATSAPP_ACCESS_TOKEN=your-access-token
# WHATSAPP_PHONE_NUMBER_ID=your-phone-id
# WHATSAPP_VERIFY_TOKEN=your-webhook-verify-token
# WHATSAPP_APP_SECRET=your-meta-app-secret
```

### Step 3: Run Database Migrations
```bash
python manage.py migrate
```

---

## 5. Running LendMate Locally

### A. Start the Web Server
```bash
python manage.py runserver
```
Visit: `http://localhost:8000`

### B. Start the Celery Worker (for Background WhatsApp Dispatches)
In a second terminal window:
```bash
# Windows (requires solo pool):
celery -A config worker --loglevel=info --pool=solo

# Linux / macOS / Docker:
celery -A config worker --loglevel=info --concurrency=2

# Or using the helper script:
scripts\run_worker.bat        # Windows
./scripts/run_worker.sh       # Linux / macOS
```

### C. Start the Celery Beat Scheduler (for Periodic Reminders & Recovery)
In a third terminal window:
```bash
celery -A config beat --loglevel=info

# Or using the helper script:
scripts\run_beat.bat          # Windows
./scripts/run_beat.sh         # Linux / macOS
```

---

## 6. Running with Docker Compose (Production & Development)

### Production Deployment via Docker Compose
To run Django, MySQL, Redis, Celery Worker, and Celery Beat in hardened containers:

1. **Configure Environment**:
   Ensure `.env` contains production secrets (see `.env.example`). Individual environment variables are explicitly passed to each service; `MYSQL_ROOT_PASSWORD` is strictly isolated to the database container.

2. **Run Database Migrations (Decoupled Release Step)**:
   In production, the `web` container runs Gunicorn directly as non-root user `lendmate` (UID 999). Run database migrations using the dedicated `migrate` profile:
   ```bash
   docker compose run --rm migrate
   ```

3. **Start Application Services**:
   ```bash
   docker compose up -d --build
   ```
   Access the application at `http://localhost:8000`. Health check: `http://localhost:8000/health/`.

### Development Override
To bind MySQL (3306) and Redis (6379) ports to `127.0.0.1` on your local host for inspection tools (e.g., MySQL Workbench, Redis Insight):
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

---

## 7. Database Backup, Restore & Maintenance

Portable scripts with secure `MYSQL_PWD` handling, `--no-tablespaces` compatibility, and ISO timestamps:

### Backup Database
```bash
# Windows
scripts\backup_db.bat

# Linux / macOS
chmod +x scripts/backup_db.sh
./scripts/backup_db.sh
```
Dumps are created in `backups/lendmate_backup_YYYYMMDD_HHMMSS.sql`.

### Restore Database
```bash
# Windows (requires explicit confirmation prompt)
scripts\restore_db.bat backups\lendmate_backup_20261107_120000.sql

# Linux / macOS
chmod +x scripts/restore_db.sh
./scripts/restore_db.sh backups/lendmate_backup_20261107_120000.sql
```

---

## 8. Release Packaging

To build a clean production distribution archive without secrets, virtual environments, bytecode, logs, or local temporary files:
```bash
python scripts/package_release.py
```
This produces `lendmate_release.zip` ready for deployment.

---

## 9. Running the Automated Tests

LendMate includes 120 comprehensive automated tests covering loan calculations, trackers, borrower consent, WhatsApp queue, Meta API payload construction, retries, ambiguous network timeouts, webhook correlation (`biz_opaque_callback_data` and replay of unmatched events), terminal status state machines, non-root execution, and UI dashboard:
```bash
# Run notification tests (75 tests):
python manage.py test notifications

# Run complete test suite across all apps (120 tests: notifications=75, accounts=6, core=12, lending=27):
python manage.py test notifications accounts core lending --noinput
```
