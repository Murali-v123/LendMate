# Meta WhatsApp Business Platform (Cloud API) Setup Guide for LendMate

This guide provides step-by-step instructions for configuring and deploying official **Meta WhatsApp Business Platform (Cloud API)** notifications in LendMate.

---

## 1. Overview & Architecture

LendMate uses a channel-neutral notification architecture where **WhatsApp is the active notification channel**. In development and testing, LendMate defaults to `MockWhatsAppBackend`, simulating dispatches and marking messages as `Mocked – Not Transmitted` without making any external network requests or incurring messaging fees.

When connecting to production, LendMate interfaces directly with the official **Meta WhatsApp Cloud API (Graph API)** via `MetaWhatsAppCloudBackend`. Delivery reports and read receipts are received in real-time through the verified LendMate webhook endpoint.

```
┌─────────────────┐       ┌──────────────────────┐       ┌────────────────────────┐
│  Django View /  │  ───> │ Notification Service  │  ───> │  Celery Task Queue     │
│  Celery Beat    │       │ (Consent & Idempot.) │       │  (select_for_update)   │
└─────────────────┘       └──────────────────────┘       └───────────┬────────────┘
                                                                     │
                                  ┌──────────────────────────────────┴────────────────────────────────┐
                                  ▼                                                                   ▼
                     ┌────────────────────────┐                                          ┌────────────────────────┐
                     │   MockWhatsAppBackend   │                                          │MetaWhatsAppCloudBackend│
                     │  (status: MOCKED,       │                                          │ (status: SUBMITTED,    │
                     │   no network call)     │                                          │  Graph API Cloud)      │
                     └────────────────────────┘                                          └───────────┬────────────┘
                                                                                                     │
                                                                                                     ▼
                                                                                         ┌────────────────────────┐
                                                                                         │ Meta WhatsApp Business │
                                                                                         └───────────┬────────────┘
                                                                                                     │ (Delivery Webhook)
                                                                                                     ▼
                                                                                         ┌────────────────────────┐
                                                                                         │ /notifications/webhook │
                                                                                         │ (status: DELIVERED)    │
                                                                                         └────────────────────────┘
```

---

## 2. Meta Developer Account Setup

