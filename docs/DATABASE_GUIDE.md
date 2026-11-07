# LendMate · Database & Migration Guide

This guide covers the MySQL database architecture, migration records, and safe operations for LendMate.

---

## Database Configuration

LendMate exclusively uses **MySQL 8.0+** across both local development and production environments.

Connection settings are loaded via environment variables in `config/settings.py`:
- `MYSQL_DATABASE` (or `DB_NAME`, default: `lendmate`)
- `MYSQL_USER` (or `DB_USER`, default: `lendmate`)
- `MYSQL_PASSWORD` (or `DB_PASSWORD`)
- `MYSQL_HOST` (or `DB_HOST`, default: `127.0.0.1`)
- `MYSQL_PORT` (or `DB_PORT`, default: `3306`)
- `MYSQL_SSL_CA` (or `DB_SSL_CA`, optional): Path to trusted SSL CA certificate bundle.
- `MYSQL_SSL_MODE` (or `DB_SSL_MODE`, optional): SSL mode (`VERIFY_IDENTITY`, `VERIFY_CA`, `REQUIRED`).

---

## Database Tables & Migration History

### 1. `accounts`
- Uses Django's built-in `auth_user` model.

### 2. `core`
- `core/migrations/0001_initial.py`: Creates `core_userpreferences` table (`payment_reminders`, `due_date_reminders`).
- `core/migrations/0002_add_sms_preferences.py`: Extends `core_userpreferences` with legacy SMS fields.
- `core/migrations/0003_userpreferences_whatsapp_loan_closed_and_more.py`: Adds WhatsApp preferences:
  - `whatsapp_notifications_enabled` (master switch, default `False`)
  - `whatsapp_loan_created` (default `True`)
  - `whatsapp_payment_received` (default `True`)
  - `whatsapp_monthly_reminders` (default `True`)
  - `whatsapp_overdue_reminders` (default `True`)
  - `whatsapp_loan_closed` (default `True`)

### 3. `lending`
- `0001_initial.py`: Baseline `Borrower` model.
- `0002_borrower_lender.py`: Associates borrowers with authenticated lenders (`lending_borrower.lender_id`).
- `0003_loan.py`: Creates `lending_loan` table.
- `0004_payment.py`: Creates `lending_payment` table.
- `0005_loan_closed_at_borrowertracker_trackeritem.py`: Adds `closed_at` and creates custom trackers.
- `0006_borrowertracker_end_date_borrowertracker_loan_and_more.py`: Adds automatic monthly tracker support.
- `0007_borrower_whatsapp_consent_alter_borrower_sms_consent.py`: Adds `whatsapp_consent` boolean (`default=False`) to `Borrower`.

### 4. `notifications`
- `0001_initial_sms_notification.py`: Creates initial notification table.
- `0002_channel_neutral_notification.py`: Safe migration converting table to channel-neutral architecture:
  - Renames model from `SMSNotification` to `Notification` (preserves existing table and all records).
  - Preserves historical records with `channel='sms'`.
  - Sets default for all new notifications to `channel='whatsapp'`.
  - Adds `updated_at` (auto_now=True) and `processed_at` (timestamp when mock or live processing completes).
  - Preserves `sent_at` exclusively for real message transmission (cleared for mocked messages).
  - Updates status choices to: `pending`, `processing`, `mocked`, `submitted`, `delivered`, `failed`, `suppressed`.
  - Indexes: `(status, next_retry_at)`, `(lender, status)`, `(channel, status)`, and `provider_message_id`.

---

## Safe Database Backup & Restore

### Backing Up Local / Remote MySQL:
Using the included scripts (auto-detects environment variables and uses safe `MYSQL_PWD` handling):
```bash
# On Windows:
scripts\backup_db.bat

# On Linux / macOS:
bash scripts/backup_db.sh
```

Both scripts read `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_HOST`, `MYSQL_PORT`, and `MYSQL_PASSWORD` from the environment if set, falling back to localhost defaults.

Or manually with `mysqldump`:
```bash
mysqldump -u lendmate -p --single-transaction --quick --lock-tables=false lendmate > lendmate_backup.sql
```

### Restoring to MySQL (Local or Cloud/Railway):
```bash
mysql -h <HOST> -P <PORT> -u <USER> -p <DATABASE_NAME> < lendmate_backup.sql
```

### Verifying Record Counts After Migration:
```sql
SELECT 'Borrowers' as model, COUNT(*) as count FROM lending_borrower
UNION ALL
SELECT 'Loans', COUNT(*) FROM lending_loan
UNION ALL
SELECT 'Payments', COUNT(*) FROM lending_payment
UNION ALL
SELECT 'Notifications', COUNT(*) FROM notifications_notification;
```
