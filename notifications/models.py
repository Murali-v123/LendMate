"""
Notification models.

Notification  – the durable queue record for every outbound notification across channels.
Each record survives restarts, prevents duplicate sends, and drives retry logic in Celery.
"""
import hashlib
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Notification(models.Model):
    # --- Channel choices ---
    CHANNEL_WHATSAPP = "whatsapp"
    CHANNEL_SMS = "sms"

    CHANNEL_CHOICES = [
        (CHANNEL_WHATSAPP, "WhatsApp"),
        (CHANNEL_SMS, "SMS"),
    ]

    # --- Type choices ---
    LOAN_CREATED = "loan_created"
    PAYMENT_RECEIVED = "payment_received"
    MONTHLY_REMINDER = "monthly_reminder"
    OVERDUE_REMINDER = "overdue_reminder"
    LOAN_CLOSED = "loan_closed"

    NOTIFICATION_TYPE_CHOICES = [
        (LOAN_CREATED, "Loan Created"),
        (PAYMENT_RECEIVED, "Payment Received"),
        (MONTHLY_REMINDER, "Monthly Payment Reminder"),
        (OVERDUE_REMINDER, "Overdue Payment Reminder"),
        (LOAN_CLOSED, "Loan Closed"),
    ]

    # --- Status choices ---
    PENDING = "pending"
    PROCESSING = "processing"
    MOCKED = "mocked"
    SUBMITTED = "submitted"
    DELIVERED = "delivered"
    FAILED = "failed"
    SUPPRESSED = "suppressed"

    # Backward compatibility alias
    SENT = "submitted"

    STATUS_CHOICES = [
        (PENDING, "Pending"),
        (PROCESSING, "Processing"),
        (MOCKED, "Mocked \u2013 Not Transmitted"),
        (SUBMITTED, "Submitted to WhatsApp"),
        (DELIVERED, "Delivered"),
        (FAILED, "Failed"),
        (SUPPRESSED, "Suppressed"),
    ]

    # --- Relationships ---
    borrower = models.ForeignKey(
        "lending.Borrower",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )
    loan = models.ForeignKey(
        "lending.Loan",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )
    payment = models.ForeignKey(
        "lending.Payment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )
    lender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )

    # --- Core fields ---
    channel = models.CharField(
        max_length=20,
        choices=CHANNEL_CHOICES,
        default=CHANNEL_WHATSAPP,
        db_index=True,
    )
    notification_type = models.CharField(
        max_length=30,
        choices=NOTIFICATION_TYPE_CHOICES,
    )
    recipient_number = models.CharField(max_length=20)
    message = models.TextField()

    # --- Status tracking ---
    status = models.CharField(
        max_length=15,
        choices=STATUS_CHOICES,
        default=PENDING,
        db_index=True,
    )
    provider_message_id = models.CharField(max_length=200, blank=True, db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True)

    # --- Idempotency ---
    # Prevents duplicate notifications for the same event.
    # Format: sha256(channel:notification_type:loan_id:payment_id:period_key)
    event_key = models.CharField(
        max_length=64,
        unique=True,
        help_text="SHA-256 hash used to deduplicate events.",
    )

    # --- Timestamps ---
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    transmission_started_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Timestamp when external transmission to provider began.",
    )
    processed_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp when mock or live processing finished.")
    sent_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp when real message was transmitted to provider network.")
    next_retry_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "next_retry_at"]),
            models.Index(fields=["lender", "status"]),
            models.Index(fields=["channel", "status"]),
        ]

    def __str__(self):
        borrower_name = self.borrower.full_name if self.borrower else "unknown"
        return f"[{self.get_channel_display()}] {self.get_notification_type_display()} \u2192 {borrower_name} [{self.status}]"

    @classmethod
    def make_event_key(cls, notification_type, loan_id=None, payment_id=None, period_key="", channel=CHANNEL_WHATSAPP):
        """
        Produce a stable SHA-256 event key to deduplicate notifications.

        period_key is e.g. "2026-11" for a November 2026 reminder,
        or "" for one-off events. payment_id is included for payment
        confirmations so each payment gets its own distinct key.
        """
        raw = f"{channel}:{notification_type}:{loan_id or ''}:{payment_id or ''}:{period_key}"
        return hashlib.sha256(raw.encode()).hexdigest()


# Backward-compatible alias for existing imports and migrations
SMSNotification = Notification


class UnmatchedWebhookEvent(models.Model):
    """
    Stores delivery status updates from Meta WhatsApp Cloud API that could not
    be matched to a Notification record at the time of arrival (e.g. if the webhook
    arrived before the worker finished saving provider_message_id, or if the worker
    crashed).

    These events are preserved and automatically replayed when the notification
    record is saved or recovered, ensuring no delivery receipt is discarded.
    """
    provider_message_id = models.CharField(max_length=200, db_index=True)
    status = models.CharField(max_length=20)
    callback_data = models.CharField(max_length=255, blank=True, db_index=True)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    resolved = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["provider_message_id", "resolved"]),
        ]

    def __str__(self):
        return f"UnmatchedWebhookEvent({self.provider_message_id}, status={self.status}, resolved={self.resolved})"
