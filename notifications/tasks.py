"""
Celery tasks for LendMate notifications.

Tasks:
  send_whatsapp_notification:
    Processes one eligible PENDING Notification record.
    - Atomically claims record with select_for_update(skip_locked=True).
    - Checks eligibility: ONLY PENDING status with next_retry_at <= now is processed.
    - Skips already PROCESSING, MOCKED, SUBMITTED, DELIVERED, FAILED, or SUPPRESSED records.
    - Transitions to PROCESSING and increments attempt count.
    - Releases DB lock and performs WhatsApp template dispatch outside the transaction.
    - If MOCKED: marks status as MOCKED, records processed_at, NEVER sets sent_at.
    - If SUBMITTED: marks status as SUBMITTED, records processed_at and sent_at.
    - If FAILED: schedules retry with exponential backoff up to 5 attempts.

Scheduled beat tasks:
  send_monthly_reminders:      Enqueues upcoming monthly payment reminders.
  send_overdue_reminders:      Enqueues reminders for overdue payments.
  recover_stuck_notifications: Recovers stale PROCESSING records and un-dispatched PENDING records.
"""
import calendar
import datetime
import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .models import Notification
from .whatsapp import WhatsAppStatus, send_whatsapp_template

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
RETRY_BACKOFF_SECONDS = [60, 300, 900, 3600, 7200]  # 1m, 5m, 15m, 1h, 2h
STUCK_THRESHOLD_MINUTES = 10


# ---------------------------------------------------------------------------
# Core WhatsApp sending task
# ---------------------------------------------------------------------------

