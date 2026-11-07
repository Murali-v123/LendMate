"""
Notification service layer.

enqueue_*() functions are the public API that views and Celery beat tasks call.
They:
  1. Check lender WhatsApp preferences (master switch and category toggle).
  2. Check borrower WhatsApp consent.
  3. Validate borrower mobile number.
  4. Create a channel-neutral Notification record (or SUPPRESSED record).
  5. Schedule the Celery task via on_commit to avoid pre-commit race conditions.

If Redis/Celery is temporarily unavailable, the notification remains in PENDING
status and will be picked up by the recover_stuck_notifications task.
"""
import logging
from typing import Optional, Tuple

from django.db import transaction

from .models import Notification
from .templates_whatsapp import (
    build_loan_created_payload,
    build_loan_closed_payload,
    build_monthly_reminder_payload,
    build_overdue_reminder_payload,
    build_payment_received_payload,
    WhatsAppTemplatePayload,
)
from .whatsapp import normalize_phone_number

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_preferences(lender):
    """Return (UserPreferences | None) for a lender safely."""
    try:
        return lender.preferences
    except Exception:
        return None


def _whatsapp_globally_enabled(preferences) -> bool:
    """Return True if the lender has WhatsApp notifications switched on."""
    if preferences is None:
        return False
    return getattr(preferences, "whatsapp_notifications_enabled", False)


def _category_enabled(preferences, notification_type: str) -> bool:
    """Return True if the specific WhatsApp notification category is enabled."""
    if preferences is None:
        return False
    mapping = {
        Notification.LOAN_CREATED: "whatsapp_loan_created",
        Notification.PAYMENT_RECEIVED: "whatsapp_payment_received",
        Notification.MONTHLY_REMINDER: "whatsapp_monthly_reminders",
        Notification.OVERDUE_REMINDER: "whatsapp_overdue_reminders",
        Notification.LOAN_CLOSED: "whatsapp_loan_closed",
    }
    field = mapping.get(notification_type)
    if not field:
        return False
    return getattr(preferences, field, False)


def _check_suppression(borrower, lender, notification_type: str) -> Tuple[bool, str]:
    """
    Returns (should_suppress: bool, suppress_reason: str).

    Checks:
      - WhatsApp globally enabled for lender.
      - Specific category enabled for lender.
      - Borrower has WhatsApp consent (explicitly checked; false by default).
      - Borrower mobile number is valid.
    """
    preferences = _get_preferences(lender)

    if not _whatsapp_globally_enabled(preferences):
        return True, "WhatsApp notifications are disabled in lender settings."

    if not _category_enabled(preferences, notification_type):
        return True, f"WhatsApp category '{notification_type}' is disabled in lender settings."

    if not getattr(borrower, "whatsapp_consent", False):
        return True, "Borrower has not consented to WhatsApp notifications."

    mobile = (borrower.mobile_number or "").strip()
    if not mobile:
        return True, "Borrower has no mobile number on file."

    if not normalize_phone_number(mobile):
        return True, f"Mobile number '{mobile}' does not appear to be a valid mobile number."

    return False, ""


def _create_notification(
    *,
    notification_type: str,
    borrower,
    loan,
    lender,
    message: str,
    event_key: str,
    payment=None,
    suppressed: bool = False,
    suppress_reason: str = "",
    channel: str = Notification.CHANNEL_WHATSAPP,
) -> Tuple[Notification, bool]:
    """
    Persist a Notification record. Returns (record, created).
    Idempotent: if event_key exists, returns existing record without modifying it.
    """
    defaults = {
        "channel": channel,
        "borrower": borrower,
        "loan": loan,
        "payment": payment,
        "lender": lender,
        "notification_type": notification_type,
        "recipient_number": (borrower.mobile_number or "").strip() if not suppressed else "",
        "message": message,
        "status": Notification.SUPPRESSED if suppressed else Notification.PENDING,
        "last_error": suppress_reason,
    }
    record, created = Notification.objects.get_or_create(
        event_key=event_key,
        defaults=defaults,
    )
    return record, created


def _schedule_task(notification_id: int):
    """
    Dispatch the Celery send task.
    If Celery/Redis is not running, leaves the record in PENDING for the
    recovery task to pick up later.
    """
    try:
        from .tasks import send_whatsapp_notification  # noqa: PLC0415
        send_whatsapp_notification.delay(notification_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Could not dispatch WhatsApp task for notification %s (broker may be unavailable): %s",
            notification_id, exc,
        )


def build_payload_for_notification(notification: Notification) -> Optional[WhatsAppTemplatePayload]:
    """Rebuild template payload for a given notification record."""
    ntype = notification.notification_type
    loan = notification.loan

    if ntype == Notification.LOAN_CREATED and loan:
        return build_loan_created_payload(loan)
    elif ntype == Notification.PAYMENT_RECEIVED and notification.payment:
        return build_payment_received_payload(notification.payment)
    elif ntype == Notification.LOAN_CLOSED and loan:
        return build_loan_closed_payload(loan)
    elif ntype in (Notification.MONTHLY_REMINDER, Notification.OVERDUE_REMINDER) and loan:
        from .tasks import _calculate_monthly_payment  # noqa: PLC0415
        monthly_amount = _calculate_monthly_payment(loan)
        due_date = loan.due_date or loan.lending_date
        if ntype == Notification.MONTHLY_REMINDER:
            return build_monthly_reminder_payload(loan, due_date, monthly_amount)
        else:
            return build_overdue_reminder_payload(loan, due_date, monthly_amount)

    return None


# ---------------------------------------------------------------------------
# Public enqueue functions
# ---------------------------------------------------------------------------

