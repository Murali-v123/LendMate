from django import forms
from django.contrib.auth import get_user_model

from .models import UserPreferences


User = get_user_model()


class BootstrapFormMixin:
    """Applies LendMate's form styling classes to every field widget."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            widget = field.widget

            if isinstance(widget, forms.CheckboxInput):
                css_class = "form-check-input"
            elif isinstance(widget, forms.Select):
                css_class = "form-select"
            else:
                css_class = "form-control"

            existing = widget.attrs.get("class", "")
            widget.attrs["class"] = " ".join(
                part for part in (existing, css_class) if part
            )


class ProfileForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]
        labels = {
            "first_name": "First name",
            "last_name": "Last name",
            "email": "Email address",
        }

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        if email and User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("An account with this email address already exists.")
        return email


class UserPreferencesForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = UserPreferences
        fields = [
            "payment_reminders",
            "due_date_reminders",
            "whatsapp_notifications_enabled",
            "whatsapp_loan_created",
            "whatsapp_payment_received",
            "whatsapp_monthly_reminders",
            "whatsapp_overdue_reminders",
            "whatsapp_loan_closed",
        ]
        labels = {
            "payment_reminders": "Payment Reminders",
            "due_date_reminders": "Due-Date Reminders",
            "whatsapp_notifications_enabled": "Enable WhatsApp Notifications",
            "whatsapp_loan_created": "Loan Created Notification",
            "whatsapp_payment_received": "Payment Received Notification",
            "whatsapp_monthly_reminders": "Monthly Payment Reminder",
            "whatsapp_overdue_reminders": "Overdue Payment Reminder",
            "whatsapp_loan_closed": "Loan Closed Notification",
        }
        help_texts = {
            "whatsapp_notifications_enabled": "Master switch. WhatsApp messages will only be sent when this is enabled.",
            "whatsapp_loan_created": "Notify borrower when a new loan is recorded.",
            "whatsapp_payment_received": "Notify borrower when a payment is recorded.",
            "whatsapp_monthly_reminders": "Send monthly payment reminders via WhatsApp.",
            "whatsapp_overdue_reminders": "Send reminders for overdue payments via WhatsApp.",
            "whatsapp_loan_closed": "Notify borrower when a loan is marked closed.",
        }