@shared_task(
    bind=True,
    max_retries=0,  # Retries handled explicitly for backoff and error tracking
    ignore_result=True,
    name="notifications.tasks.send_whatsapp_notification",
)
def send_whatsapp_notification(self, notification_id: int):
    """
    Process a single Notification from the queue.

    Uses select_for_update(skip_locked=True) to prevent concurrent workers
    from processing the same notification. Only eligible PENDING notifications
    are claimed for transmission.
    """
    try:
        with transaction.atomic():
            try:
                notification = (
                    Notification.objects
                    .select_for_update(skip_locked=True)
                    .select_related("borrower", "loan", "payment", "lender")
                    .get(pk=notification_id)
                )
            except Notification.DoesNotExist:
                logger.warning(
                    "Notification %s not found or currently locked by another worker, skipping.",
                    notification_id,
                )
                return

            # Crucial duplicate check: ONLY eligible PENDING notifications can be claimed
            if notification.status != Notification.PENDING:
                logger.info(
                    "Notification %s is in status '%s' (not PENDING), skipping duplicate processing.",
                    notification_id, notification.status,
                )
                return

            # Respect next_retry_at: do not send before scheduled retry time
            now = timezone.now()
            if notification.next_retry_at and notification.next_retry_at > now:
                logger.info(
                    "Notification %s next_retry_at (%s) is in the future, skipping.",
                    notification_id, notification.next_retry_at,
                )
                return

            # Skip if max attempts already reached
            if notification.attempts >= MAX_ATTEMPTS:
                logger.error(
                    "Notification %s reached max attempts (%d), marking failed.",
                    notification_id, MAX_ATTEMPTS,
                )
                notification.status = Notification.FAILED
                notification.save(update_fields=["status", "updated_at"])
                return

            # Atomically claim: transition to PROCESSING
            notification.status = Notification.PROCESSING
            notification.attempts += 1
            notification.transmission_started_at = None
            notification.save(update_fields=["status", "attempts", "transmission_started_at", "updated_at"])

        # Send via WhatsApp outside atomic block so DB row lock is released
        from .service import build_payload_for_notification  # noqa: PLC0415
        payload = build_payload_for_notification(notification)

        if payload:
            template_name = payload.template_name
            language_code = payload.language_code
            parameters = payload.parameters
        else:
            template_name = f"lendmate_{notification.notification_type}"
            language_code = "en"
            parameters = [notification.borrower.full_name if notification.borrower else "Borrower"]

        # Hook executed strictly immediately before live external network transmission.
        # MockWhatsAppBackend NEVER invokes this callback.
        def _on_before_live_send():
            now_ts = timezone.now()
            notification.transmission_started_at = now_ts
            notification.save(update_fields=["transmission_started_at", "updated_at"])

        result = send_whatsapp_template(
            to=notification.recipient_number,
            template_name=template_name,
            language_code=language_code,
            body_parameters=parameters,
            fallback_text=notification.message,
            on_before_send=_on_before_live_send,
            biz_opaque_callback_data=f"notif_{notification.pk}",
        )

        now = timezone.now()
        should_retry = False
        backoff = 0

        if result.status == WhatsAppStatus.MOCKED:
            # Simulated in development - NEVER marked as sent or delivered, NEVER set sent_at,
            # and NEVER set transmission_started_at (it was not an external transmission).
            notification.status = Notification.MOCKED
            notification.provider_message_id = result.provider_message_id or ""
            notification.processed_at = now
            notification.sent_at = None
            notification.transmission_started_at = None
            notification.last_error = ""
            notification.next_retry_at = None

        elif result.status == WhatsAppStatus.SUBMITTED:
            # Accepted by Meta WhatsApp Cloud API - pending webhook for delivery confirmation
            notification.status = Notification.SUBMITTED
            notification.provider_message_id = result.provider_message_id or ""
            notification.processed_at = now
            notification.sent_at = now
            notification.last_error = ""
            notification.next_retry_at = None

        else:
            # Transient, permanent, or uncertain failure
            attempt_index = min(notification.attempts - 1, len(RETRY_BACKOFF_SECONDS) - 1)
            backoff = RETRY_BACKOFF_SECONDS[attempt_index]
            should_retry = False

            # Process uncertain outcomes BEFORE checking maximum-attempt condition
            if result.is_uncertain:
                # Outcome is genuinely uncertain — Meta may have already received and processed
                # this request. Retrying risks duplicate transmission to the borrower.
                # Mark SUBMITTED with diagnostic marker and await webhook resolution or manual review.
                notification.status = Notification.SUBMITTED
                notification.next_retry_at = None
                notification.last_error = f"[UNCERTAIN] {result.error}"[:500]
                logger.warning(
                    "Notification %s outcome is UNCERTAIN (possible duplicate if retried). "
                    "Marked SUBMITTED — awaiting webhook confirmation or manual review. Error: %s",
                    notification_id, result.error,
                )
            elif notification.attempts >= MAX_ATTEMPTS:
                notification.status = Notification.FAILED
                notification.next_retry_at = None
                notification.last_error = result.error[:500] if result.error else ""
                logger.error(
                    "Notification %s failed permanently after %d attempts. Error: %s",
                    notification_id, notification.attempts, result.error,
                )
            else:
                notification.status = Notification.PENDING
                notification.next_retry_at = now + datetime.timedelta(seconds=backoff)
                notification.last_error = result.error[:500] if result.error else ""
                notification.transmission_started_at = None
                should_retry = True
                logger.warning(
                    "Notification %s failed (attempt %d/%d). Retry in %ds. Error: %s",
                    notification_id, notification.attempts, MAX_ATTEMPTS, backoff, result.error,
                )

        # Save updated notification status and retry timestamps BEFORE scheduling another task
        notification.save(update_fields=[
            "status",
            "provider_message_id",
            "processed_at",
            "sent_at",
            "transmission_started_at",
            "last_error",
            "next_retry_at",
            "updated_at",
        ])

        # If a webhook event arrived before the worker finished, replay it now
        if notification.provider_message_id:
            try:
                from .views import replay_unmatched_webhooks_for_notification  # noqa: PLC0415
                replay_unmatched_webhooks_for_notification(notification)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error replaying unmatched webhooks for %s: %s", notification_id, exc)

        # Schedule async retry ONLY after database state is fully persisted and only if eligible PENDING
        if should_retry and notification.status == Notification.PENDING:
            try:
                send_whatsapp_notification.apply_async(
                    args=[notification_id],
                    countdown=backoff,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Could not schedule async retry for notification %s: %s",
                    notification_id, exc,
                )

    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error processing notification %s: %s", notification_id, exc)
        try:
            with transaction.atomic():
                notif = (
                    Notification.objects
                    .select_for_update()
                    .filter(pk=notification_id, status=Notification.PROCESSING)
                    .first()
                )
                if notif:
                    if notif.transmission_started_at is not None:
                        # Transmission was already initiated externally — outcome is uncertain.
                        # Never reset to PENDING or resend, as Meta may have delivered the message.
                        notif.status = Notification.SUBMITTED
                        notif.next_retry_at = None
                        notif.last_error = f"[UNCERTAIN] Unexpected error after transmission started: {str(exc)}"[:500]
                    elif notif.attempts >= MAX_ATTEMPTS:
                        notif.status = Notification.FAILED
                        notif.next_retry_at = None
                        notif.last_error = f"Unexpected error before transmission: {str(exc)}"[:500]
                    else:
                        notif.status = Notification.PENDING
                        notif.last_error = f"Unexpected error before transmission: {str(exc)}"[:500]
                    notif.save(update_fields=["status", "next_retry_at", "last_error", "updated_at"])
        except Exception:  # noqa: BLE001
            pass