### Step 1: Create a Meta for Developers Account
1. Go to [developers.facebook.com](https://developers.facebook.com) and log in with your Facebook account.
2. Complete verification and agree to the Meta Developer Terms.

### Step 2: Create a Meta App
1. In the App Dashboard, click **Create App**.
2. Select **Other** as the use case, then choose **Business** as the app type.
3. Enter your app name (e.g., `LendMate Notifications`) and your contact email.
4. Select your **Meta Business Account** (or let Meta create one for you).
5. Click **Create App**.

### Step 3: Add WhatsApp Product
1. On the App Dashboard, scroll down to **Add products to your app**.
2. Find **WhatsApp** and click **Set up**.
3. You will be taken to the WhatsApp **API Setup** quickstart screen.

---

## 3. Test Phone Number & Credentials

On the WhatsApp **API Setup** screen:

1. **Temporary Access Token**:
   - Meta provides a 24-hour test token. Use this for initial test sends.
   - For production, create a **System User** with permanent access in Meta Business Manager (see Section 4).
2. **Phone Number ID**:
   - Located on the API Setup page under **Phone number ID**.
   - Copy this value into `WHATSAPP_PHONE_NUMBER_ID`.
3. **WhatsApp Business Account ID**:
   - Located under **WhatsApp Business Account ID**.
   - Copy this value into `WHATSAPP_BUSINESS_ACCOUNT_ID`.
4. **Recipient Phone Numbers for Testing**:
   - While using the test number, you can only send messages to up to 5 verified phone numbers.
   - Add your test mobile number under **To** dropdown -> **Manage phone number list**.
   - Verify it with the 6-digit OTP sent to your WhatsApp account.

---

## 4. Production System User & Permanent Token

Temporary tokens expire in 24 hours. For persistent production use:

1. Go to [business.facebook.com/settings](https://business.facebook.com/settings).
2. Navigate to **Users** -> **System Users**.
3. Click **Add**, name the user (e.g. `lendmate-backend`), and assign the **Admin** or **Employee** role.
4. Under **Assigned Assets**, assign your WhatsApp Business Account with full control permissions.
5. Click **Generate New Token**:
   - Select your App.
   - Set token expiration to **Never**.
   - Select the required permissions:
     - `whatsapp_business_messaging`
     - `whatsapp_business_management`
6. Copy the generated permanent token and configure it as `WHATSAPP_ACCESS_TOKEN`.

---

## 5. Message Template Creation & Approval

Meta requires all business-initiated messages outside the 24-hour customer care window to use **pre-approved message templates**.

In Meta WhatsApp Manager ([business.facebook.com/wa/manage/home/](https://business.facebook.com/wa/manage/home/)):
1. Navigate to **Account Tools** -> **Message Templates**.
2. Click **Create Template**.
3. Create the 5 LendMate templates with Category: **Utility** and Language: **English (en)**:

### Template 1: Loan Created
- **Template Name**: `lendmate_loan_created`
- **Category**: `Utility`
- **Language**: `English` (`en`)
- **Body Content**:
  ```
  Hello {{1}}, a loan of {{2}} has been recorded by {{3}} on {{4}}. Interest: {{5}}. Expected return date: {{6}}. Please contact your lender for details.
  ```
- **Parameter Samples**:
  - `{{1}}`: `Ravi Kumar`
  - `{{2}}`: `₹100,000.00`
  - `{{3}}`: `Jane Doe`
  - `{{4}}`: `15 Jan 2026`
  - `{{5}}`: `2.00% Monthly`
  - `{{6}}`: `15 Jan 2027`

### Template 2: Monthly Payment Reminder
- **Template Name**: `lendmate_monthly_reminder`
- **Category**: `Utility`
- **Language**: `English` (`en`)
- **Body Content**:
  ```
  Hello {{1}}, this is a reminder regarding your loan with {{2}}. Your scheduled payment of {{3}} is due on {{4}}. Please contact your lender if you have already made the payment.
  ```
- **Parameter Samples**:
  - `{{1}}`: `Ravi Kumar`
  - `{{2}}`: `Jane Doe`
  - `{{3}}`: `₹2,000.00`
  - `{{4}}`: `15 Nov 2026`

### Template 3: Payment Received
- **Template Name**: `lendmate_payment_received`
- **Category**: `Utility`
- **Language**: `English` (`en`)
- **Body Content**:
  ```
  Hello {{1}}, your payment of {{2}} has been recorded on {{3}}. Principal paid: {{4}}. Interest paid: {{5}}. Remaining principal: {{6}}. Thank you.
  ```
- **Parameter Samples**:
  - `{{1}}`: `Ravi Kumar`
  - `{{2}}`: `₹5,000.00`
  - `{{3}}`: `07 Nov 2026`
  - `{{4}}`: `₹3,000.00`
  - `{{5}}`: `₹2,000.00`
  - `{{6}}`: `₹97,000.00`

### Template 4: Overdue Payment Reminder
- **Template Name**: `lendmate_overdue_reminder`
- **Category**: `Utility`
- **Language**: `English` (`en`)
- **Body Content**:
  ```
  Hello {{1}}, our records show that your scheduled payment of {{2}} was due on {{3}}. Please contact {{4}} to discuss the payment status.
  ```
- **Parameter Samples**:
  - `{{1}}`: `Ravi Kumar`
  - `{{2}}`: `₹2,000.00`
  - `{{3}}`: `15 Oct 2026`
  - `{{4}}`: `Jane Doe`

### Template 5: Loan Closed
- **Template Name**: `lendmate_loan_closed`
- **Category**: `Utility`
- **Language**: `English` (`en`)
- **Body Content**:
  ```
  Hello {{1}}, your loan with {{2}} has been marked as closed. Thank you. Please contact your lender if you need clarification about your payment records.
  ```
- **Parameter Samples**:
  - `{{1}}`: `Ravi Kumar`
  - `{{2}}`: `Jane Doe`

> Utility templates are typically approved by Meta within minutes to a few hours.

---

## 6. Webhook Configuration

LendMate includes a built-in webhook endpoint at:
`https://your-domain.com/notifications/webhook/whatsapp/`

### Step 1: In Meta App Dashboard
1. Go to **WhatsApp** -> **Configuration** -> **Webhook**.
2. Click **Edit**.
3. **Callback URL**: Enter `https://your-domain.com/notifications/webhook/whatsapp/`
   *(In local development, use an HTTPS reverse tunnel such as ngrok or Cloudflare Tunnels).*
4. **Verify Token**: Enter the exact secret string you set in `WHATSAPP_VERIFY_TOKEN`.
5. Click **Verify and Save**. Meta will immediately send a verification `GET` challenge to your LendMate server.

### Step 2: Subscribe to Webhook Fields
In the Webhook configuration section, click **Manage** under Webhook fields and subscribe to:
- `messages` (includes inbound messages, delivery receipts: `sent`, `delivered`, `read`, and `failed`).

### Step 3: App Secret Verification
In Meta App Dashboard -> **App settings** -> **Basic**:
- Copy the **App Secret**.
- Add it to `WHATSAPP_APP_SECRET`. LendMate validates the `X-Hub-Signature-256` header using HMAC-SHA256 for all delivery updates.

---

## 7. Environment Variables Configuration

In your `.env` file (never commit this file):

```ini
# --- WhatsApp Provider Configuration ---

# For local development / testing without live API:
WHATSAPP_BACKEND=notifications.whatsapp.MockWhatsAppBackend

# For live Meta Cloud API:
# WHATSAPP_BACKEND=notifications.whatsapp.MetaWhatsAppCloudBackend

# Meta Cloud API Credentials:
WHATSAPP_ACCESS_TOKEN=EAAG...your_meta_system_user_access_token
WHATSAPP_PHONE_NUMBER_ID=109283746501928
WHATSAPP_BUSINESS_ACCOUNT_ID=987162534019283
WHATSAPP_API_VERSION=v20.0

# Webhook Security Tokens:
WHATSAPP_VERIFY_TOKEN=generate-a-strong-random-verify-token-here
WHATSAPP_APP_SECRET=your_meta_app_secret_here

# Optional: Override default template names if customized in Meta
WHATSAPP_TEMPLATE_LOAN_CREATED=lendmate_loan_created
WHATSAPP_TEMPLATE_PAYMENT_RECEIVED=lendmate_payment_received
WHATSAPP_TEMPLATE_MONTHLY_REMINDER=lendmate_monthly_reminder
WHATSAPP_TEMPLATE_OVERDUE_REMINDER=lendmate_overdue_reminder
WHATSAPP_TEMPLATE_LOAN_CLOSED=lendmate_loan_closed
WHATSAPP_TEMPLATE_LANGUAGE=en
```

---

## 8. Running Redis & Celery

LendMate queues notifications asynchronously using Celery and Redis.

### 1. Start Redis
```bash
# Docker:
docker run -d -p 6379:6379 --name lendmate-redis redis:7-alpine

# Or native Redis server:
redis-server
```

### 2. Start Celery Worker
```bash
# Windows (solo pool avoids OS fork limitations):
celery -A config worker --loglevel=info --pool=solo

# Linux / macOS:
celery -A config worker --loglevel=info
```

### 3. Start Celery Beat Scheduler (for daily reminders)
```bash
celery -A config beat --loglevel=info
```

---

## 9. Switching Between Mock and Meta Backends

### Safe Development Mode (Default)
```ini
WHATSAPP_BACKEND=notifications.whatsapp.MockWhatsAppBackend
```
- Completely isolated from the network.
- Simulates realistic generation of message IDs (`mock-wa-...`).
- Notifications display with badge: **Mocked – Not Transmitted**.
- Ideal for manual testing, creating loans, registering payments, and automated test suites.

### Live Production Mode
```ini
WHATSAPP_BACKEND=notifications.whatsapp.MetaWhatsAppCloudBackend
```
- Transmits through `https://graph.facebook.com/v20.0/{phone_number_id}/messages`.
- Notifications transition from **Pending** -> **Processing** -> **Submitted to WhatsApp**.
- Delivery report webhook transitions notification to **Delivered** (or **Failed** with detailed reason).

---

## 10. Verification Checklist

Before going live:
- [ ] Borrower has `whatsapp_consent = True` explicitly granted in their profile.
- [ ] Lender has enabled **WhatsApp Notifications (Master Switch)** in Settings.
- [ ] The 5 utility message templates are approved in Meta WhatsApp Manager.
- [ ] `WHATSAPP_ACCESS_TOKEN` is a non-expiring System User token with messaging permissions.
- [ ] Webhook URL is verified and returns `200` with Meta's challenge.
- [ ] Webhook signature verification succeeds with `WHATSAPP_APP_SECRET`.
- [ ] Celery worker and beat scheduler are running.
