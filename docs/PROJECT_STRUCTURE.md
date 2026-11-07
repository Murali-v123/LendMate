# LendMate · Project Structure & Organization Guide

This document describes the directory organization of LendMate, detailing where each layer of the application lives, why it is structured this way, and how components interact.

---

## High-Level Architectural Layout

```
LendMate/
│
├── frontend/                     # All presentation-tier code (HTML, CSS, JS, Images, Icons)
│   ├── templates/                # Server-rendered Django templates
│   │   ├── accounts/             # Login, registration, password change views
│   │   ├── core/                 # Lender dashboard and settings templates
│   │   ├── layouts/              # Base shell, authentication shell, topbars, sidebars
│   │   ├── lending/              # Borrower profiles, loan forms, payment history, trackers
│   │   ├── notifications/        # Outbound notification logs, WhatsApp status filters, retry UI
│   │   ├── partials/             # Reusable UI fragments (navigation links, alerts, form fields)
│   │   └── registration/         # Password reset workflows
│   │
│   └── static/                   # Static assets served to the browser
│       ├── css/                  # Custom LendMate stylesheets (warm luxury design system)
│       ├── js/                   # Client-side JavaScript helpers
│       ├── img/                  # Logos and branding SVG assets
│       └── favicon/              # Browser tab icon assets
│
├── accounts/                     # Backend App: Lender authentication, registration, password management
├── core/                         # Backend App: Main dashboard metrics, user preferences, security
├── lending/                      # Backend App: Borrowers, loans, payments, custom & automatic trackers
├── notifications/                # Backend App: Durable WhatsApp queue, Meta Cloud API adapter, Celery tasks
├── config/                       # Backend App: Django settings, WSGI, ASGI, URLs, Celery instance
│
├── infrastructure/               # Container and deployment configurations
│   ├── Dockerfile                # Multi-stage production container setup
│   ├── docker-compose.yml        # 5-service local stack (Web, MySQL, Redis, Worker, Beat)
│   └── deployment/               # Platform-as-a-Service deployment files (Procfile, railway.toml)
│
├── docs/                         # Project architecture and developer guides
│   ├── PROJECT_STRUCTURE.md      # This document: full folder map
│   ├── FRONTEND_GUIDE.md         # Guide for UI, HTML templates, CSS, and styling changes
│   ├── BACKEND_GUIDE.md          # Guide for views, models, forms, business logic, and SMS
│   ├── DATABASE_GUIDE.md         # MySQL models, migrations, and safe backup/restore procedures
│   └── DEPLOYMENT_GUIDE.md       # Production setup on Railway, Docker, and VPS
│
├── scripts/                      # Cross-platform helper scripts for development and operations
│   ├── run_server.bat / .sh      # Launch Django development server
│   ├── run_worker.bat / .sh      # Launch Celery background worker
│   ├── run_beat.bat / .sh        # Launch Celery Beat task scheduler
│   ├── run_tests.bat / .sh       # Execute test suite across all apps
│   └── backup_db.bat / .sh       # Safe timestamped MySQL dump
│
├── tests/                        # Integration and end-to-end smoke tests
│   └── test_system_integration.py # Validates template discovery, static files, and endpoints
│
├── manage.py                     # Django management entry point
├── requirements.txt              # Pinned Python package dependencies
├── .env.example                  # Safe configuration template with placeholders
├── .gitignore                    # Git exclusions (caches, virtualenvs, secrets)
└── README.md                     # Main introductory documentation and quick-start guide
```

---

## Layer Separation Rationale

### 1. Presentation Tier (`frontend/`)
All HTML templates and static assets are consolidated under `frontend/`. This ensures developers or designers working on UI components never need to hunt through Python backend directories to find a page or stylesheet.
- **Configured in Django**: `config/settings.py` points `TEMPLATES['DIRS']` to `frontend/templates/` and `STATICFILES_DIRS` to `frontend/static/`.

### 2. Domain & Application Logic (`accounts/`, `core/`, `lending/`, `notifications/`, `config/`)
Each Django app represents an isolated domain bounded context:
- `accounts`: User identity and session security.
- `core`: Overall business dashboard aggregations and lender preferences.
- `lending`: Core financial ledger (loans, payments, interest calculations, checklists).
- `notifications`: Asynchronous communications (durable WhatsApp queue, Celery worker jobs, Meta Cloud API provider).
- `config`: Django runtime orchestration and Celery application definition.

### 3. Infrastructure & Deployment (`infrastructure/`)
Contains all container recipes, compose manifests, and process definitions needed to run the 5 production services (Django Web, MySQL, Redis, Celery Worker, Celery Beat).