# Backward compatibility alias
send_sms_notification = send_whatsapp_notification


# ---------------------------------------------------------------------------
# Scheduled task: monthly reminders
# ---------------------------------------------------------------------------

@shared_task(
    ignore_result=True,
    name="notifications.tasks.send_monthly_reminders",
)
def send_monthly_reminders():
    """
    Check for loans whose monthly payment is coming up in the next 3 days
    and enqueue a WhatsApp reminder for each one.
    """
    from lending.models import Loan  # noqa: PLC0415
    from .service import enqueue_monthly_reminder  # noqa: PLC0415

    now = timezone.localtime(timezone.now())
    today = now.date()
    lookahead = today + datetime.timedelta(days=3)

    loans = (
        Loan.objects
        .filter(status="open", interest_period="monthly", monthly_due_day__isnull=False)
        .select_related("borrower", "borrower__lender", "borrower__lender__preferences")
        .prefetch_related("payments")
    )

    sent_count = 0
    for loan in loans:
        if not loan.borrower or not loan.borrower.lender:
            continue

        due_day = loan.monthly_due_day
        for check_date in _dates_in_range(today, lookahead):
            try:
                max_day = calendar.monthrange(check_date.year, check_date.month)[1]
                actual_due_day = min(due_day, max_day)
                if check_date.day != actual_due_day:
                    continue

                due_date = check_date
                period_key = f"{due_date.year}-{due_date.month:02d}"
                monthly_amount = _calculate_monthly_payment(loan)

                _record, created = enqueue_monthly_reminder(
                    loan=loan,
                    due_date=due_date,
                    monthly_amount=monthly_amount,
                    period_key=period_key,
                )
                if created:
                    sent_count += 1

            except Exception:  # noqa: BLE001
                logger.exception("Error generating monthly reminder for loan %s", loan.pk)

    logger.info("send_monthly_reminders: %d new WhatsApp reminder(s) enqueued.", sent_count)


# ---------------------------------------------------------------------------
# Scheduled task: overdue reminders
# ---------------------------------------------------------------------------

@shared_task(
    ignore_result=True,
    name="notifications.tasks.send_overdue_reminders",
)
def send_overdue_reminders():
    """
    Check for open monthly loans whose payment due date has passed and
    no payment has been recorded for that period.
    """
    from lending.models import Loan, Payment  # noqa: PLC0415
    from .service import enqueue_overdue_reminder  # noqa: PLC0415

    now = timezone.localtime(timezone.now())
    today = now.date()
    lookback = today - datetime.timedelta(days=30)

    loans = (
        Loan.objects
        .filter(status="open", interest_period="monthly", monthly_due_day__isnull=False)
        .select_related("borrower", "borrower__lender", "borrower__lender__preferences")
        .prefetch_related("payments")
    )

    sent_count = 0
    for loan in loans:
        if not loan.borrower or not loan.borrower.lender:
            continue

        for check_date in _month_due_dates_in_range(loan, lookback, today - datetime.timedelta(days=1)):
            try:
                period_key = f"overdue-{check_date.year}-{check_date.month:02d}"

                period_start = check_date.replace(day=1)
                period_end_month = check_date.month % 12 + 1
                period_end_year = check_date.year + (1 if check_date.month == 12 else 0)
                period_end = datetime.date(period_end_year, period_end_month, 1)

                has_payment = loan.payments.filter(
                    payment_date__gte=period_start,
                    payment_date__lt=period_end,
                ).exists()

                if has_payment:
                    continue

                monthly_amount = _calculate_monthly_payment(loan)

                _record, created = enqueue_overdue_reminder(
                    loan=loan,
                    due_date=check_date,
                    monthly_amount=monthly_amount,
                    period_key=period_key,
                )
                if created:
                    sent_count += 1

            except Exception:  # noqa: BLE001
                logger.exception("Error generating overdue reminder for loan %s", loan.pk)

    logger.info("send_overdue_reminders: %d new WhatsApp overdue reminder(s) enqueued.", sent_count)


