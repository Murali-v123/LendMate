"""
Comprehensive tests for the LendMate WhatsApp notification system.

All tests use mocks or MockWhatsAppBackend — no real network calls or WhatsApp messages are sent.
"""
import datetime
import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import UserPreferences
from lending.models import Borrower, Loan, Payment
from .models import Notification
from .service import (
    enqueue_loan_closed,
    enqueue_loan_created,
    enqueue_monthly_reminder,
    enqueue_overdue_reminder,
    enqueue_payment_received,
)
from .tasks import (
    recover_stuck_notifications,
    send_monthly_reminders,
    send_overdue_reminders,
    send_whatsapp_notification,
)
from .templates_whatsapp import (
    build_loan_closed_payload,
    build_loan_created_payload,
    build_monthly_reminder_payload,
    build_overdue_reminder_payload,
    build_payment_received_payload,
)
from .whatsapp import (
    BaseWhatsAppBackend,
    MetaWhatsAppCloudBackend,
    MockWhatsAppBackend,
    WhatsAppResult,
    WhatsAppStatus,
    mask_phone_number,
    normalize_phone_number,
    send_whatsapp_template,
)
from .views import _handle_status_update, replay_unmatched_webhooks_for_notification

User = get_user_model()


class LendMateWhatsAppTestMixin:
    """Creates a lender, preferences, a borrower and a loan for reuse."""

    def setUp(self):
        super().setUp()
        self.lender = User.objects.create_user(
            username="testlender",
            password="testpass1234",
            first_name="Test",
            last_name="Lender",
            email="lender@example.com",
        )
        self.prefs = UserPreferences.objects.create(
            user=self.lender,
            whatsapp_notifications_enabled=True,
            whatsapp_loan_created=True,
            whatsapp_payment_received=True,
            whatsapp_monthly_reminders=True,
            whatsapp_overdue_reminders=True,
            whatsapp_loan_closed=True,
        )
        self.borrower = Borrower.objects.create(
            lender=self.lender,
            full_name="Ravi Kumar",
            mobile_number="9876543210",
            whatsapp_consent=True,
            sms_consent=False,
        )
        self.loan = Loan.objects.create(
            borrower=self.borrower,
            principal=Decimal("100000.00"),
            interest_rate=Decimal("2.00"),
            interest_period="monthly",
            interest_basis="original",
            lending_date=datetime.date(2026, 1, 15),
            due_date=datetime.date(2027, 1, 15),
            monthly_due_day=15,
            status="open",
        )


# ===========================================================================
# 1. Mock WhatsApp Backend Tests
# ===========================================================================

class MockWhatsAppBackendTests(SimpleTestCase):
    def test_mock_backend_returns_mocked_status(self):
        backend = MockWhatsAppBackend()
        result = backend.send_template(
            to="9876543210",
            template_name="lendmate_loan_created",
            language_code="en",
            body_parameters=["Ravi", "₹10,000.00"],
            fallback_text="Test message",
        )
        self.assertEqual(result.status, WhatsAppStatus.MOCKED)
        self.assertFalse(result.was_transmitted)
        self.assertEqual(result.provider, "mock")
        self.assertTrue(result.provider_message_id.startswith("mock-wa-"))
        self.assertEqual(result.details["template"], "lendmate_loan_created")

    @override_settings(WHATSAPP_BACKEND="notifications.whatsapp.MockWhatsAppBackend")
    def test_send_whatsapp_template_helper_uses_configured_backend(self):
        result = send_whatsapp_template(
            to="9876543210",
            template_name="lendmate_loan_created",
            language_code="en",
            body_parameters=["Ravi"],
        )
        self.assertEqual(result.status, WhatsAppStatus.MOCKED)
        self.assertFalse(result.was_transmitted)


# ===========================================================================
# 2. Meta WhatsApp Cloud Backend Request Construction & Credentials
# ===========================================================================

class MetaWhatsAppCloudBackendTests(SimpleTestCase):
    def setUp(self):
        self.backend = MetaWhatsAppCloudBackend()

    def test_phone_normalization_valid_indian_numbers(self):
        self.assertEqual(normalize_phone_number("9876543210"), "919876543210")
        self.assertEqual(normalize_phone_number("+919876543210"), "919876543210")
        self.assertEqual(normalize_phone_number("09876543210"), "919876543210")
        self.assertEqual(normalize_phone_number("+91 98765-43210"), "919876543210")

    def test_phone_normalization_invalid_numbers(self):
        self.assertIsNone(normalize_phone_number("123456"))
        self.assertIsNone(normalize_phone_number("5876543210"))
        self.assertIsNone(normalize_phone_number(""))

    def test_phone_masking(self):
        self.assertEqual(mask_phone_number("919876543210"), "9198****3210")
        self.assertEqual(mask_phone_number("123"), "****")

    def test_build_payload_structure(self):
        payload = self.backend.build_payload(
            to="919876543210",
            template_name="lendmate_loan_created",
            language_code="en",
            body_parameters=["Ravi", "₹100,000.00", "Lender"],
        )
        self.assertEqual(payload["messaging_product"], "whatsapp")
        self.assertEqual(payload["to"], "919876543210")
        self.assertEqual(payload["type"], "template")
        self.assertEqual(payload["template"]["name"], "lendmate_loan_created")
        self.assertEqual(payload["template"]["language"]["code"], "en")
        components = payload["template"]["components"]
        self.assertEqual(len(components), 1)
        self.assertEqual(components[0]["type"], "body")
        params = components[0]["parameters"]
        self.assertEqual(len(params), 3)
        self.assertEqual(params[0], {"type": "text", "text": "Ravi"})
        self.assertEqual(params[1], {"type": "text", "text": "₹100,000.00"})

    @override_settings(
        WHATSAPP_ACCESS_TOKEN="",
        WHATSAPP_PHONE_NUMBER_ID="12345",
    )
    def test_missing_access_token_fails_gracefully(self):
        result = self.backend.send_template(
            to="9876543210",
            template_name="test",
            language_code="en",
            body_parameters=[],
        )
        self.assertEqual(result.status, WhatsAppStatus.FAILED)
        self.assertIn("WHATSAPP_ACCESS_TOKEN is not configured", result.error)

    @override_settings(
        WHATSAPP_ACCESS_TOKEN="secret-token",
        WHATSAPP_PHONE_NUMBER_ID="",
    )
    def test_missing_phone_id_fails_gracefully(self):
        result = self.backend.send_template(
            to="9876543210",
            template_name="test",
            language_code="en",
            body_parameters=[],
        )
        self.assertEqual(result.status, WhatsAppStatus.FAILED)
        self.assertIn("WHATSAPP_PHONE_NUMBER_ID is not configured", result.error)

    @override_settings(
        WHATSAPP_ACCESS_TOKEN="secret-token",
        WHATSAPP_PHONE_NUMBER_ID="99887766",
        WHATSAPP_API_VERSION="v20.0",
    )
    @patch("requests.post")
    def test_successful_meta_api_submission(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "messaging_product": "whatsapp",
            "contacts": [{"input": "919876543210", "wa_id": "919876543210"}],
            "messages": [{"id": "wamid.HBgLMTIzNDU2"}],
        }
        mock_post.return_value = mock_response

        result = self.backend.send_template(
            to="9876543210",
            template_name="lendmate_loan_created",
            language_code="en",
            body_parameters=["Ravi Kumar"],
        )

        self.assertEqual(result.status, WhatsAppStatus.SUBMITTED)
        self.assertTrue(result.was_transmitted)
        self.assertEqual(result.provider_message_id, "wamid.HBgLMTIzNDU2")
        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        self.assertEqual(call_url, "https://graph.facebook.com/v20.0/99887766/messages")

    @override_settings(
        WHATSAPP_ACCESS_TOKEN="secret-token",
        WHATSAPP_PHONE_NUMBER_ID="99887766",
    )
    @patch("requests.post")
    def test_meta_api_error_response_sanitized(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "error": {
                "message": "(#100) Param template['name'] is not valid",
                "type": "OAuthException",
                "code": 100,
                "error_subcode": 2388040,
                "fbtrace_id": "A1B2C3D4",
            }
        }
        mock_post.return_value = mock_response

        result = self.backend.send_template(
            to="9876543210",
            template_name="invalid_template",
            language_code="en",
            body_parameters=[],
        )

        self.assertEqual(result.status, WhatsAppStatus.FAILED)
        self.assertIn("Meta API Error (100/2388040)", result.error)
        # Ensure access token is never leaked in error
        self.assertNotIn("secret-token", result.error)


# ===========================================================================
# 3. WhatsApp Message Templates Formatting Tests
# ===========================================================================

