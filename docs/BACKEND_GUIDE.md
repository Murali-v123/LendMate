# LendMate · Backend Guide

This guide explains the backend architecture of LendMate, detailing where business logic, models, controllers, background workers, and third-party integrations reside.

---

## Backend Application Inventory

LendMate is composed of 5 focused Django apps:

### 1. `config/` – Application Orchestration
- `config/settings.py`: Central configuration, environment variable readers, Celery Beat crontab schedules, security flags, logging, database connectors, and Meta WhatsApp Cloud API settings.
- `config/celery.py`: Celery application instance configuring Redis broker and task auto-discovery.
- `config/urls.py`: Root URL routing including admin, authentication, lending, notifications, and `/health/` health check.
- `config/wsgi.py` & `config/asgi.py`: WSGI / ASGI production deployment handlers.

### 2. `accounts/` – Identity & Security
- `accounts/views.py`: `RegisterView`, `LendMatePasswordChangeView`.
- `accounts/forms.py`: Registration and password change validation.
- `accounts/urls.py`: Account-related endpoints.

### 3. `core/` – Lender Dashboard & Preferences
- `core/models.py`: `UserPreferences` storing reminder toggles and WhatsApp notification preferences (`whatsapp_notifications_enabled` master switch, `whatsapp_loan_created`, `whatsapp_payment_received`, `whatsapp_monthly_reminders`, `whatsapp_overdue_reminders`, `whatsapp_loan_closed`). Legacy SMS preference fields are preserved for migration compatibility.
- `core/views.py`: Aggregates portfolio figures (total lent, principal repaid, outstanding balance, interest collected) for the authenticated lender.
- `core/forms.py`: `ProfileForm` and `UserPreferencesForm`.

### 4. `lending/` – Financial Ledger & Loan Management
- `lending/models.py`:
  - `Borrower`: Name, contact details, notes, `whatsapp_consent` boolean, and legacy `sms_consent`.
  - `Loan`: Principal, interest rate, monthly due day, lending date, return date, status (open/closed), and closed timestamp.
  - `Payment`: Amount, principal component, interest component, date, validation checks ensuring principal paid cannot exceed total balance.
  - `BorrowerTracker` & `TrackerItem`: Custom and automated monthly tracking checklists.
- `lending/views.py`: Borrower CRUD, Loan CRUD, Payment entry, Loan closing/reopening, Tracker generators, and safe notification trigger invocations.

### 5. `notifications/` – WhatsApp Notification Queue, Meta Cloud API & Workers
- `notifications/models.py`: `Notification` model (channel-neutral with WhatsApp as the active channel). Durable queue surviving restarts with statuses (`pending`, `processing`, `mocked`, `submitted`, `delivered`, `failed`, `suppressed`), retry counters, error logs, and SHA-256 idempotency `event_key`.
- `notifications/service.py`: Enqueue service verifying borrower WhatsApp consent, lender master switch, category preferences, and Indian mobile format before enqueuing.
- `notifications/tasks.py`: Celery tasks:
  - `send_whatsapp_notification`: Atomically claims eligible PENDING notifications with row-locking and dispatches via WhatsApp backend with exponential backoff retries.
  - `send_monthly_reminders`: Scheduled task checking upcoming due dates in the next 3 days.
  - `send_overdue_reminders`: Scheduled task finding unpaid loans past their due day.
  - `recover_stuck_notifications`: Maintenance task rescuing stale worker jobs and un-dispatched pending records.
- `notifications/whatsapp.py`: Provider adapter (`BaseWhatsAppBackend`, `MockWhatsAppBackend`, `MetaWhatsAppCloudBackend`, phone validation).
- `notifications/templates_whatsapp.py`: The 5 domain-populated WhatsApp templates with INR currency formatting.
- `notifications/views.py`: Notification history dashboard, retry view, and the official Meta WhatsApp delivery webhook endpoint (`/notifications/webhook/whatsapp/`).

---

## Where to Make Common Backend Changes

| Goal | Files to modify |
| :--- | :--- |
| **Change WhatsApp message wording or parameters** | `notifications/templates_whatsapp.py` |
| **Switch WhatsApp backend (Mock vs Meta Cloud)** | Set `WHATSAPP_BACKEND` in `.env` / `config/settings.py` |
| **Configure Meta WhatsApp Cloud API credentials** | Set `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET` in `.env` |
| **Modify loan interest calculation** | `lending/models.py` (`outstanding_principal` property) and `notifications/tasks.py` (`_calculate_monthly_payment`) |
| **Change monthly reminder lead time (default 3 days)** | `notifications/tasks.py` (`send_monthly_reminders`) |
| **Change Celery Beat scheduled times** | `config/settings.py` (`CELERY_BEAT_SCHEDULE`) |
| **Add validation to payments or loans** | `lending/forms.py` and `lending/models.py` |
| **Add new notification events** | Add type to `notifications/models.py`, create template builder in `notifications/templates_whatsapp.py`, and create helper in `notifications/service.py` |
| **Future SMS Extension** | Implement `BaseSMSBackend` adapter and add `channel=Notification.CHANNEL_SMS` dispatch in `notifications/service.py` |