# ---------------------------------------------------------------------------
# Scheduled task: recover stuck notifications
# ---------------------------------------------------------------------------

@shared_task(
    ignore_result=True,
    name="notifications.tasks.recover_stuck_notifications",
)
def recover_stuck_notifications():
    """
    Recover notifications that require attention:
      1. Reset genuinely stale PROCESSING records (stuck > STUCK_THRESHOLD_MINUTES).
      2. Recover un-dispatched PENDING records (e.g. Redis was unavailable during enqueue).
      3. Dispatch PENDING records whose scheduled next_retry_at has arrived.
    """
    now = timezone.now()
    stuck_cutoff = now - datetime.timedelta(minutes=STUCK_THRESHOLD_MINUTES)
    pending_grace_cutoff = now - datetime.timedelta(minutes=2)

    stale_recovered_count = 0
    pending_dispatched_count = 0

    # 1. Recover stale PROCESSING notifications
    # Only recover WhatsApp channel — historical SMS records must not be re-dispatched.
    stuck_qs = Notification.objects.filter(
        status=Notification.PROCESSING,
        updated_at__lt=stuck_cutoff,
        channel=Notification.CHANNEL_WHATSAPP,
    )
    for notif in stuck_qs:
        dispatch_pk = None
        with transaction.atomic():
            try:
                locked = (
                    Notification.objects
                    .select_for_update(skip_locked=True)
                    .get(pk=notif.pk)
                )
            except Notification.DoesNotExist:
                continue

            if locked.status != Notification.PROCESSING or (locked.updated_at and locked.updated_at >= stuck_cutoff):
                continue

            if locked.transmission_started_at is not None:
                # Worker crashed or timed out AFTER external transmission started!
                # Meta API may have accepted or delivered the message.
                # Changing back to PENDING or resending would risk duplicate transmission to borrower.
                # Mark as SUBMITTED (uncertain) and await Meta webhook delivery resolution.
                locked.status = Notification.SUBMITTED
                locked.next_retry_at = None
                locked.last_error = (
                    f"[UNCERTAIN] Worker crashed or timed out after external transmission started at "
                    f"{locked.transmission_started_at.isoformat()} (stuck in PROCESSING). "
                    "Awaiting webhook confirmation or manual review; will not automatically resend."
                )[:500]
                locked.save(update_fields=["status", "next_retry_at", "last_error", "updated_at"])
                logger.warning(
                    "Notification %s recovered from stale PROCESSING: transmission started at %s. "
                    "Marked SUBMITTED (uncertain); will not automatically resend.",
                    locked.pk, locked.transmission_started_at,
                )
                try:
                    from .views import replay_unmatched_webhooks_for_notification  # noqa: PLC0415
                    replay_unmatched_webhooks_for_notification(locked)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Error replaying unmatched webhooks during recovery for %s: %s", locked.pk, exc)
                # dispatch_pk remains None -> will not automatically resend!
            elif locked.attempts >= MAX_ATTEMPTS:
                locked.status = Notification.FAILED
                locked.next_retry_at = None
                locked.last_error = f"Failed permanently: stuck in PROCESSING before transmission after {locked.attempts} attempts."
                locked.save(update_fields=["status", "next_retry_at", "last_error", "updated_at"])
            else:
                # Crashed BEFORE transmission began (e.g. payload build, memory error, SIGTERM).
                # Confirmed pre-transmission failure: safe to retry.
                locked.status = Notification.PENDING
                locked.last_error = "Recovered from stale PROCESSING state (crashed before external transmission started)."
                locked.save(update_fields=["status", "last_error", "updated_at"])
                dispatch_pk = locked.pk
                stale_recovered_count += 1

        # Dispatch AFTER the transaction commits so the worker sees PENDING status
        if dispatch_pk is not None:
            send_whatsapp_notification.delay(dispatch_pk)

    # 2. Recover un-dispatched PENDING notifications (created when Redis was down).
    # Includes attempts > 0 (failed once, Redis went down before retry could be scheduled).
    undispatched_qs = Notification.objects.filter(
        status=Notification.PENDING,
        next_retry_at__isnull=True,
        updated_at__lt=pending_grace_cutoff,
        attempts__lt=MAX_ATTEMPTS,
        channel=Notification.CHANNEL_WHATSAPP,
    )
    for notif in undispatched_qs:
        dispatch_pk = None
        with transaction.atomic():
            try:
                locked = (
                    Notification.objects
                    .select_for_update(skip_locked=True)
                    .get(pk=notif.pk)
                )
            except Notification.DoesNotExist:
                continue

            if (
                locked.status == Notification.PENDING
                and locked.next_retry_at is None
                and locked.attempts < MAX_ATTEMPTS
            ):
                locked.save(update_fields=["updated_at"])
                dispatch_pk = locked.pk
                pending_dispatched_count += 1

        if dispatch_pk is not None:
            send_whatsapp_notification.delay(dispatch_pk)

    # 3. Recover PENDING notifications whose scheduled retry time has arrived
    due_retries_qs = Notification.objects.filter(
        status=Notification.PENDING,
        next_retry_at__lte=now,
        attempts__lt=MAX_ATTEMPTS,
        channel=Notification.CHANNEL_WHATSAPP,
    )
    for notif in due_retries_qs:
        dispatch_pk = None
        with transaction.atomic():
            try:
                locked = (
                    Notification.objects
                    .select_for_update(skip_locked=True)
                    .get(pk=notif.pk)
                )
            except Notification.DoesNotExist:
                continue

            if locked.status == Notification.PENDING and locked.next_retry_at and locked.next_retry_at <= now:
                # Clear next_retry_at so subsequent beat cycles do not re-enqueue
                locked.next_retry_at = None
                locked.save(update_fields=["next_retry_at", "updated_at"])
                dispatch_pk = locked.pk
                pending_dispatched_count += 1

        if dispatch_pk is not None:
            send_whatsapp_notification.delay(dispatch_pk)

    if stale_recovered_count or pending_dispatched_count:
        logger.info(
            "recover_stuck_notifications: recovered %d stale PROCESSING and dispatched %d pending/due notifications.",
            stale_recovered_count,
            pending_dispatched_count,
        )

    return stale_recovered_count + pending_dispatched_count


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dates_in_range(start, end):
    """Yield each date from start to end inclusive."""
    current = start
    while current <= end:
        yield current
        current += datetime.timedelta(days=1)


def _month_due_dates_in_range(loan, start, end):
    """
    Yield the due date for each month in [start, end] for this loan.
    Clamps the due day to the last day of the month.
    """
    due_day = loan.monthly_due_day
    cur = start.replace(day=1)
    while cur <= end:
        max_day = calendar.monthrange(cur.year, cur.month)[1]
        actual_day = min(due_day, max_day)
        due_date = datetime.date(cur.year, cur.month, actual_day)
        if start <= due_date <= end:
            yield due_date
        if cur.month == 12:
            cur = datetime.date(cur.year + 1, 1, 1)
        else:
            cur = datetime.date(cur.year, cur.month + 1, 1)


def _calculate_monthly_payment(loan):
    """
    Calculate the expected monthly payment amount for a loan.
    """
    from decimal import Decimal  # noqa: PLC0415

    rate = loan.interest_rate / Decimal("100")

    if loan.interest_basis == "reducing":
        base = loan.outstanding_principal
    else:
        base = loan.principal

    return base * rate