class WhatsAppTemplateFormattingTests(LendMateWhatsAppTestMixin, TestCase):
    def test_loan_created_payload(self):
        payload = build_loan_created_payload(self.loan)
        self.assertEqual(payload.template_name, "lendmate_loan_created")
        self.assertIn("Ravi Kumar", payload.parameters)
        self.assertIn("₹100,000.00", payload.parameters)
        self.assertIn("Test Lender", payload.parameters)
        self.assertIn("2.00% Monthly", payload.parameters)
        self.assertIn("15 Jan 2027", payload.parameters)
        self.assertIn("Hello Ravi Kumar, a loan of ₹100,000.00", payload.rendered_text)

    def test_payment_received_payload(self):
        payment = Payment.objects.create(
            loan=self.loan,
            amount=Decimal("5000.00"),
            principal_component=Decimal("3000.00"),
            interest_component=Decimal("2000.00"),
            payment_date=datetime.date(2026, 2, 15),
        )
        payload = build_payment_received_payload(payment)
        self.assertEqual(payload.template_name, "lendmate_payment_received")
        self.assertIn("₹5,000.00", payload.parameters)
        self.assertIn("₹3,000.00", payload.parameters)
        self.assertIn("₹2,000.00", payload.parameters)
        self.assertIn("₹97,000.00", payload.parameters)
        self.assertIn("Hello Ravi Kumar, your payment of ₹5,000.00", payload.rendered_text)

    def test_monthly_reminder_payload(self):
        payload = build_monthly_reminder_payload(
            self.loan,
            datetime.date(2026, 2, 15),
            Decimal("2000.00"),
        )
        self.assertEqual(payload.template_name, "lendmate_monthly_reminder")
        self.assertIn("₹2,000.00", payload.parameters)
        self.assertIn("15 Feb 2026", payload.parameters)

    def test_overdue_reminder_payload(self):
        payload = build_overdue_reminder_payload(
            self.loan,
            datetime.date(2026, 1, 15),
            Decimal("2000.00"),
        )
        self.assertEqual(payload.template_name, "lendmate_overdue_reminder")
        self.assertIn("₹2,000.00", payload.parameters)
        self.assertIn("15 Jan 2026", payload.parameters)

    def test_loan_closed_payload(self):
        payload = build_loan_closed_payload(self.loan)
        self.assertEqual(payload.template_name, "lendmate_loan_closed")
        self.assertIn("Ravi Kumar", payload.parameters)
        self.assertIn("Test Lender", payload.parameters)


# ===========================================================================
# 4. Consent and Suppression Tests
# ===========================================================================

class ConsentAndSuppressionTests(LendMateWhatsAppTestMixin, TestCase):
    def test_suppressed_when_borrower_whatsapp_consent_false(self):
        self.borrower.whatsapp_consent = False
        self.borrower.save()

        notif = enqueue_loan_created(self.loan)
        self.assertEqual(notif.status, Notification.SUPPRESSED)
        self.assertIn("Borrower has not consented to WhatsApp notifications", notif.last_error)

    def test_withdrawn_consent_prevents_subsequent_notifications(self):
        # 1. First event with consent active -> Pending
        notif1 = enqueue_loan_created(self.loan)
        self.assertEqual(notif1.status, Notification.PENDING)

        # 2. Borrower withdraws WhatsApp consent
        self.borrower.whatsapp_consent = False
        self.borrower.save()

        payment = Payment.objects.create(
            loan=self.loan,
            amount=Decimal("1000.00"),
            principal_component=Decimal("1000.00"),
            interest_component=Decimal("0.00"),
            payment_date=datetime.date(2026, 3, 1),
        )
        notif2 = enqueue_payment_received(payment)
        self.assertEqual(notif2.status, Notification.SUPPRESSED)
        self.assertIn("Borrower has not consented", notif2.last_error)

    def test_suppressed_when_lender_whatsapp_globally_disabled(self):
        self.prefs.whatsapp_notifications_enabled = False
        self.prefs.save()

        notif = enqueue_loan_created(self.loan)
        self.assertEqual(notif.status, Notification.SUPPRESSED)
        self.assertIn("WhatsApp notifications are disabled in lender settings", notif.last_error)

    def test_suppressed_when_individual_category_disabled(self):
        self.prefs.whatsapp_loan_created = False
        self.prefs.save()

        notif = enqueue_loan_created(self.loan)
        self.assertEqual(notif.status, Notification.SUPPRESSED)
        self.assertIn("category 'loan_created' is disabled", notif.last_error)

        # But payment received category is still on
        payment = Payment.objects.create(
            loan=self.loan,
            amount=Decimal("1000.00"),
            principal_component=Decimal("1000.00"),
            interest_component=Decimal("0.00"),
            payment_date=datetime.date(2026, 3, 1),
        )
        notif2 = enqueue_payment_received(payment)
        self.assertEqual(notif2.status, Notification.PENDING)

    def test_suppressed_when_invalid_phone_number(self):
        self.borrower.mobile_number = "12345"
        self.borrower.save()

        notif = enqueue_loan_created(self.loan)
        self.assertEqual(notif.status, Notification.SUPPRESSED)
        self.assertIn("does not appear to be a valid mobile number", notif.last_error)


# ===========================================================================
# 5. Idempotency & Duplicate Prevention Tests
# ===========================================================================

class IdempotencyTests(LendMateWhatsAppTestMixin, TestCase):
    def test_duplicate_loan_created_prevented(self):
        notif1 = enqueue_loan_created(self.loan)
        notif2 = enqueue_loan_created(self.loan)
        self.assertEqual(notif1.pk, notif2.pk)
        self.assertEqual(Notification.objects.filter(loan=self.loan).count(), 1)

    def test_duplicate_monthly_reminder_prevented(self):
        rec1, created1 = enqueue_monthly_reminder(
            self.loan, datetime.date(2026, 2, 15), Decimal("2000.00"), "2026-02"
        )
        self.assertTrue(created1)

        rec2, created2 = enqueue_monthly_reminder(
            self.loan, datetime.date(2026, 2, 15), Decimal("2000.00"), "2026-02"
        )
        self.assertFalse(created2)
        self.assertEqual(rec1.pk, rec2.pk)


# ===========================================================================
# 6. Celery Task Processing & Retry Tests
# ===========================================================================

class CeleryTaskTests(LendMateWhatsAppTestMixin, TestCase):
    @override_settings(WHATSAPP_BACKEND="notifications.whatsapp.MockWhatsAppBackend")
    def test_mock_backend_processing_results_in_mocked_status(self):
        notif = enqueue_loan_created(self.loan)
        self.assertEqual(notif.status, Notification.PENDING)

        send_whatsapp_notification(notif.pk)
        notif.refresh_from_db()

        # Crucial requirement: Mocked notification must NEVER be marked as SENT or DELIVERED
        self.assertEqual(notif.status, Notification.MOCKED)
        self.assertNotEqual(notif.status, Notification.SUBMITTED)
        self.assertNotEqual(notif.status, Notification.DELIVERED)
        self.assertTrue(notif.provider_message_id.startswith("mock-wa-"))
        self.assertEqual(notif.attempts, 1)

    @patch("notifications.tasks.send_whatsapp_template")
    def test_submitted_status_on_live_provider_acceptance(self, mock_send):
        mock_send.return_value = WhatsAppResult(
            status=WhatsAppStatus.SUBMITTED,
            provider="meta_cloud",
            provider_message_id="wamid.12345678",
        )

        notif = enqueue_loan_created(self.loan)
        send_whatsapp_notification(notif.pk)
        notif.refresh_from_db()

        # Provider accepted -> SUBMITTED, awaiting delivery webhook
        self.assertEqual(notif.status, Notification.SUBMITTED)
        self.assertNotEqual(notif.status, Notification.DELIVERED)
        self.assertEqual(notif.provider_message_id, "wamid.12345678")

    @patch("notifications.tasks.send_whatsapp_template")
    def test_task_retries_transient_failure_until_max_attempts(self, mock_send):
        mock_send.return_value = WhatsAppResult(
            status=WhatsAppStatus.FAILED,
            provider="meta_cloud",
            error="Network timeout",
        )

        notif = enqueue_loan_created(self.loan)

        # Attempt 1 -> PENDING with retry scheduled
        send_whatsapp_notification(notif.pk)
        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.PENDING)
        self.assertEqual(notif.attempts, 1)
        self.assertIsNotNone(notif.next_retry_at)

        # Advance attempts to 4 and simulate retry countdown reached
        notif.attempts = 4
        notif.next_retry_at = timezone.now() - datetime.timedelta(seconds=1)
        notif.save()

        # Attempt 5 -> FAILED permanently
        send_whatsapp_notification(notif.pk)
        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.FAILED)
        self.assertEqual(notif.attempts, 5)
        self.assertIsNone(notif.next_retry_at)


# ===========================================================================
# 7. Recovery of Stale Processing Notifications
# ===========================================================================

class StuckNotificationRecoveryTests(LendMateWhatsAppTestMixin, TestCase):
    @patch("notifications.tasks.send_whatsapp_notification.delay")
    def test_stale_processing_notification_recovered_correctly(self, mock_delay):
        notif_stale = Notification.objects.create(
            lender=self.lender,
            borrower=self.borrower,
            loan=self.loan,
            notification_type=Notification.LOAN_CREATED,
            recipient_number="9876543210",
            status=Notification.PROCESSING,
            attempts=1,
            event_key="test-stale-key",
        )
        # Artificially set updated_at to 15 minutes ago
        past_time = timezone.now() - datetime.timedelta(minutes=15)
        Notification.objects.filter(pk=notif_stale.pk).update(updated_at=past_time)

        notif_recent = Notification.objects.create(
            lender=self.lender,
            borrower=self.borrower,
            loan=self.loan,
            notification_type=Notification.PAYMENT_RECEIVED,
            recipient_number="9876543210",
            status=Notification.PROCESSING,
            attempts=1,
            event_key="test-recent-key",
        )

        recover_stuck_notifications()

        notif_stale.refresh_from_db()
        notif_recent.refresh_from_db()

        # Stale record (> 10m) should be reset to PENDING and redispatched
        self.assertEqual(notif_stale.status, Notification.PENDING)
        self.assertIn("Recovered from stale PROCESSING state", notif_stale.last_error)
        mock_delay.assert_called_with(notif_stale.pk)

        # Fresh record (< 10m) must NOT be interrupted
        self.assertEqual(notif_recent.status, Notification.PROCESSING)