def enqueue_loan_created(loan) -> Notification:
    """Enqueue a loan-created WhatsApp notification for the borrower."""
    borrower = loan.borrower
    lender = borrower.lender

    event_key = Notification.make_event_key(
        Notification.LOAN_CREATED,
        loan_id=loan.pk,
        channel=Notification.CHANNEL_WHATSAPP,
    )

    suppress, reason = _check_suppression(borrower, lender, Notification.LOAN_CREATED)
    payload = build_loan_created_payload(loan) if not suppress else None
    message = payload.rendered_text if payload else ""

    record, created = _create_notification(
        notification_type=Notification.LOAN_CREATED,
        borrower=borrower,
        loan=loan,
        lender=lender,
        message=message,
        event_key=event_key,
        suppressed=suppress,
        suppress_reason=reason,
        channel=Notification.CHANNEL_WHATSAPP,
    )

    if created and not suppress:
        pk = record.pk
        transaction.on_commit(lambda: _schedule_task(pk))

    return record


def enqueue_payment_received(payment) -> Notification:
    """Enqueue a payment-received WhatsApp notification for the borrower."""
    loan = payment.loan
    borrower = loan.borrower
    lender = borrower.lender

    event_key = Notification.make_event_key(
        Notification.PAYMENT_RECEIVED,
        loan_id=loan.pk,
        payment_id=payment.pk,
        channel=Notification.CHANNEL_WHATSAPP,
    )

    suppress, reason = _check_suppression(borrower, lender, Notification.PAYMENT_RECEIVED)
    payload = build_payment_received_payload(payment) if not suppress else None
    message = payload.rendered_text if payload else ""

    record, created = _create_notification(
        notification_type=Notification.PAYMENT_RECEIVED,
        borrower=borrower,
        loan=loan,
        lender=lender,
        payment=payment,
        message=message,
        event_key=event_key,
        suppressed=suppress,
        suppress_reason=reason,
        channel=Notification.CHANNEL_WHATSAPP,
    )

    if created and not suppress:
        pk = record.pk
        transaction.on_commit(lambda: _schedule_task(pk))

    return record


def enqueue_loan_closed(loan) -> Notification:
    """Enqueue a loan-closed WhatsApp notification for the borrower."""
    borrower = loan.borrower
    lender = borrower.lender

    event_key = Notification.make_event_key(
        Notification.LOAN_CLOSED,
        loan_id=loan.pk,
        channel=Notification.CHANNEL_WHATSAPP,
    )

    suppress, reason = _check_suppression(borrower, lender, Notification.LOAN_CLOSED)
    payload = build_loan_closed_payload(loan) if not suppress else None
    message = payload.rendered_text if payload else ""

    record, created = _create_notification(
        notification_type=Notification.LOAN_CLOSED,
        borrower=borrower,
        loan=loan,
        lender=lender,
        message=message,
        event_key=event_key,
        suppressed=suppress,
        suppress_reason=reason,
        channel=Notification.CHANNEL_WHATSAPP,
    )

    if created and not suppress:
        pk = record.pk
        transaction.on_commit(lambda: _schedule_task(pk))

    return record


def enqueue_monthly_reminder(loan, due_date, monthly_amount, period_key) -> Tuple[Notification, bool]:
    """
    Enqueue a monthly payment reminder via WhatsApp.

    period_key: string like '2026-11' for November 2026.
    Idempotent: get_or_create with event_key.
    """
    borrower = loan.borrower
    lender = borrower.lender

    event_key = Notification.make_event_key(
        Notification.MONTHLY_REMINDER,
        loan_id=loan.pk,
        period_key=period_key,
        channel=Notification.CHANNEL_WHATSAPP,
    )

    suppress, reason = _check_suppression(borrower, lender, Notification.MONTHLY_REMINDER)
    payload = build_monthly_reminder_payload(loan, due_date, monthly_amount) if not suppress else None
    message = payload.rendered_text if payload else ""

    record, created = _create_notification(
        notification_type=Notification.MONTHLY_REMINDER,
        borrower=borrower,
        loan=loan,
        lender=lender,
        message=message,
        event_key=event_key,
        suppressed=suppress,
        suppress_reason=reason,
        channel=Notification.CHANNEL_WHATSAPP,
    )

    if created and not suppress:
        pk = record.pk
        transaction.on_commit(lambda: _schedule_task(pk))

    return record, created


def enqueue_overdue_reminder(loan, due_date, monthly_amount, period_key) -> Tuple[Notification, bool]:
    """
    Enqueue an overdue payment reminder via WhatsApp.

    period_key: string like 'overdue-2026-10' for an October 2026 overdue.
    """
    borrower = loan.borrower
    lender = borrower.lender

    event_key = Notification.make_event_key(
        Notification.OVERDUE_REMINDER,
        loan_id=loan.pk,
        period_key=period_key,
        channel=Notification.CHANNEL_WHATSAPP,
    )

    suppress, reason = _check_suppression(borrower, lender, Notification.OVERDUE_REMINDER)
    payload = build_overdue_reminder_payload(loan, due_date, monthly_amount) if not suppress else None
    message = payload.rendered_text if payload else ""

    record, created = _create_notification(
        notification_type=Notification.OVERDUE_REMINDER,
        borrower=borrower,
        loan=loan,
        lender=lender,
        message=message,
        event_key=event_key,
        suppressed=suppress,
        suppress_reason=reason,
        channel=Notification.CHANNEL_WHATSAPP,
    )

    if created and not suppress:
        pk = record.pk
        transaction.on_commit(lambda: _schedule_task(pk))

    return record, created
