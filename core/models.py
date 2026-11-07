
from django.conf import settings
from django.db import models


class UserPreferences(models.Model):

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="preferences"
    )

    # --- Existing reminder preferences ---
    payment_reminders = models.BooleanField(default=True)
    due_date_reminders = models.BooleanField(default=True)

    # --- WhatsApp notification preferences ---
    whatsapp_notifications_enabled = models.BooleanField(
        default=False,
        help_text="Master switch: enable WhatsApp notifications for this lender's borrowers."
    )
    whatsapp_loan_created = models.BooleanField(
        default=True,
        help_text="Send WhatsApp notification when a new loan is recorded."
    )
    whatsapp_payment_received = models.BooleanField(
        default=True,
        help_text="Send WhatsApp notification when a payment is recorded."
    )
    whatsapp_monthly_reminders = models.BooleanField(
        default=True,
        help_text="Send monthly payment reminder via WhatsApp."
    )
    whatsapp_overdue_reminders = models.BooleanField(
        default=True,
        help_text="Send overdue payment reminder via WhatsApp."
    )
    whatsapp_loan_closed = models.BooleanField(
        default=True,
        help_text="Send WhatsApp notification when a loan is closed."
    )

    # --- SMS notification preferences (deprecated / preserved for future multi-channel expansion) ---
    sms_notifications_enabled = models.BooleanField(
        default=False,
        help_text="Master switch: enable SMS notifications for this lender's borrowers (deprecated)."
    )
    sms_loan_created = models.BooleanField(
        default=True,
        help_text="Send SMS when a new loan is recorded (deprecated)."
    )
    sms_payment_received = models.BooleanField(
        default=True,
        help_text="Send SMS when a payment is recorded (deprecated)."
    )
    sms_monthly_reminders = models.BooleanField(
        default=True,
        help_text="Send monthly payment reminder SMS (deprecated)."
    )
    sms_overdue_reminders = models.BooleanField(
        default=True,
        help_text="Send overdue payment reminder SMS (deprecated)."
    )
    sms_loan_closed = models.BooleanField(
        default=True,
        help_text="Send SMS when a loan is closed (deprecated)."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Preferences - {self.user.username}"