# ===========================================================================
# 8. Webhook Verification and Delivery Updates
# ===========================================================================

class WhatsAppWebhookTests(LendMateWhatsAppTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.webhook_url = reverse("notifications:whatsapp_webhook")

    @override_settings(WHATSAPP_VERIFY_TOKEN="my-secret-verify-token")
    def test_webhook_get_verification_success(self):
        response = self.client.get(
            self.webhook_url,
            {
                "hub.mode": "subscribe",
                "hub.verify_token": "my-secret-verify-token",
                "hub.challenge": "challenge_12345",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "challenge_12345")

    @override_settings(WHATSAPP_VERIFY_TOKEN="my-secret-verify-token")
    def test_webhook_get_verification_wrong_token_rejected(self):
        response = self.client.get(
            self.webhook_url,
            {
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong-token",
                "hub.challenge": "challenge_12345",
            },
        )
        self.assertEqual(response.status_code, 403)

    @override_settings(WHATSAPP_APP_SECRET="app-secret-1234")
    def test_webhook_post_signature_validation(self):
        body = json.dumps({"entry": []}).encode("utf-8")
        valid_signature = "sha256=" + hmac.new(
            b"app-secret-1234", body, hashlib.sha256
        ).hexdigest()

        # Valid signature -> 200
        response = self.client.post(
            self.webhook_url,
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=valid_signature,
        )
        self.assertEqual(response.status_code, 200)

        # Invalid signature -> 403
        bad_response = self.client.post(
            self.webhook_url,
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256="sha256=bad-sig",
        )
        self.assertEqual(bad_response.status_code, 403)

    @override_settings(WHATSAPP_APP_SECRET="test-app-secret")
    def test_webhook_delivery_status_transitions(self):
        notif = Notification.objects.create(
            lender=self.lender,
            borrower=self.borrower,
            loan=self.loan,
            notification_type=Notification.LOAN_CREATED,
            recipient_number="9876543210",
            status=Notification.SUBMITTED,
            provider_message_id="wamid.HBgL1234",
            event_key="webhook-test-1",
        )

        secret = b"test-app-secret"

        # 1. Delivery update -> DELIVERED
        payload_delivered = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "statuses": [
                                    {
                                        "id": "wamid.HBgL1234",
                                        "status": "delivered",
                                        "timestamp": "1731000000",
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        body1 = json.dumps(payload_delivered).encode("utf-8")
        sig1 = "sha256=" + hmac.new(secret, body1, hashlib.sha256).hexdigest()

        response = self.client.post(
            self.webhook_url,
            data=body1,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=sig1,
        )
        self.assertEqual(response.status_code, 200)
        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.DELIVERED)

        # 2. Duplicate or stale 'sent' event should NEVER downgrade DELIVERED
        payload_sent = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "statuses": [
                                    {
                                        "id": "wamid.HBgL1234",
                                        "status": "sent",
                                        "timestamp": "1730999990",
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        body2 = json.dumps(payload_sent).encode("utf-8")
        sig2 = "sha256=" + hmac.new(secret, body2, hashlib.sha256).hexdigest()

        self.client.post(
            self.webhook_url,
            data=body2,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=sig2,
        )
        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.DELIVERED)


# ===========================================================================
# 9. Notification Dashboard & History UI Tests
# ===========================================================================

class NotificationDashboardTests(LendMateWhatsAppTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.history_url = reverse("notifications:history")
        self.notif_mocked = Notification.objects.create(
            lender=self.lender,
            borrower=self.borrower,
            loan=self.loan,
            notification_type=Notification.LOAN_CREATED,
            recipient_number="9876543210",
            status=Notification.MOCKED,
            event_key="dash-mocked",
            message="Test mocked notification message",
        )
        self.notif_submitted = Notification.objects.create(
            lender=self.lender,
            borrower=self.borrower,
            loan=self.loan,
            notification_type=Notification.PAYMENT_RECEIVED,
            recipient_number="9876543210",
            status=Notification.SUBMITTED,
            event_key="dash-submitted",
            message="Test submitted notification message",
        )
        self.notif_delivered = Notification.objects.create(
            lender=self.lender,
            borrower=self.borrower,
            loan=self.loan,
            notification_type=Notification.MONTHLY_REMINDER,
            recipient_number="9876543210",
            status=Notification.DELIVERED,
            event_key="dash-delivered",
            message="Test delivered notification message",
        )
        self.notif_failed = Notification.objects.create(
            lender=self.lender,
            borrower=self.borrower,
            loan=self.loan,
            notification_type=Notification.OVERDUE_REMINDER,
            recipient_number="9876543210",
            status=Notification.FAILED,
            event_key="dash-failed",
            last_error="Simulated provider connection failure",
            attempts=1,
            message="Test failed notification message",
        )

    def test_dashboard_displays_all_statuses(self):
        self.client.force_login(self.lender)
        response = self.client.get(self.history_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "WhatsApp Notifications")
        self.assertContains(response, "Mocked – Not Transmitted")
        self.assertContains(response, "Submitted to WhatsApp")
        self.assertContains(response, "Delivered")
        self.assertContains(response, "Failed")

    def test_dashboard_filtering_by_status(self):
        self.client.force_login(self.lender)

        # Filter: mocked
        res_mocked = self.client.get(self.history_url + "?status=mocked")
        self.assertEqual(res_mocked.status_code, 200)
        self.assertContains(res_mocked, "Test mocked notification message")
        self.assertNotContains(res_mocked, "Test submitted notification message")

        # Filter: submitted
        res_submitted = self.client.get(self.history_url + "?status=submitted")
        self.assertEqual(res_submitted.status_code, 200)
        self.assertContains(res_submitted, "Test submitted notification message")
        self.assertNotContains(res_submitted, "Test mocked notification message")

        # Filter: delivered
        res_delivered = self.client.get(self.history_url + "?status=delivered")
        self.assertEqual(res_delivered.status_code, 200)
        self.assertContains(res_delivered, "Test delivered notification message")

        # Filter: failed
        res_failed = self.client.get(self.history_url + "?status=failed")
        self.assertEqual(res_failed.status_code, 200)
        self.assertContains(res_failed, "Test failed notification message")

    @patch("notifications.tasks.send_whatsapp_notification.delay")
    def test_manual_retry_failed_notification(self, mock_delay):
        self.client.force_login(self.lender)
        retry_url = reverse("notifications:retry", kwargs={"pk": self.notif_failed.pk})
        response = self.client.post(retry_url, follow=True)
        self.assertEqual(response.status_code, 200)

        self.notif_failed.refresh_from_db()
        self.assertEqual(self.notif_failed.status, Notification.PENDING)
        mock_delay.assert_called_with(self.notif_failed.pk)


# ===========================================================================
# 10. Critical WhatsApp Migration & Concurrency Scenarios
# ===========================================================================

class WhatsAppCriticalCorrectionsTests(LendMateWhatsAppTestMixin, TestCase):
    """
    Direct coverage for the 13 required verification scenarios:
    1. Historical notification channel retention (channel='sms').
    2. New notification channel default (channel='whatsapp').
    3. Two workers claiming the same notification (worker 2 skips).
    4. Duplicate Celery task delivery (idempotent skip when not PENDING).
    5. PROCESSING notifications skipped by worker.
    6. Un-dispatched PENDING notifications (Redis failure) recovered.
    7. Retry timing and next_retry_at (future skipped, due recovered).
    8. Mocked notifications have sent_at=None, valid processed_at, correct UI labeling.
    9. Borrower form preserves sms_consent when omitted in POST (tested in lending).
    10. Webhook updates prevent status downgrades (DELIVERED protected).
    11. Webhook requests with invalid or missing signature rejected (403).
    12. Webhook delivery updates work for delivered and read events.
    13. Existing notification history preserved and queryable.
    """

    def test_01_historical_channel_retention(self):
        """Historical notifications retain channel='sms'."""
        historical = Notification.objects.create(
            lender=self.lender,
            borrower=self.borrower,
            loan=self.loan,
            channel=Notification.CHANNEL_SMS,
            notification_type=Notification.LOAN_CREATED,
            recipient_number="9876543210",
            status="sent",
            event_key="hist-sms-01",
        )
        historical.refresh_from_db()
        self.assertEqual(historical.channel, Notification.CHANNEL_SMS)
        self.assertEqual(historical.channel, "sms")

    def test_02_new_notification_channel_default(self):
        """New notifications default to channel='whatsapp'."""
        new_notif = Notification.objects.create(
            lender=self.lender,
            borrower=self.borrower,
            loan=self.loan,
            notification_type=Notification.LOAN_CREATED,
            recipient_number="9876543210",
            event_key="new-notif-02",
        )
        self.assertEqual(new_notif.channel, Notification.CHANNEL_WHATSAPP)
        self.assertEqual(new_notif.channel, "whatsapp")

        # Also via service enqueue function
        enqueued = enqueue_loan_created(self.loan)
        self.assertEqual(enqueued.channel, Notification.CHANNEL_WHATSAPP)

    @patch("notifications.tasks.send_whatsapp_template")
    def test_03_two_workers_claiming_same_notification(self, mock_send):
        """When worker 1 claims a notification, worker 2 safely skips it."""
        notif = enqueue_loan_created(self.loan)
        self.assertEqual(notif.status, Notification.PENDING)

        # Worker 1 claims it (changes status to PROCESSING inside transaction)
        Notification.objects.filter(pk=notif.pk).update(status=Notification.PROCESSING)

        # Worker 2 attempts to process the same notification
        send_whatsapp_notification(notif.pk)
        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.PROCESSING)

        # mock_send should not be called by worker 2
        mock_send.assert_not_called()

    @patch("notifications.tasks.send_whatsapp_template")
    def test_04_duplicate_celery_task_delivery(self, mock_send):
        """Duplicate Celery task delivery for the same notification is safely skipped."""
        mock_send.return_value = WhatsAppResult(
            status=WhatsAppStatus.SUBMITTED,
            provider="meta_cloud",
            provider_message_id="wamid.dup_test",
        )
        notif = enqueue_loan_created(self.loan)

        # First task execution succeeds
        send_whatsapp_notification(notif.pk)
        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.SUBMITTED)

        # Duplicate delivery of the task arrives
        send_whatsapp_notification(notif.pk)
        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.SUBMITTED)

        # Provider API was invoked exactly once
        self.assertEqual(mock_send.call_count, 1)

    @patch("notifications.tasks.send_whatsapp_template")
    def test_05_processing_notifications_skipped(self, mock_send):
        """Worker skips notifications currently in PROCESSING state."""
        notif = Notification.objects.create(
            lender=self.lender,
            borrower=self.borrower,
            loan=self.loan,
            notification_type=Notification.LOAN_CREATED,
            recipient_number="9876543210",
            status=Notification.PROCESSING,
            event_key="proc-skip-test",
        )
        send_whatsapp_notification(notif.pk)
        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.PROCESSING)
        mock_send.assert_not_called()

    @patch("notifications.tasks.send_whatsapp_notification.delay")
    def test_06_redis_undispatched_pending_recovered(self, mock_delay):
        """
        Pending notifications that were created but never dispatched
        (e.g., Redis broker downtime) are safely recovered.
        """
        notif = Notification.objects.create(
            lender=self.lender,
            borrower=self.borrower,
            loan=self.loan,
            notification_type=Notification.LOAN_CREATED,
            recipient_number="9876543210",
            status=Notification.PENDING,
            attempts=0,
            event_key="redis-fail-key",
        )
        # Artificially set created_at and updated_at to 5 minutes ago
        past_time = timezone.now() - datetime.timedelta(minutes=5)
        Notification.objects.filter(pk=notif.pk).update(
            created_at=past_time,
            updated_at=past_time,
        )

        recovered_count = recover_stuck_notifications()
        self.assertGreaterEqual(recovered_count, 1)
        mock_delay.assert_called_with(notif.pk)

    def test_07_retry_timing_future_and_due(self):
        """
        Notifications with future next_retry_at are skipped;
        notifications with due next_retry_at are processed.
        """
        # 1. Future next_retry_at -> skipped
        notif_future = Notification.objects.create(
            lender=self.lender,
            borrower=self.borrower,
            loan=self.loan,
            notification_type=Notification.LOAN_CREATED,
            recipient_number="9876543210",
            status=Notification.PENDING,
            attempts=1,
            next_retry_at=timezone.now() + datetime.timedelta(minutes=10),
            event_key="retry-future-key",
        )
        send_whatsapp_notification(notif_future.pk)
        notif_future.refresh_from_db()
        self.assertEqual(notif_future.status, Notification.PENDING)
        self.assertEqual(notif_future.attempts, 1)

        # 2. Due next_retry_at -> recovered and dispatched
        notif_due = Notification.objects.create(
            lender=self.lender,
            borrower=self.borrower,
            loan=self.loan,
            notification_type=Notification.LOAN_CREATED,
            recipient_number="9876543210",
            status=Notification.PENDING,
            attempts=1,
            next_retry_at=timezone.now() - datetime.timedelta(minutes=1),
            event_key="retry-due-key",
        )
        with patch("notifications.tasks.send_whatsapp_notification.delay") as mock_delay:
            recovered = recover_stuck_notifications()
            self.assertGreaterEqual(recovered, 1)
            mock_delay.assert_called_with(notif_due.pk)

    @override_settings(WHATSAPP_BACKEND="notifications.whatsapp.MockWhatsAppBackend")
    def test_08_mocked_notification_timestamps_and_labeling(self):
        """
        MOCKED notifications have sent_at is None, valid processed_at,
        and are never marked or displayed as sent or delivered.
        """
        notif = enqueue_loan_created(self.loan)
        send_whatsapp_notification(notif.pk)
        notif.refresh_from_db()

        self.assertEqual(notif.status, Notification.MOCKED)
        self.assertIsNone(notif.sent_at)
        self.assertIsNotNone(notif.processed_at)
        self.assertIn("Mocked", notif.get_status_display())
        self.assertNotIn("Sent", notif.get_status_display())
        self.assertNotIn("Delivered", notif.get_status_display())

    @override_settings(WHATSAPP_APP_SECRET="test-secret-key")
    def test_09_webhook_downgrade_prevention(self):
        """
        DELIVERED notifications cannot be downgraded to SUBMITTED or FAILED
        by late or out-of-order webhook events.
        """
        notif = Notification.objects.create(
            lender=self.lender,
            borrower=self.borrower,
            loan=self.loan,
            notification_type=Notification.LOAN_CREATED,
            recipient_number="9876543210",
            status=Notification.DELIVERED,
            provider_message_id="wamid.protect_downgrade",
            event_key="protect-downgrade-key",
        )

        secret = b"test-secret-key"
        # Out-of-order 'failed' event arrives
        payload_failed = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "statuses": [
                                    {
                                        "id": "wamid.protect_downgrade",
                                        "status": "failed",
                                        "errors": [{"code": 131026, "title": "Undeliverable"}],
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        body = json.dumps(payload_failed).encode("utf-8")
        sig = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()

        resp = self.client.post(
            reverse("notifications:whatsapp_webhook"),
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=sig,
        )
        self.assertEqual(resp.status_code, 200)

        notif.refresh_from_db()
        # Status must remain DELIVERED
        self.assertEqual(notif.status, Notification.DELIVERED)

    @override_settings(WHATSAPP_APP_SECRET="test-secret-key")
    def test_10_webhook_signature_rejections(self):
        """Webhook requests with missing or invalid signatures are rejected with 403."""
        webhook_url = reverse("notifications:whatsapp_webhook")
        body = json.dumps({"entry": []}).encode("utf-8")

        # 1. Missing signature header
        resp_missing = self.client.post(webhook_url, data=body, content_type="application/json")
        self.assertEqual(resp_missing.status_code, 403)

        # 2. Invalid signature header
        resp_invalid = self.client.post(
            webhook_url,
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256="sha256=invalidhash",
        )
        self.assertEqual(resp_invalid.status_code, 403)

        # 3. Missing WHATSAPP_APP_SECRET in settings
        with override_settings(WHATSAPP_APP_SECRET=""):
            resp_no_secret = self.client.post(
                webhook_url,
                data=body,
                content_type="application/json",
                HTTP_X_HUB_SIGNATURE_256="sha256=anything",
            )
            self.assertEqual(resp_no_secret.status_code, 403)

    @override_settings(WHATSAPP_APP_SECRET="test-secret-key")
    def test_11_webhook_delivered_and_read_events(self):
        """Webhook correctly transitions SUBMITTED records to DELIVERED on 'delivered' and 'read'."""
        notif = Notification.objects.create(
            lender=self.lender,
            borrower=self.borrower,
            loan=self.loan,
            notification_type=Notification.LOAN_CREATED,
            recipient_number="9876543210",
            status=Notification.SUBMITTED,
            provider_message_id="wamid.deliv_and_read",
            event_key="deliv-read-key",
            sent_at=timezone.now(),
        )

        secret = b"test-secret-key"
        timestamp_str = "1762512000"

        # 1. 'delivered' event
        payload_deliv = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "statuses": [
                                    {
                                        "id": "wamid.deliv_and_read",
                                        "status": "delivered",
                                        "timestamp": timestamp_str,
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        body_deliv = json.dumps(payload_deliv).encode("utf-8")
        sig_deliv = "sha256=" + hmac.new(secret, body_deliv, hashlib.sha256).hexdigest()

        resp_deliv = self.client.post(
            reverse("notifications:whatsapp_webhook"),
            data=body_deliv,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=sig_deliv,
        )
        self.assertEqual(resp_deliv.status_code, 200)

        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.DELIVERED)

        # 2. 'read' event confirms DELIVERED
        payload_read = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "statuses": [
                                    {
                                        "id": "wamid.deliv_and_read",
                                        "status": "read",
                                        "timestamp": timestamp_str,
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        body_read = json.dumps(payload_read).encode("utf-8")
        sig_read = "sha256=" + hmac.new(secret, body_read, hashlib.sha256).hexdigest()

        resp_read = self.client.post(
            reverse("notifications:whatsapp_webhook"),
            data=body_read,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=sig_read,
        )
        self.assertEqual(resp_read.status_code, 200)

        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.DELIVERED)

    def test_12_notification_history_preserved_and_accessible(self):
        """Historical SMS and active WhatsApp notifications are preserved and queryable."""
        sms_notif = Notification.objects.create(
            lender=self.lender,
            borrower=self.borrower,
            loan=self.loan,
            channel=Notification.CHANNEL_SMS,
            notification_type=Notification.LOAN_CREATED,
            recipient_number="9876543210",
            status="sent",
            event_key="hist-hist-sms",
        )
        wa_notif = Notification.objects.create(
            lender=self.lender,
            borrower=self.borrower,
            loan=self.loan,
            channel=Notification.CHANNEL_WHATSAPP,
            notification_type=Notification.PAYMENT_RECEIVED,
            recipient_number="9876543210",
            status=Notification.SUBMITTED,
            event_key="hist-hist-wa",
        )

        all_for_lender = Notification.objects.filter(lender=self.lender)
        self.assertIn(sms_notif, all_for_lender)
        self.assertIn(wa_notif, all_for_lender)
        self.assertEqual(all_for_lender.filter(channel="sms").count(), 1)
        self.assertGreaterEqual(all_for_lender.filter(channel="whatsapp").count(), 1)


# ===========================================================================
# Production Readiness Tests
# ===========================================================================


class ProductionReadinessTests(LendMateWhatsAppTestMixin, TestCase):
    """
    New tests covering production readiness corrections:
    1. enqueue_overdue_reminder uses on_commit dispatch (not direct call).
    2. Recovery of PENDING notifications with attempts > 0 (un-dispatched after a failure).
    3. next_retry_at in the future is respected — notification is NOT recovered.
    4. Historical SMS notifications are excluded from WhatsApp recovery.
    5. Uncertain Meta API outcome sets status=SUBMITTED, NOT reset to PENDING.
    6. WhatsAppResult.is_uncertain field exists and defaults to False.
    7. Historical SMS records show 'Sent via SMS (historical)' in history template.
    8. Dispatch inside a rolled-back transaction does NOT send the notification.
    9. Recovery dispatch occurs outside atomic block (after commit).
    """

    # ------------------------------------------------------------------
    # 1. enqueue_overdue_reminder uses on_commit
    # ------------------------------------------------------------------
    def test_overdue_reminder_uses_on_commit_dispatch(self):
        """
        enqueue_overdue_reminder must dispatch the Celery task via
        transaction.on_commit — not inside the atomic block.
        When the outer transaction is rolled back, no task is dispatched.
        """
        from unittest.mock import patch as _patch

        dispatched = []

        # Patch _schedule_task at the service level to record calls
        with _patch("notifications.service._schedule_task", side_effect=lambda pk: dispatched.append(pk)) as mock_schedule:
            # Simulate a rolled-back transaction
            try:
                from django.db import transaction as _tx
                with _tx.atomic():
                    _record, created = enqueue_overdue_reminder(
                        loan=self.loan,
                        due_date=datetime.date(2026, 11, 1),
                        monthly_amount=Decimal("2000"),
                        period_key="overdue-2026-11",
                    )
                    # Roll back the transaction
                    raise ValueError("Intentional rollback")
            except ValueError:
                pass

        # on_commit callbacks are NOT called when transaction rolls back
        self.assertEqual(dispatched, [], "Dispatch must NOT occur when outer transaction rolls back")

    # ------------------------------------------------------------------
    # 2. Recovery of PENDING with attempts > 0
    # ------------------------------------------------------------------
    @patch("notifications.tasks.send_whatsapp_notification.delay")
    def test_recovery_pending_with_attempts_gt_zero(self, mock_delay):
        """
        PENDING notifications with attempts > 0 (failed once, Redis went down
        before retry countdown was scheduled) should be recovered.
        """
        notif = Notification.objects.create(
            lender=self.lender,
            borrower=self.borrower,
            loan=self.loan,
            notification_type=Notification.LOAN_CREATED,
            recipient_number="9876543210",
            status=Notification.PENDING,
            attempts=2,                # Has had 2 attempts
            next_retry_at=None,        # No scheduled retry (Redis was down)
            event_key="pend-attempts-gt-zero",
            channel=Notification.CHANNEL_WHATSAPP,
        )
        past_time = timezone.now() - datetime.timedelta(minutes=10)
        Notification.objects.filter(pk=notif.pk).update(
            created_at=past_time, updated_at=past_time,
        )

        recovered = recover_stuck_notifications()
        self.assertGreaterEqual(recovered, 1)
        mock_delay.assert_called_with(notif.pk)

    # ------------------------------------------------------------------
    # 3. next_retry_at in the future must NOT be recovered
    # ------------------------------------------------------------------
    @patch("notifications.tasks.send_whatsapp_notification.delay")
    def test_recovery_respects_future_next_retry_at(self, mock_delay):
        """
        PENDING notifications whose next_retry_at is in the future must NOT
        be dispatched by the recovery task.
        """
        future_time = timezone.now() + datetime.timedelta(minutes=30)
        notif = Notification.objects.create(
            lender=self.lender,
            borrower=self.borrower,
            loan=self.loan,
            notification_type=Notification.LOAN_CREATED,
            recipient_number="9876543210",
            status=Notification.PENDING,
            attempts=1,
            next_retry_at=future_time,
            event_key="pend-future-retry",
            channel=Notification.CHANNEL_WHATSAPP,
        )

        recover_stuck_notifications()
        # Delay must NOT have been called for this specific notification
        for call_args in mock_delay.call_args_list:
            self.assertNotEqual(call_args[0][0], notif.pk,
                                "Future next_retry_at must prevent recovery dispatch")

    # ------------------------------------------------------------------
    # 4. SMS channel excluded from WhatsApp recovery
    # ------------------------------------------------------------------
    @patch("notifications.tasks.send_whatsapp_notification.delay")
    def test_recovery_excludes_sms_channel(self, mock_delay):
        """
        PENDING notifications with channel='sms' (historical records) must
        NEVER be dispatched via WhatsApp by the recovery task.
        """
        notif_sms = Notification.objects.create(
            lender=self.lender,
            borrower=self.borrower,
            loan=self.loan,
            notification_type=Notification.LOAN_CREATED,
            recipient_number="9876543210",
            status=Notification.PENDING,
            attempts=0,
            next_retry_at=None,
            event_key="sms-excluded-recovery",
            channel=Notification.CHANNEL_SMS,
        )
        past_time = timezone.now() - datetime.timedelta(minutes=10)
        Notification.objects.filter(pk=notif_sms.pk).update(
            created_at=past_time, updated_at=past_time,
        )

        recover_stuck_notifications()
        for call_args in mock_delay.call_args_list:
            self.assertNotEqual(call_args[0][0], notif_sms.pk,
                                "SMS historical notifications must NOT be dispatched via WhatsApp")

    # ------------------------------------------------------------------
    # 5. Uncertain outcome → SUBMITTED, never reset to PENDING
    # ------------------------------------------------------------------
    @patch("notifications.tasks.send_whatsapp_template")
    def test_uncertain_outcome_marked_submitted_not_pending(self, mock_send):
        """
        When the WhatsApp API result has is_uncertain=True, the notification
        must be marked SUBMITTED (not reset to PENDING for automatic retry),
        because retrying risks sending the message twice.
        """
        mock_send.return_value = WhatsAppResult(
            status=WhatsAppStatus.FAILED,
            provider="meta_cloud",
            error="ReadTimeout — response not received",
            is_uncertain=True,
        )
        notif = Notification.objects.create(
            lender=self.lender,
            borrower=self.borrower,
            loan=self.loan,
            notification_type=Notification.LOAN_CREATED,
            recipient_number="9876543210",
            status=Notification.PENDING,
            event_key="uncertain-outcome-test",
            channel=Notification.CHANNEL_WHATSAPP,
        )

        send_whatsapp_notification(notif.pk)
        notif.refresh_from_db()

        self.assertEqual(notif.status, Notification.SUBMITTED,
                         "Uncertain outcome must be marked SUBMITTED, not PENDING")
        self.assertIsNone(notif.next_retry_at,
                          "No automatic retry should be scheduled for uncertain outcomes")
        self.assertIn("UNCERTAIN", notif.last_error,
                      "last_error must note the uncertain outcome")

    # ------------------------------------------------------------------
    # 6. WhatsAppResult.is_uncertain field
    # ------------------------------------------------------------------
    def test_whatsapp_result_is_uncertain_field_defaults_false(self):
        """WhatsAppResult.is_uncertain defaults to False for all existing code paths."""
        result_default = WhatsAppResult(
            status=WhatsAppStatus.SUBMITTED,
            provider="meta_cloud",
        )
        self.assertFalse(result_default.is_uncertain)

        result_uncertain = WhatsAppResult(
            status=WhatsAppStatus.FAILED,
            provider="meta_cloud",
            is_uncertain=True,
        )
        self.assertTrue(result_uncertain.is_uncertain)

    # ------------------------------------------------------------------
    # 7. Historical SMS status display in history template
    # ------------------------------------------------------------------
    def test_sms_historical_status_display_in_history_template(self):
        """
        SMS historical notifications with status='submitted' render as
        'Sent via SMS (historical)' in the notification history template,
        not as 'Submitted to WhatsApp'.
        """
        self.client.force_login(self.lender)
        sms_notif = Notification.objects.create(
            lender=self.lender,
            borrower=self.borrower,
            loan=self.loan,
            channel=Notification.CHANNEL_SMS,
            notification_type=Notification.LOAN_CREATED,
            recipient_number="9876543210",
            status="submitted",
            event_key="sms-display-test",
        )

        response = self.client.get(reverse("notifications:history"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # Must show SMS historical label
        self.assertIn("Sent via SMS (historical)", content)
        # Must NOT show the WhatsApp-specific label for this SMS record
        self.assertNotIn("Submitted to WhatsApp", content.split("Sent via SMS (historical)")[0]
                         if "Sent via SMS (historical)" in content else content)

    # ------------------------------------------------------------------
    # 8. Dispatch failure (Celery/Redis down) leaves notification PENDING
    # ------------------------------------------------------------------
    @patch("notifications.tasks.send_whatsapp_notification.delay",
           side_effect=Exception("Connection refused"))
    def test_celery_dispatch_failure_leaves_notification_pending(self, mock_delay):
        """
        If Celery/Redis is unavailable during enqueue, the notification
        record must remain in PENDING status (not raise an unhandled exception).
        The recovery task will pick it up later.
        """
        # enqueue_loan_created calls _schedule_task via on_commit — test that
        # service gracefully handles broker failure
        from notifications.service import _schedule_task

        notif = Notification.objects.create(
            lender=self.lender,
            borrower=self.borrower,
            loan=self.loan,
            notification_type=Notification.LOAN_CREATED,
            recipient_number="9876543210",
            status=Notification.PENDING,
            event_key="dispatch-failure-test",
            channel=Notification.CHANNEL_WHATSAPP,
        )

        # _schedule_task should not raise even when broker is unavailable
        try:
            _schedule_task(notif.pk)
        except Exception:
            self.fail("_schedule_task must not propagate broker exceptions")

        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.PENDING,
                         "Notification must remain PENDING when dispatch fails")

    # ------------------------------------------------------------------
    # 9. Recovery dispatches AFTER transaction commit, not inside atomic
    # ------------------------------------------------------------------
    @patch("notifications.tasks.send_whatsapp_notification.delay")
    def test_recovery_dispatch_occurs_after_transaction_commit(self, mock_delay):
        """
        In recover_stuck_notifications, dispatch must happen AFTER each
        atomic block completes (after DB commit), so the worker always sees
        the updated status when it queries for PENDING.
        """
        notif = Notification.objects.create(
            lender=self.lender,
            borrower=self.borrower,
            loan=self.loan,
            notification_type=Notification.LOAN_CREATED,
            recipient_number="9876543210",
            status=Notification.PROCESSING,
            attempts=1,
            event_key="recovery-after-commit-test",
            channel=Notification.CHANNEL_WHATSAPP,
        )
        # Set updated_at well past the stuck threshold
        old_time = timezone.now() - datetime.timedelta(minutes=20)
        Notification.objects.filter(pk=notif.pk).update(updated_at=old_time)

        recover_stuck_notifications()

        notif.refresh_from_db()
        # Status must have been reset to PENDING (by the atomic block)
        self.assertEqual(notif.status, Notification.PENDING)
        # Delay was called (dispatch happened after commit)
        mock_delay.assert_called_with(notif.pk)

    # ------------------------------------------------------------------
    # 10. Uncertain outcome processed BEFORE max-attempt check
    # ------------------------------------------------------------------
    @patch("notifications.tasks.send_whatsapp_template")
    def test_uncertain_outcome_processed_before_max_attempts(self, mock_send):
        """
        Even when notification.attempts has reached MAX_ATTEMPTS (5),
        an uncertain transmission outcome must be preserved as SUBMITTED
        with [UNCERTAIN] marker — NOT marked FAILED.
        """
        mock_send.return_value = WhatsAppResult(
            status=WhatsAppStatus.FAILED,
            provider="meta_cloud",
            error="ReadTimeout on 5th attempt",
            is_uncertain=True,
        )
        notif = Notification.objects.create(
            lender=self.lender,
            borrower=self.borrower,
            loan=self.loan,
            notification_type=Notification.LOAN_CREATED,
            recipient_number="9876543210",
            status=Notification.PENDING,
            attempts=4,  # Next attempt will make it 5 (>= MAX_ATTEMPTS)
            event_key="uncertain-at-max-attempts",
            channel=Notification.CHANNEL_WHATSAPP,
        )

        send_whatsapp_notification(notif.pk)
        notif.refresh_from_db()

        self.assertEqual(notif.status, Notification.SUBMITTED,
                         "Uncertain outcome must be SUBMITTED even on final attempt")
        self.assertIn("UNCERTAIN", notif.last_error)
        self.assertIsNone(notif.next_retry_at)

    # ------------------------------------------------------------------
    # 11. Ambiguous connection failure classified as uncertain
    # ------------------------------------------------------------------
    def test_ambiguous_connection_failure_classified_as_uncertain(self):
        """
        A connection failure where bytes may have been transmitted (e.g. RemoteDisconnected
        or Connection reset) must be classified as is_uncertain=True.
        """
        import requests
        from notifications.whatsapp import _is_confirmed_pre_transmission_error

        # Ambiguous errors
        err_reset = requests.exceptions.ConnectionError("Connection reset by peer")
        self.assertFalse(_is_confirmed_pre_transmission_error(err_reset))

        err_remote_disc = requests.exceptions.ConnectionError("RemoteDisconnected: Remote end closed connection without response")
        self.assertFalse(_is_confirmed_pre_transmission_error(err_remote_disc))

        err_generic_drop = requests.exceptions.ConnectionError("Connection aborted")
        self.assertFalse(_is_confirmed_pre_transmission_error(err_generic_drop))

    # ------------------------------------------------------------------
    # 12. Confirmed pre-transmission connection error safe to retry
    # ------------------------------------------------------------------
    def test_confirmed_pre_transmission_connection_error_safe_to_retry(self):
        """
        A connection failure confirmed to have occurred before payload transmission
        (e.g. DNS failure, Connection Refused, ConnectTimeout, SSLError) is safe to retry.
        """
        import requests
        from notifications.whatsapp import _is_confirmed_pre_transmission_error

        err_dns = requests.exceptions.ConnectionError("Failed to resolve 'graph.facebook.com' (NameResolutionError)")
        self.assertTrue(_is_confirmed_pre_transmission_error(err_dns))

        err_refused = requests.exceptions.ConnectionError("NewConnectionError: [Errno 111] Connection refused")
        self.assertTrue(_is_confirmed_pre_transmission_error(err_refused))

        err_ssl = requests.exceptions.SSLError("SSL: CERTIFICATE_VERIFY_FAILED")
        self.assertTrue(_is_confirmed_pre_transmission_error(err_ssl))

        err_timeout = requests.exceptions.ConnectTimeout("TCP handshake timed out")
        self.assertTrue(_is_confirmed_pre_transmission_error(err_timeout))

    # ------------------------------------------------------------------
    # 13. State saved before async retry task scheduling
    # ------------------------------------------------------------------
    @patch("notifications.tasks.send_whatsapp_template")
    def test_state_saved_before_retry_task_scheduling(self, mock_send):
        """
        When a transient failure occurs, the notification record must have its
        updated status (PENDING) and next_retry_at saved in the database BEFORE
        apply_async is called to schedule the next attempt.
        """
        mock_send.return_value = WhatsAppResult(
            status=WhatsAppStatus.FAILED,
            provider="meta_cloud",
            error="Connection refused (pre-transmission)",
            is_uncertain=False,
        )
        notif = Notification.objects.create(
            lender=self.lender,
            borrower=self.borrower,
            loan=self.loan,
            notification_type=Notification.LOAN_CREATED,
            recipient_number="9876543210",
            status=Notification.PENDING,
            attempts=0,
            event_key="state-saved-before-retry",
            channel=Notification.CHANNEL_WHATSAPP,
        )

        db_state_at_scheduling = {}

        def capture_db_state(*args, **kwargs):
            # Check DB state at the exact moment apply_async is invoked
            reloaded = Notification.objects.get(pk=notif.pk)
            db_state_at_scheduling["status"] = reloaded.status
            db_state_at_scheduling["attempts"] = reloaded.attempts
            db_state_at_scheduling["next_retry_at"] = reloaded.next_retry_at

        with patch("notifications.tasks.send_whatsapp_notification.apply_async", side_effect=capture_db_state):
            send_whatsapp_notification(notif.pk)

        # Verify that by the time apply_async ran, status was already saved as PENDING
        # and next_retry_at was already saved in DB
        self.assertEqual(db_state_at_scheduling.get("status"), Notification.PENDING)
        self.assertEqual(db_state_at_scheduling.get("attempts"), 1)
        self.assertIsNotNone(db_state_at_scheduling.get("next_retry_at"))

    # ------------------------------------------------------------------
    # 14. Crash recovery BEFORE transmission begins recovers to PENDING
    # ------------------------------------------------------------------
    @patch("notifications.tasks.send_whatsapp_notification.delay")
    def test_crash_recovery_before_transmission_begins_recovers_to_pending(self, mock_delay):
        """
        If a worker crashes before external transmission starts
        (transmission_started_at is None), recover_stuck_notifications resets
        the notification to PENDING and safely re-dispatches it.
        """
        notif = Notification.objects.create(
            lender=self.lender,
            borrower=self.borrower,
            loan=self.loan,
            notification_type=Notification.LOAN_CREATED,
            recipient_number="9876543210",
            status=Notification.PROCESSING,
            attempts=1,
            transmission_started_at=None,
            event_key="crash-recovery-before-transmission",
            channel=Notification.CHANNEL_WHATSAPP,
        )
        old_time = timezone.now() - datetime.timedelta(minutes=20)
        Notification.objects.filter(pk=notif.pk).update(updated_at=old_time)

        recover_stuck_notifications()

        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.PENDING)
        self.assertIn("crashed before external transmission", notif.last_error)
        mock_delay.assert_called_with(notif.pk)

    # ------------------------------------------------------------------
    # 15. Crash recovery AFTER transmission begins marks UNCERTAIN & never resends
    # ------------------------------------------------------------------
    @patch("notifications.tasks.send_whatsapp_notification.delay")
    def test_crash_recovery_after_transmission_begins_marks_uncertain_and_never_resends(self, mock_delay):
        """
        If a worker crashes after external transmission begins
        (transmission_started_at is NOT None), recover_stuck_notifications marks
        the outcome as SUBMITTED with [UNCERTAIN] and NEVER automatically resends.
        """
        started_time = timezone.now() - datetime.timedelta(minutes=25)
        notif = Notification.objects.create(
            lender=self.lender,
            borrower=self.borrower,
            loan=self.loan,
            notification_type=Notification.LOAN_CREATED,
            recipient_number="9876543210",
            status=Notification.PROCESSING,
            attempts=1,
            transmission_started_at=started_time,
            event_key="crash-recovery-after-transmission",
            channel=Notification.CHANNEL_WHATSAPP,
        )
        old_time = timezone.now() - datetime.timedelta(minutes=20)
        Notification.objects.filter(pk=notif.pk).update(updated_at=old_time)

        recover_stuck_notifications()

        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.SUBMITTED)
        self.assertIsNone(notif.next_retry_at)
        self.assertTrue(notif.last_error.startswith("[UNCERTAIN]"))
        mock_delay.assert_not_called()

    # ------------------------------------------------------------------
    # 16. Uncertain crash recovery resolved by Meta webhook delivery event
    # ------------------------------------------------------------------
    def test_uncertain_crash_recovery_resolved_by_webhook_event(self):
        """
        When a notification was marked UNCERTAIN due to a worker crash after transmission,
        a subsequent Meta WhatsApp webhook delivery report resolves it to DELIVERED.
        """
        notif = Notification.objects.create(
            lender=self.lender,
            borrower=self.borrower,
            loan=self.loan,
            notification_type=Notification.LOAN_CREATED,
            recipient_number="9876543210",
            status=Notification.SUBMITTED,
            provider_message_id="wamid.crash_resolved_by_webhook",
            last_error="[UNCERTAIN] Worker crashed after external transmission started",
            event_key="crash-resolved-webhook",
            channel=Notification.CHANNEL_WHATSAPP,
        )

        from notifications.views import _handle_status_update
        _handle_status_update("wamid.crash_resolved_by_webhook", "delivered", {})

        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.DELIVERED)
        self.assertEqual(notif.last_error, "")

    # ------------------------------------------------------------------
    # 17. Worker task passes on_before_send callback and biz_opaque_callback_data
    # ------------------------------------------------------------------
    @patch("notifications.tasks.send_whatsapp_template")
    def test_worker_task_persists_transmission_started_timestamp_before_send(self, mock_send):
        """
        send_whatsapp_notification must pass an on_before_send callback and
        biz_opaque_callback_data to send_whatsapp_template.

        The on_before_send callback, when invoked (by a live backend), persists
        transmission_started_at before the network request is made.

        Design note: MockWhatsAppBackend NEVER calls on_before_send, so
        transmission_started_at remains None for mocked sends. This test verifies
        the callback mechanism by calling on_before_send directly from within the
        mock, then confirming the DB state.
        """
        db_transmission_started_at = []
        biz_callback_data_seen = []

        def capture_callback(*args, **kwargs):
            # Simulate what MetaWhatsAppCloudBackend does: call on_before_send
            on_before = kwargs.get("on_before_send")
            biz_callback_data_seen.append(kwargs.get("biz_opaque_callback_data", ""))
            if callable(on_before):
                on_before()  # This should persist transmission_started_at
                reloaded = Notification.objects.get(pk=notif.pk)
                db_transmission_started_at.append(reloaded.transmission_started_at)
            return WhatsAppResult(
                status=WhatsAppStatus.SUBMITTED,
                provider="meta_cloud",
                provider_message_id="wamid.test_timestamp_persisted",
            )

        mock_send.side_effect = capture_callback

        notif = Notification.objects.create(
            lender=self.lender,
            borrower=self.borrower,
            loan=self.loan,
            notification_type=Notification.LOAN_CREATED,
            recipient_number="9876543210",
            status=Notification.PENDING,
            attempts=0,
            event_key="timestamp-persisted-test",
            channel=Notification.CHANNEL_WHATSAPP,
        )

        send_whatsapp_notification(notif.pk)

        # on_before_send was called once and transmission_started_at was persisted
        self.assertEqual(len(db_transmission_started_at), 1)
        self.assertIsNotNone(db_transmission_started_at[0])
        # biz_opaque_callback_data must reference the notification pk
        self.assertEqual(len(biz_callback_data_seen), 1)
        self.assertIn(str(notif.pk), biz_callback_data_seen[0])


# ===========================================================================
# Webhook Correlation Regression Tests
# ===========================================================================

class WebhookCorrelationTests(LendMateWhatsAppTestMixin, TestCase):
    """
    Regression tests for the webhook correlation and status state-machine fixes.

    Covers:
    - biz_opaque_callback_data correlation when provider_message_id not yet persisted
    - UnmatchedWebhookEvent storage and replay
    - Safe status state machine (no downgrades on DELIVERED or FAILED)
    - Duplicate webhook idempotency
    - MockWhatsAppBackend does NOT set transmission_started_at
    - on_before_send hook mechanism for live backends
    - Recovery path correctness

    No real network calls are made. No real WhatsApp messages are sent.
    """

    def setUp(self):
        super().setUp()

    def _make_notif(self, **kwargs):
        defaults = dict(
            lender=self.lender,
            borrower=self.borrower,
            loan=self.loan,
            notification_type=Notification.LOAN_CREATED,
            recipient_number="9876543210",
            channel=Notification.CHANNEL_WHATSAPP,
        )
        defaults.update(kwargs)
        return Notification.objects.create(**defaults)

    # ------------------------------------------------------------------
    # WC-1. Webhook arrives before provider_message_id is persisted
    # ------------------------------------------------------------------
    def test_webhook_arrives_before_provider_id_persistence(self):
        """
        When a webhook arrives before the worker saves provider_message_id,
        biz_opaque_callback_data='notif_<pk>' must correlate the notification,
        fill in provider_message_id, and apply the status transition.
        """
        notif = self._make_notif(
            status=Notification.SUBMITTED,
            provider_message_id="",
            event_key="wh-before-persist",
        )
        wamid = "wamid.early_webhook_wc1"

        _handle_status_update(
            wamid,
            "delivered",
            {"biz_opaque_callback_data": f"notif_{notif.pk}"},
        )

        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.DELIVERED)
        self.assertEqual(notif.provider_message_id, wamid)

    # ------------------------------------------------------------------
    # WC-2. Unknown webhook stored as UnmatchedWebhookEvent (not discarded)
    # ------------------------------------------------------------------
    def test_webhook_stored_as_unmatched_when_no_correlation_possible(self):
        """
        A webhook with an unknown wamid and no callback_data must be stored
        in UnmatchedWebhookEvent (not silently discarded).
        """
        from .models import UnmatchedWebhookEvent
        unknown_wamid = "wamid.completely_unknown_wc2"
        _handle_status_update(unknown_wamid, "delivered", {})

        self.assertTrue(
            UnmatchedWebhookEvent.objects.filter(
                provider_message_id=unknown_wamid,
                resolved=False,
            ).exists()
        )

    # ------------------------------------------------------------------
    # WC-3. Unmatched webhook replayed when notification is linked
    # ------------------------------------------------------------------
    def test_unmatched_webhook_replayed_when_notification_linked(self):
        """
        An unmatched webhook event stored with a provider_message_id is replayed
        and resolves to the correct status when replay is triggered.
        """
        from .models import UnmatchedWebhookEvent
        from .views import replay_unmatched_webhooks_for_notification
        wamid = "wamid.replay_wc3"
        UnmatchedWebhookEvent.objects.create(
            provider_message_id=wamid,
            status="delivered",
            callback_data="",
            payload={"id": wamid, "status": "delivered"},
            resolved=False,
        )

        notif = self._make_notif(
            status=Notification.SUBMITTED,
            provider_message_id=wamid,
            event_key="replay-wc3",
        )

        result = replay_unmatched_webhooks_for_notification(notif)

        self.assertTrue(result)
        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.DELIVERED)
        event = UnmatchedWebhookEvent.objects.get(provider_message_id=wamid)
        self.assertTrue(event.resolved)

    # ------------------------------------------------------------------
    # WC-4. Duplicate webhook delivery is a safe no-op (idempotent)
    # ------------------------------------------------------------------
    def test_duplicate_webhook_delivery_is_safe_noop(self):
        """
        A second 'delivered' webhook for an already-DELIVERED notification
        must be ignored (idempotent — no DB error, status unchanged).
        """
        wamid = "wamid.duplicate_delivered_wc4"
        notif = self._make_notif(
            status=Notification.DELIVERED,
            provider_message_id=wamid,
            event_key="duplicate-delivered-wc4",
        )

        _handle_status_update(wamid, "delivered", {})

        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.DELIVERED)

    # ------------------------------------------------------------------
    # WC-5. FAILED + late 'sent' must NOT downgrade to SUBMITTED
    # ------------------------------------------------------------------
    def test_failed_followed_by_sent_does_not_downgrade(self):
        """
        A late 'sent' webhook event must NOT downgrade a FAILED notification
        back to SUBMITTED.
        """
        wamid = "wamid.failed_then_sent_wc5"
        notif = self._make_notif(
            status=Notification.FAILED,
            provider_message_id=wamid,
            last_error="Delivery failed",
            event_key="failed-then-sent-wc5",
        )

        _handle_status_update(wamid, "sent", {})

        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.FAILED)

    # ------------------------------------------------------------------
    # WC-6. DELIVERED + late 'failed' must NOT downgrade
    # ------------------------------------------------------------------
    def test_delivered_followed_by_failed_does_not_downgrade(self):
        """
        A late 'failed' webhook event must NOT downgrade a DELIVERED notification.
        """
        wamid = "wamid.delivered_then_failed_wc6"
        notif = self._make_notif(
            status=Notification.DELIVERED,
            provider_message_id=wamid,
            event_key="delivered-then-failed-wc6",
        )

        _handle_status_update(
            wamid,
            "failed",
            {"errors": [{"code": 131026, "title": "Message undeliverable"}]},
        )

        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.DELIVERED)

    # ------------------------------------------------------------------
    # WC-7. DELIVERED + late 'sent' must NOT downgrade
    # ------------------------------------------------------------------
    def test_delivered_followed_by_sent_does_not_downgrade(self):
        """
        A late 'sent' webhook event must NOT downgrade a DELIVERED notification.
        """
        wamid = "wamid.delivered_then_sent_wc7"
        notif = self._make_notif(
            status=Notification.DELIVERED,
            provider_message_id=wamid,
            event_key="delivered-then-sent-wc7",
        )

        _handle_status_update(wamid, "sent", {})

        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.DELIVERED)

    # ------------------------------------------------------------------
    # WC-8. Out-of-order: 'sent' then 'delivered' applies correctly
    # ------------------------------------------------------------------
    def test_out_of_order_sent_before_delivered_is_safe(self):
        """
        Out-of-order webhooks: a 'sent' event followed by 'delivered'
        must result in final status DELIVERED.
        """
        wamid = "wamid.out_of_order_wc8"
        notif = self._make_notif(
            status=Notification.SUBMITTED,
            provider_message_id=wamid,
            event_key="out-of-order-wc8",
        )

        _handle_status_update(wamid, "sent", {})
        notif.refresh_from_db()
        # 'sent' on SUBMITTED is a no-op (already SUBMITTED — Rule 5)
        self.assertEqual(notif.status, Notification.SUBMITTED)

        _handle_status_update(wamid, "delivered", {})
        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.DELIVERED)

    # ------------------------------------------------------------------
    # WC-9. MockWhatsAppBackend crash recovery: transmission_started_at stays None
    # ------------------------------------------------------------------
    @patch("notifications.tasks.send_whatsapp_notification.delay")
    def test_mock_backend_crash_recovery_leaves_transmission_started_at_none(self, mock_delay):
        """
        A PROCESSING notification with transmission_started_at=None simulates a
        mock-backend crash (before any external transmission). Recovery must reset
        it to PENDING so it can be safely retried — NOT marked UNCERTAIN.
        """
        notif = self._make_notif(
            status=Notification.PROCESSING,
            attempts=1,
            transmission_started_at=None,
            event_key="mock-crash-recovery-wc9",
        )
        old_time = timezone.now() - datetime.timedelta(minutes=20)
        Notification.objects.filter(pk=notif.pk).update(updated_at=old_time)

        recover_stuck_notifications()

        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.PENDING)
        # Must have been queued for retry
        mock_delay.assert_called_with(notif.pk)

    # ------------------------------------------------------------------
    # WC-10. on_before_send hook persists transmission_started_at
    # ------------------------------------------------------------------
    @patch("notifications.tasks.send_whatsapp_template")
    def test_live_backend_on_before_send_sets_transmission_timestamp(self, mock_send):
        """
        When send_whatsapp_notification is called and the simulated live backend
        invokes on_before_send, transmission_started_at must be persisted in the
        database before the network response is processed.

        MockWhatsAppBackend NEVER calls on_before_send. This test explicitly
        invokes the callback (as MetaWhatsAppCloudBackend would) to verify the
        mechanism works end-to-end through the task layer.
        """
        db_state_at_send = []

        def simulate_live_send(*args, **kwargs):
            on_before = kwargs.get("on_before_send")
            if callable(on_before):
                on_before()  # Simulate MetaWhatsAppCloudBackend calling the hook
                reloaded = Notification.objects.get(pk=notif.pk)
                db_state_at_send.append(reloaded.transmission_started_at)
            return WhatsAppResult(
                status=WhatsAppStatus.SUBMITTED,
                provider="meta_cloud",
                provider_message_id="wamid.on_before_send_wc10",
            )

        mock_send.side_effect = simulate_live_send

        notif = self._make_notif(
            status=Notification.PENDING,
            attempts=0,
            event_key="on-before-send-wc10",
        )

        send_whatsapp_notification(notif.pk)

        self.assertEqual(len(db_state_at_send), 1,
                         "on_before_send must have been called once")
        self.assertIsNotNone(db_state_at_send[0],
                              "transmission_started_at must be non-None after on_before_send")

    # ------------------------------------------------------------------
    # WC-11. biz_opaque_callback_data='notif_<pk>' passed to send_whatsapp_template
    # ------------------------------------------------------------------
    @patch("notifications.tasks.send_whatsapp_template")
    def test_biz_opaque_callback_data_references_notification_pk(self, mock_send):
        """
        send_whatsapp_notification must pass biz_opaque_callback_data='notif_<pk>'
        to send_whatsapp_template to enable webhook correlation.
        """
        callback_data_seen = []

        def capture(*args, **kwargs):
            callback_data_seen.append(kwargs.get("biz_opaque_callback_data", ""))
            return WhatsAppResult(
                status=WhatsAppStatus.MOCKED,
                provider="mock",
                provider_message_id="wamid.mock_callback_wc11",
            )

        mock_send.side_effect = capture

        notif = self._make_notif(
            status=Notification.PENDING,
            attempts=0,
            event_key="callback-data-wc11",
        )

        send_whatsapp_notification(notif.pk)

        self.assertEqual(len(callback_data_seen), 1)
        self.assertEqual(callback_data_seen[0], f"notif_{notif.pk}")

    # ------------------------------------------------------------------
    # WC-12. Webhook resolves uncertain (SUBMITTED+[UNCERTAIN]) notification
    # ------------------------------------------------------------------
    def test_webhook_resolves_uncertain_notification(self):
        """
        A SUBMITTED notification with [UNCERTAIN] in last_error (crash after
        transmission) must be resolved to DELIVERED when a 'delivered' webhook
        arrives, and last_error must be cleared.
        """
        wamid = "wamid.uncertain_resolved_wc12"
        notif = self._make_notif(
            status=Notification.SUBMITTED,
            provider_message_id=wamid,
            last_error="[UNCERTAIN] Worker crashed after external transmission started",
            event_key="uncertain-resolved-wc12",
        )

        _handle_status_update(wamid, "delivered", {})

        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.DELIVERED)
        self.assertEqual(notif.last_error, "")

    # ------------------------------------------------------------------
    # WC-13. Duplicate unmatched webhook events are idempotent
    # ------------------------------------------------------------------
    def test_duplicate_unmatched_webhook_events_are_idempotent(self):
        """
        Receiving the same unmatched webhook twice must result in exactly one
        UnmatchedWebhookEvent record (update_or_create idempotency).
        """
        from .models import UnmatchedWebhookEvent
        unknown_wamid = "wamid.duplicate_unmatched_wc13"

        _handle_status_update(unknown_wamid, "sent", {})
        _handle_status_update(unknown_wamid, "sent", {})

        count = UnmatchedWebhookEvent.objects.filter(
            provider_message_id=unknown_wamid
        ).count()
        self.assertEqual(count, 1)
